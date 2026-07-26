# Polymarket Autonomous Paper-Trading Agent — Build Plan

**Status:** Phase 0 (not started)
**Owner:** Hermes agent (Nous Research), running on always-on Ubuntu VM
**Human:** ChrisFromNEPA
**Last updated:** 2026-07-26

---

## 0. Read this first

This document is the single source of truth for the build. Hermes should work
through it phase by phase, and **report back** using the protocol in §9.

If you (Hermes) disagree with something here, **say so in a report before
implementing a deviation.** Several decisions in this plan are deliberate and
counterintuitive, and are load-bearing for the experiment's validity.

---

## 1. Mission, stated honestly

Build a fully autonomous agent that trades Polymarket prediction markets with
**fake money**, long-term, and produces a **falsifiable record** of whether it
has genuine predictive edge.

The goal is **not** "make money." That framing produces an agent that
rationalizes trades and a backtest that flatters itself. The goal is a
measurable edge that either shows up in the numbers or does not.

Grounding reality: analysis of Polymarket wallets finds only ~7.6% finish
profitable, with the top ~0.04% capturing ~70% of all PnL. Most participants
lose. An agent that "looks profitable" after a few weeks of paper trading is
almost certainly measuring a bug in its own fill model, not alpha.

### The one metric that matters

**Brier score of the agent's probability estimate vs. the Brier score of the
market price at the same moment.**

For every decision, log the agent's probability estimate `p_agent` and the
market's implied probability `p_market` at decision time. When the market
resolves to outcome `y ∈ {0,1}`, compute:

```
brier_agent  = mean((p_agent  - y)^2)
brier_market = mean((p_market - y)^2)
```

If `brier_agent >= brier_market`, **the agent has no predictive edge**,
regardless of what the P&L says. P&L over a few hundred trades is dominated by
variance; Brier is not. This comparison is the experiment.

Log this for *every* market the agent evaluates — including ones it declined to
trade. Declined evaluations are free calibration data.

---

## 2. Success criteria

| Criterion | Bar |
|---|---|
| Predictive edge | `brier_agent < brier_market`, sustained over 200+ resolved markets |
| Calibration | Reliability curve within ±5% across confidence buckets |
| P&L | Positive **after** modeled spread/slippage, attributed per strategy |
| Benchmark | Beats "always buy the favorite" and "buy-and-hold market price" |
| Honesty | Fill model passes the adversarial tests in Phase 2 |

A negative result is a **valid and useful outcome**. Do not tune the simulator
until the result turns positive — that is the primary failure mode of this
entire class of project.

---

## 3. Hazards — known false edges (do NOT build these as-is)

The existing `js/scanner.js` implements three "arbitrage" strategies. **All
three are false-positive generators in their current form.** They must not be
ported forward without the fixes noted.

### 3.1 Calendar spreads (`js/scanner.js:4`)
Pairs markets by "3+ common words ≥4 chars" overlap (`scanner.js:28-32`), then
flags `pEarly > pLate + 0.02`.

**Why it's wrong:** word overlap does not establish that one market's outcome is
logically *nested* inside another's. "Will X happen by March" vs "Will X happen
by June" is a real nesting. "Will Trump win Iowa" vs "Will Trump win Ohio"
shares 3+ words and is not. You will get garbage pairs flagged as free money.

**Fix:** require verified logical nesting — same underlying event, same
resolution source, strictly nested time windows — parsed from resolution
criteria, not from question-text word overlap. If nesting can't be established
with high confidence, discard the pair.

### 3.2 Mutual exclusivity (`js/scanner.js:94`)
Sums `outcomePrices[0]` across markets and flags sum > 1.03 (`scanner.js:121`).

**Why it's wrong, two ways:**
1. It sums **mid/last-trade prices**, which are not executable. Real arbitrage
   requires the sum of **NO asks** to clear the threshold after fees. Mid-price
   sums exceed 1.0 routinely from spread artifacts alone, with zero executable
   edge.
2. Polymarket's **NegRisk adapter** structurally enforces exclusivity on these
   markets and lets traders convert NO baskets into YES + collateral. These are
   among the most heavily arbitraged markets on the platform. A retail-visible
   3% edge sitting there is far more likely a data artifact than an opportunity.

**Fix:** use executable asks only, subtract fees, detect `negRisk: true` and
account for adapter mechanics. Expect this strategy to find approximately
nothing. That is the correct result.

### 3.3 Wide spreads (`js/scanner.js:135`)
Flags spread > 5% as a market-making opportunity (`scanner.js:159`).

**Why it's wrong — this is the most dangerous one.** A wide spread in a thin
market is compensation for **adverse selection**, not free money. The spread is
wide *because* informed flow picks off resting orders. A naive paper simulator
will "fill" both sides instantly and print fabricated profit.

