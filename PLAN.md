# Polymarket Autonomous Forecasting Agent — Build Plan v2

**Version:** 2.0 (supersedes v1.0 of 2026-07-26)
**Status:** Phase 2.5 — remediation, then Phase 3
**Owner:** Hermes agent (Nous Research), always-on Ubuntu VM
**Human:** ChrisFromNEPA
**Last updated:** 2026-07-26

---

## 0. What changed in v2, and why

v1 got the skeleton built fast — data layer, fill engine, portfolio, settlement,
risk, MCP, dashboard. Then the first live cycle produced a result that was invalid
four ways over (see **`reports/review-01.md`**).

The most important thing that happened: **the honest fill engine caught a
worthless strategy on cycle one.** That is the system working. v2 builds on that.

Three things drive v2:

1. **A hard economic finding.** The agent bought NO at $0.999 — risking 99.9¢ to
   win 0.1¢. Generalized: *on longshots, the bid-ask spread exceeds the
   favorite-longshot edge.* A few-cent statistical bias cannot survive crossing a
   multi-cent spread. The mechanical strategy is likely dead on arrival as a
   profit source.

2. **Prior art exists and we were reinventing it.** Polymarket published an
   official agent framework; a third party has already built almost exactly our
   architecture (MCP + SQLite + Claude + paper trading). We should mine both.

3. **The research literature says where the real edge is.** LLM forecasters now
   reach Brier scores statistically indistinguishable from human superforecasters
   — but only with retrieval, ensembling, and **post-hoc statistical
   calibration**. And crucially: *LLMs beat markets at long horizons and lose to
   them near resolution.* That tells us exactly which markets to trade.

**Strategic pivot:** the favorite-longshot strategy is demoted from "the edge" to
"the pipeline validator." The real candidate edge is a **calibrated LLM
forecaster on long-horizon markets, executed passively.**

---

## 1. Mission

Build a fully autonomous agent that trades Polymarket with **fake money**,
long-term, producing a **falsifiable record** of whether it has genuine
predictive edge.

Not "make money" — that framing produces an agent that rationalizes trades and a
backtest that flatters itself. Only ~7.6% of Polymarket wallets finish profitable.

### The metric that matters

**Brier score of the agent vs. the market price at decision time.**

```
brier_agent  = mean((p_agent  - y)^2)
brier_market = mean((p_market - y)^2)
```

If `brier_agent >= brier_market`, there is no predictive edge, whatever P&L says.
Log it for every market evaluated, **including declined ones** — free calibration
data.

### Concrete targets from the literature

| Forecaster | Brier (ForecastBench) |
|---|---|
| Human superforecasters | **0.096** |
| Best LLM + crowd access | 0.122 |
| Best LLM, no crowd | 0.136 |
| General public | 0.121 |
| AIA Forecaster (SOTA agentic) | **0.0753** vs. superforecaster 0.0740 |

An ensemble of 12 LLMs performed indistinguishably from a crowd of 925 humans.

**Our bar:** `brier_agent < brier_market` on the markets actually traded. Absolute
Brier isn't comparable across question sets — only the paired comparison counts.

⚠️ **Critical caveat from the same literature:** *high probabilistic calibration
does not guarantee superior trading returns.* Beating the market's Brier is
necessary but not sufficient — costs can still eat the edge. Track both, and never
report one without the other.

---

## 2. Prior art — use, mine, or avoid

Do not rebuild what exists. Evaluate each of these in Phase 2.5 and report a
recommendation.

