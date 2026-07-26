# Polymarket Autonomous Trading Agent — Build Plan v3

**Version:** 3.0 (supersedes v2.0 of 2026-07-26)
**Status:** Phase E — economic viability study (blocking)
**Owner:** Hermes agent (Nous Research), always-on Ubuntu VM
**Human:** ChrisFromNEPA
**Last updated:** 2026-07-26

---

> ### 👉 Hermes: the current task list is [`reports/WORK-ORDER.md`](reports/WORK-ORDER.md).
> This document is the *why*. That one is the *what next*, in order.

## 0. What changed in v3 — realignment with the actual goal

📄 **Read [`docs/ECONOMICS.md`](docs/ECONOMICS.md) first. It is the most important
document in this repo right now.**

The goal is **an agent that makes money**. v1 and v2 built **an apparatus for
detecting self-deception**. Those overlap, but they are not the same, and the gap
has become the binding problem.

Every defensive component works: honest fills, integrity checks, the
execution-price invariant, control-gated backtests, a running book recorder.
**No offensive component exists.** There is not one strategy with demonstrated
edge, and the project has never asked whether a profitable configuration exists
at all.

Three corrections:

**1. Brier was made the objective. It is a diagnostic.**
Brier averages forecast quality across *all* markets; profit comes from
*selectively* trading the few where edge exceeds cost. An agent can beat the
market's Brier everywhere and never find a tradeable spread. The literature this
plan cites says it outright — *high probabilistic calibration does not guarantee
superior trading returns* — and we built the scoreboard around calibration anyway.

> **Objective:** risk-adjusted profit after realistic costs
> **Diagnostic:** Brier vs. market — tells us whether profit was skill
> **Guardrail:** honest fills, integrity — stops us fooling ourselves

**2. "Expect zero trades" was treated as success. It is a dead end.**
Correct *behaviour* under the invariant, yes — but an agent that never trades
makes no money. If every book prices worse than our own fair value, the chosen
configuration cannot work and must change. Abstinence is not an outcome.

**3. The binding constraint is not forecast quality — it is that
`half_spread > edge` on every market examined.**
That is an execution and market-selection problem. No amount of calibration work
fixes it. Accordingly, calibration and ensembling move **down** the priority list,
and viability analysis plus **maker execution** move to the top.

**Venue reality (new, and material):** the offshore API this agent reads excludes
US persons by ToS. Polymarket's QCEX acquisition created CFTC-regulated
**Polymarket US**, which US traders can access — but that is a *different venue*,
possibly with different books. Edge measured here may not be tradeable there.
See ECONOMICS.md §6.

**What does not change:** none of the epistemic guardrails loosen. A profit
objective brings exactly the pressure they were built to resist.

## 1. What changed in v2, and why

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

## 2. Mission

Build a fully autonomous agent that **makes money** on prediction markets —
proven first with **fake money**, on a **falsifiable record**, at costs modelled
honestly enough that the paper result would survive contact with real execution.

Both halves are load-bearing. Drop the profit half and we build a very rigorous
measurement of nothing — which is what v2 did. Drop the rigour half and we build
a system that reports profit it never had, which is what ~92% of Polymarket
wallets effectively experience.

### The objective

**Risk-adjusted profit after realistic costs**, per `docs/ECONOMICS.md`:

```
net_edge = |p_agent − p_market| − half_spread − fees − slippage
return   = (net_edge × position_size × trade_count) / capital_at_risk
```

Minimum viable economics: **≥20 qualifying trades/month**, **≥2¢ net edge per
share after costs**, **>8% annualised**. Below those, there is no compounding, no
sample, and no reason to continue.

### The diagnostic

**Brier score of the agent vs. the market price at decision time.**

```
brier_agent  = mean((p_agent  - y)^2)
brier_market = mean((p_market - y)^2)
```

If `brier_agent >= brier_market`, any profit was luck, not skill — so it will not
persist. Brier is how we tell those apart. It is **not** the thing we are trying
to maximise. Log it for every market evaluated, **including declined ones** — free
calibration data.

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

