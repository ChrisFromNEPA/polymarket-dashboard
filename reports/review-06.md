# Code Review 06 — the forecaster (never reviewed until now)

**Date:** 2026-07-26 · **From:** Claude
**Reviewed:** `agent/strategies/forecaster.py`
**Verdict:** 🔴 Would have produced garbage if wired up. Fixed, with 25 tests.
**CI:** 82 passed, 2 xfailed.

This module carries the actual edge and had **never been reviewed or tested**.

---

## 1. 🔴 Every proposal reported `p_market = 0.50`

`ForecastResult.market_price` defaulted to `0.50`, and `_to_proposal` read
`p_market` straight from it:

```python
market_price: float = 0.50      # dataclass default
...
p_market = forecast.market_price # used for edge, sizing, direction
```

`_mechanical_forecast` hardcoded `market_price=0.50`, and nothing required a
`forecaster_fn` to set it. So **every proposal claimed the market was priced at
0.50** regardless of reality — feeding 0.50 into Kelly sizing, the direction
choice, and the fair-value invariant.

This is the same failure shape as the backwards orderbook: a plausible-looking
default silently standing in for real data.

**Fixed:** `market_price` is now `Optional[float] = None`, filled in `scan()` from
the token's own book via `get_midpoint`. A missing price yields no proposal.

---

## 2. 🔴 No market selection — the biggest lever, absent

Only `MIN_VOLUME` was checked. No price range, no horizon, no structure test — so
nothing prevented exactly the 2028 nomination longshots that produced every bad
trade.

**Fixed:** `market_is_eligible()` implements RESEARCH §1 — **7–60 day horizon,
price 0.10–0.90, binary only (NegRisk excluded), ≥$50k volume**. Rejections carry
a reason string so the decision feed shows what was filtered and why.

Regression test asserts the AOC 2028 market (830 days, NegRisk, p=0.1375) **can
never be eligible again**.

---

## 3. 🔴 No hallucination guards

RESEARCH §2.3 names three defences; none existed.

**Fixed:**
- `citations: list[str]` — a forecast with none is **discarded as hallucination**
- `skip: bool` — first-class "no opinion", honoured in `scan()`
- Mechanical baseline now reports `confidence=0.0` so it can **never** clear the
  gate. Previously 0.3, exactly at `MIN_CONFIDENCE`.

---

## 4. 🟠 Calibration bugs

- **Zero-variance path was wrong.** When all forecasts were identical, `slope`
  was left stale while `intercept` was *still updated* — silently turning
  calibration into a constant shift toward the base rate. Now bails entirely.
- **Mislabelled.** The docstring said "Platt scaling / isotonic regression"; it is
  ordinary least squares on raw probabilities — a linear probability model. It
  **cannot express the extremization** RESEARCH §2 says LLM forecasts need, since
  that requires a log-odds transform. Relabelled honestly; the real fix is a
  future task.
- `fit()` now raises on mismatched input lengths instead of silently zipping short.

---

## 5. 🟡 Smaller issues fixed

- Duplicate `if abs_edge < MIN_EDGE` check (appeared twice) — removed.
- `LONG_HORIZON_DAYS` defined and never used — replaced by the real horizon filter.
- Forecaster exceptions were swallowed into a skip counter with no message; they
  are now recorded in `result.errors`.

---

## 6. ⚠️ Still open — market-blind discipline is not enforced

PLAN §5.3 requires the forecaster to produce `p_raw` **before seeing `p_market`**,
or `p_agent` collapses into a transform of the market price (Defect 1).

`scan()` now attaches the price *after* the forecast, which is the right shape.
But `forecaster_fn` receives the whole `Market` object, and if that carries books
the model can still see prices. **The discipline lives in the `forecaster_fn`
implementation and is not structurally enforced.**

When the live LLM forecaster is built, it must be passed a market view stripped of
prices. Worth a test that asserts the view contains no price fields.

---

## 7. Actions

| # | Action | Priority |
|---|---|---|
| 1 | Wire the live LLM forecaster with a **price-stripped** market view | 🔴 |
| 2 | Replace linear calibration with log-odds extremization / Platt | 🟠 |
| 3 | Add `as_of` so retrieval is date-bounded (review-05 §3) | 🟠 |
| 4 | Model tiering + inference ≤5% of bet size (RESEARCH §2.4) | 🟠 |
| 5 | Publish `end_date` on positions so the dashboard horizon check works | 🟠 |

**Note:** the selection filter now lives in the forecaster. The runner still
scans via `trending()`, so it should adopt `market_is_eligible()` too — otherwise
the longshot strategy keeps seeing markets the forecaster would reject.
