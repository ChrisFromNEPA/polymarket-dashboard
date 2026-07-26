"""Forecaster tests — market selection, price handling, calibration, hallucination guards.

This module had never been reviewed or tested. It carries the actual edge, and
audit found it would have produced garbage if wired up — most seriously, every
proposal reported p_market = 0.50 regardless of the real price.

Reference: reports/review-06.md
"""

from datetime import datetime, timedelta, timezone

import pytest

from agent.polymarket.models import Market, Token
from agent.strategies.forecaster import (
    Calibration,
    ForecastResult,
    ForecasterStrategy,
    _days_until,
)


# ── Fixtures ─────────────────────────────────────────────────

def mk_market(days=30, volume=200_000, neg_risk=False, closed=False, question="Will X happen?"):
    end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    return Market(
        question=question,
        slug="slug",
        condition_id="0xcond",
        tokens=[Token("yes-token", "Yes"), Token("no-token", "No")],
        volume=volume,
        liquidity=50_000,
        closed=closed,
        neg_risk=neg_risk,
        end_date=end,
    )


def good_forecast(p_raw=0.70, confidence=0.8, citations=("ev1",), skip=False):
    return ForecastResult(
        question="Will X happen?",
        p_raw=p_raw,
        confidence=confidence,
        reasoning="Base rate 40%, two credible reports raise it.",
        citations=list(citations),
        skip=skip,
    )


class FakeClient:
    """Returns a fixed midpoint for any token."""
    def __init__(self, mid=0.50):
        self.mid = mid
        self.calls = 0

    async def get_midpoint(self, token_id):
        self.calls += 1
        return self.mid


# ── Market selection (docs/RESEARCH.md §1) ───────────────────

def test_accepts_a_market_that_fits_the_profile():
    s = ForecasterStrategy()
    ok, reason = s.market_is_eligible(mk_market(days=30), 0.45)
    assert ok, reason


@pytest.mark.parametrize("price", [0.002, 0.05, 0.95, 0.999])
def test_rejects_extreme_prices(price):
    """At $0.002 the tick size is half the price — no room to be right in."""
    s = ForecasterStrategy()
    ok, reason = s.market_is_eligible(mk_market(), price)
    assert not ok
    assert "outside" in reason


@pytest.mark.parametrize("days,frag", [(1, "resolves in"), (800, "information decays")])
def test_rejects_bad_horizons(days, frag):
    """Too near: markets aggregate news faster than we do.
    Too far: any information decays. The 2028 markets were >800 days out."""
    s = ForecasterStrategy()
    ok, reason = s.market_is_eligible(mk_market(days=days), 0.45)
    assert not ok
    assert frag in reason


def test_rejects_negrisk_multi_outcome():
    """128 candidates for one nomination is one correlated bet, not 128."""
    s = ForecasterStrategy()
    ok, reason = s.market_is_eligible(mk_market(neg_risk=True), 0.45)
    assert not ok
    assert "NegRisk" in reason


def test_rejects_the_exact_markets_the_agent_was_trading():
    """Regression for the whole episode: 2028 nomination longshots."""
    s = ForecasterStrategy()
    aoc = mk_market(days=830, neg_risk=True,
                    question="Will Alexandria Ocasio-Cortez win the 2028 Democratic nomination?")
    ok, reason = s.market_is_eligible(aoc, 0.1375)
    assert not ok, "these markets must never be eligible again"


def test_rejects_missing_price_and_missing_end_date():
    s = ForecasterStrategy()
    assert not s.market_is_eligible(mk_market(), None)[0]
    m = mk_market()
    m.end_date = None
    assert not s.market_is_eligible(m, 0.45)[0]


def test_rejects_low_volume_and_closed():
    s = ForecasterStrategy()
    assert not s.market_is_eligible(mk_market(volume=100), 0.45)[0]
    assert not s.market_is_eligible(mk_market(closed=True), 0.45)[0]


# ── The critical bug: p_market must be real ──────────────────

@pytest.mark.asyncio
async def test_proposal_uses_the_real_market_price_not_a_default():
    """THE regression test.

    ForecastResult.market_price used to default to 0.50, and _to_proposal read
    p_market from it. Every proposal therefore claimed p_market = 0.50 no matter
    the real price, which would have fed 0.50 into Kelly sizing and the
    fair-value check.
    """
    client = FakeClient(mid=0.32)
    s = ForecasterStrategy(client=client)

    async def fn(_market):
        return good_forecast(p_raw=0.70)

    res = await s.scan([mk_market(days=30)], forecaster_fn=fn)
    assert len(res.proposals) == 1
    p = res.proposals[0]
    assert p.market_probability == pytest.approx(0.32)
    assert p.market_probability != pytest.approx(0.50)
    assert p.agent_probability == pytest.approx(0.70)


