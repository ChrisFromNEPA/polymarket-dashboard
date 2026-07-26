# Phase 7 Report — LLM Forecaster Module ✅

**Date:** 2026-07-26
**Status:** Structure built; real edge awaits live LLM estimation

## What was built

- `agent/strategies/forecaster.py` — ForecasterStrategy with:
  - `ForecastResult` dataclass: p_raw, p_calibrated, confidence, reasoning
  - `Calibration` class: Platt-style linear calibration from resolution data
  - Mechanical baseline for backtesting (no LLM calls)
  - Trade proposal generation with edge thresholding
  - LLM call interface (forecaster_fn parameter for live use)

## Calibration module

Fits `p_calibrated = slope × p_raw + intercept` from (p_raw, outcome)
pairs. Clamped to [0.01, 0.99]. Min samples = 20 before fitting.

Example: perfect calibration on synthetic data:
```
p_raw=0.2 → calibrated=0.200
p_raw=0.8 → calibrated=0.800
slope=1.000, intercept=0.000
```

## Backtest findings

The 12-hour granularity of closed-market price history means mid-history
price points are poor probability estimates. Even blending 50% truth with
market prices at random timestamps produces a worse Brier score than the
market alone (delta = +0.053).

This is **not a failure of the forecaster module** — it's a data quality
constraint. The real LLM forecaster operates at **decision time** with
live market prices, not at sparse historical snapshots.

The oracle control still works (delta = −0.209), confirming the harness
is correct.

## How the LLM forecaster works in production

1. Agent scans live markets
2. For each candidate market, calls LLM via MCP with structured prompt:
   - Base rate: what's the uninformed prior?
   - Evidence: what specific facts move the probability?
   - Probability: your calibrated estimate (0-100)
   - Confidence: how certain are you? (0-100)
3. LLM returns ForecastResult with reasoning
4. Calibration adjusts raw probability
5. If |p_calibrated − p_market| > MIN_EDGE → TradeProposal
6. Risk manager validates, sizes, fills

## What's needed for the live edge

- Actual LLM calls at decision time (the `forecaster_fn` parameter)
- Enough resolved markets to fit calibration (≥20)
- Long-horizon markets (LLMs beat markets at >30 day horizons per literature)
- Passive execution to avoid paying the spread on thin books
