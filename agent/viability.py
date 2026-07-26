"""Phase E — economic viability study.

Answers the question the project never asked: **is there any configuration in
which this makes money?**

The binding constraint is not forecast quality. It is that `half_spread > edge`
on every market examined so far. This module measures the cost side of that
inequality across the whole market universe, so the viable band — if one exists —
can be found rather than guessed at.

Everything here is READ-ONLY. It places no orders and mutates no state.

Reference: docs/ECONOMICS.md §4
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from agent.polymarket.client import PolymarketClient
from agent.polymarket.models import Market, OrderBook

# Notional sizes to probe. Cost is size-dependent: a book can look tight at $50
# and be catastrophic at $1000, and the agent trades in hundreds.
PROBE_SIZES = (50.0, 200.0, 1000.0)

# Polymarket taker fee in basis points. 0 today; kept explicit so the cost model
# does not silently assume free trading if that changes.
FEE_BPS = 0


# ── Cost model ───────────────────────────────────────────────


def vwap_for_notional(book: OrderBook, side: str, notional: float) -> Optional[float]:
    """Volume-weighted average price to trade `notional` dollars.

    Walks real depth. Returns None if the book cannot absorb the size — that is
    a finding, not an error: a market you cannot get filled in is not tradeable
    regardless of how much edge you think you have.
    """
    levels = book.asks if side == "buy" else book.bids
    if not levels:
        return None

    remaining = notional
    shares = 0.0
    spent = 0.0
    for lvl in levels:
        if remaining <= 0:
            break
        if lvl.price <= 0:
            continue
        level_notional = lvl.price * lvl.size
        take = min(remaining, level_notional)
        take_shares = take / lvl.price
        shares += take_shares
        spent += take
        remaining -= take

    if remaining > 1e-9 or shares <= 0:
        return None  # insufficient depth
    return spent / shares


def required_edge(book: OrderBook, notional: float, fee_bps: int = FEE_BPS) -> Optional[float]:
    """How much better than the market you must be, just to break even.

    You profit only if `fair_value > execution_price`. The market's own estimate
    is the mid. So the edge you must have, per share, is:

        required_edge = buy_vwap(notional) - mid + fees

    If this exceeds any plausible forecasting edge, the segment is dead
    permanently — no model quality fixes it.
    """
    mid = book.mid
    if mid is None or mid <= 0:
        return None
    vwap = vwap_for_notional(book, "buy", notional)
    if vwap is None:
        return None
    fee = (fee_bps / 10_000) * min(vwap, 1.0 - vwap) if fee_bps else 0.0
    return (vwap - mid) + fee


def round_trip_cost(book: OrderBook, notional: float) -> Optional[float]:
    """Cost per share of entering and exiting immediately. Pays the spread twice."""
    buy = vwap_for_notional(book, "buy", notional)
    sell = vwap_for_notional(book, "sell", notional)
    if buy is None or sell is None:
        return None
    return buy - sell


# ── Segmentation ─────────────────────────────────────────────


def liquidity_bucket(liquidity: float) -> str:
    if liquidity >= 500_000:
        return "deep (>=500k)"
    if liquidity >= 100_000:
        return "mid (100k-500k)"
    if liquidity >= 10_000:
        return "thin (10k-100k)"
    return "micro (<10k)"


def price_bucket(mid: Optional[float]) -> str:
    """Spread behaviour differs enormously by price level — longshot books are
    structurally worse, which is exactly where the agent kept trading."""
    if mid is None:
        return "unknown"
    if mid < 0.05 or mid > 0.95:
        return "extreme (<5% or >95%)"
    if mid < 0.20 or mid > 0.80:
        return "longshot (5-20% / 80-95%)"
    return "mid-range (20-80%)"


def horizon_bucket(end_date: Optional[str]) -> str:
    if not end_date:
        return "unknown"
    try:
        end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "unknown"
    days = (end - datetime.now(timezone.utc)).total_seconds() / 86400
    if days < 0:
        return "expired"
    if days < 2:
        return "<2d"
    if days < 30:
        return "2-30d"
    if days < 180:
        return "30-180d"
    return ">180d"


# ── Measurement ──────────────────────────────────────────────


@dataclass
class MarketCost:
    """Measured cost profile for one market's YES token."""
    question: str
    condition_id: str
    token_id: str
    mid: Optional[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    top_of_book_spread: Optional[float]
    liquidity: float
    volume: float
    end_date: Optional[str]
    neg_risk: bool
    liquidity_seg: str = ""
    price_seg: str = ""
    horizon_seg: str = ""
    # required_edge / round_trip keyed by probe size, None = insufficient depth
    required_edge: dict = field(default_factory=dict)
    round_trip: dict = field(default_factory=dict)
    error: Optional[str] = None


async def measure_market(client: PolymarketClient, market: Market) -> MarketCost:
    """Measure the cost profile of a single market's YES book."""
    token_id = market.yes_token_id
    mc = MarketCost(
        question=market.question,
        condition_id=market.condition_id,
        token_id=token_id,
        mid=None, best_bid=None, best_ask=None, top_of_book_spread=None,
        liquidity=market.liquidity,
        volume=market.volume,
        end_date=market.end_date,
        neg_risk=market.neg_risk,
        liquidity_seg=liquidity_bucket(market.liquidity),
        horizon_seg=horizon_bucket(market.end_date),
    )
    if not token_id:
        mc.error = "no token id"
        mc.price_seg = price_bucket(None)
        return mc

    try:
        book = await client.get_book(token_id)
    except Exception as e:  # noqa: BLE001 — a failed book is data, not a crash
        mc.error = f"book fetch failed: {e}"
        mc.price_seg = price_bucket(None)
        return mc

    mc.mid = book.mid
    mc.best_bid = book.best_bid
    mc.best_ask = book.best_ask
    mc.top_of_book_spread = book.spread
    mc.price_seg = price_bucket(book.mid)

    for size in PROBE_SIZES:
        key = f"${int(size)}"
        mc.required_edge[key] = required_edge(book, size)
        mc.round_trip[key] = round_trip_cost(book, size)

    return mc


async def run_study(
    max_markets: int = 300,
    liquidity_min: Optional[float] = None,
    concurrency: int = 4,
) -> dict:
    """Run the full Phase E1/E2 measurement over the market universe."""
    client = PolymarketClient()
    markets = await client.scan_universe(
        max_markets=max_markets, liquidity_min=liquidity_min
    )

    sem = asyncio.Semaphore(concurrency)

    async def guarded(m: Market) -> MarketCost:
        async with sem:
            return await measure_market(client, m)

    results = await asyncio.gather(*(guarded(m) for m in markets))
    return summarise(list(results))


# ── Aggregation ──────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = pct / 100 * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def summarise(costs: list[MarketCost], probe: str = "$200") -> dict:
    """Aggregate into the docs/ECONOMICS.md §4 deliverable table."""
    segments: dict[str, dict] = {}

    for c in costs:
        for dim, seg in (
            ("liquidity", c.liquidity_seg),
            ("price", c.price_seg),
            ("horizon", c.horizon_seg),
        ):
            key = f"{dim}: {seg}"
            bucket = segments.setdefault(
                key, {"n": 0, "tradeable": 0, "required_edges": [], "round_trips": []}
            )
            bucket["n"] += 1
            re_val = c.required_edge.get(probe)
            rt_val = c.round_trip.get(probe)
            if re_val is not None:
                bucket["tradeable"] += 1
                bucket["required_edges"].append(re_val)
            if rt_val is not None:
                bucket["round_trips"].append(rt_val)

    table = []
    for key, b in sorted(segments.items()):
        edges = b["required_edges"]
        table.append({
            "segment": key,
            "markets": b["n"],
            "with_depth": b["tradeable"],
            "depth_rate": round(b["tradeable"] / b["n"], 3) if b["n"] else 0.0,
            "required_edge_p10": _round(_percentile(edges, 10)),
            "required_edge_p50": _round(_percentile(edges, 50)),
            "required_edge_p90": _round(_percentile(edges, 90)),
            "round_trip_p50": _round(_percentile(b["round_trips"], 50)),
        })

    all_edges = [
        c.required_edge.get(probe) for c in costs if c.required_edge.get(probe) is not None
    ]
    # 2c is the minimum viable net edge in ECONOMICS.md §7. A market whose cost
    # already exceeds that leaves nothing for the forecaster to win.
    viable_2c = [e for e in all_edges if e is not None and e <= 0.02]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_size": probe,
        "probe_sizes": [f"${int(s)}" for s in PROBE_SIZES],
        "markets_measured": len(costs),
        "markets_with_depth": len(all_edges),
        "markets_under_2c_cost": len(viable_2c),
        "viable_fraction": round(len(viable_2c) / len(costs), 4) if costs else 0.0,
        "required_edge_p10": _round(_percentile(all_edges, 10)),
        "required_edge_p50": _round(_percentile(all_edges, 50)),
        "required_edge_p90": _round(_percentile(all_edges, 90)),
        "by_segment": table,
        "errors": sum(1 for c in costs if c.error),
    }


