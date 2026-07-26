# Dashboard Redesign Plan

**Version:** 1.0 · 2026-07-26
**Status:** design — implement as PLAN.md Phase 8
**Purpose:** rebuild the web UI as an instrument for a long-running forecasting
experiment, not a trading terminal.

---

## 1. What this dashboard is for

We are running a **months-long experiment** to answer one question: *does the
agent forecast better than the market?* The dashboard is the instrument we read
that answer from. It has exactly five jobs:

1. **Is there edge?** — Brier vs. market, with a sample size and a confidence interval
2. **Is it calibrated?** — reliability diagram, ECE
3. **What is it thinking?** — decision feed, *including what it rejected and why*
4. **Is it alive?** — last cycle, errors, gaps
5. **How's the money?** — equity and positions, **deliberately demoted**

Everything else is noise.

---

## 2. Three design principles

### 2.1 P&L is not the headline. Brier is.

This is the most important decision in the redesign, and it is deliberately
uncomfortable.

If P&L is the biggest number on screen, that is what gets optimized — by Hermes,
and by you. Over a few hundred trades P&L is mostly variance; a lucky month reads
as skill and invites tuning that destroys the experiment. PLAN.md §1 already
states the metric; the UI must reflect it or the plan is decorative.

**The hero number is the paired Brier delta.** P&L lives further down, next to
its execution-quality caveat.

### 2.2 The UI must make it hard to fool yourself

- Every metric shows **n** beside it. A Brier delta over 12 resolutions is noise.
- Show **confidence intervals**, never bare point estimates.
- Badge every P&L figure `modeled` or `measured` (see [TESTING.md](TESTING.md) §4.3).
- Show **rejected** decisions as prominently as accepted ones — survivorship bias
  in the decision feed hides the agent's real behaviour.
- When the CI crosses zero, the UI must literally say **"no detectable edge yet"**
  rather than rendering a green number.

### 2.3 One portfolio, not two

Today the header shows a balance from the **manual localStorage portfolio**, which
has nothing to do with the agent's portfolio in `state/portfolio.json`. Two
different sources of truth in one interface, both labelled "$10,000."

**Delete the manual paper-trading UI.** Also delete the **Arbitrage Scanner** tab —
its three strategies are documented false-positive generators (PLAN.md §3.1–3.3),
and shipping them in the UI actively misleads.

---

## 3. Stack — stay boring

Keep **vanilla JS + static files on GitHub Pages**. No build step, no framework.
Push to `main` deploys. The whole app is "fetch some JSON, draw some SVG," and a
toolchain would add failure modes without adding capability.

Charts (equity curve, reliability diagram, bar histograms) are **hand-rolled
inline SVG** — a few dozen lines each, no CDN dependency, no version drift.

Restructure the files, though — today `js/app.js` mixes manual trading, market
browsing, and agent viewing in one place:

```
index.html
css/style.css
js/
  data.js       # fetch + cache state/*.json, schema validation
  views/
    verdict.js      # hero: Brier delta, health
    calibration.js  # reliability diagram, ECE
    decisions.js    # decision feed incl. rejections
    positions.js    # positions, equity curve
    resolutions.js  # settled forecasts scorecard
  charts.js     # small SVG chart helpers
  app.js        # routing + bootstrap only
```

---

## 4. The data contract (do this first — it blocks everything)

The dashboard is only as good as the JSON. **Agree this schema with the publisher
(`agent/publish/snapshots.py`) before writing any UI code.** Every field the UI
needs must be published; the UI computes nothing it can get wrong.

### `state/meta.json` — health (new)
```json
{
  "last_cycle_at": "2026-07-26T12:00:00Z",
  "next_cycle_eta": "2026-07-26T16:00:00Z",
  "mode": "shadow | paper",
  "agent_version": "git sha",
  "cycles_total": 128,
  "errors_last_24h": 0,
  "recorder_gap_minutes_24h": 0
}
```

### `state/scorecard.json` — the headline (extend)
```json
{
  "n_resolved": 143,
  "brier_agent": 0.118,
  "brier_market": 0.124,
  "brier_delta": -0.006,
  "brier_delta_ci95": [-0.017, 0.004],
  "verdict": "no_detectable_edge | edge_detected | worse_than_market",
  "ece": 0.041,
  "by_strategy": { "favorite-longshot": {...}, "forecaster": {...} },
  "benchmarks": { "always_favorite": 0.131, "market_parrot": 0.124 }
}
```
`verdict` is computed by the agent, not the UI — one place to get it right.

### `state/calibration.json` — reliability (new)
```json
{ "bins": [ {"p_lo":0.0,"p_hi":0.1,"n":22,"predicted":0.05,"realized":0.09} ] }
```

### `state/equity.json` — extend
Points need `total_equity`, not just `cash` (the current chart plots `cash`, which
is the Defect-3 bug duplicated in the front end):
```json
{ "points": [ {"t":"...","cash":0,"positions_value":0,"total_equity":0} ],
  "execution_quality": "modeled | measured" }
```

### `state/portfolio.json` — extend
Each position needs `mark_price`, `unrealized_pnl`, `fair_estimate`,
`edge_at_entry`. Showing `fair_estimate` beside `avg_entry_price` would have made
the $0.999 trade obvious at a glance.

