"""Backtest harness control tests.

docs/TESTING.md §4.4 makes the control strategies the gate for everything
downstream: "Nothing downstream is trustworthy until these pass." Until now they
were run ad hoc and never as a regression test — the same pattern that let the
Phase E result stand unchallenged for a day.

These tests pin the harness's real behaviour, and use xfail to record where the
implementation is weaker than the specification rather than pretending otherwise.

Reference: reports/review-05.md
"""

import pytest

from agent.backtest.corpus import CorpusMarket
from agent.polymarket.models import PricePoint
from agent.backtest.replay import (
    BacktestReport,
    ForecastResult,
    ReplayHarness,
    contamination_probe,
    control_market_parrot,
    control_oracle,
    control_random,
)


# ── Fixtures ─────────────────────────────────────────────────

def market(cid, p_at_mid, outcome, n=5):
    """A corpus market whose mid-history price is p_at_mid.

    `outcome` is a read-only property derived from `winner`, so it is set via
    winner rather than assigned.
    """
    return CorpusMarket(
        question=f"Q{cid}",
        condition_id=cid,
        slug=cid,
        winner="Yes" if outcome == 1 else "No",
        volume=100_000.0,
        token_id_yes=f"yes-{cid}",
        token_id_no=f"no-{cid}",
        price_history=[
            PricePoint(timestamp=1000 + i, price=p_at_mid) for i in range(n)
        ],
    )


class FakeCorpus:
    def __init__(self, markets):
        self.markets = markets


# A well-calibrated corpus: confident markets that resolved as priced.
CALIBRATED = FakeCorpus([
    market("a", 0.90, 1), market("b", 0.85, 1), market("c", 0.10, 0),
    market("d", 0.15, 0), market("e", 0.80, 1), market("f", 0.20, 0),
])


# ── Brier arithmetic ─────────────────────────────────────────

def test_brier_arithmetic():
    f = ForecastResult(
        condition_id="x", question="q", timestamp=0,
        p_market=0.60, p_agent=0.80, outcome=1, winner="Yes",
    )
    assert f.brier_agent == pytest.approx(0.04)     # (0.8-1)^2
    assert f.brier_market == pytest.approx(0.16)    # (0.6-1)^2
    assert f.brier_delta == pytest.approx(-0.12)    # negative = agent better


def test_empty_report_does_not_divide_by_zero():
    r = BacktestReport(strategy_name="none")
    assert r.brier_agent == 0.0
    assert r.brier_market == 0.0
    assert r.count == 0


# ── Control: market-parrot ───────────────────────────────────

def test_market_parrot_scores_exactly_zero_delta():
    """The single most important control.

    A strategy whose p_agent IS p_market must score a Brier delta of exactly 0.
    This is the direct regression test for Defect 1, where the longshot strategy's
    p_agent was a deterministic transform of p_market. If a transform of the
    market price can show edge, the metric is lying.
    """
    h = ReplayHarness(CALIBRATED)
    r = h.run(control_market_parrot, "market-parrot")
    assert r.count == 6
    assert r.brier_delta == pytest.approx(0.0, abs=1e-12)
    assert r.edge_count == 0, "parroting the market cannot beat the market"


def test_verify_controls_flags_a_broken_parrot():
    """If scoring breaks, verify_controls must catch it."""
    h = ReplayHarness(CALIBRATED)
    good = h.run(control_market_parrot, "market-parrot")
    assert h.verify_controls([good])["market-parrot → delta ≈ 0"][0] is True

    # Corrupt the scoring: shift every agent forecast.
    for f in good.forecasts:
        f.p_agent = min(0.99, f.p_agent + 0.30)
    assert h.verify_controls([good])["market-parrot → delta ≈ 0"][0] is False


# ── Control: oracle ──────────────────────────────────────────

def test_oracle_is_handed_the_answer_and_therefore_proves_only_wiring():
    """Oracle receives the outcome directly, so a near-zero Brier is guaranteed.

    Worth pinning explicitly: this control tests that Brier plumbing is connected,
    NOT that the harness is sound. It cannot fail for an interesting reason.
    """
    h = ReplayHarness(CALIBRATED)
    r = h.run(control_oracle, "oracle")
    # Forecasts are clamped to [0.01, 0.99], so even perfect knowledge scores
    # (0.99 - 1)^2 = 0.0001 rather than 0.
    assert r.brier_agent == pytest.approx(0.0001, abs=1e-9)
    assert r.brier_delta < 0
    assert r.edge_count == r.count, "a perfect oracle should win every market"


