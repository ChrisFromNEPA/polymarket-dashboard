"""Phase 2 adversarial tests — prove the fill engine is honest.

All tests use the STRICT book-walking mode. No external API calls.
These tests verify:
  1. Depth limits prevent overfill
  2. Round-trip loses money (pays spread twice)
  3. NO positions marked from own book (not from YES book)
  4. Settlement ties out to the cent
  5. Passive orders don't fill without real trades (placeholder)
"""

import pytest

from agent.engine.fills import FillEngine
from agent.engine.portfolio import PortfolioEngine
from agent.engine.settlement import SettlementEngine, SettlementResult
from agent.polymarket.client import PolymarketClient
from agent.polymarket.models import BookLevel, OrderBook


# ── Test fixtures ────────────────────────────────────────────

def make_book(bids=None, asks=None, last_trade=None):
    """Create an OrderBook for testing."""
    return OrderBook(
        token_id="test_token",
        bids=[BookLevel(price=p, size=s) for p, s in (bids or [])],
        asks=[BookLevel(price=p, size=s) for p, s in (asks or [])],
        last_trade_price=last_trade,
    )


# Books with realistic spreads
TIGHT_YES_BOOK = make_book(
    bids=[(0.62, 100), (0.61, 200), (0.60, 500)],
    asks=[(0.64, 80), (0.65, 150), (0.66, 300)],
    last_trade=0.63,
)

TIGHT_NO_BOOK = make_book(
    bids=[(0.36, 80), (0.35, 150), (0.34, 300)],   # NO bid = what you can sell NO at
    asks=[(0.38, 100), (0.39, 200), (0.40, 500)],   # NO ask = what you can buy NO at
    last_trade=0.37,
)

EMPTY_BOOK = make_book(bids=[], asks=[])


# ── Test 1: Depth limits prevent overfill ────────────────────

@pytest.mark.asyncio
async def test_depth_limits_prevent_overfill():
    """Buying more than book depth cannot fill entirely at top-of-book price."""
    client = PolymarketClient()
    engine = FillEngine(client, mode="strict")

    # Book has 80 + 150 + 300 = 530 shares on the ask side
    # Request 1000 shares → should only fill 530
    result = await engine._market_order("test_token", 1000, "buy", TIGHT_YES_BOOK)

    assert result.filled, "Should fill what's available"
    assert result.filled_size == 530, f"Should fill 530 shares, got {result.filled_size}"
    assert result.filled_size < result.requested_size, "Should not fill beyond depth"
    assert "partial" in result.reason.lower(), f"Should report partial fill: {result.reason}"

    # Verify volume-weighted average price:
    # 80 @ 0.64 + 150 @ 0.65 + 300 @ 0.66 = 51.2 + 97.5 + 198.0 = 346.7
    # avg = 346.7 / 530 = 0.65415...
    expected_avg = (80 * 0.64 + 150 * 0.65 + 300 * 0.66) / 530
    assert abs(result.avg_price - expected_avg) < 0.001, (
        f"Expected avg {expected_avg:.4f}, got {result.avg_price:.4f}"
    )

    # Top-of-book price is 0.64 — we walked past it
    assert result.avg_price > 0.64, "Should pay more than top-of-book for large order"


# ── Test 2: Round-trip loses money ────────────────────────────