**Fix:** do not implement passive market making until the Phase 2 fill engine
can prove a resting order only fills when the market actually traded through it.
Then expect the edge to largely evaporate. That is the correct result.

### 3.4 Confirmed real bug — NO positions are mismarked (`js/app.js:39`)

**Investigated and confirmed. This is a genuine bug, fix it in the port.**

`js/app.js:29` correctly passes the per-outcome token (`tokenYes`/`tokenNo`) to
the price fetcher. But the NO branch at `js/app.js:37-39` does:

```js
} else {
  // NO token value = 1 - best ask for YES, or from orderbook
  return asks.length ? 1 - parseFloat(asks[0].price) : 0.5;
}
```

The comment says "best ask for YES" but the function was passed the **NO
token**, so `asks[0].price` is the ask on the NO book — already the NO price.
Computing `1 - ask_NO ≈ 1 - (1 - p_YES) = p_YES` marks every NO position at
roughly the **YES** price.

Concretely: hold NO trading at $0.30 and the dashboard values it at ~$0.69.

Correct behavior: mark each outcome token from **its own book's best bid**
(what you could actually sell into), consistently for YES and NO.

> **Note for the record:** an earlier review claimed the code "reuses one
> tokenId for both outcomes." That claim was **wrong** — token routing is
> correct. The bug is the inversion described above. Don't go hunting for the
> wrong bug.

### 3.5 No settlement exists
Nothing in the current code resolves positions to $1/$0. Without settlement the
portfolio drifts on mark-to-market forever and never produces a verdict. This is
a missing core mechanic, not a nice-to-have.

---

## 4. Architecture

SQLite is the source of truth — atomic, transactional, queryable. GitHub
receives **published snapshots**. Using git commits as the live database would
create race conditions and an unusable commit history.

```
   Hermes (cron, autonomous, Ubuntu VM)
      │  MCP tools
      ▼
┌──────────────────────────────────────────┐
│  agent/  (Python)                        │
│  ┌────────────┬──────────────┬────────┐  │
│  │ Data layer │ Fill engine  │ Risk   │  │◄── Polymarket
│  │ Gamma/CLOB │ walks book,  │ Kelly, │  │    Gamma / CLOB
│  │ prices-hist│ settlement   │ caps   │  │    /prices-history
│  └────────────┴──────────────┴────────┘  │
│     Strategies: longshot │ LLM forecaster │
└──────────────────┬───────────────────────┘
                   │ SQLite = truth
                   ▼ publish snapshots
        state/*.json ──► git push ──► GitHub Pages
                                      (read-only dashboard)
```

**Key inversion:** the LLM *proposes*; the deterministic engine *validates,
sizes, and fills*. Guardrails are enforced in code and are never trusted to the
model. An LLM asked to respect a position limit will eventually not.

### Single repo, deliberately
The Python agent lives in this same repo as the dashboard. GitHub Pages serves
static files from root and ignores the Python. This means the dashboard fetches
`state/portfolio.json` as a **same-origin relative path** — no CORS, no second
deploy target.

### Target layout
```
index.html, css/, js/        # dashboard (Pages serves from root)
agent/
  __init__.py
  config.py                  # thresholds, caps, tunables — no magic numbers inline
  polymarket/
    client.py                # Gamma + CLOB HTTP, retries, rate limiting
    models.py                # Market, Token, Book, Position dataclasses
    history.py               # /prices-history wrapper
  engine/
    fills.py                 # order book walking, slippage  ← most important file
    portfolio.py             # cash, positions, avg price, realized/unrealized
    settlement.py            # resolution polling → $1/$0
  strategies/
    base.py                  # Strategy protocol: propose() -> [TradeProposal]
    longshot.py              # Phase 4 — first and only strategy at launch
  risk/
    manager.py               # fractional Kelly, caps, circuit breaker
  backtest/
    replay.py                # /prices-history replay harness
  publish/
    snapshots.py             # SQLite → state/*.json → git push
  mcp_server.py              # tools Hermes calls
tests/                       # pytest — must pass before any phase is "done"
state/                       # published JSON (committed)
reports/                     # Hermes status reports (see §9)
```

---

## 5. Environment

