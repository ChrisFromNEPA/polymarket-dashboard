"""Execution-price invariant tests.

These encode the bug that produced every invalid run so far: the risk manager
sized and validated against the MIDPOINT while the fill engine walked the BOOK,
so a trade approved at an implied 0.8625 executed at 0.9990.

The binding rule: never pay more than your own fair value, measured at the price
you actually fill at, including fees.

Reference: reports/review-03.md
"""

import pytest

from agent.engine.fills import FillEngine, FillResult
from agent.engine.portfolio import PortfolioEngine
from agent.polymarket.client import PolymarketClient
from agent.polymarket.models import BookLevel, OrderBook
from agent.risk.manager import RiskManager
from agent.strategies.base import TradeProposal


# ── Fixtures ─────────────────────────────────────────────────

def make_book(bids=None, asks=None, last_trade=None):
    return OrderBook(
        token_id="tok_no",
        bids=[BookLevel(price=p, size=s) for p, s in (bids or [])],
        asks=[BookLevel(price=p, size=s) for p, s in (asks or [])],
        last_trade_price=last_trade,
    )


# The real AOC market shape. YES midpoint 0.1375 → NO "looks like" 0.8625,
# but the NO book only offers liquidity at 0.999.
AOC_NO_BOOK = make_book(
    bids=[(0.80, 500)],
    asks=[(0.999, 5000)],
    last_trade=0.86,
)


def aoc_proposal():
    """Buy NO on a market the agent thinks is 8.75% likely.

    Fair value of NO = 1 - 0.0875 = 0.9125.
    """
    return TradeProposal(
        token_id="tok_no",
        outcome="No",
        direction="BUY",
        market_question="Will Alexandria Ocasio-Cortez win the 2028 Democratic nomination?",
        condition_id="0xaoc",
        market_probability=0.1375,   # p_market for YES
        agent_probability=0.0875,    # p_agent for YES
        confidence=1.0,
        strategy_name="favorite-longshot",
        yes_token_id="tok_yes",
        no_token_id="tok_no",
    )


def fresh_manager(cash=10_000.0):
    return RiskManager(PortfolioEngine(starting_cash=cash))


# ── The regression test ──────────────────────────────────────

@pytest.mark.asyncio
async def test_rejects_fill_above_fair_value_even_when_midpoint_looks_fine():
    """THE regression test for reports/review-03.md.

    Midpoint implies NO is worth 0.8625, which is below fair value 0.9125, so the
    midpoint-based pre-filter approves. The book fills at 0.999, which is ABOVE
    fair value. It must be rejected.
    """
    engine = FillEngine(PolymarketClient())
    mgr = fresh_manager()
    proposal = aoc_proposal()

    # Pre-filter passes — this is exactly why the bug was invisible.
    pre = mgr.evaluate(proposal)
    assert pre.approved, "midpoint pre-filter should pass; that is the trap"

    # Quote against the real book.
    quote = await engine.market_buy("tok_no", 500, book=AOC_NO_BOOK)
    assert quote.filled
    assert quote.avg_price == pytest.approx(0.999, abs=1e-6)

    # The binding check must reject.
    decision = mgr.validate_execution(
        proposal=proposal, fill=quote, actual_outcome="No", actual_direction="BUY"
    )
    assert not decision.approved
    assert "fair value" in decision.reason.lower()


@pytest.mark.asyncio
async def test_accepts_fill_below_fair_value():
    """A genuinely good price must still be allowed through."""
    engine = FillEngine(PolymarketClient())
    mgr = fresh_manager()
    proposal = aoc_proposal()  # fair NO = 0.9125

    cheap_book = make_book(bids=[(0.85, 500)], asks=[(0.88, 500)])
    quote = await engine.market_buy("tok_no", 100, book=cheap_book)

    decision = mgr.validate_execution(
        proposal=proposal, fill=quote, actual_outcome="No", actual_direction="BUY"
    )
    assert decision.approved, decision.reason


