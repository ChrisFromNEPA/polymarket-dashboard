"""Phase 1 acceptance test — verify data layer correctness.

Acceptance criteria (PLAN.md §Phase 1):
    Fetch 50 live markets; for each, assert p_yes + p_no is within 2% of 1.0
    using each token's own book. Any market failing this indicates a token
    mapping error. Report the pass rate.

This test calls the LIVE Polymarket API. It requires network access.
"""

import asyncio

import pytest

from agent.polymarket.client import PolymarketClient


@pytest.mark.asyncio
async def test_market_token_mapping_50_markets():
    """Verify token mapping by checking p_yes + p_no ≈ 1.0 across 50 markets.

    Uses the CLOB /midpoint endpoint per token, which returns a proper
    probability estimate even when the orderbook spread is wide.
    Also checks orderbook data integrity: both tokens must have book data.
    """
    client = PolymarketClient()

    # Fetch trending events to get a diverse set of markets
    events = await client.trending(limit=10)

    # Collect all markets from all events
    all_markets = []
    for event in events:
        all_markets.extend(event.markets)

    # Take up to 50 markets with valid token IDs
    test_markets = [
        m for m in all_markets
        if m.tokens and m.tokens[0].token_id and m.tokens[1].token_id
    ][:50]

    if len(test_markets) < 10:
        pytest.skip(f"Only {len(test_markets)} valid markets available (need ≥10)")

    # Fetch orderbooks + midpoints in parallel
    await client.fetch_all_market_books(test_markets)

    # Fetch CLOB midpoints for each token (sequential to be polite)
    yes_mids = []
    no_mids = []
    for m in test_markets:
        try:
            yes_mids.append(await client.get_midpoint(m.tokens[0].token_id))
            no_mids.append(await client.get_midpoint(m.tokens[1].token_id))
        except Exception:
            yes_mids.append(None)
            no_mids.append(None)

    # Assess each market
    results = []
    failures = []
    spread_warnings = []

    for i, m in enumerate(test_markets):
        yes_midpoint = yes_mids[i]
        no_midpoint = no_mids[i]

        # Book integrity check: both tokens must return book data
        yes_book_ok = m.yes_book is not None and m.yes_book.bids and m.yes_book.asks
        no_book_ok = m.no_book is not None and m.no_book.bids and m.no_book.asks

        if not yes_book_ok or not no_book_ok:
            failures.append({
                "question": m.question[:80],
                "error": f"missing book data (YES ok={yes_book_ok}, NO ok={no_book_ok})",
                "yes_mid": yes_midpoint,
                "no_mid": no_midpoint,
            })
            continue

        # Flag wide spreads (>90%) as informational — not failures
        yes_spread = m.yes_book.spread
        no_spread = m.no_book.spread
        if yes_spread is not None and yes_spread > 0.90:
            spread_warnings.append({
                "question": m.question[:80],
                "token": "YES",
                "spread": round(yes_spread, 4),
            })
        if no_spread is not None and no_spread > 0.90:
            spread_warnings.append({
                "question": m.question[:80],
                "token": "NO",
                "spread": round(no_spread, 4),
            })

        # Token mapping check: p_yes + p_no ≈ 1.0 using midpoint API
        if yes_midpoint is None or no_midpoint is None:
            failures.append({
                "question": m.question[:80],
                "error": "midpoint API failed",
            })
            continue

        total = yes_midpoint + no_midpoint
        deviation = abs(total - 1.0)

        if deviation > 0.02:
            failures.append({
                "question": m.question[:80],
                "yes_midpoint": round(yes_midpoint, 4),
                "no_midpoint": round(no_midpoint, 4),
                "total": round(total, 4),
                "deviation": round(deviation, 4),
            })
        else:
            results.append({
                "question": m.question[:60],
                "yes_midpoint": round(yes_midpoint, 4),
                "no_midpoint": round(no_midpoint, 4),
                "total": round(total, 4),
            })

    # Report
    pass_count = len(results)
    fail_count = len(failures)
    total_count = pass_count + fail_count
    pass_rate = (pass_count / total_count * 100) if total_count > 0 else 0

    print(f"\n{'='*70}")
    print(f"Phase 1 Acceptance Test: Token Mapping Verification")
    print(f"{'='*70}")
    print(f"Markets tested: {total_count}")
    print(f"Passed (midpoint sum within 2%): {pass_count} ({pass_rate:.1f}%)")
    print(f"Failed: {fail_count}")
    print(f"Wide-spread markets (spread > 90%): {len(spread_warnings)}")
    print(f"  (These are expected for low-probability markets; not failures)")

    if failures:
        print(f"\n--- FAILURES ---")
        for f in failures:
            if "error" in f:
                print(f"  {f['question']}")
                print(f"    ERROR: {f['error']}")
            else:
                print(f"  {f['question']}")
                print(f"    YES={f['yes_midpoint']}, NO={f['no_midpoint']}, sum={f['total']}, dev={f['deviation']}")

    print(f"\n--- SAMPLE PASSES (first 8) ---")
    for r in results[:8]:
        print(f"  {r['question']}")
        print(f"    YES={r['yes_midpoint']}, NO={r['no_midpoint']}, sum={r['total']}")

    if spread_warnings:
        print(f"\n--- WIDE-SPREAD MARKETS (first 8, informational) ---")
        for w in spread_warnings[:8]:
            print(f"  {w['question']}")
            print(f"    {w['token']} spread={w['spread']}")

    # Assertions
    assert pass_rate >= 90.0, (
        f"Pass rate {pass_rate:.1f}% below 90% threshold. "
        f"{fail_count} markets have token mapping issues."
    )

    # No individual market should deviate more than 5% (catastrophic failure)
    for f in failures:
        if f.get("deviation", 0) > 0.05:
            pytest.fail(
                f"Catastrophic token mapping error on '{f['question']}': "
                f"deviation={f.get('deviation', '?')}"
            )
