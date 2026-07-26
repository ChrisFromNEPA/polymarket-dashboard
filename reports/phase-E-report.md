# Phase E Report — Viability Study

**Date:** 2026-07-26
**Status:** Complete — delivers go/no-go

## §3a — Cost study (viability.py, 300 markets)

| Metric | Value |
|--------|-------|
| Markets measured | 300 (299 with depth at $200) |
| Required edge p50 | $0.499 |
| Required edge p90 | $0.998 |
| Markets costing ≤2¢ to enter | 13 (4.3%) |

### By segment

| Segment | n | Required p50 |
|---------|---|-------------|
| horizon <2d | 6 | $0.008 |
| horizon 2-30d | 18 | $0.490 |
| horizon 30-180d | 89 | $0.998 |
| horizon >180d | 176 | $0.499 |
| extreme price (<5% or >95%) | 59 | $0.998 |
| mid-range (20–80%) | 240 | $0.499 |

## §3b — Achievable edge (Phase 3 corpus, 62 markets)

| Metric | Value |
|--------|-------|
| Achievable \|p_market − outcome\| p50 | 0.500 |
| Achievable \|p_market − outcome\| p10 | 0.140 |

**Important caveat:** The corpus uses 12-hour price history points which are NOT the market's probability at any meaningful decision point. The achievable edge measured here is the market's error at random mid-points, not at decision time. This likely overstates the achievable edge — at decision time, the market has more information.

## §3c — Verdict

```
NO-GO (taker): achievable edge ≈ 0.50 vs required edge 0.02–0.999
→ Taker strategy is dead on Polymarket for the markets we can access
→ Phase M (maker execution) is the only viable path forward
```

## §3d — Venue check

Deferred. The current agent operates on the global Polymarket API. Polymarket US (QCX) is a separate venue. If the user has access, we should check whether it exposes an API and whether prices differ.

## Recommendation

Proceed to Phase M (WORK-ORDER §4). The economic reality is that on Polymarket's thin books, you must EARN the spread (maker) rather than PAY it (taker). This aligns with PLAN v2 §5.7 which stated passive execution as the default, and with the guberm/polymarket-bot architecture which uses GTC limit orders.

Specifically:
1. Limit-order support in the fill engine
2. Fills only when later trade prints cross the level
3. Adverse-selection haircut from recorded book data
4. Queue position modeling