- **Runtime:** always-on Ubuntu VM (Hermes's host). This is the only place the
  agent runs. GitHub Pages can only *display* — it cannot run the agent.
- **Python:** 3.11+. Use `uv` (Hermes already depends on it).
- **The human's Windows machine has no Python and no WSL.** All Python execution
  and testing happens on the VM. Code may be authored on Windows and pushed;
  Hermes runs and validates it.
- **Dependencies:** keep minimal — `httpx`, `pydantic`, `pytest`. Justify any
  addition in a report.
- **Secrets:** never commit tokens. Git push auth via a fine-grained PAT scoped
  to this repo with `contents:write`, stored in the VM environment only.

---

## 6. Scope decision — launch with ONE strategy

**Launch with favorite-longshot bias only.** This is decided; do not expand
scope without reporting first.

Rationale: the favorite-longshot bias (longshots systematically overpriced,
favorites underpriced) is the best-evidenced systematic edge in prediction
markets, it is **mechanical**, and it is **backtestable** against
`/prices-history`. It validates the entire pipeline honestly.

Adding the LLM forecaster on day one makes it impossible to distinguish "bad
forecasts" from "broken simulator." The fill engine must be proven trustworthy
against a mechanical strategy first. The LLM forecaster is Phase 7, gated on
Phase 2's adversarial tests passing.

---

## 7. Phases

Each phase has **acceptance criteria**. A phase is not done until its tests pass
on the VM and a report is filed per §9.

### Phase 1 — Data layer
Port `js/api.js` to Python, correctly.

- Gamma: trending events, search, event-by-slug.
- CLOB: `/book`, `/midpoint`, `/spread`, `/prices-history`.
- Model each market's **two outcome tokens separately**, each with its own book.
- Capture `negRisk` flag, `conditionId`, full **resolution criteria text**, close
  time, and volume/liquidity.
- Rate limiting + retry with backoff. Be a well-behaved API client.

**Acceptance:** fetch 50 live markets; for each, assert `p_yes + p_no` is within
2% of 1.0 using each token's own book. Any market failing this indicates a token
mapping error. Report the pass rate.

### Phase 2 — Honest fill engine ← THE CRITICAL PHASE
This file determines whether the entire experiment is meaningful.

- **Marketable orders** walk the live book level by level, consuming size at
  each price, and pay the spread. No filling at mid. Ever.
- **Size limits:** if the book lacks depth, the order **partially fills or is
  rejected**. Never synthesize liquidity that isn't there.
- **Passive orders** rest and fill **only when subsequent trade prints cross
  them** — verified against later price history, not assumed.
- **Latency:** model a delay between decision and fill; the book may move.
- **Fees:** apply Polymarket's fee structure.
- **Settlement** (`settlement.py`): poll resolution status, settle positions to
  $1/$0, realize P&L, mark the market closed.
- **Bias toward pessimism.** Where uncertain, assume the worse fill. A
  conservative simulator that understates edge is useful; an optimistic one is
  worthless.

**Acceptance — adversarial tests, all must pass:**
1. Buying more than book depth cannot fill entirely at the top-of-book price.
2. An immediate buy-then-sell round trip **loses money** (pays spread twice).
3. A passive order in a market that never traded through it does **not** fill.
4. A resolved market settles positions to exactly $1/$0 and realized P&L ties
   out against cash movements to the cent.
5. Marking a NO position uses the NO book's own bid (regression test for §3.4).

If test 2 shows a profit, the fill engine is broken. Stop and report.

### Phase 3 — Backtest harness
Replay `/prices-history` to validate strategies before any forward trading.

- Deterministic, seeded, reproducible.
- Reuses the **exact same** fill engine as live. No separate backtest fill path —
  that divergence is how backtests come to lie.
- Reports: P&L, Brier vs market, calibration curve, max drawdown, trade count.

**Acceptance:** a deliberately edgeless strategy (trade at market price at
random) backtests to approximately **negative** the spread cost. If a random
strategy shows profit, the harness is broken.

### Phase 4 — Favorite-longshot strategy
- Fit the bias curve on historical resolved markets: bucket by entry price,
  measure realized frequency vs. implied probability.
- Trade only where the historical deviation exceeds spread + fees by a margin.
- Emit `TradeProposal` objects with an explicit `p_agent` estimate — required for
  Brier scoring.

**Acceptance:** backtest shows the bias curve, with confidence intervals and
sample size per bucket. If the effect is inside the error bars, **report that
honestly** rather than trading it.

### Phase 5 — Risk manager
- **Fractional Kelly (quarter-Kelly).** For a contract at price `c` with agent
  probability `p`: `f* = (p - c) / (1 - c)`, then size at `0.25 * f*`. Full
  Kelly on a mis-estimated probability blows up the account.
- Max % of bankroll per position; max exposure per correlated event cluster.
- Minimum liquidity/volume floor; reject closed or near-expiry markets.
- Daily trade cap; per-market cooldown to prevent churn.
- **Circuit breaker:** on drawdown > X%, halt trading and require human review.

**Acceptance:** unit tests prove every limit holds against adversarial proposals,
including proposals that would individually pass but collectively breach a
cluster cap.

### Phase 6 — MCP server + autonomy
- Expose tools: `scan_markets`, `get_book`, `get_market_detail`,
  `propose_trade`, `get_portfolio`, `get_scorecard`, `get_recent_decisions`.
- `propose_trade` runs the full risk gauntlet and **may reject**. Rejection with
  a reason is a normal, expected outcome.
- Register with Hermes; drive via its built-in cron: scan → estimate → size →
  execute → log reasoning.

**Acceptance:** a full unattended cycle runs end to end and writes a decision log
including declined trades with reasons.

### Phase 7 — GitHub publishing
Snapshots written to `state/`:
- `portfolio.json` — cash, positions, live marks, totals
- `trades.jsonl` — append-only executed trades w/ thesis + `p_agent`
- `decisions.json` — **including rejected trades and why** (key observability)
- `equity.json` — time series for charting
- `scorecard.json` — Brier vs market, calibration, P&L per strategy

Plus a **scheduled GitHub Action** that re-marks the portfolio every ~15 min so
the dashboard stays live even when Hermes is idle.

**Acceptance:** dashboard renders live from committed JSON with no CORS errors;
Action runs green on schedule.

### Phase 8 — Dashboard as observability
Rebuild the site as a read-only window into the agent:
- Equity curve, open positions with live marks
- **Decision feed** — the agent's thesis per trade, and what it rejected
- Calibration chart: `p_agent` vs realized frequency
- Brier-vs-market scoreboard

Manual trading moves to a clearly separated sandbox mode.

### Phase 9 — LLM forecaster (gated)
**Do not start until Phase 2 acceptance tests pass and Phase 4 has produced a
clean backtest.**

- Structured forecasting: base rate → evidence → probability → confidence.
- Only trade when `p_agent` beats `p_market` by a hurdle exceeding spread + fees.
- LLMs are systematically overconfident; the hurdle is doing real work.
- Log full reasoning for every estimate for later calibration analysis.

---

## 8. Anti-goals

- ❌ No real-money trading. No wallet, no private keys, no signing. Ever.
- ❌ Do not tune the simulator to make results look better.
- ❌ Do not let the LLM enforce its own risk limits.
- ❌ Do not add strategies before the fill engine passes its adversarial tests.
- ❌ Do not report P&L without the accompanying Brier comparison.

---

## 9. Reporting protocol — how Hermes reports back

**Running log:** `reports/STATUS.md`, newest entry at top:

```markdown
## 2026-07-27 — Phase 2 — in progress
**Done:** book-walking fill implemented; tests 1,3,5 passing
**Blocked:** test 2 (round trip) shows +$0.02 profit — investigating fee sign
**Next:** verify fee application direction
**Confidence:** medium — suspect fees applied as credit not debit
```

**Per-phase completion:** `reports/phase-N-report.md` containing:
- What was built, and any deviation from this plan **with justification**
- Acceptance criteria results — each one, pass/fail, with actual numbers
- Anything discovered that contradicts this plan (**especially valuable**)
- Recommended changes to later phases

**Blockers:** open a GitHub issue labeled `blocker` + `phase-N`. Do not silently
work around a blocker that invalidates an assumption in this plan.

**Commits:** `phase-N: short description`. Small and frequent.

### Report contradictions loudly
If Hermes finds that the favorite-longshot effect doesn't replicate, or that the
fill engine kills the edge, or that this plan is wrong somewhere — **that is the
most valuable possible output.** Report it prominently. Do not quietly adjust
parameters until the numbers look good.

---

## 10. Open questions for the human

1. **Bankroll:** keep $10,000 starting fake capital, or a different figure?
2. **Cadence:** how often should the trading cycle run — hourly, 4-hourly, daily?
3. **Circuit breaker:** what drawdown % should halt trading for review? (20%?)
4. **Market scope:** all markets, or restrict to categories (politics, sports,
   crypto) for a cleaner first experiment?

Hermes: propose defaults for these in your Phase 0 report rather than blocking
on them.

---

## 11. References

- [Polymarket prices-history API](https://docs.polymarket.com/api-reference/markets/get-prices-history)
- [Polymarket NegRisk docs](https://docs.polymarket.com/advanced/neg-risk)
- [neg-risk-ctf-adapter](https://github.com/Polymarket/neg-risk-ctf-adapter)
- [Systematic Edges in Prediction Markets — QuantPedia](https://quantpedia.com/systematic-edges-in-prediction-markets/)
- [Accuracy, Skill, and Bias on Polymarket — SSRN](https://papers.ssrn.com/sol3/Delivery.cfm/5910522.pdf?abstractid=5910522&mirid=1)
- [Hermes agent](https://github.com/nousresearch/hermes-agent)
