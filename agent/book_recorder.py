#!/usr/bin/env python3
"""Book Recorder — snapshots Polymarket orderbooks for Track B replay.

Runs as a standalone cron job, fully independent of trading.
Its only job: accrue data you cannot get later.

Usage:
    python3 agent/book_recorder.py              # One snapshot, then exit
    python3 agent/book_recorder.py --watch 30   # Watch top 30 markets

Storage: state/book_snapshots.jsonl (append-only JSON lines)
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.polymarket.client import PolymarketClient

SNAPSHOT_FILE = Path("state/book_snapshots.jsonl")


async def snapshot_market(client: PolymarketClient, market) -> dict | None:
    """Capture full L2 book for both outcome tokens."""
    try:
        tokens = market.tokens if hasattr(market, 'tokens') else []
        if len(tokens) < 2:
            return None

        yes_book = await client.get_book(tokens[0].token_id)
        no_book = await client.get_book(tokens[1].token_id)
        yes_mid = await client.get_midpoint(tokens[0].token_id)
        no_mid = await client.get_midpoint(tokens[1].token_id)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "condition_id": market.condition_id,
            "question": market.question[:120],
            "volume": market.volume,
            "liquidity": market.liquidity,
            "yes": {
                "token_id": tokens[0].token_id,
                "midpoint": yes_mid,
                "best_bid": yes_book.best_bid,
                "best_ask": yes_book.best_ask,
                "spread": yes_book.spread,
                "bid_depth": sum(b.size for b in yes_book.bids[:5]),
                "ask_depth": sum(a.size for a in yes_book.asks[:5]),
            },
            "no": {
                "token_id": tokens[1].token_id,
                "midpoint": no_mid,
                "best_bid": no_book.best_bid,
                "best_ask": no_book.best_ask,
                "spread": no_book.spread,
                "bid_depth": sum(b.size for b in no_book.bids[:5]),
                "ask_depth": sum(a.size for a in no_book.asks[:5]),
            },
        }
    except Exception as e:
        return {"timestamp": datetime.now(timezone.utc).isoformat(), "error": str(e)}


async def run_snapshot(watch_count: int = 30):
    """Take one snapshot of the top N markets by liquidity."""
    client = PolymarketClient()

    # Get top markets by liquidity (tighter spreads = more useful book data)
    events = await client.trending(limit=15)
    all_markets = []
    for e in events:
        all_markets.extend(e.markets)

    # Sort by liquidity descending, take top N
    all_markets.sort(key=lambda m: m.liquidity, reverse=True)
    targets = all_markets[:watch_count]

    snapshots = []
    for m in targets:
        snap = await snapshot_market(client, m)
        if snap and "error" not in snap:
            snapshots.append(snap)

    # Append to JSONL
    with open(SNAPSHOT_FILE, "a") as f:
        for snap in snapshots:
            f.write(json.dumps(snap) + "\n")

    # Stats
    file_size = SNAPSHOT_FILE.stat().st_size if SNAPSHOT_FILE.exists() else 0
    line_count = 0
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE) as f:
            line_count = sum(1 for _ in f)

    print(f"Snapshot: {len(snapshots)} markets captured")
    print(f"Total snapshots: {line_count} lines, {file_size/1024:.1f} KB")
    print(f"File: {SNAPSHOT_FILE.absolute()}")

    return len(snapshots)


if __name__ == "__main__":
    watch = 30
    if "--watch" in sys.argv:
        idx = sys.argv.index("--watch")
        if idx + 1 < len(sys.argv):
            watch = int(sys.argv[idx + 1])

    asyncio.run(run_snapshot(watch_count=watch))
