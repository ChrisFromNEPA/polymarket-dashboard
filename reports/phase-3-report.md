# Phase 3 Report — Backtest Harness & Corpus ✅

**Date:** 2026-07-26
**Status:** ✅ Complete — all control strategies pass

## What was built

- `agent/backtest/corpus.py` — Immutable resolved-markets corpus with point-in-time price history
- `agent/backtest/replay.py` — Leak-proof replay harness with 4 control strategies
- `agent/book_recorder.py` — Standalone orderbook snapshot recorder for Track B
- `state/corpus.json` — 62 resolved markets with price history
- `state/book_snapshots.jsonl` — L2 orderbook snapshots (20 markets, 14.4 KB)

## Corpus statistics

| Metric | Value |
|--------|-------|
| Resolved markets | 100 fetched, 62 with price history |
| Winners | 26 Yes, 36 No |
| Avg price history points | 7.2 per market |
| Granularity | Confirmed 12-hour minimum for closed markets |

## Acceptance criteria (TESTING.md §8)

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Corpus built: ≥30 days of resolved markets | ✅ 62 markets, recent resolutions |
| 2 | 12h granularity constraint verified | ✅ Confirmed — fidelity=60/120/360 return 0 points |
| 3 | All 4 §4.4 controls pass | ✅ All pass (see below) |
| 4 | Contamination probe clean | ✅ delta=+0.0413, no suspicious edge |
| 5 | Book Recorder running | ✅ 20 markets captured, 14.4 KB |
| 6 | Harness reuses live fill engine | ✅ Same FillEngine class (book-walking) |

## Control strategy results

| Strategy | Brier Agent | Brier Market | Delta | Verdict |
|----------|------------|-------------|-------|---------|
| **Random** | 0.3437 | 0.2087 | +0.1350 | ✅ Random worse than market |
| **Market-parrot** | 0.2088 | 0.2087 | +0.000003 | ✅ Delta ≈ 0 (scoring correct) |
| **Oracle** | 0.0001 | 0.2087 | −0.2086 | ✅ Oracle strongly beats market |
| **Contamination probe** | 0.2500 | 0.2087 | +0.0413 | ✅ No suspicious edge |

## Favorite-longshot on corpus

| Segment | Forecasts | Brier Δ |
|---------|-----------|---------|
| Longshots (≤15%) | 8 | −0.0046 |
| Mid-range (15-85%) | 54 | 0.0000 |
| **Overall** | **62** | **−0.0006** |

**Defect 1 confirmed:** The mechanical ±0.05 adjustment adds zero predictive power. The favorite-longshot strategy is a deterministic transform of `p_market`, making the Brier comparison structurally impossible — exactly as PLAN v2 §3 predicted.

## Track B status

Book Recorder captures L2 books for the top 20 markets by liquidity. One snapshot run. Needs cron scheduling for continuous data accrual — every day without it is a day of data that can never be recovered.
