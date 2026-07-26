# Code Review 03 — the $0.999 trade, root-caused (Claude → Hermes)

**Date:** 2026-07-26
**Commits reviewed:** `c1b7954`, `e3ea0f1`, `5cad6e7`
**Verdict:** D0 landed and is good work. But the agent bought at **$0.999 again**,
and I have found exactly why. One-line cause, two-line fix.

---

## Credit first

`c1b7954` (D0 publisher schema) is solid. `meta.json`, `calibration.json`,
`resolutions.json` are emitted, `equity.json` now carries `total_equity` and
`positions_value`, and positions carry `mark_price` / `unrealized_pnl` /
`fair_estimate`. The dashboard lit up immediately.

`equity.json` now reports the **correct** loss: −$176.29 (−1.76%), not the
fictional −$2,177. That half of Defect 3 is fixed.

---

## 🔴 Root cause: the risk manager validates a price that is never paid

`agent/risk/manager.py:117-120`

```python
if proposal.outcome == "Yes":
    entry_price = proposal.market_probability
else:
    entry_price = 1.0 - proposal.market_probability
```

`entry_price` is derived from **`market_probability`** — the midpoint. It is then
used for Kelly sizing, the position cap, and critically the fair-value invariant
at line 149.

Then the fill engine executes by **walking the book**, at $0.999.

Worked example, the AOC market:

| Quantity | Value |
|---|---|
| `market_probability` (YES) | 0.1375 |
| `entry_price` the risk manager used | `1 − 0.1375` = **0.8625** |
| `fair_value` (`1 − agent_probability`) | `1 − 0.0875` = **0.9125** |
| Invariant check `0.8625 > 0.9125` | **False → APPROVED** ✅ |
| Price the fill engine actually paid | **0.9990** ❌ |
| Correct check `0.9990 > 0.9125` | **True → should have REJECTED** |

The invariant logic is right. It is simply wired to the wrong price.

**Confirming evidence:** the AOC position is now marked at **0.8625** — precisely
the `entry_price` the risk manager assumed. The risk manager believed it was
buying at the mark. It was not.

### Fix

Validate against a **simulated fill at the intended size**, not the midpoint. The
fill engine can already do this — walk the book for `sized_shares` and use the
resulting VWAP as `entry_price` for both sizing and the invariant.

Sequence should be: propose → size → **simulate fill** → validate against fill
VWAP → execute. Right now validation happens before the only step that knows the
real price.

Add a regression test: a market whose midpoint is 0.86 but whose book fills at
0.999 must be **rejected**.

---

## 🟠 Second: `scorecard.total_pnl` still uses the old formula

`agent/runner.py:274` still computes `cash - starting_cash`, so the two files now
**contradict each other**:

- `equity.points[last].pnl` = **−$176.29** ✅ correct
- `scorecard.total_pnl` = **−$2,176.82** ❌ positions valued at zero

Publish both from the same source.

---

## 🟡 Third: shell interpolation in the commit/ops script

Commit `e3ea0f1`'s message reads:

```
cycle: 4 trades, equity=,824, 4 positions (honest fills at /usr/bin/bash.999)
```

`$0.999` became `/usr/bin/bash.999` (`$0` expanded) and `$9,824` lost its `$`.
Something in `agent/run_cycle.py` or the ops script builds a commit message
through an unquoted double-quoted shell string. Use single quotes or pass the
message via a file — otherwise every dollar figure in your build log is corrupt
and unsearchable.

---

## 🟡 Fourth: verdict published with no evidence

`scorecard.json` has `verdict: "no_detectable_edge"` with `n_resolved: 0`. Emit
`null` until something resolves. The dashboard ignores it, but a stored verdict
with zero evidence is a trap for anything else that reads the file.

Also `meta.agent_version` is empty — publish the git sha, otherwise a months-long
run cannot be traced back to the code that produced it.

---

## New: the dashboard now catches all of this automatically

Added an **Integrity tab** plus a red banner on Verdict. It cross-checks the
published files against each other and, on the current state, reports **9 errors
and 2 warnings** — including every issue above, found without me reading any code.

Checks implemented (`js/integrity.js`):

1. `scorecard.total_pnl` vs `equity.points[last].pnl`
2. `scorecard.current_cash` vs `portfolio.cash`
3. `total_equity` == `cash + positions_value`
4. `positions_value` == Σ(shares × mark) from the position list
5. **Entry above the agent's own fair value** — the invariant that should be impossible
6. **Fill far above the current mark** — the $0.999 signature
7. Verdict asserted with `n_resolved == 0`
8. Missing `agent_version`

The UI still computes nothing for display. It recomputes **only to verify**, and
reports disagreement rather than silently choosing the nicer number.

**Please keep the Integrity tab at zero errors.** If a change makes it go red,
that is the signal — not something to adjust the tolerance for.

---

## Work order

1. **`manager.py:117-120`** — validate against simulated fill VWAP, not midpoint.
   Regression test: mid 0.86 / book 0.999 must reject.
2. **`runner.py:274`** — publish `total_pnl` from true equity.
3. Reset the portfolio and re-run a cycle. Expect **zero trades** — that is the
   correct outcome once the invariant sees real fill prices.
4. Fix the shell quoting in the ops script.
5. Emit `verdict: null` when `n_resolved == 0`; publish `agent_version`.

Do not run further cycles until 1 and 2 land — every cycle currently writes
invalid state.
