# Testing & Simulation Architecture

**Version:** 1.0 · 2026-07-26
**Status:** design — implement as PLAN.md Phase 3
**Answers:** "can we use a month of previous Polymarket data to simulate the bot?"

---

## 1. The short answer

**Yes for forecasting skill. No for execution. And the reason matters enormously.**

You can replay a month (or a year) of resolved markets and measure whether the
agent forecasts better than the market did. That is the core experiment and it can
start today.

You **cannot** faithfully replay how the agent's orders would have *filled*,
because the data required to do that does not exist anywhere — not from
Polymarket, not from the subgraphs, not from any third party.

Conflating these two is the single most common way a trading backtest lies. So we
split them into two tracks and never let one borrow the other's credibility.

---

## 2. The hard constraint (verify before designing around it)

### 2.1 No historical order books exist

`/prices-history` returns **prices**, not depth. The subgraphs index **trades**,
not resting book state. Nobody archives Polymarket L2 book snapshots publicly.

Since our fill engine walks book depth, there is **nothing to walk** for a past
moment in time. Any historical fill number is a model, not a measurement.

### 2.2 Resolved markets are capped at 12-hour granularity

[py-clob-client issue #216](https://github.com/Polymarket/py-clob-client/issues/216):
`/prices-history` returns data at **12+ hour granularity for closed markets**.
Hourly (`fidelity=60`) requests come back **empty** — confirmed even on the 2024
US Presidential market, the highest-volume market in the platform's history. The
issue is open with no Polymarket response and no workaround.

**Consequence:** historical replay operates on 12h candles. That is:
- ✅ **fine** for long-horizon forecasting — which is exactly our v2 pivot (PLAN §5.1)
- ❌ **useless** for intraday, market-making, or latency strategies

Hermes: **verify both of these yourself in Phase 3 before building.** If you find
finer data or a book archive, that changes the design and is worth a loud report.

---

## 3. Three tracks

| Track | Tests | Data | Available | Covers |
|---|---|---|---|---|
| **A — Forecast backtest** | Predictive skill (Brier vs market) | Resolved markets + 12h prices | **Today** | Months/years |
| **B — Execution replay** | Fills, spread, slippage, passive fill rate | Recorded book snapshots | **After ~30 days of recording** | From start date |
| **C — Shadow mode** | End-to-end, live, no risk | Live books, decisions logged | **Today** | Forward only |

**Start A and the Track-B recorder on the same day.** B's data does not exist
retroactively — every day you delay is a day you can never test against.

---

## 4. Track A — Forecast backtest

This is what answers "how would the bot have done last month."

### 4.1 Build the corpus

```
GET https://gamma-api.polymarket.com/markets
      ?closed=true
      &end_date_min=<T-30d>
      &end_date_max=<T>
      &limit=500&offset=<paginate>
```

The Gamma markets endpoint supports `closed`, `end_date_min` / `end_date_max`,
`liquidity_num_min`, `volume_num_min`, `uma_resolution_status`, plus `limit` /
`offset` and `order`.

Capture per market:

| Field | Use |
|---|---|
| `question`, `description` | prompt input — **description holds the resolution criteria** |
| `outcomes`, `outcomePrices` | **ground-truth label** — winner is the outcome whose final price ≈ 1 |
| `clobTokenIds` | fetch price history per outcome token |
| `closedTime`, `umaResolutionStatus` | resolution timing; drop anything disputed/unresolved |
| `volumeNum`, `liquidityNum` | filters + execution model input |
| `negRisk`, `conditionId` | cluster grouping |

Then per token: `GET /prices-history?market=<token_id>&interval=max&fidelity=720`.

Store in SQLite. Treat the corpus as **immutable once built** — rebuilding it
after seeing results is how overfitting sneaks in. Version it.

### 4.2 Point-in-time discipline — the thing that will break this

At simulated time `T`, the agent may see **only** data timestamped `≤ T`. Every
backtest failure mode here is a leak.

**Five leaks to close, in order of danger:**

1. **Retrieval leak (worst).** News/web search will happily return articles
   published *after* resolution. If your retrieval tool cannot hard-filter by
   publication date, **Track A is invalid** — do not proceed until it can. Assume
   the filter is broken until you prove it works.
2. **Parametric leak.** The model's own training data may contain the outcome.
   Mitigate by preferring markets that resolved **after the model's knowledge
   cutoff** — for current models that means recent resolutions are safest, which
   happily coincides with "last month."
3. **Field leak.** Never pass `outcomePrices`, `closedTime`, resolution status, or
   the final price into the prompt. Build the prompt from an explicit allowlist of
   fields, not by dumping the market object.
4. **Selection leak.** Filtering the corpus by anything only knowable after
   resolution (e.g. "markets that ended cleanly") biases results. Filter on
   `T`-observable fields only.
5. **Tuning leak.** Hold out a slice the tuner never sees. Thresholds and
   calibration fit on train; report on holdout.

**Contamination probe (mandatory):** run the forecaster on a set of markets whose
outcomes were genuinely unknowable at `T` — coin-flip-ish, low-information
markets. If Brier comes back suspiciously good, you have a leak. Run this probe
*before* trusting any headline result.

### 4.3 Execution model — honest about being a model

No historical books, so synthesize costs and **say so on every output**:

1. **Calibrate from live data.** Sample live books now across liquidity and price
   buckets. Fit `spread ≈ f(liquidity, price_level, time_to_resolution)`.
   Deep-longshot books really are ~99% wide; top markets are tight. The model must
   reproduce that shape.
2. **Apply conservatively.** Bias toward wider spreads and worse fills.
3. **Report a band, never a point.** Every P&L figure gets optimistic / central /
   pessimistic execution. If the strategy is only profitable under optimistic
   execution, it is not profitable.
4. **Label it.** Any Track-A P&L is tagged `execution: modeled`. Only Track B and
   live forward trading produce `execution: measured`.

**Brier is unaffected by all of this** — it depends only on `p_agent`,
`p_market`, and the outcome. That is precisely why Brier is the primary metric:
it is the one number a missing book cannot corrupt.

### 4.4 Control strategies — the harness must pass these first

Run before any real strategy. These bound the harness:

| Control | Expected result | If violated |
|---|---|---|
| **Random** — trade at market, random side | ≈ **negative** the cost of trading | Harness fabricates edge — **stop** |
| **Market-parrot** — `p_agent = p_market` | Brier delta ≈ **0.000** | Scoring is broken |
| **Oracle** — `p_agent =` true outcome | Strongly positive | Wiring is broken (upper bound only) |
| **Contamination probe** (§4.2) | No edge on unknowable markets | Leak — **stop** |

The market-parrot control is the direct regression test for the Defect-1 failure
(PLAN §3): a strategy whose `p_agent` is a transform of `p_market` **must** score
a Brier delta of zero. If it shows edge, the metric is lying.

---

## 5. Track B — Execution replay (start recording today)

### 5.1 The Book Recorder

A standalone cron job, fully independent of trading. Its only job is to accrue
data you cannot get later.

- **Watchlist:** top N markets by *current liquidity*, plus every market the agent
  holds or has evaluated.
- **Interval:** 5–15 min (start at 10).
- **Capture per snapshot:** full L2 book for **both** outcome tokens, midpoint,
  spread, last trade price, timestamp.
- **Storage:** SQLite, compressed. Estimate size for 30 days before starting and
  report it — this is the one component with real disk cost.
- **Robustness:** it must never crash the trading agent, and must survive restarts
  without gaps. Log gaps explicitly; a silent gap is worse than a missing day.

### 5.2 What it unlocks after ~30 days

- Replaying fills against **real depth** — measured, not modeled
- **Passive fill rates**: how often does a resting limit order actually get taken?
  Critical, because PLAN v2 §5.7 makes passive execution the default
- Calibrating the Track-A execution model against measured reality
- Realistic slippage by size

### 5.3 It also validates the fill engine

Once book history exists, re-run the Phase 2 adversarial tests against **recorded
real books** rather than hand-built fixtures. That closes the loop on the one
component everything else depends on.

---

## 6. Track C — Shadow mode

Between "backtest" and "trading," run the agent live with execution disabled:
scan, forecast, size, log the decision and the market state — then do nothing.

- Zero risk, real-time, uses live books
- Produces the `p_agent` / `p_market` pairs needed for Brier as markets resolve
- Surfaces operational bugs (rate limits, crashes, gaps) before money is at stake
- **Run shadow mode continuously, forever**, alongside live paper trading — it is
  the cheapest source of calibration data and the control group for the traded set

---

## 7. What "a month of results" will and won't tell you

**Will:**
- Whether `brier_agent < brier_market` on ~30 days of resolutions
- Calibration curve and ECE, and whether post-hoc calibration improves them
- Whether modeled costs exceed the modeled edge (this alone may kill a strategy —
  and it is the most likely outcome for favorite-longshot)

**Won't:**
- Actual fill quality — that needs Track B
- Whether the edge survives real passive execution
- Statistical significance. **A month is not enough.** With ~100–200 resolutions
  and a small Brier delta, a one-month result is a smoke test, not a verdict.
  Report confidence intervals and resist concluding anything from a point estimate.

**Sample-size guidance:** report the paired Brier delta with a bootstrap CI. If
the CI crosses zero, the honest statement is "no detectable edge yet," not "the
agent is winning."

---

## 8. Acceptance criteria (PLAN Phase 3)

1. Corpus built: ≥30 days of resolved markets with outcomes, price history, and
   resolution criteria. Report count, date range, and filters applied.
2. Both §2 constraints independently verified and reported (12h granularity; no
   book archive).
3. All four §4.4 controls pass. **Random must lose money.**
4. Contamination probe clean; retrieval date-filtering proven to work.
5. Book Recorder running, with a 7-day gap report and disk-usage projection.
6. Harness reuses the **live fill engine** — no separate backtest fill path.
7. Every P&L output tagged `modeled` or `measured`.

---

## 9. Sequencing

```
Day 0   ├─ Start Book Recorder                    (data starts accruing)
        ├─ Build Track A corpus (last 30–90 days)
        └─ Implement §4.4 controls  ← gate: random must lose
Day 1-3 ├─ Track A: longshot backtest → expect "no edge after costs"
        └─ Track A: forecaster v1 → first real Brier vs market
Day 3+  └─ Track C shadow mode continuous
Day 30  └─ Track B replay unlocked → validate fills against real books
```

Nothing downstream is trustworthy until the §4.4 controls pass.

---

## 10. References

- [prices-history API](https://docs.polymarket.com/api-reference/markets/get-prices-history) ·
  [Gamma list markets](https://docs.polymarket.com/api-reference/markets/list-markets)
- [Issue #216 — 12h granularity on resolved markets](https://github.com/Polymarket/py-clob-client/issues/216)
- [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills) — 8 reference docs incl. `market-data.md`
- [warproxxx/poly_data](https://github.com/warproxxx/poly_data) — evaluate as corpus shortcut
- [ForecastBench](https://www.forecastbench.org/) — external calibration benchmark