⚠️ **The caveat that reshaped v3:** *high probabilistic calibration does not
guarantee superior trading returns.* We quoted this in v2 and then made
calibration the headline anyway. Beating the market's Brier is **necessary but
not sufficient** — a perfectly calibrated agent still earns nothing if no market
prices within its edge. Never report either number without the other.

### Kill criteria

Stated now so they can be honoured later, when it is inconvenient
(`docs/ECONOMICS.md` §7):

1. Phase E finds **no segment** where achievable edge exceeds required edge, as
   taker *or* maker.
2. After 3 months, qualifying trades/month < 5 — untestable in any useful horizon.
3. Honest maker-fill modelling erases the maker advantage.
4. `brier_agent ≥ brier_market` after 200 resolutions.

**A clean "this does not work, here is the evidence" is a successful outcome** —
and far more valuable than a system that trades indefinitely without edge.

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

### Phase E — Economic viability study (BLOCKING — do this before anything else)

📄 Full spec: [`docs/ECONOMICS.md`](docs/ECONOMICS.md) §4.

Answer one question with numbers: **is there any configuration in which this makes
money?** It is answerable in days from data we already collect, and every other
phase is wasted effort if the answer is no.

- **E1 — Map the opportunity set.** Across the *full* market universe (not just
  `trending`), measure `half_spread` at realistic size ($50 / $200 / $1000 —
  walking the book, not the midpoint), volume, liquidity, days to resolution,
  category, `negRisk`. Publish the joint distribution by segment. We currently
  have one unvalidated data point ("99.8% spreads") driving every design decision.
- **E2 — Edge budget.** Per segment: `required_edge = half_spread + fees +
  slippage`. Segments needing more edge than any plausible forecaster provides
  are dead permanently — cross them off.
- **E3 — Achievable edge.** From the Phase 3 corpus, measure `|p_market − outcome|`
  by segment and horizon, and how much was knowable in advance rather than in
  hindsight.
- **E4 — Overlay.** The viable band is where achievable edge exceeds required
  edge. Deliver the §4 table plus a **go/no-go recommendation with numbers**.
- **E5 — Venue check.** Confirm which venue's books we are recording, whether
  Polymarket US (QCX) exposes an API, and whether its books differ. See
  ECONOMICS.md §6.

**Acceptance:** the E4 table is published, and either a viable band is identified
with an estimated trades/month, or a kill criterion is invoked. Anything else is
not an answer.

### Phase M — Maker execution (likely the actual unlock)

If Phase E shows required edge exceeds achievable edge as a taker, we are paying
the spread when we should be earning it. Passive execution has been the stated
default since v2 §5.7 while the fill engine has only ever supported market orders.

- Limit-order support in the fill engine.
- **Fills only when later trade prints cross the level** — never on touch.
- **Adverse-selection haircut**, measured from recorded book data: price drift in
  the N minutes after a fill at that level. Resting orders fill preferentially
  when you are wrong.
- **Queue position** — being at a price is not being first in line.

**Acceptance:** all three of the above implemented. Until then, do not report
maker P&L at all — a simulator that fills every resting order on touch will
manufacture spectacular fake returns.

### Phase 2.5 — Remediation (do after Phase E)
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

### Phase 4 — Replace the longshot strategy (do not try to fix it)

⚠️ **v3 change:** this strategy is structurally incapable of edge, not
mis-tuned. `strategies/longshot.py:90` sets `p_agent = p_market − BIAS_STRENGTH`,
so `edge` is algebraically the constant `BIAS_STRENGTH` and the gate can never
fail. `p_agent` is a deterministic function of `p_market`, carrying **zero
independent information** — which also makes the Brier comparison meaningless by
construction.

No parameter change fixes that. Either fit a real bias curve from resolved
markets (below), or retire it and keep it only as a pipeline exercise.

**Original scope, if refitting:**
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
- ❌ Do not report maker/passive P&L before adverse selection is modelled.
- ❌ Do not treat "zero trades" as a successful outcome. It is a signal that the
  configuration is wrong, not evidence of discipline.
- ❌ Do not let the profit objective loosen a single guardrail. The pressure it
  creates is exactly what the guardrails exist to resist.
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
