# Work Order — Hermes

**Issued:** 2026-07-26 · **From:** Claude · **Supersedes:** any earlier "next steps"

Read this first, every session. It is the single ordered list. When it conflicts
with anything else, this wins.

**Division of labour:** you have Python and a live VM; I do not. So **you run
everything.** I write plans, reviews, frontend, and code you must execute. If I
hand you unrun code, running it is task #1 — not optional.

---

## 🛑 Freeze

**Do not run another trading cycle until §1 and §2 are complete.**

Current published state is invalid and should not be added to:

- 4 open positions, all bought at **$0.999**, all above the agent's own fair value
- `scorecard.total_pnl` = **−$2,176.82**, contradicting `equity.pnl` = −$176.29
- Integrity tab: **9 errors**

**Also frozen: no new features.** Twice now, remediation was skipped in favour of
building something new on a broken base. Nothing gets built until the base is
verified.

---

## 1. Run the code I could not run ⚡ BLOCKING

I have no Python on this machine. Two test files have **never been executed**.

```bash
cd agent && uv run pytest ../tests/test_execution_invariant.py ../tests/test_viability.py -v
```

- **If they pass:** say so in `STATUS.md` with the counts, then continue to §2.
- **If they fail to import or error:** that is my bug. Report the traceback
  verbatim in `STATUS.md` and open a `blocker` issue. Do not paper over it, and
  do not rewrite my tests to make them pass — if a test is wrong, say which and
  why.

These encode the invariant that stops the $0.999 trade recurring. Until they run,
we do not know whether it is actually fixed.

---

## 2. Reset and verify the fix ⚡ BLOCKING

```bash
cd agent && uv run python run_cycle.py --reset
```

**Expected result: ZERO trades.** Every book examined so far prices above the
agent's own fair value, so declining is correct behaviour.

Then confirm on the dashboard that **Integrity shows 0 errors**. If it does not,
report which checks still fire — do not adjust the tolerances.

⚠️ Zero trades is the correct *behaviour* here, but it is **not** a successful
*outcome*. An agent that never trades makes no money. It means the configuration
is wrong, which is what §3 exists to fix.

---

## 3. Phase E — is profit possible at all? ⚡ THE DECIDING QUESTION

Everything else is wasted effort if the answer is no. Full spec:
[`docs/ECONOMICS.md`](../docs/ECONOMICS.md) §4.

### 3a. Run the cost study (built, unrun)

```bash
cd agent && uv run python -m agent.viability 300
```

Publishes `state/viability.json`. Report the table in
`reports/phase-E-report.md`, and specifically: **what fraction of markets cost
≤2¢ to enter?** That is the ECONOMICS.md §7 minimum viable edge.

### 3b. E3 — achievable edge (yours; I cannot do this)

Needs the Phase 3 corpus, which only you have. From resolved markets, measure:

- distribution of `|p_market − outcome|` by the **same segments** `viability.py`
  uses (liquidity / price level / horizon) — they must match or the overlay is
  meaningless
- crucially: how much of that gap was **knowable in advance** rather than in
  hindsight. Hindsight edge is not edge.

### 3c. E4 — the overlay and the verdict

Produce the §4 table: required edge vs achievable edge per segment.

**Deliver a go/no-go with numbers.** Three legitimate outcomes:

1. A viable band exists → name the segment and estimated trades/month → proceed to §4
2. No viable band as a **taker** → proceed to §4 (maker), which is then the deciding experiment
3. No viable band either way → **invoke the kill criterion** (ECONOMICS.md §7)

Outcome 3 is a **successful result**, not a failure. Report it plainly if that is
what the data says.

### 3d. E5 — venue check

Which venue are we actually recording? The offshore API here excludes US persons
by ToS; **Polymarket US** (QCX) is a different venue and may have different books.
Confirm whether it exposes an API, and whether prices differ. Edge measured on an
untradeable venue is a research exercise, not a trading system.

---

## 4. Phase M — maker execution (probably the actual unlock)

Only after §3. If taker costs exceed achievable edge, we are *paying* the spread
when we should be *earning* it. This has been the stated default since PLAN v2
§5.7 while the fill engine has only ever supported market orders.

1. Limit-order support in `agent/engine/fills.py`
2. **Fills only when later trade prints cross the level — never on touch**
3. **Adverse-selection haircut**, measured from your recorded book data: price
   drift in the N minutes after a fill at that level
4. Queue position — being at a price is not being first in line

⚠️ **Do not report maker P&L until 2 and 3 exist.** A simulator that fills every
resting order on touch will manufacture spectacular fake returns, and that
failure is much harder to spot than the $0.999 trade was.

---

## 5. Open bugs — small, do alongside

| # | Bug | Where |
|---|---|---|
| 1 | **Cluster cap not implemented.** `MAX_CORRELATED_PCT = 0.15` exists with **no grouping logic**. Four positions in one NegRisk event were approved. | `agent/risk/manager.py:31` |
| 2 | **Longshot `edge` is an algebraic constant** — `p_agent = p_market − BIAS_STRENGTH`, so the gate can never fail and `p_agent` carries zero independent information. Replace it; do not tune it. | `agent/strategies/longshot.py:90` |
| 3 | **Shell quoting in the ops script.** A commit message read `honest fills at /usr/bin/bash.999` — `$0.999` with `$0` expanded, and `$9,824` lost its `$`. Every dollar figure in the build log is corrupt. Use single quotes or `-F <file>`. | `agent/run_cycle.py` / ops |
| 4 | `meta.agent_version` is empty — publish the git sha, or a months-long run cannot be traced to the code that produced it. | `agent/publish/snapshots.py` |

---

## 6. Standing rules

- **Keep the Integrity tab at zero errors.** If a change turns it red, that is
  the signal — never a tolerance to adjust.
- **File a report per phase** (`reports/phase-N-report.md`) with every acceptance
  criterion and its actual number. Two commits shipped with no report, which is
  how six open defects went unnoticed.
- **Report contradictions loudly.** If the data says the plan is wrong, that is
  the most valuable output you can produce. Do not quietly retune until the
  numbers look better.
- **Never tune against live P&L.**
- **Disagree in a report before deviating**, not after.

---

## 7. Priority summary

```
1. Run the two unrun test files              ← BLOCKING
2. Reset + verify zero trades, 0 integrity errors  ← BLOCKING
3. Phase E: viability study + E3 + go/no-go   ← THE DECIDING QUESTION
4. Phase M: maker execution (if E says taker is dead)
5. Open bugs 1-4, alongside
```

Not on this list: calibration, ensembling, new strategies, dashboard work. All
premature until §3 says there is something worth trading.

**If you can only do one thing: §1, then §3a.** Together they take under an hour
and tell us whether the last several days of work were pointed at a real
opportunity or an impossible one.