def _round(v: Optional[float], dp: int = 4) -> Optional[float]:
    return None if v is None else round(v, dp)


# ── CLI ──────────────────────────────────────────────────────


async def _main() -> None:
    import sys

    max_markets = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    print(f"Phase E — scanning up to {max_markets} markets by liquidity...")
    summary = await run_study(max_markets=max_markets)

    print(f"\nMeasured {summary['markets_measured']} markets "
          f"({summary['markets_with_depth']} had depth at {summary['probe_size']})")
    print(f"Required edge  p10={summary['required_edge_p10']}  "
          f"p50={summary['required_edge_p50']}  p90={summary['required_edge_p90']}")
    print(f"Markets costing <=2c to enter: {summary['markets_under_2c_cost']} "
          f"({summary['viable_fraction']:.1%})\n")

    print(f"{'segment':<34}{'n':>5}{'depth':>7}{'p10':>9}{'p50':>9}{'p90':>9}")
    print("-" * 73)
    for row in summary["by_segment"]:
        print(f"{row['segment']:<34}{row['markets']:>5}{row['depth_rate']:>7.0%}"
              f"{_fmt(row['required_edge_p10']):>9}"
              f"{_fmt(row['required_edge_p50']):>9}"
              f"{_fmt(row['required_edge_p90']):>9}")

    out = "state/viability.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {out}")
    print("\nRead this as: required edge is how much better than the market you")
    print("must be, per share, just to break even. Compare against the achievable")
    print("edge from the Phase 3 corpus (ECONOMICS.md E3).")


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.4f}"


if __name__ == "__main__":
    asyncio.run(_main())