@pytest.mark.asyncio
async def test_round_trip_loses_money():
    """An immediate buy-then-sell round trip loses money (pays spread twice)."""
    client = PolymarketClient()
    engine = FillEngine(client, mode="strict")
    portfolio = PortfolioEngine(starting_cash=1000)

    token_id = "test_yes"

    # BUY 100 YES shares: crosses the ask side
    buy_result = await engine._market_order(token_id, 100, "buy", TIGHT_YES_BOOK)
    assert buy_result.filled
    assert buy_result.filled_size == 100

    # Add position at the fill price
    portfolio.add_position(token_id, "Yes", buy_result.filled_size, buy_result.avg_price)

    # IMMEDIATELY SELL 100 YES shares: crosses the bid side
    sell_result = await engine._market_order(token_id, 100, "sell", TIGHT_YES_BOOK)
    assert sell_result.filled
    assert sell_result.filled_size == 100

    pnl, remaining = portfolio.reduce_position(token_id, "Yes", sell_result.filled_size, sell_result.avg_price)

    # Round-trip MUST lose money: buy at ask (~0.64), sell at bid (~0.62)
    assert pnl < 0, (
        f"Round-trip P&L should be negative (buy at {buy_result.avg_price:.4f}, "
        f"sell at {sell_result.avg_price:.4f}), got P&L={pnl:.4f}. "
        f"If this shows profit the fill engine is broken."
    )

    # Verify the math:
    # Buy 100 @ 0.64 (top of ask) = -64.00
    # Sell 100 @ 0.62 (top of bid) = +62.00
    # P&L = -2.00
    # But with depth, might get slightly different fills
    # The key assertion: P&L < 0
    print(f"Buy price: {buy_result.avg_price:.4f}, Sell price: {sell_result.avg_price:.4f}")
    print(f"Round-trip P&L: ${pnl:.4f}")


# ── Test 3: NO positions marked from NO book (not YES) ────────

@pytest.mark.asyncio
async def test_no_position_marked_from_own_book():
    """Marking a NO position uses the NO book's own bid, not the YES book.

    This is the regression test for PLAN.md §3.4 — the confirmed bug
    where js/app.js marked NO positions at roughly the YES price.
    """
    client = PolymarketClient()
    engine = FillEngine(client, mode="strict")
    portfolio = PortfolioEngine(starting_cash=1000)

    no_token_id = "test_no"

    # BUY 50 NO shares at the NO ask (crossing the NO ask side)
    # NO ask is 0.38 (first level of TIGHT_NO_BOOK asks)
    buy_result = await engine._market_order(no_token_id, 50, "buy", TIGHT_NO_BOOK)
    assert buy_result.filled
    # Should fill at NO ask ~0.38
    expected_no_ask = TIGHT_NO_BOOK.asks[0].price  # 0.38
    assert abs(buy_result.avg_price - expected_no_ask) < 0.01

    portfolio.add_position(no_token_id, "No", buy_result.filled_size, buy_result.avg_price,
                           market_question="Test NO position")

    # Now mark the position: what can we sell NO at?
    # The NO book's best BID is 0.36 (what we can sell NO for)
    no_best_bid = await engine.get_best_bid(no_token_id, TIGHT_NO_BOOK)
    assert abs(no_best_bid - 0.36) < 0.001, (
        f"NO best bid should be 0.36 (from NO book), got {no_best_bid}"
    )

    # This is the critical check: the NO mark price is from the NO book.
    # If we used the YES book, we'd get YES_bid ≈ 0.62, marking NO at ~0.62
    # which is the bug from §3.4.
    # get_best_bid(no_token) returns NO book bid (0.36), not YES book bid (0.62)

    # Verify the NO position is valued at the NO bid, not the YES bid
    yes_best_bid = await engine.get_best_bid("test_yes", TIGHT_YES_BOOK)
    assert abs(yes_best_bid - 0.62) < 0.001, f"YES best bid should be 0.62"

    # The NO bid (0.36) should NOT equal the YES bid (0.62)
    assert abs(no_best_bid - yes_best_bid) > 0.20, (
        f"NO bid ({no_best_bid}) should differ significantly from YES bid ({yes_best_bid})"
    )

    print(f"NO best bid: {no_best_bid:.4f} (from NO book)")
    print(f"YES best bid: {yes_best_bid:.4f} (from YES book)")
    print("NO position correctly valued from its own book ✓")


# ── Test 4: Settlement ties out to the cent ────────────────────