| Project | What it gives us | Verdict |
|---|---|---|
| **[Polymarket/py-sdk](https://github.com/Polymarket)** (supersedes [py-clob-client](https://github.com/Polymarket/py-clob-client)) | Official, maintained client | **Evaluate to replace our hand-rolled client** |
| [Polymarket/agents](https://github.com/Polymarket/agents) | Official framework: RAG/Chroma, superforecasting prompts, Gamma/CLOB wrappers | **ARCHIVED May 2026** — mine the prompts + RAG design, don't depend on it |
| [artvandelay/polymarket-agents](https://github.com/artvandelay/polymarket-agents) | MCP server (10 tools), bot loop, SQLite schema, Claude strategy, Kelly EV | **Closest prior art — study its schema and tool surface.** Caveat: mock data in places, no backtesting |
| [warproxxx/poly_data](https://github.com/warproxxx/poly_data) | Historical markets, order events, trades retriever | **Strong candidate for the Phase 3 backtest corpus** |
| [Polymarket/resolution-subgraph](https://github.com/Polymarket/resolution-subgraph) | Resolution events | Settlement + backtest ground-truth labels |
| [pascal-labs/polymarket-sdk](https://github.com/pascal-labs/polymarket-sdk) | WebSocket feeds, position mgmt | Mine for the WebSocket approach |
| [CloddsBot](https://github.com/alsk1992/CloddsBot) | Multi-venue (Polymarket + Kalshi + others) | Reference for future cross-venue arb |
| [ForecastBench](https://www.forecastbench.org/) | Standard forecasting benchmark | Calibrate our forecaster against it |

⚠️ **Subgraph caveat:** Polymarket migrated to new CTF Exchange contracts on
**2026-04-28** and stopped supporting the old subgraph indexer. Old
Goldsky/GraphQL pipelines return incomplete data. Verify any subgraph source
returns post-April-2026 data before building on it.

⚠️ **Legal:** Polymarket's ToS prohibits trading by US persons. We are paper
trading only — no wallet, no keys, no orders. Keep it that way (§8).

---

## 3. Blocking defects — fix before any new features

Full detail with file:line in **`reports/review-01.md`**. Summary:

| # | Defect | Location |
|---|---|---|
| 1 | Strategy `edge` is a constant; `p_agent` is a deterministic function of `p_market` → Brier comparison structurally impossible | `strategies/longshot.py:90` |
| 2 | Economics ignore spread — bought NO at 0.999 to win 0.1¢ | strategy design |
| 3 | P&L values open positions at **zero**; `get_total_equity()` never called | `runner.py:205,218` |
| 4 | Correlated-cluster cap not enforced — 4/4 positions in one NegRisk event | `risk/manager.py` |
| 5 | `mode` param is a no-op; `_realistic_fill` is unreachable dead code containing fabricated liquidity | `engine/fills.py:166` |
| 6 | "99.8% spreads on 100% of markets" was worked around, not diagnosed | `polymarket/client.py` |

**Required order:** 6 → 3 → 5 → 4 → Phase 3 → 1 & 2.

**Do not resume live cycles until 6, 3, 5, 4 are done.** Reset the portfolio
afterward — `state/portfolio.json` records an invalid run.

---

## 4. Architecture

SQLite is the source of truth. GitHub receives published snapshots. Git-as-database
would create race conditions and an unreadable history.

```
   Hermes (cron, autonomous, Ubuntu VM)
      │  MCP tools
      ▼
┌────────────────────────────────────────────────────┐
│  agent/  (Python)                                  │
│                                                    │
│  Data      │ Fill engine  │ Risk      │ Forecaster │
│  Gamma/    │ book-walk,   │ ¼-Kelly,  │ retrieval  │
│  CLOB/ws   │ passive,     │ cluster   │ + ensemble │
│  history   │ settlement   │ caps      │ + CALIB.   │
│                                                    │
│  Strategies: longshot (validator) │ forecaster     │
└──────────────────┬─────────────────────────────────┘
                   │ SQLite = truth
                   ▼ publish snapshots
        state/*.json ──► git push ──► GitHub Pages
                                      (read-only dashboard)
```

**Key inversion, unchanged:** the LLM *proposes*; deterministic code *validates,
sizes, and fills*. Guardrails live in code. An LLM asked to respect a position
limit will eventually not.

---

## 5. The forecasting stack (the core of v2)

This is where real edge is plausible. Build it in this order — **each layer is
useless without the one before it.**

### 5.1 Market selection — trade where LLMs actually win

Research finding: **LLMs outperform markets at long forecast horizons and lose
their edge in the final hours**, because they aggregate new information more
slowly than markets do.

Therefore:
- **Prefer long-horizon markets** (weeks to months to resolution).
- **Hard-exclude near-resolution markets** — configurable, start at 48h.
- Require real liquidity (from the Defect 6 diagnosis, by *current* liquidity).
- Prefer markets with objective, checkable resolution sources.

### 5.2 Retrieval — the agent must read before it forecasts

- News + web search scoped to the market's resolution window.
- Extract and reason over the **full resolution criteria text**, not the title.
  LLMs are genuinely good at fine-print reading; this is a real edge source.
- Cache retrieved evidence in SQLite, keyed to the decision, so the reasoning is
  auditable after resolution.

### 5.3 Structured forecast — base rate first

Force this output shape. Free-form reasoning produces anchored, overconfident
numbers:

1. **Reference class** and its base rate
2. **Evidence for**, with source and date
3. **Evidence against**, with source and date
4. **Time-to-resolution** adjustment
5. **`p_raw`** — the probability estimate
6. **Confidence** — and *why*

The model must produce `p_raw` **without seeing `p_market`** for the first pass.
Otherwise it anchors on the market and `p_agent` collapses into a transform of
`p_market` — which is precisely how Defect 1 happened.

### 5.4 Ensemble + supervisor reconciliation

- Query **multiple models** (Hermes supports many providers) and/or multiple
  prompt framings. An ensemble of 12 LLMs matched a 925-human crowd.
- Use **confidence gating**, not naive averaging: override the ensemble mean only
  when follow-up evidence shows genuine resolving power.
- A **supervisor pass** reconciles disagreement between ensemble members and
  produces a single `p_ensemble` plus a disagreement measure.

### 5.5 Post-hoc calibration — the step that makes it work ⭐

**This is the single highest-value component and the one most likely to be
skipped. Do not skip it.**

RLHF-tuned LLMs **hedge toward mid-range probabilities**. Correct this
statistically, not by prompting:

- **Extremization** — log-odds power transform, pushing moderate estimates outward
- **Platt scaling** — logistic recalibration
- **Isotonic regression** — non-parametric, needs more data
- **Temperature scaling** — simplest baseline

Fit on the Phase 3 historical corpus; refit periodically as live resolutions
accumulate. Track **Expected Calibration Error (ECE)** alongside Brier, plus
reliability diagrams and overconfidence rate.

`p_agent = calibrate(p_ensemble)` — and `p_agent` is what gets logged for Brier
and used for sizing. Never trade on `p_raw`.

### 5.6 Trade gate — edge must survive costs

```
edge          = |p_agent - p_market|
cost          = half_spread + fees + slippage_estimate
edge_net      = edge - cost
trade only if   edge_net > hurdle   AND   ensemble_disagreement < max_disagreement
```

The hurdle exists because LLMs are overconfident. Start conservative (3–5¢) and
tune only against backtest results, never against live P&L.

### 5.7 Execution — passive by default

Defect 2's lesson: crossing the spread destroys a few-cent edge. Post passive
limit orders and accept non-fills. This makes the **passive-fill simulation**
(Phase 2.5) load-bearing for the whole project — if it's optimistic, everything
downstream is fiction.

---

## 6. Phases

Each phase has acceptance criteria. Not done until tests pass on the VM **and** a
report is filed per §9.

### Phase 2.5 — Remediation (BLOCKING, do first)
Fix Defects 6, 3, 5, 4 in that order. Evaluate the §2 prior art and report a
build-vs-adopt recommendation for the API client.

**Acceptance:**
- Spread distribution reported across top 50 markets by *current liquidity*, with
  a diagnosis of the 99.8% finding
- Equity = cash + Σ(shares × mark), marks from each token's own best bid;
  circuit breaker wired to true equity
- `_realistic_fill` and `mode` deleted; **passive-order test implemented and
  passing** (resting order fills only when later prints cross it)
- Cluster cap test: 4 proposals in one NegRisk event cannot all be approved
- Portfolio reset; `state/` reflects a clean start

### Phase 3 — Backtest harness + historical corpus (NO LONGER SKIPPABLE)

📄 **Full design: [`docs/TESTING.md`](docs/TESTING.md) — read it before starting.**

Two hard constraints discovered in research, both to be independently verified:
- **No historical order books exist** anywhere. Execution cannot be backtested
  historically; any historical fill number is a *model*, not a measurement.
- **`/prices-history` is capped at 12h granularity for resolved markets**
  ([issue #216](https://github.com/Polymarket/py-clob-client/issues/216)) — fine
  for long-horizon forecasting, useless for intraday.

Therefore testing splits into three tracks:
- **Track A — forecast backtest** (available today, months of history): measures
  Brier vs. market. Brier is immune to the missing-book problem.
- **Track B — execution replay** (needs ~30 days of self-recorded books):
  measures real fills and passive fill rates. **Start the Book Recorder on day 0
  — this data cannot be obtained retroactively.**
- **Track C — shadow mode** (today, forever): live decisions, no execution.

**Acceptance:** the four control strategies in `docs/TESTING.md` §4.4 must pass —
**random must lose money**, and market-parrot (`p_agent = p_market`) must score a
Brier delta of exactly ~0. Plus a clean contamination probe with proven
date-filtered retrieval. Nothing downstream is trustworthy until these pass.

### Phase 4 — Longshot, refit from data (validator, not profit centre)
- Fit the bias curve on resolved markets: bucket by entry price, realized
  frequency vs. implied, with CIs and per-bucket sample size.
- Gate on `edge_net > hurdle` (§5.6).

**Acceptance:** publish the fitted curve. **Expect it to trade rarely or never
after costs — that is the correct result, and it validates the pipeline.** If the
effect sits inside the error bars, report that plainly.

### Phase 5 — Risk manager hardening
- Fractional Kelly (**quarter-Kelly**): for price `c`, agent probability `p`,
  `f* = (p - c) / (1 - c)`, size at `0.25 × f*`.
- Reject asymmetric-payoff traps: cap the max price paid per share (a 0.999 buy
  should be structurally impossible).
- Cluster caps by NegRisk group / event id; per-market cooldown; daily trade cap.
- Circuit breaker on true-equity drawdown.

**Acceptance:** unit tests prove every limit holds against adversarial proposals,
including ones that pass individually but breach a cluster cap collectively.

### Phase 6 — Forecaster v1 (retrieval + structured output)
Implements §5.1–5.3. Single model, no ensemble yet.

**Acceptance:** on a held-out set of *already-resolved* markets the model has no
training-data access to, report `brier_agent` vs `brier_market`. Blind: the
forecaster must not see `p_market` before producing `p_raw`.

### Phase 7 — Ensemble + calibration ⭐
Implements §5.4–5.5.

**Acceptance:** calibration measurably improves ECE on held-out data vs.
uncalibrated. Report reliability diagrams before/after. This is the phase most
likely to determine whether the project succeeds.

### Phase 8 — Autonomy, publishing, dashboard

📄 **Dashboard design: [`docs/DASHBOARD.md`](docs/DASHBOARD.md) — read before starting.**

- MCP tools + Hermes cron loop (4-hourly default).
- `state/`: `meta.json`, `scorecard.json`, `calibration.json`, `resolutions.json`,
  `portfolio.json`, `equity.json`, `decisions.json` (**including rejected trades
  and why**), `trades.jsonl`. Full schema contract in DASHBOARD.md §4 — **agree it
  before writing UI code.**
- Scheduled GitHub Action re-marks the portfolio every ~15 min so the dashboard
  stays live when Hermes is idle.
- Rebuild the UI as an experiment instrument, not a trading terminal: **Brier
  delta is the hero number, P&L is demoted**; delete the manual localStorage
  trading UI and the arbitrage scanner tab (false-positive generators, §3.1–3.3).

**Acceptance:** a full unattended cycle end-to-end; dashboard renders from
committed JSON with no CORS errors; exactly one portfolio in the UI; a confidence
interval crossing zero renders "no detectable edge yet" rather than a green
number.

### Phase 9 — Long-run operation
- Weekly auto-generated report: Brier vs. market, ECE, P&L by strategy, drawdown.
- Refit calibration as resolutions accumulate.
- Benchmarks: "always buy the favorite", "buy at market and hold", random.

---

## 7. Open questions — defaults accepted

Hermes's Phase 0 defaults are **accepted** with one change:

1. **Bankroll:** $10,000 ✅
2. **Cadence:** 4-hourly ✅
3. **Circuit breaker:** 20% drawdown ✅ — but on **true equity** (Defect 3)
4. **Market scope:** ⚠️ **changed** — additionally require long horizon
   (exclude <48h to resolution, §5.1) and filter by *current liquidity*, not
   lifetime volume

---

## 8. Anti-goals

- ❌ No real-money trading. No wallet, no private keys, no order signing. Ever.
  (Also: Polymarket ToS prohibits US persons from trading.)
- ❌ Do not tune the simulator, hurdle, or thresholds against live P&L.
- ❌ Do not let the LLM enforce its own risk limits.
- ❌ Do not let the forecaster see `p_market` before producing `p_raw`.
- ❌ Do not report P&L without the paired Brier comparison.
- ❌ Do not add a strategy before the fill engine passes **all six** adversarial
  tests, passive order included.

---

## 9. Reporting protocol

**Running log:** `reports/STATUS.md`, newest first. Short entries.

**Per-phase:** `reports/phase-N-report.md` — what was built, deviations **with
justification**, every acceptance criterion with actual numbers, and anything
discovered that contradicts this plan.

**Blockers:** GitHub issue labeled `blocker` + `phase-N`.

**Commits:** `phase-N: short description`. Small and frequent.

### Report contradictions loudly
If the longshot bias doesn't replicate, if calibration doesn't improve ECE, if the
forecaster can't beat the market's Brier — **that is the most valuable possible
output.** Report it prominently. Do not quietly adjust parameters until the numbers
look good.

The v1 cycle already proved this works: honest fills surfaced a worthless strategy
immediately. Keep that property.

---

## 10. References

**Polymarket**
- [prices-history API](https://docs.polymarket.com/api-reference/markets/get-prices-history) ·
  [NegRisk](https://docs.polymarket.com/advanced/neg-risk) ·
  [Clients & SDKs](https://docs.polymarket.com/api-reference/clients-sdks) ·
  [Subgraph overview](https://docs.polymarket.com/developers/subgraph/overview)
- [py-clob-client](https://github.com/Polymarket/py-clob-client) ·
  [agents (archived)](https://github.com/Polymarket/agents) ·
  [resolution-subgraph](https://github.com/Polymarket/resolution-subgraph)

**Prior art**
- [artvandelay/polymarket-agents](https://github.com/artvandelay/polymarket-agents) ·
  [warproxxx/poly_data](https://github.com/warproxxx/poly_data) ·
  [pascal-labs/polymarket-sdk](https://github.com/pascal-labs/polymarket-sdk) ·
  [CloddsBot](https://github.com/alsk1992/CloddsBot)

**Forecasting research**
- [ForecastBench](https://www.forecastbench.org/) ·
  [AIA Forecaster](https://arxiv.org/pdf/2511.07678) ·
  [Foresight Arena](https://arxiv.org/pdf/2605.00420) ·
  [LLMs vs expert forecasters](https://arxiv.org/pdf/2507.04562) ·
  [Superforecasting LLM assistant](https://www.emergentmind.com/topics/superforecasting-llm-assistant)

**Market edges**
- [Systematic Edges in Prediction Markets](https://quantpedia.com/systematic-edges-in-prediction-markets/) ·
  [Accuracy, Skill, and Bias on Polymarket](https://papers.ssrn.com/sol3/Delivery.cfm/5910522.pdf?abstractid=5910522&mirid=1)
