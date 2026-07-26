# Dashboard Gap Analysis & Implementation Proposal

**Date:** 2026-07-26  
**For:** Claude review  
**References:** `docs/DASHBOARD.md` (the plan), current `index.html` + `js/app.js`

---

## 1. Verdict: the current dashboard is wrong for this project

`docs/DASHBOARD.md` is correct. The current UI was built for the original vision
("manual paper trading terminal") and the project has pivoted to "autonomous
forecasting experiment." The mismatch is structural, not cosmetic.

## 2. Gap analysis — current vs. required

| What's there | What it should be | Severity |
|---|---|---|
| **P&L** as header hero (`$10,000.00`) | **Brier delta** as hero, with CI and n | 🔴 Blocking |
| **Manual trading** (BUY/SELL modal, localStorage portfolio) | Read-only agent observer — no trading UI | 🔴 Blocking |
| **Arbitrage Scanner** tab (3 false-positive strategies) | Deleted — PLAN §3.1–3.3 says these mislead | 🔴 Blocking |
| **Markets** tab (trending browser with Trade buttons) | Keep as **market research** view, remove Trade buttons | 🟡 |
| **Portfolio** tab (manual localStorage positions) | **Agent positions** from `state/portfolio.json` only | 🔴 Blocking |
| **Agent** tab (reads `state/` but shows cash as equity) | **Verdict hero** + calibration + decision feed + positions | 🔴 Blocking |
| **News Edge** tab | Delete — superseded by forecaster reasoning in decision feed | 🟡 |
| Two separate portfolios (header localStorage + agent state) | One portfolio — the agent's | 🔴 Blocking |
| Equity chart plots `p.cash` not `total_equity` | Plot `total_equity` from `state/equity.json` | 🟡 |
| No Brier anywhere | Brier is the hero number | 🔴 Blocking |
| No calibration view | Reliability diagram + ECE | 🔴 Blocking |
| No resolution log | `state/resolutions.json` — settled forecasts, scored | 🔴 Blocking |
| No `modeled`/`measured` badges | Every P&L tagged per TESTING.md §4.3 | 🟡 |
| `js/app.js` is 549 lines of mixed concerns | Split into `data.js`, `views/`, `charts.js`, `app.js` | 🟡 |

## 3. Proposed implementation sequence

Follows `docs/DASHBOARD.md` §7 phases exactly. Here's the concrete work per phase:

### D0 — Data contract (publisher side)
**File:** `agent/publish/snapshots.py`  
Add three new state files and extend two existing:

| File | Action | Fields |
|------|--------|--------|
| `state/meta.json` | **New** | `last_cycle_at`, `next_cycle_eta`, `mode`, `agent_version`, `cycles_total`, `errors_last_24h` |
| `state/scorecard.json` | **Extend** | `n_resolved`, `brier_delta`, `brier_delta_ci95`, `verdict`, `ece`, `by_strategy`, `benchmarks` |
| `state/calibration.json` | **New** | `bins[]` with `p_lo`, `p_hi`, `n`, `predicted`, `realized` |
| `state/equity.json` | **Extend** | Add `total_equity`, `positions_value`, `execution_quality` to each point |
| `state/decisions.json` | **Extend** | Add `action` (traded/rejected), `reject_reason`, `p_agent`, `p_market`, `edge_gross`, `edge_net`, `reasoning` |
| `state/resolutions.json` | **New** | `items[]`: question, p_agent, p_market, outcome, brier_agent, brier_market, pnl, resolved_at |

### D1 — Strip legacy
- Delete the localStorage `Portfolio` module from `js/portfolio.js`
- Remove the Trade modal from `index.html`
- Remove all Trade buttons from market rows
- Remove "Arbitrage Scanner" tab
- Remove "News Edge" tab
- Remove the dual-balance header (keep agent balance from `state/`)
- Remove `js/scanner.js` (false-positive generator)

### D2 — Verdict hero
- New `js/views/verdict.js` — renders from `state/scorecard.json`
- Hero card: `verdict` string from JSON, Brier numbers, CI, sample size
- Health strip: last cycle time, mode badge, error count
- Color driven by `verdict`, not by sign of point estimate
- CI crossing zero → neutral grey, text "no detectable edge yet"

### D3 — Calibration view
- New `js/views/calibration.js` — reliability diagram from `state/calibration.json`
- Hand-rolled SVG: predicted vs realized per bucket, diagonal line, bar widths = bin N
- ECE number beside chart

### D4 — Decision feed
- New `js/views/decisions.js` — from `state/decisions.json`
- Default filter: "all" (rejections visible)
- Each entry: market, p_agent vs p_market, edge, size, outcome badge (if resolved)
- Expandable reasoning text
- Filter by traded/rejected/all, by strategy

### D5 — Positions & equity
- Rewrite `js/views/positions.js` — from `state/portfolio.json`
- Equity chart plots `total_equity` (not cash)
- Positions show: mark_price, unrealized_pnl, fair_estimate, edge_at_entry
- Cluster grouping visible
- `modeled`/`measured` execution badge in header

### D6 — Resolutions
- New `js/views/resolutions.js` — from `state/resolutions.json`
- Every settled forecast listed with both Brier contributions
- Sortable table, best/worst calls

### D7 — Long-run data management
- Publisher downsamples equity: raw ≤7d, hourly ≤90d, daily beyond
- Decisions paginated: `recent.json` (last 200) + monthly archives
- Portfolio `recent_trades` capped, linked to archives
- File size projection for 6/12 months

### D8 — Polish
- Responsive layout
- Charts have text equivalents for screen readers
- Contrast checks

## 4. File structure after redesign

```
index.html                    # stripped to skeleton
css/style.css                 # keep, extend
js/
  data.js                     # fetch + cache state/*.json
  views/
    verdict.js                # hero Brier + health
    calibration.js            # reliability diagram
    decisions.js              # decision feed
    positions.js              # positions + equity curve
    resolutions.js            # settled forecasts
    markets.js                # market research (read-only)
  charts.js                   # small SVG chart helpers
  app.js                      # routing + bootstrap only
```

Removed files: `js/portfolio.js`, `js/scanner.js`

## 5. What to do with the Markets tab

Keep it but repurpose. The agent needs market discovery — the Markets tab becomes a
**read-only research view**: search markets, see prices, view orderbook depth. No
Trade buttons. Useful for understanding what the agent is seeing without executing
trades manually.

## 6. Recommendation

**Start with D0+D1 in a single commit.** D0 (publisher schema changes) is pure
Python and blocks the UI. D1 (strip legacy) removes the actively misleading
parts — worth doing even before the new views exist, because shipping a "Trade"
button that creates a localStorage portfolio separate from the agent's portfolio is
confusing.

Then D2–D8 in sequence, one commit per phase. Claude: confirm or revise the
sequence above.
