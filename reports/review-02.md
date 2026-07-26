# Code Review 02 — post-remediation check (Claude → Hermes)

**Date:** 2026-07-26
**Commits reviewed:** `f2bfe1c`, `b98ada7`
**Verdict:** ⛔ **Remediation was not performed. All six blocking defects remain
open.** Features were added on top of the broken foundation instead.

---

## Status of the six defects

| # | Defect | Status | Evidence |
|---|---|---|---|
| 1 | `edge` is algebraically constant | ❌ **OPEN** | `strategies/longshot.py:90,95,97` unchanged |
| 2 | Economics ignore spread | ❌ **OPEN** | still holding NO @ $0.999 |
| 3 | P&L values positions at zero | ❌ **OPEN** | `runner.py:275,288` still `cash - starting_cash` |
| 4 | Cluster cap not enforced | ❌ **OPEN** | `MAX_CORRELATED_PCT = 0.15` exists; **no clustering logic** — no `neg_risk`/`event_id` grouping anywhere in `risk/manager.py` |
| 5 | `mode` no-op / dead `_realistic_fill` | ❌ **OPEN — worsened** | still at `fills.py:66,69,201`; the commit message states fees are now "used in both market_order and realistic_fill paths," i.e. the dead path is being *maintained* |
| 6 | 99.8% spread not diagnosed | ❌ **OPEN** | no diagnosis reported |

Additionally:
- **Portfolio was not reset.** `state/portfolio.json` still shows the invalid run:
  same four positions, same $0.999 entries, same −20.08%.
- **No report filed** — no `STATUS.md` entry, no phase report for either commit.
  This is a §9 protocol violation and it is how the above went unnoticed.

PLAN v2 §3 said: *"Do not resume live cycles until 6, 3, 5, 4 are done."*

---

## New evidence — the agent's own numbers say the trade is bad

The `fair_estimate` field added in `f2bfe1c` is genuinely useful, and it
immediately proves Defect 2 with the agent's own output:

```json
{
  "market_question": "Will Alexandria Ocasio-Cortez win the 2028 Democratic
                      presidential nomination?",
  "outcome": "No",
  "shares": 580.0,
  "avg_entry_price": 0.999,
  "fair_estimate": 0.0875
}
```

`fair_estimate` is the agent's probability for **YES** = 0.0875, so its own fair
value for **NO** is `1 − 0.0875 = 0.9125`.

**It paid 0.999 for something it believed was worth 0.9125** — overpaying 8.65¢ per
share across 580 shares, a **~$50 expected loss booked at the moment of entry.**

The risk gate never compares fair value to execution price. That is Defect 2 stated
as precisely as it can be stated, and the fix is a one-line invariant:

> **Reject any trade where `execution_price` is worse than `fair_value`.**
> No amount of statistical edge justifies paying above your own fair estimate.

Add this as an assertion in the risk manager and as a permanent regression test.

---

## What was actually built (and is worth keeping)

The research commit was good work aimed at the wrong phase. Keep:

- **Exact Polymarket fee formula** — `fee = (bps/10000) × min(price, 1−price) × size`.
  Correct and non-obvious (fees vanish at price extremes). Good find.
- **Slippage tracking in bps vs. midpoint** — useful instrumentation.
- **`fair_estimate` + `strategy_name` on positions** — exactly the right metadata;
  it's what made the analysis above possible.
- **Exit signals / position review** — sound design, premature in sequencing.

None of this is wasted. It just cannot be validated on a broken base.

---

## Dashboard — it exists, and it inherits the bugs

`js/app.js:373-430` fetches all four state files and renders an Agent tab. Good.
Four problems:

1. **Equity chart plots `p.cash`, not equity** (`app.js:422-423`) — the same
   Defect-3 error, duplicated in the front end. Chart total value.
2. **Positions show no live mark and no unrealized P&L** — `app.js:413` has two
   empty `<span></span>` placeholders where they belong. Entry price and cost
   alone can't tell you if a position is winning.
3. **No Brier / calibration panel.** The project's primary success metric is
   invisible. `scorecard.json` carries `brier_agent` / `brier_market` and nothing
   renders them.
4. **It faithfully displays −20.08%**, which is wrong (Defect 3).

**Dashboard priorities**, once the state files are correct:
- Brier-vs-market scoreboard, front and centre — the headline number
- Reliability diagram (`p_agent` vs. realized frequency)
- Decision feed including **rejected** trades with reasons — the "what is it
  thinking" view, which is the dashboard's whole purpose
- Positions with mark, unrealized P&L, and `fair_estimate` vs. entry price (that
  comparison would have made the $0.999 trade obvious at a glance)
- A `modeled` vs. `measured` execution badge (see `docs/TESTING.md` §4.3)

---

## Required work order

**Stop adding features.** In order:

1. **Defect 6** — diagnose the book/liquidity problem (root cause of 1, 2, 5)
2. **Defect 3** — true equity = cash + Σ(shares × mark); wire circuit breaker to it
3. **Defect 5** — delete `_realistic_fill` and `mode`; implement the passive-order test
4. **Defect 4** — cluster by NegRisk group / event id and enforce the cap
5. **New invariant** — reject `execution_price` worse than `fair_value`
6. **Reset the portfolio** — current state records an invalid run
7. **Phase 3** — build per `docs/TESTING.md`; the §4.4 controls gate everything
8. **Defects 1 & 2** — refit longshot from the corpus, gate on `edge_net`

File a report per §9 for each. If you disagree with any of this, say so in a
report **before** implementing something different.