@pytest.mark.asyncio
async def test_no_proposal_when_price_is_unavailable():
    s = ForecasterStrategy(client=None)

    async def fn(_market):
        return good_forecast()

    res = await s.scan([mk_market()], forecaster_fn=fn)
    assert res.proposals == []


# ── Hallucination guards (RESEARCH §2.3) ─────────────────────

@pytest.mark.asyncio
async def test_uncitable_forecasts_are_discarded():
    """If it cannot cite the evidence, it is hallucinating."""
    s = ForecasterStrategy(client=FakeClient(0.40))

    async def fn(_market):
        return good_forecast(citations=())

    res = await s.scan([mk_market()], forecaster_fn=fn)
    assert res.proposals == []
    assert any("hallucination" in e for e in res.errors)


@pytest.mark.asyncio
async def test_skip_is_honoured():
    s = ForecasterStrategy(client=FakeClient(0.40))

    async def fn(_market):
        return good_forecast(skip=True)

    res = await s.scan([mk_market()], forecaster_fn=fn)
    assert res.proposals == []


@pytest.mark.asyncio
async def test_low_confidence_does_not_trade():
    s = ForecasterStrategy(client=FakeClient(0.40))

    async def fn(_market):
        return good_forecast(p_raw=0.90, confidence=0.1)

    res = await s.scan([mk_market()], forecaster_fn=fn)
    assert res.proposals == []


@pytest.mark.asyncio
async def test_mechanical_baseline_never_proposes_a_trade():
    """An uninformed 0.50 prior must produce no signal. If it ever does, the
    edge gate is broken — that is the whole point of keeping this baseline."""
    s = ForecasterStrategy(client=FakeClient(0.40))
    res = await s.scan([mk_market()])
    assert res.proposals == []


@pytest.mark.asyncio
async def test_a_failing_forecaster_is_recorded_not_swallowed():
    s = ForecasterStrategy(client=FakeClient(0.40))

    async def boom(_market):
        raise RuntimeError("provider down")

    res = await s.scan([mk_market()], forecaster_fn=boom)
    assert res.proposals == []
    assert any("provider down" in e for e in res.errors)


# ── Direction ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_buys_yes_when_agent_is_above_market_and_no_when_below():
    s = ForecasterStrategy(client=FakeClient(0.40))

    async def high(_m):
        return good_forecast(p_raw=0.70)

    async def low(_m):
        return good_forecast(p_raw=0.15)

    up = await s.scan([mk_market()], forecaster_fn=high)
    down = await s.scan([mk_market()], forecaster_fn=low)
    assert up.proposals[0].outcome == "Yes"
    assert up.proposals[0].token_id == "yes-token"
    assert down.proposals[0].outcome == "No"
    assert down.proposals[0].token_id == "no-token"


# ── Calibration ──────────────────────────────────────────────

def test_calibration_is_identity_before_enough_samples():
    c = Calibration(min_samples=20)
    c.fit([0.3] * 5, [0, 1, 0, 1, 0])
    assert c.slope == 1.0 and c.intercept == 0.0


def test_calibration_bails_when_every_forecast_is_identical():
    """Zero variance means no relationship to fit.

    Previously the slope was left stale while the intercept was still updated,
    silently turning calibration into a constant shift toward the base rate.
    """
    c = Calibration(min_samples=5)
    c.fit([0.5] * 10, [1, 0, 1, 0, 1, 0, 1, 0, 1, 0])
    assert c.slope == 1.0
    assert c.intercept == 0.0


def test_calibration_fits_a_slope_on_varied_forecasts():
    c = Calibration(min_samples=4)
    c.fit([0.1, 0.3, 0.7, 0.9], [0, 0, 1, 1])
    assert c.slope > 0
    assert 0.0 <= c.calibrate(0.5) <= 1.0


def test_calibrate_always_returns_a_valid_probability():
    c = Calibration(slope=5.0, intercept=-2.0)
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert 0.01 <= c.calibrate(p) <= 0.99


def test_fit_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        Calibration(min_samples=2).fit([0.1, 0.2], [1])


# ── Helper ───────────────────────────────────────────────────

def test_days_until_handles_bad_input():
    assert _days_until(None) is None
    assert _days_until("not-a-date") is None
    assert _days_until((datetime.now(timezone.utc) + timedelta(days=10)).isoformat()) == pytest.approx(10, abs=0.01)
