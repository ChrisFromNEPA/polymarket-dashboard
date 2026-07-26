# Code Review 05 — the backtest harness does not test what the plan says

**Date:** 2026-07-26 · **From:** Claude
**Reviewed:** `agent/backtest/replay.py`
**Verdict:** 🟠 The "4 control strategies all pass" claim is true of the checks as
*implemented*, but the implemented checks are materially weaker than the spec —
and the most important one was silently replaced.

---

## Why this matters

`docs/TESTING.md` §4.4 makes these controls the gate for the whole project:

> Nothing downstream is trustworthy until these pass.

They were run ad hoc and **never had a regression test**. That is the same pattern
that let the Phase E result stand: a claim nothing independently verified.

---

## 1. 🔴 The random control does not test what it was specified to test

**Spec** (TESTING.md §4.4, PLAN Phase 3 acceptance):

> **Random** — trade at market, random side → ≈ **negative the cost of trading**.
> If random shows profit, the harness fabricates edge — **stop**.

**Implemented** (`replay.py:194`):

```python
passed = r.brier_delta > 0   # random has worse Brier than the market
```

That is a **Brier** check, not a **P&L** check. They are different claims, and
the substitution removes the only test that would catch a harness that
manufactures profit.

Worse, TESTING.md §4.4 also requires:

> Reuses the **exact same fill engine** as live. No separate backtest fill path —
> that divergence is how backtests come to lie.

**The harness never touches the fill engine.** `ForecastResult` carries no price
paid, no size, no fees, no P&L. It is a *forecast scorer*, not a backtester.

**Consequence:** the harness can tell you whether forecasts are well-calibrated.
It **cannot** tell you whether a strategy makes money, and it never could have —
so the Phase 3 acceptance criterion has never actually been met.

**Fix:** route control trades through `FillEngine` against corpus book data and
assert `pnl < 0` for random. If book history is unavailable (it is — see
TESTING.md §2), then say so explicitly and stop claiming P&L backtests are
possible at all.

---

## 2. 🔴 The contamination probe cannot detect contamination

```python
def contamination_probe(p_market, _outcome_hidden=0):
    return 0.50
```

A constant 0.50 always scores Brier 0.25. The check is:

```python
passed = abs(r.brier_delta) < 0.05     # i.e. |0.25 − brier_market| < 0.05
```

So it passes only when `brier_market ∈ [0.20, 0.30]` — that is a test of **whether
the market was uninformative**, not whether data leaked.

Two failure modes, both bad:

- On a **well-calibrated** corpus (`brier_market` ≈ 0.02) it reports
  **"POSSIBLE DATA LEAK"** when nothing leaked. A false alarm that will be
  rationalised away the first time it fires.
- It can **never** detect a real leak, because a constant has no data access.
  Nothing can leak into `return 0.50`.

**Fix:** a contamination probe must run the **actual forecaster**, with retrieval
enabled, on markets whose outcomes were genuinely unknowable at time T, and check
for suspicious edge. Until the forecaster is live, this control should be marked
*not yet implementable* rather than reported as passing.

---

## 3. 🟠 Point-in-time discipline is claimed but not enforced

The module docstring says:

> Enforces: at simulated time T, the strategy sees ONLY data ≤ T.

Nothing enforces it. `run()` passes a single float (`p_market`) to the forecaster,
so there is nothing to leak — the claim is **vacuous today and unearned
tomorrow**. When a retrieval-backed forecaster is plugged in, the harness offers
no mechanism to bound its data access.

TESTING.md §4.2 calls the retrieval leak the worst of five, and says to assume the
date filter is broken until proven otherwise. That proof does not exist.

**Fix:** pass an explicit `as_of` timestamp into the forecaster interface and make
retrieval accept it, so the bound is structural rather than aspirational.

---

## 4. 🔴 The oracle threshold false-negatives on a well-calibrated corpus

**Found by CI on its first run**, via a test of mine that failed for a better
reason than I wrote it for.

`verify_controls` requires `brier_delta < -0.1` for oracle. But `brier_delta` is
bounded by how badly the market was priced: on a well-calibrated corpus
`brier_market` is already ~0.024, so **even a perfect oracle can only reach
−0.024** and the check reports:

```
✗ oracle failed — wiring broken
```

…when nothing is broken. Measured on a six-market calibrated fixture:
`brier_agent = 0.0001`, `brier_market = 0.0242`, `delta = −0.0241`. Fails a
threshold of −0.1 by 4×.

This is the **same class of defect as the contamination probe (§2)**: the
threshold encodes an assumption about how mispriced the market is, rather than
testing whether the harness works. Both will fire spuriously precisely when the
data is *good*, which is when a spurious alarm is most likely to be rationalised
away.

Separately, `control_oracle` is handed `market.outcome` directly, so it can never
fail for an interesting reason. It is a plumbing check and should be labelled one.

**Fix:** assert oracle achieves near-zero *absolute* Brier (`brier_agent < 0.001`)
and wins every market (`edge_count == count`), rather than a fixed delta against
an unknown baseline.

---

## 5. 🟡 Sampling is arbitrary; one parameter is dead

- `mid_idx = len(price_history) // 2` — one sample per market, always at
  mid-history. With 12h granularity and variable history lengths, that samples
  wildly different times-to-resolution across markets, with no record of which.
- `sample_every_n` is accepted and **never used**.

**Fix:** sample at a controlled *time-to-resolution* (e.g. T−30d, T−7d) so results
are comparable, and record it on each `ForecastResult`. Either implement
`sample_every_n` or remove it.

---

## What I added

- **`tests/test_backtest_controls.py`** — pins real behaviour, including the
  market-parrot control scoring **exactly** zero delta (the direct regression test
  for Defect 1), that non-oracle strategies never receive the outcome, and
  determinism under a fixed seed.
- Gaps 1 and 2 are recorded as **`xfail`** rather than silently omitted, so they
  surface in CI as known-missing and flip to a failure the moment someone fixes
  them.
- **`.github/workflows/tests.yml`** — CI on every push to `agent/` or `tests/`,
  plus an import check that catches the "renamed a function, forgot a caller"
  class of breakage.

---

## Why CI matters more than any individual fix here

**Every bug in this project has been found by manual review.** The backwards
orderbook survived two weeks. Two test files I wrote sat unrun for days because I
have no Python locally and the run kept slipping.

CI removes that dependency entirely: code that does not pass cannot sit quietly in
`main`. It would not have caught the orderbook bug — no test existed for it — but
it will catch every regression from here, and it makes "I wrote code I cannot run"
a solved problem rather than a recurring risk.

---

## Actions

| # | Action | Priority |
|---|---|---|
| 1 | Route control trades through `FillEngine`; assert random loses money — or state plainly that P&L backtesting is impossible without book history | 🔴 |
| 2 | Replace the contamination probe with one that runs the real forecaster; mark it *not implementable* until then | 🔴 |
| 3 | Add `as_of` to the forecaster interface so point-in-time is structural | 🟠 |
| 4 | Fix the oracle check: assert `brier_agent < 0.001` and `edge_count == count`, not a fixed −0.1 delta | 🔴 |
| 5 | Sample at controlled time-to-resolution; implement or delete `sample_every_n` | 🟡 |
