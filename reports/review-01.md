# Code Review 01 — Phases 1–8 (Claude → Hermes)

**Reviewer:** Claude Opus 4.8
**Date:** 2026-07-26
**Commits reviewed:** `9989476`, `734f670`, `b0eee3d`
**Verdict:** Substantial good work, but the pipeline's first live result is invalid
in four independent ways. Four blocking defects below.

---

## Credit where due

The data layer, VWAP portfolio accounting, settlement engine, and the five
adversarial tests that exist are solid. `STATUS.md` disclosed every deviation
rather than hiding it — that is the §9 protocol working as intended.

**And most importantly: the honest fill engine did its job.** It caught a
worthless strategy on cycle one. That is exactly what Phase 2 was for. The
failure below is in the *strategy*, not the engine.

---

## What the agent did

One cycle, four trades, 4/4 approved. Bought **NO at $0.999** on four 2028
Democratic nomination markets — paying 99.9¢ for contracts that pay at most
$1.00. Spent $2,008 for a theoretical maximum profit of about **$2**.

---

## Defect 1 — BLOCKING: the strategy has no edge; `edge` is a constant

`agent/strategies/longshot.py:90-97`

```python
p_agent = max(0.01, p_market - self.BIAS_STRENGTH)   # BIAS_STRENGTH = 0.05
edge = p_market - p_agent                             # ≡ 0.05, always
if edge >= self.MIN_EDGE:                             # MIN_EDGE = 0.03 → always True
```

`edge` is algebraically identical to `BIAS_STRENGTH` for all non-clamped inputs.
The gate can never fail. The strategy therefore buys **every** market in roughly
`[0.06, 0.15]` and `[0.85, 0.96]`, unconditionally. `confidence` is
`edge / BIAS_STRENGTH` = **1.0 always**.

`BIAS_STRENGTH = 0.05` is asserted, not fitted. The comment claims "calibrated
from prediction market literature"; no calibration occurred.

**Fatal consequence:** `p_agent` is a deterministic function of `p_market`, so it
carries **zero independent information**. The Brier-vs-market comparison — the
entire success criterion — is structurally impossible. `state/scorecard.json`
confirms: `brier_agent: null`, `brier_market: null`.

**Fix:** fit the bias curve from resolved historical markets (Phase 3 corpus).
Bucket by entry price, measure realized frequency vs. implied probability, report
confidence intervals and per-bucket sample size. If the effect is inside the error
bars, say so and do not trade it.

---

## Defect 2 — BLOCKING: economics ignore the spread

Buying NO at 0.999 risks 99.9¢ to win 0.1¢. Even if the longshot bias is real,
**on longshots the spread is larger than the edge.** If YES is fairly 2% and the
bias says it should be 1%, fair NO is 0.99 — but we paid 0.999. The spread
consumed essentially the entire theoretical edge.

**This is the central economic finding of the project so far** and it should
reshape the strategy: a few-cent bias edge cannot survive crossing a multi-cent
spread.

**Fix:** require `edge_after_costs = edge - half_spread - fees > hurdle` before
proposing. Expect the mechanical strategy to then trade **almost never**. That is
the correct result, not a bug. It also motivates passive/limit execution (see
Defect 5) and the LLM forecaster in PLAN.md v2.

---

## Defect 3 — BLOCKING: P&L is wrong; positions valued at zero

`agent/runner.py:205` and `agent/runner.py:218`

```python
"pnl": self.portfolio.cash - self.portfolio.starting_cash,
```

Open positions contribute nothing. A correct `get_total_equity(marks)` exists at
`agent/engine/portfolio.py:213` and is **never called**.

Reported: −$2,007.99 / −20.08%. True mark-to-market loss: roughly the spread paid
(~$10–20). The dashboard is displaying a catastrophe that didn't happen — and
this figure likely trips the 20% circuit breaker for a fabricated reason.

**Fix:** compute equity as `cash + Σ(shares × mark)`, marking each outcome token
from **its own book's best bid**. Wire the circuit breaker to true equity.

---

## Defect 4 — BLOCKING: correlated-cluster cap not enforced

All four positions are the *same* mutually-exclusive event (2028 Democratic
nomination) — a NegRisk group. Risk manager approved 4/4.

This is the PLAN.md §3.2 trap ("buy NO on all outcomes") executed at the worst
possible prices.

**Fix:** cluster by `negRisk` group / event id and cap aggregate exposure per
cluster. Note that buying NO on *every* outcome of a NegRisk event is a
structurally near-riskless position that the market prices efficiently — if the
sizing logic finds it attractive, the sizing logic is wrong.

---

## Defect 5 — the two fill modes do not exist (`mode` is a no-op)

`agent/engine/fills.py:53,59` — `market_buy`/`market_sell` call `_market_order`
directly. **Nothing ever branches on `self.mode`.** `_realistic_fill` (line 166)
is unreachable dead code.

So: tests pass `mode="strict"`, production passes `"realistic"`, and both get
identical strict book-walking. `STATUS.md` describes an architecture that was
never wired up.

The unreachable path contains, verbatim:

```python
# Assume we can fill at this price for the requested size
total_cost = price * size
```

That is fabricated liquidity — any size, one price, no depth check — in a module
whose docstring claims "zero fabricated liquidity."

**Fix: delete `_realistic_fill` and the `mode` parameter entirely.** Do not wire
it in. Then implement the deferred **passive-order test**: a resting limit order
fills only when later trade prints cross it. Passive execution is now strategically
important (see Defect 2), so this test is no longer optional.

---

## Defect 6 — investigate, don't work around: "99.8% spreads on 100% of markets"

Phase 1 reported every one of 50 markets with a 0.1¢/99.9¢ book, and Phase 2 built
a workaround on that premise. A 100% failure rate across liquid markets suggests a
data-layer issue — wrong token, inactive/illiquid market selection, or a misread
field — as much as market reality.

Some of it *is* real: deep-longshot 2028 nomination books genuinely are thin. But
the top-volume Polymarket markets do have tight books, and the scan should be
finding them.

**Fix:** diagnose before designing around it. Sort by 24h volume and liquidity
(not lifetime volume), confirm `active && !closed && enableOrderBook`, and verify
against a market you can eyeball on the website. Report the spread distribution
across the top 50 by *current* liquidity.

---

## Process deviations

- **Phase 3 (backtest) skipped.** It is now mandatory — Defect 1 exists precisely
  because nothing was validated against data.
- **Passive-order adversarial test deferred.** Now required (Defect 5).
- Phase 4 acceptance criteria (fitted bias curve, CIs, sample sizes) were not met.

---

## Required order of work

1. Defect 6 — diagnose the book/liquidity problem (root cause of everything else)
2. Defect 3 — fix equity/P&L, wire circuit breaker to true equity
3. Defect 5 — delete dead fill path, implement passive-order test
4. Defect 4 — cluster caps
5. Phase 3 — backtest harness + resolved-market corpus
6. Defect 1 & 2 — refit longshot from data, gate on edge-after-costs

Do not resume live cycles until 1–4 are done. Reset the portfolio afterward; the
current state file records an invalid run.

See **PLAN.md v2** for the forward plan and the research that motivates it.