@pytest.mark.asyncio
async def test_settlement_ties_out():
    """A resolved market settles positions to exactly $1/$0 and
    realized P&L ties out against cash movements to the cent."""
    portfolio = PortfolioEngine(starting_cash=1000)
    initial_cash = portfolio.cash

    # Buy 100 YES at 0.65
    portfolio.add_position("yes_token", "Yes", 100, 0.65, market_question="Test")
    cost = 100 * 0.65  # $65
    assert abs(portfolio.cash - (initial_cash - cost)) < 0.001

    # Buy 50 NO at 0.30
    portfolio.add_position("no_token", "No", 50, 0.30, market_question="Test")
    cost_no = 50 * 0.30  # $15
    expected_cash = initial_cash - cost - cost_no
    assert abs(portfolio.cash - expected_cash) < 0.001

    # Market resolves YES
    # YES position → $1 * 100 = $100 (profit = $35)
    # NO position → $0 * 50 = $0 (loss = $15)
    yes_pnl = portfolio.settle_position("yes_token", "Yes", 1.0)
    no_pnl = portfolio.settle_position("no_token", "No", 0.0)

    assert abs(yes_pnl - 35.0) < 0.001, f"YES settlement P&L should be $35, got {yes_pnl}"
    assert abs(no_pnl + 15.0) < 0.001, f"NO settlement P&L should be -$15, got {no_pnl}"

    # Final cash: 1000 - 65 - 15 + 100 + 0 = 1020
    expected_final = initial_cash - cost - cost_no + 100.0 + 0.0  # 1020
    assert abs(portfolio.cash - expected_final) < 0.001, (
        f"Final cash should be ${expected_final:.2f}, got ${portfolio.cash:.2f}"
    )

    # Net P&L: 35 - 15 = 20
    net_pnl = portfolio.cash - initial_cash
    assert abs(net_pnl - 20.0) < 0.001, f"Net P&L should be $20, got {net_pnl}"

    # No positions left
    assert portfolio.open_position_count == 0

    print(f"Initial cash: ${initial_cash:.2f}")
    print(f"Final cash: ${portfolio.cash:.2f}")
    print(f"Net P&L: ${net_pnl:.2f}")
    print(f"YES settled: ${yes_pnl:.2f}, NO settled: ${no_pnl:.2f}")
    print("Settlement ties out to the cent ✓")


# ── Test 5: Empty book rejects fills ──────────────────────────

@pytest.mark.asyncio
async def test_empty_book_rejects_fills():
    """A market with an empty book should not fill."""
    client = PolymarketClient()
    engine = FillEngine(client, mode="strict")

    result = await engine._market_order("empty_token", 100, "buy", EMPTY_BOOK)
    assert not result.filled, "Empty book should not fill"
    assert "no book levels" in result.reason.lower()


# ── Test 6: SettlementEngine resolution logic ─────────────────

def test_settlement_value_logic():
    """SettlementEngine.settle_position_value returns correct $1/$0."""
    assert SettlementEngine.settle_position_value("Yes", "Yes") == 1.0
    assert SettlementEngine.settle_position_value("Yes", "No") == 0.0
    assert SettlementEngine.settle_position_value("No", "Yes") == 0.0
    assert SettlementEngine.settle_position_value("No", "No") == 1.0


@pytest.mark.asyncio
async def test_portfolio_mark_no_uses_no_book():
    """get_best_bid for a NO token returns the NO book bid price."""
    client = PolymarketClient()
    engine = FillEngine(client, mode="strict")

    # NO book: bids at 0.36, 0.35, 0.34; asks at 0.38, 0.39, 0.40
    no_bid = await engine.get_best_bid("test_no", TIGHT_NO_BOOK)
    assert abs(no_bid - 0.36) < 0.001, f"NO bid should be 0.36, got {no_bid}"

    # YES book: bids at 0.62, 0.61, 0.60
    yes_bid = await engine.get_best_bid("test_yes", TIGHT_YES_BOOK)
    assert abs(yes_bid - 0.62) < 0.001, f"YES bid should be 0.62, got {yes_bid}"

    # They must be different (the whole point)
    assert abs(no_bid - yes_bid) > 0.20
