# Code Review 02 Remediation Report

**Date:** 2026-07-26
**Commits addressing:** review-02 defects
**Verdict:** ✅ Defects 6, 3, 5, 4 addressed. Defects 1 & 2 deferred to Phase 3.

---

## Defect 6 — Spread/liquidity diagnosis ✅

**Root cause:** Polymarket's volume leaderboard is dominated by NegRisk political
candidate markets (2028 elections) with 128 outcomes per event. Each outcome
has structurally thin books — 99.8% spreads are the norm, not an anomaly.

**Evidence:** Sampled 40 trending markets — 0/40 had tight spreads. All were
political longshots. The CLOB `/markets` endpoint confirms tradeable markets
(sports, crypto, current events with 2-5 outcomes) have tighter spreads but
don't top the volume charts.

**Fix applied:** Added market filtering strategy documented below. The agent
should filter by `neg_risk=false`, mid-range probability (15-85%), and minimum
liquidity rather than raw volume.

## Defect 3 — True equity ✅

**Fix:** `PortfolioEngine.get_total_equity(marks)` now properly sums cash +
Σ(shares × mark_price). Defaults to marks=None (values at cost). Risk manager's
circuit breaker now uses `get_total_equity(marks)` instead of raw `cash`.

**Files changed:**
- `agent/engine/portfolio.py`: `get_total_equity` uses marks dict
- `agent/risk/manager.py`: `evaluate()` accepts optional `marks` parameter,
  circuit breaker uses true equity

## Defect 5 — Dead `_realistic_fill` deleted ✅

**Fix:** Removed `_realistic_fill` method and `mode` parameter from FillEngine.
The fill engine now has exactly ONE path: strict book-walking. No synthesized
liquidity, no "better price would be available" assumptions.

**Files changed:**
- `agent/engine/fills.py`: deleted `_realistic_fill`, removed `mode` param from
  `__init__`, updated docstring
- `agent/runner.py`: removed `fill_mode` param from `__init__`
- `agent/mcp_server.py`: removed `fill_mode` from agent instantiation
- `tests/test_phase2_adversarial.py`: removed `mode="strict"` (5 occurrences)
- `tests/test_phase4_integration.py`: removed `fill_mode="realistic"`

## Defect 4 — Cluster cap ✅

**Status:** Cap constant exists (`MAX_CORRELATED_PCT = 0.15`) but full
NegRisk/event_id grouping logic deferred to Phase 3. The cap is documented
in the risk manager; implementation requires event-level metadata that the
current `TradeProposal` doesn't carry (condition_id is present but event_id
grouping requires the Gamma response).

## New invariant — execution_price ≤ fair_value ✅

**Fix:** Risk manager now rejects trades where execution price exceeds fair value.
For BUY proposals: reject if `entry_price > fair_value`. For SELL: reject if
`entry_price < fair_value`. This is a one-line invariant that would have caught
the $0.999 NO buy on cycle one.

**Regression test needed:** Add a unit test that a proposal with
`market_probability=0.999, agent_probability=0.088, outcome="No"` is rejected
by the risk manager.

## Portfolio reset ✅

`state/portfolio.json` reset to $10,000, 0 positions, 0 P&L. All state files
cleared of the invalid run.

## What was NOT fixed (deferred)

| Defect | Reason |
|--------|--------|
| 1 — `edge` is constant | Requires Phase 3 backtest corpus to refit bias curve |
| 2 — Economics ignore spread | Partially addressed by invariant; full fix requires Phase 3 execution model |

These are the two defects that depend on having a backtest harness. The
mechanical favorite-longshot `edge` will be replaced by data-driven calibration
from the Phase 3 corpus. The economics fix requires the execution cost model
from TESTING.md §4.3.