@pytest.mark.asyncio
async def test_fees_can_push_an_otherwise_fair_price_over_the_line():
    """Validation uses effective_price, so fees count against the edge."""
    mgr = fresh_manager()
    proposal = aoc_proposal()  # fair NO = 0.9125

    # 0.9120/share is fair, but fees push the effective price above 0.9125.
    fill = FillResult(
        filled=True, token_id="tok_no", side="buy",
        filled_size=100, requested_size=100,
        avg_price=0.9120, total_cost=91.20, fee=0.20, reason="filled",
    )
    assert fill.effective_price > 0.9125

    decision = mgr.validate_execution(
        proposal=proposal, fill=fill, actual_outcome="No", actual_direction="BUY"
    )
    assert not decision.approved


def test_fair_value_flips_for_the_no_side():
    """agent_probability is always P(YES). Using it unflipped for NO would
    compare 0.999 against 0.0875 and reject for the wrong reason — or, with the
    inequality the other way, approve nonsense."""
    mgr = fresh_manager()
    proposal = aoc_proposal()

    # 0.90 is below fair NO (0.9125) → allowed
    ok = FillResult(filled=True, token_id="t", side="buy", filled_size=10,
                    requested_size=10, avg_price=0.90, total_cost=9.0, reason="filled")
    assert mgr.validate_execution(proposal, ok, "No", "BUY").approved

    # 0.93 is above fair NO → rejected
    bad = FillResult(filled=True, token_id="t", side="buy", filled_size=10,
                     requested_size=10, avg_price=0.93, total_cost=9.3, reason="filled")
    assert not mgr.validate_execution(proposal, bad, "No", "BUY").approved


def test_outcome_casing_does_not_invert_fair_value():
    """A stray lowercase side must not silently flip the guard into its opposite."""
    mgr = fresh_manager()
    proposal = aoc_proposal()   # fair NO = 0.9125, fair YES = 0.0875

    fill = FillResult(filled=True, token_id="t", side="buy", filled_size=10,
                      requested_size=10, avg_price=0.93, total_cost=9.3, reason="filled")

    # 0.93 is above fair NO either way it is spelled.
    assert not mgr.validate_execution(proposal, fill, "No", "BUY").approved
    assert not mgr.validate_execution(proposal, fill, "no", "BUY").approved

    # Anything unrecognised is refused, not guessed at.
    assert not mgr.validate_execution(proposal, fill, "maybe", "BUY").approved


def test_unfilled_quote_is_rejected():
    """An empty book must not be treated as a free pass."""
    mgr = fresh_manager()
    empty = FillResult(
        filled=False, token_id="t", side="buy", filled_size=0, requested_size=100,
        avg_price=0.0, total_cost=0.0, reason="rejected — no book levels on this side",
    )
    assert not mgr.validate_execution(aoc_proposal(), empty, "No", "BUY").approved


def test_position_cap_uses_real_cost_not_midpoint_cost():
    """Sizing from the midpoint understates cost when the book is worse.

    Shares sized at an assumed 0.8625 cost far more at 0.999, which can breach
    the 5% position cap even though the share count looked compliant.
    """
    mgr = fresh_manager(cash=10_000.0)   # 5% cap = $500
    proposal = aoc_proposal()

    # 560 shares × 0.8625 = $483 (under cap). At 0.999 it is $559 (over cap).
    fill = FillResult(
        filled=True, token_id="tok_no", side="buy",
        filled_size=560, requested_size=560,
        avg_price=0.999, total_cost=559.44, reason="filled",
    )
    # Give it a fair value high enough that only the cap can reject it.
    proposal.agent_probability = 0.0   # fair NO = 1.0, so price is "fair"
    decision = mgr.validate_execution(proposal, fill, "No", "BUY")
    assert not decision.approved
    assert "cap" in decision.reason.lower()


# ── Budget accounting ────────────────────────────────────────

def test_rejected_trades_do_not_consume_the_daily_cap():
    """evaluate() used to charge the cap and start a cooldown before the trade
    executed, so proposals killed at execution still starved real ones."""
    mgr = fresh_manager()
    proposal = aoc_proposal()

    for _ in range(3):
        mgr.evaluate(proposal)

    assert mgr.daily_trade_count == 0, "quoting must not consume trade budget"
    assert proposal.condition_id not in mgr.last_trade_times, \
        "cooldown must not start until a trade actually fills"

    mgr.commit_trade(proposal.condition_id)
    assert mgr.daily_trade_count == 1
    assert proposal.condition_id in mgr.last_trade_times
