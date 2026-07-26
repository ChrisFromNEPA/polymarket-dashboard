"""Phase E cost-model tests.

The viability study's whole value is that its cost numbers are trustworthy. If
`required_edge` is wrong, the go/no-go decision is wrong, and the project either
chases an impossible edge or abandons a viable one.

All arithmetic below is hand-checked in the comments.

Reference: docs/ECONOMICS.md §4
"""

import pytest

from agent.polymarket.models import BookLevel, OrderBook
from agent.viability import (
    horizon_bucket,
    liquidity_bucket,
    price_bucket,
    required_edge,
    round_trip_cost,
    summarise,
    vwap_for_notional,
    MarketCost,
)


def book(bids=None, asks=None):
    return OrderBook(
        token_id="t",
        bids=[BookLevel(price=p, size=s) for p, s in (bids or [])],
        asks=[BookLevel(price=p, size=s) for p, s in (asks or [])],
    )


# Tight, deep book: mid = (0.48 + 0.50) / 2 = 0.49
TIGHT = book(bids=[(0.48, 1000)], asks=[(0.50, 1000)])

# The AOC shape that produced every bad trade.
# mid = (0.80 + 0.999) / 2 = 0.8995
AOC = book(bids=[(0.80, 500)], asks=[(0.999, 5000)])

# Two ask levels, for walking: 0.50 x 100 (=$50), then 0.52 x 100 (=$52)
LADDER = book(bids=[(0.48, 1000)], asks=[(0.50, 100), (0.52, 100)])


# ── VWAP walking ─────────────────────────────────────────────

def test_vwap_single_level():
    """$100 at 0.50 fills entirely on level one."""
    assert vwap_for_notional(TIGHT, "buy", 100) == pytest.approx(0.50)


def test_vwap_walks_multiple_levels():
    """$60: takes all $50 of level one (100 sh), then $10 of level two.

    $10 / 0.52 = 19.2308 sh  ->  total 119.2308 sh for $60
    VWAP = 60 / 119.2308 = 0.50322
    """
    assert vwap_for_notional(LADDER, "buy", 60) == pytest.approx(0.50322, abs=1e-5)


def test_vwap_returns_none_on_insufficient_depth():
    """A book you cannot get filled in is not tradeable, however good the edge."""
    # LADDER holds $50 + $52 = $102 of asks.
    assert vwap_for_notional(LADDER, "buy", 500) is None


def test_vwap_returns_none_on_empty_side():
    assert vwap_for_notional(book(bids=[(0.4, 10)]), "buy", 10) is None


def test_vwap_sell_side_walks_bids():
    assert vwap_for_notional(TIGHT, "sell", 100) == pytest.approx(0.48)


# ── Required edge ────────────────────────────────────────────

def test_required_edge_is_small_on_a_tight_book():
    """mid 0.49, buy VWAP 0.50 -> need 1c of edge to break even."""
    assert required_edge(TIGHT, 100) == pytest.approx(0.01, abs=1e-6)


def test_required_edge_is_brutal_on_the_aoc_book():
    """THE finding that reshaped the plan.

    mid = 0.8995, buy VWAP = 0.999  ->  required edge ~= 0.0995.

    You must beat the market by ~10 percentage points just to break even. No
    forecaster does that reliably, which is why this segment is dead regardless
    of model quality — and why the agent lost money on every one of these.
    """
    re = required_edge(AOC, 200)
    assert re == pytest.approx(0.0995, abs=1e-4)
    assert re > 0.02, "must exceed the 2c minimum viable edge from ECONOMICS.md §7"


def test_required_edge_grows_with_size():
    """Cost is size-dependent — a book tight at $50 can be awful at $1000."""
    small = required_edge(LADDER, 50)
    large = required_edge(LADDER, 100)
    assert small is not None and large is not None
    assert large > small


def test_required_edge_none_without_depth():
    assert required_edge(LADDER, 10_000) is None


# ── Round trip ───────────────────────────────────────────────

def test_round_trip_pays_the_spread_twice():
    """Enter and exit immediately on the tight book: 0.50 - 0.48 = 0.02."""
    assert round_trip_cost(TIGHT, 100) == pytest.approx(0.02, abs=1e-6)


def test_round_trip_is_always_positive():
    """A negative round trip would mean free money from crossing the spread —
    proof the cost model is broken."""
    for b in (TIGHT, AOC, LADDER):
        rt = round_trip_cost(b, 50)
        if rt is not None:
            assert rt > 0


# ── Segmentation ─────────────────────────────────────────────

def test_price_buckets_separate_longshots():
    """Longshot books behave differently and must not be averaged in with
    mid-range ones — that averaging is what hid the problem."""
    assert price_bucket(0.02) == "extreme (<5% or >95%)"
    assert price_bucket(0.99) == "extreme (<5% or >95%)"
    assert price_bucket(0.10) == "longshot (5-20% / 80-95%)"
    assert price_bucket(0.50) == "mid-range (20-80%)"
    assert price_bucket(None) == "unknown"


def test_liquidity_buckets():
    assert liquidity_bucket(1_000_000) == "deep (>=500k)"
    assert liquidity_bucket(50_000) == "thin (10k-100k)"
    assert liquidity_bucket(500) == "micro (<10k)"


def test_horizon_bucket_handles_bad_input():
    assert horizon_bucket(None) == "unknown"
    assert horizon_bucket("not-a-date") == "unknown"


# ── Aggregation ──────────────────────────────────────────────

def _mc(req, price_seg="mid-range (20-80%)"):
    return MarketCost(
        question="q", condition_id="c", token_id="t",
        mid=0.5, best_bid=0.49, best_ask=0.51, top_of_book_spread=0.02,
        liquidity=200_000, volume=100_000, end_date=None, neg_risk=False,
        liquidity_seg="mid (100k-500k)", price_seg=price_seg, horizon_seg="2-30d",
        required_edge={"$200": req}, round_trip={"$200": None if req is None else req * 2},
    )


def test_summary_counts_viable_markets_at_the_2c_bar():
    costs = [_mc(0.005), _mc(0.015), _mc(0.08), _mc(None)]
    s = summarise(costs)
    assert s["markets_measured"] == 4
    assert s["markets_with_depth"] == 3
    assert s["markets_under_2c_cost"] == 2      # 0.005 and 0.015
    assert s["viable_fraction"] == pytest.approx(0.5)


def test_summary_reports_no_viable_markets_honestly():
    """If nothing clears the bar the study must say zero, not round up to hope."""
    s = summarise([_mc(0.09), _mc(0.12)])
    assert s["markets_under_2c_cost"] == 0
    assert s["viable_fraction"] == 0.0


def test_summary_segments_do_not_crash_on_empty_input():
    s = summarise([])
    assert s["markets_measured"] == 0
    assert s["by_segment"] == []
