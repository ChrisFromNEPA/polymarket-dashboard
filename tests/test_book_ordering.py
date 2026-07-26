"""Orderbook ordering — the root-cause regression tests.

Polymarket's /book returns levels WORST-FIRST:
    bids ascending  — bids[0] is the LOWEST bid
    asks descending — asks[0] is the HIGHEST ask

Reading index 0 as "best" picks the worst price on both sides. That single
mistake produced essentially every bad result in this project:

  * $0.999 fills — the fill engine walked asks from index 0 (0.999) when the
    real best ask was 0.003
  * "99.8% spreads on 100% of markets" — computing 0.999 − 0.001
  * midpoints pinned at 0.5 — the mean of those two
  * the Phase E verdict that taker execution was dead

Fixture below is the REAL book for the highest-liquidity market on Polymarket
at the time of the fix ("Will Kim Kardashian win the 2028 Democratic
presidential nomination?"), captured verbatim from the API.

Reference: reports/review-04.md
"""

import pytest

from agent.engine.fills import FillEngine
from agent.polymarket.client import PolymarketClient, _parse_book_levels
from agent.polymarket.models import BookLevel, OrderBook

# Verbatim API shape: bids ascending, asks descending.
RAW_BIDS = [{"price": "0.001", "size": "2223085.8"}, {"price": "0.002", "size": "1641243.24"}]
RAW_ASKS = [
    {"price": "0.999", "size": "100"},
    {"price": "0.998", "size": "100"},
    {"price": "0.005", "size": "393452.35"},
    {"price": "0.004", "size": "13000"},
    {"price": "0.003", "size": "574406.79"},
]


def real_book() -> OrderBook:
    return OrderBook(
        token_id="kim2028",
        bids=_parse_book_levels(RAW_BIDS, "bids"),
        asks=_parse_book_levels(RAW_ASKS, "asks"),
    )


# ── Parsing ──────────────────────────────────────────────────

def test_parser_returns_best_first():
    bids = _parse_book_levels(RAW_BIDS, "bids")
    asks = _parse_book_levels(RAW_ASKS, "asks")
    assert bids[0].price == 0.002, "best bid is the HIGHEST bid"
    assert asks[0].price == 0.003, "best ask is the LOWEST ask"


def test_best_bid_and_ask_are_the_real_top_of_book():
    b = real_book()
    assert b.best_bid == 0.002
    assert b.best_ask == 0.003


def test_spread_is_one_tick_not_ninety_nine_percent():
    """The finding that reframes the whole project.

    This market's real spread is a single tick. It was previously measured as
    0.998, which is what made every book look untradeable.
    """
    b = real_book()
    assert b.spread == pytest.approx(0.001, abs=1e-9)
    assert b.spread < 0.01


def test_midpoint_is_not_pinned_to_one_half():
    """mid was (0.001 + 0.999) / 2 = 0.5 for essentially every market, which is
    why 0.5 appeared everywhere in the viability output."""
    b = real_book()
    assert b.mid == pytest.approx(0.0025, abs=1e-9)
    assert b.mid != pytest.approx(0.5, abs=1e-6)


# ── The invariant holds however the book is built ────────────

def test_orderbook_sorts_defensively_on_construction():
    """Callers and tests must not be able to create a mis-ordered book."""
    b = OrderBook(
        token_id="t",
        bids=[BookLevel(0.10, 5), BookLevel(0.40, 5), BookLevel(0.25, 5)],
        asks=[BookLevel(0.90, 5), BookLevel(0.50, 5), BookLevel(0.70, 5)],
    )
    assert [l.price for l in b.bids] == [0.40, 0.25, 0.10]
    assert [l.price for l in b.asks] == [0.50, 0.70, 0.90]
    assert b.best_bid == 0.40
    assert b.best_ask == 0.50


# ── The bug's actual consequence ─────────────────────────────

@pytest.mark.asyncio
async def test_market_buy_fills_at_the_best_ask_not_the_worst():
    """THE regression test. This is the $0.999 trade.

    Buying 1000 shares should fill at 0.003 — the best ask — not 0.999.
    """
    engine = FillEngine(PolymarketClient())
    fill = await engine.market_buy("kim2028", 1000, book=real_book())

    assert fill.filled
    assert fill.avg_price == pytest.approx(0.003, abs=1e-9)
    assert fill.avg_price < 0.01, "must never walk from the worst ask again"
    assert fill.total_cost == pytest.approx(3.0, abs=1e-6)


@pytest.mark.asyncio
async def test_sell_fills_at_the_best_bid_not_the_worst():
    engine = FillEngine(PolymarketClient())
    fill = await engine.market_sell("kim2028", 1000, book=real_book())
    assert fill.filled
    assert fill.avg_price == pytest.approx(0.002, abs=1e-9)


@pytest.mark.asyncio
async def test_round_trip_still_loses_money():
    """Fixing the ordering must not accidentally make trading free — the
    round trip must still pay the spread."""
    engine = FillEngine(PolymarketClient())
    buy = await engine.market_buy("kim2028", 1000, book=real_book())
    sell = await engine.market_sell("kim2028", 1000, book=real_book())
    assert sell.total_cost < buy.total_cost


# ── Viability cost model, on a correct book ──────────────────

def test_required_edge_is_tiny_on_a_correctly_read_book():
    """Phase E reported a required edge of ~0.499 for markets like this.
    Read correctly it is 0.0005 — three orders of magnitude smaller, which
    invalidates the 'taker is dead' verdict.
    """
    from agent.viability import required_edge

    re = required_edge(real_book(), 100)
    assert re == pytest.approx(0.0005, abs=1e-6)
    assert re < 0.02, "well inside the 2c minimum viable edge"