def test_oracle_threshold_false_negatives_on_a_calibrated_corpus():
    """`verify_controls` requires oracle to beat the market by 0.1 Brier.

    On a well-calibrated corpus `brier_market` is already ~0.024, so **even a
    perfect oracle can only achieve −0.024** and the check reports
    "✗ oracle failed — wiring broken" when nothing is broken.

    This is the same class of defect as the contamination probe: the threshold
    encodes an assumption about how badly priced the market is, not about whether
    the harness works. Found by CI on its first run.

    See reports/review-05.md §4.
    """
    h = ReplayHarness(CALIBRATED)
    r = h.run(control_oracle, "oracle")

    # The oracle is essentially perfect...
    assert r.brier_agent < 0.001
    # ...yet the control reports failure.
    passed, msg = h.verify_controls([r])["oracle → strongly beats market"]
    assert passed is False, "flip this assertion when the threshold is fixed"
    assert "failed" in msg.lower()


def test_non_oracle_strategies_never_receive_the_outcome():
    """The harness hides the label by passing 0 for everything except oracle."""
    seen = []

    def spy(p_market, outcome_hidden=0):
        seen.append(outcome_hidden)
        return p_market

    h = ReplayHarness(CALIBRATED)
    h.run(spy, "spy")
    assert set(seen) == {0}, "outcome leaked to a non-oracle strategy"


# ── Control: random ──────────────────────────────────────────

def test_random_is_worse_than_a_calibrated_market():
    h = ReplayHarness(CALIBRATED, seed=42)
    r = h.run(control_random, "random")
    assert r.brier_delta > 0
    assert h.verify_controls([r])["random → loses to market"][0] is True


def test_harness_is_deterministic_for_a_given_seed():
    a = ReplayHarness(CALIBRATED, seed=7).run(control_random, "random")
    b = ReplayHarness(CALIBRATED, seed=7).run(control_random, "random")
    assert [f.p_agent for f in a.forecasts] == [f.p_agent for f in b.forecasts]


# ── Gaps between spec and implementation ─────────────────────

@pytest.mark.xfail(
    reason="TESTING.md §4.4 requires the random control to LOSE MONEY, measured "
           "through the live fill engine. The harness has no P&L path at all — it "
           "scores Brier only, so the acceptance criterion is unimplemented. "
           "See reports/review-05.md.",
    strict=False,
)
def test_random_control_loses_money_through_the_fill_engine():
    h = ReplayHarness(CALIBRATED, seed=42)
    r = h.run(control_random, "random")
    assert hasattr(r, "pnl"), "BacktestReport has no P&L — spec not implemented"
    assert r.pnl < 0


@pytest.mark.xfail(
    reason="contamination_probe returns a constant 0.50, so its Brier is always "
           "0.25. The check |0.25 - brier_market| < 0.05 therefore tests whether "
           "the MARKET was uninformative, not whether data leaked. A constant "
           "cannot leak. A real probe must run the actual forecaster (with "
           "retrieval) on unknowable markets. See reports/review-05.md.",
    strict=False,
)
def test_contamination_probe_detects_a_leak():
    """A well-calibrated market should not trip the leak alarm — but it does."""
    h = ReplayHarness(CALIBRATED)
    r = h.run(contamination_probe, "contamination-probe")
    # brier_market here is ~0.017 (well calibrated), so |0.25 - 0.017| = 0.233
    # and the probe reports a leak that does not exist.
    assert h.verify_controls([r])["contamination-probe → no edge"][0] is True


def test_contamination_probe_currently_false_alarms_on_good_markets():
    """Pin the actual (wrong) behaviour so the fix is visibly a change."""
    h = ReplayHarness(CALIBRATED)
    r = h.run(contamination_probe, "contamination-probe")
    passed, msg = h.verify_controls([r])["contamination-probe → no edge"]
    assert passed is False, "documents the false alarm; flip this when fixed"
    assert "LEAK" in msg


# ── Sampling ─────────────────────────────────────────────────

def test_markets_without_enough_history_are_skipped():
    thin = FakeCorpus([market("short", 0.5, 1, n=1), market("ok", 0.5, 1, n=4)])
    r = ReplayHarness(thin).run(control_market_parrot, "market-parrot")
    assert r.count == 1


def test_sample_every_n_is_accepted_but_ignored():
    """Dead parameter — one sample per market regardless. Pinned so the
    signature is not mistaken for working functionality."""
    h = ReplayHarness(CALIBRATED)
    assert h.run(control_market_parrot, "p", sample_every_n=1).count == 6
    assert h.run(control_market_parrot, "p", sample_every_n=99).count == 6