### `state/decisions.json` — extend
Include **rejected** decisions: `action` (`traded`/`rejected`), `reject_reason`,
`p_agent`, `p_market`, `edge_gross`, `edge_net`, `reasoning`, `sources`.

### `state/resolutions.json` — settled forecasts (new)
```json
{ "items": [ {"question":"...","p_agent":0.21,"p_market":0.30,
              "outcome":1,"brier_agent":0.62,"brier_market":0.49,
              "pnl":-12.40,"resolved_at":"..."} ] }
```
This is what makes a long-run experiment legible: every closed forecast, scored.

---

## 5. Page structure

Five views, ordered by importance. Not tabs mirroring a trading app — sections
mirroring the experiment.

### 5.1 Verdict (hero)
```
┌─────────────────────────────────────────────────────┐
│  NO DETECTABLE EDGE YET                             │
│  Brier  0.118 agent  vs  0.124 market               │
│  Δ −0.006   95% CI [−0.017, +0.004]   n = 143       │
│  ────────────────────────────────────────────────   │
│  ● live · last cycle 42m ago · next in 3h18m        │
│  mode: paper · execution: modeled · 0 errors/24h    │
└─────────────────────────────────────────────────────┘
```
Colour is driven by `verdict`, never by the sign of a point estimate. A CI
crossing zero renders neutral grey, not green.

### 5.2 Calibration
Reliability diagram: predicted vs. realized per bucket, with the diagonal, and bin
counts as bar widths (so sparse buckets look sparse). ECE beside it. Toggle for
pre/post calibration once Phase 7 lands — that comparison is the direct evidence
the calibration layer is earning its place.

### 5.3 Decision feed ⭐
The "what is it thinking" view, and the most valuable thing here day to day.

Each entry: market, `p_agent` vs `p_market`, edge gross/net, size, **outcome badge
once resolved**, expandable reasoning + sources. Filter by traded/rejected/all and
by strategy.

**Default the filter to "all"** so rejections are visible without seeking them
out. A feed of only executed trades hides most of the agent's behaviour.

### 5.4 Positions & equity
Equity curve plotting **`total_equity`** with a benchmark line. Positions table:
question, outcome, shares, entry, **mark**, **unrealized**, **fair_estimate**,
edge at entry. Cluster grouping visible so four positions in one NegRisk event
read as one concentrated bet.

Header carries the `modeled`/`measured` execution badge.

### 5.5 Resolutions
Settled forecasts, sortable. Best and worst calls by Brier contribution. This is
the long-run record — where months of work becomes a legible track record.

---

## 6. Long-run data management

The current design breaks silently as data accumulates. At 15-minute marks,
`equity.json` reaches ~35k points in a year and the browser will choke.

- **Downsample on publish:** raw ≤7 days, hourly ≤90 days, daily beyond.
- **Paginate** decisions and resolutions — publish `recent.json` (last 200) plus
  monthly archives `decisions-2026-07.json`.
- **Cap** `portfolio.json` `recent_trades` and link to archives.
- Views default to **last 30 days** with an **all-time** toggle.

Hermes: report projected file sizes at 6 and 12 months before implementing.

---

## 7. Phases

| # | Work | Acceptance |
|---|---|---|
| **D0** | Agree the §4 schema with the publisher | Schemas documented; publisher emits all fields incl. `meta.json`, `calibration.json`, `resolutions.json` |
| **D1** | Strip legacy: delete manual trading UI + scanner tab; remove the localStorage portfolio and duplicate header balance | Exactly one portfolio in the UI; no localStorage trading; scanner gone |
| **D2** | Verdict hero + health strip | Renders `verdict` verbatim from JSON; CI crossing zero shows neutral, not green; stale cycle (>2× cadence) shows a warning |
| **D3** | Calibration view | Reliability diagram matches `calibration.json`; sparse bins visibly sparse |
| **D4** | Decision feed | Rejections shown by default; reasoning expandable; resolved entries badged |
| **D5** | Positions & equity, fixed | Equity plots `total_equity`; positions show mark + unrealized + `fair_estimate`; execution badge present |
| **D6** | Resolutions view | Every settled forecast listed with both Brier contributions |
| **D7** | Long-run data management (§6) | Downsampling + archives live; 12-month size projection reported |
| **D8** | Responsive + accessibility | Usable on a phone; charts have text equivalents; contrast passes |

**D0 and D1 first.** D0 unblocks everything; D1 removes the actively misleading
parts, which is worth doing even before the new views exist.

---

## 8. Anti-goals

- ❌ No manual trading UI. This dashboard observes an agent; it is not a game.
- ❌ No P&L as the hero number.
- ❌ No arbitrage scanner (false-positive generators, PLAN §3.1–3.3).
- ❌ No metric without its sample size.
- ❌ No green number on a CI that crosses zero.
- ❌ No build step, no framework, no CDN dependency.
- ❌ The UI computes no statistics — it renders what the agent published. One
  place to be wrong, and it is the place with tests.

---

## 9. Related

- [PLAN.md](../PLAN.md) — §1 the metric, §3 defects, Phase 8
- [TESTING.md](TESTING.md) — §4.3 modeled vs. measured execution
- [reports/review-02.md](../reports/review-02.md) — current dashboard bugs
