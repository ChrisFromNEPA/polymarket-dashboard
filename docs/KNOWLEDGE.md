# Polymarket Knowledge Base

**Purpose:** Technical reference for the Hermes agent. Read this after PLAN.md.
Every fact here is verified against live API responses or official docs.

---

## 1. API landscape

Polymarket exposes three APIs:

| API | Endpoint | Auth | What it serves |
|-----|----------|------|----------------|
| **Gamma** | `gamma-api.polymarket.com` | None | Events, markets, metadata, resolution status |
| **CLOB** | `clob.polymarket.com` | None (read) | Orderbooks, prices, midpoints |
| **Data** | `data-api.polymarket.com` | None | Historical timeseries, volume, activity |

### Key endpoints we use

```
Gamma:
  GET /events              — trending events (limit, offset)
  GET /markets             — markets with volume, outcomes, clobTokenIds

CLOB:
  GET /book?token_id=X     — L2 orderbook (BOTH sides, deepest first)
  GET /midpoint?token_id=X — current midpoint price
  GET /price?token_id=X&side=BUY&size=N — executable price estimate

Data:
  GET /timeseries?market=X&interval=1d&fidelity=720 — price history
```

### Critical: book ordering

The CLOB `/book` endpoint returns levels **worst-first**:
- **bids**: ascending (0.001, 0.002, 0.003, ...)
- **asks**: descending (0.999, 0.998, 0.997, ...)

**bids[0] and asks[0] are the WORST prices, not the best.**
Sort bids descending and asks ascending before use.
Our `OrderBook.__post_init__` enforces this defensively.
This bug caused all fills at $0.999 for the first 2 weeks.

---

## 2. Market structure

### Token model
- Every binary market has two CLOB tokens: YES and NO
- Token IDs are the `clobTokenIds` from the Gamma API
- YES token pays $1.00 if Yes, $0.00 if No
- NO token pays $1.00 if No, $0.00 if Yes
- YES price + NO price ≈ $1.00 (minus spread)

### Outcome tokens (conditional)
- For multi-outcome markets, each outcome has a conditional token
- "Conditional" = pays only if the parent event resolves to that outcome
- We currently only handle binary markets

### NegRisk events
- Multi-outcome events where at most one outcome resolves Yes
- Common for political primaries: 128 candidates, one winner
- Positions in the same NegRisk event are **correlated**
- If one outcome resolves Yes, all others must resolve No
- Risk manager must group positions by NegRisk event_id

---

## 3. Orderbook and trading

### Tick size
- Minimum tick: 0.001 ($0.001)
- Prices are in the range [0.001, 0.999]
- Books can have levels at every tick

### Order types (CLOB V2)
- **GTC** (Good Till Cancelled): rests until filled or cancelled
- **GTD** (Good Till Date): rests until a specified time
- **FOK** (Fill Or Kill): completely fills or is rejected
- **FAK** (Fill And Kill): fills what it can, cancels remainder

### Fee structure (2026)

| Role | Fee |
|------|-----|
| **Maker** (limit order that rests) | **0%** (plus earns daily rebates) |
| **Taker** (market order) | Category-dependent |
| Geopolitical / world events | 0% (both sides) |

**Taker Rebate Program** (launched May 29, 2026): 7 tiers based on weighted monthly volume, up to significant rebate percentages.

**→ For paper trading, maker execution is the obvious path.**
Post limit orders, earn the spread instead of paying it.

### Fill simulation constraints
- Market orders: walk the book level by level, VWAP fill
- Limit orders: rest and fill only when subsequent trade prints cross the level
- Never fill at mid — that's fabricated liquidity
- Never fill resting orders on touch alone — that's the primary failure mode of naive simulators

---

## 4. Market lifecycle

```
Created → Active → (Paused) → Resolved
                              ├─ Yes: payout $1.00
                              └─ No:  payout $0.00
```

### Resolution via UMA Optimistic Oracle
1. **Proposal:** Anyone proposes an outcome with a bond
2. **Challenge window:** ~2 hours for disputes
3. **Dispute:** Goes to UMA token holder vote (rare)
4. **Settlement:** Final price set, positions resolve
5. **Payouts:** Token holders can redeem at the final price

### Resolution detection
- Gamma API `closed: true` — market is no longer active
- `outcomePrices` — final token prices (e.g., `["1","0"]` = Yes won)
- CLOB midpoint should converge to $1.00 or $0.00 at resolution

---

## 5. Price history data

### Granularity constraint
- **Active markets:** 1-hour minimum fidelity (`fidelity=60`)
- **Closed markets:** 12-hour minimum fidelity (`fidelity=720`)
- `fidelity=60/120/360` returns **0 points** for closed markets
- This was confirmed on 62 resolved markets

### Implication for backtesting
- Closed-market price points are too sparse for strategy evaluation
- At 12-hour gaps, mid-history `p_market` is a poor probability estimate
- Backtests on closed markets will misleadingly show no edge
- Live forward-testing is the only reliable path

---

## 6. Common pitfalls (learned the hard way)

### The orderbook direction bug
**Symptom:** All fills at $0.999, "99.8% spreads on 100% of markets"
**Cause:** Reading bids[0]/asks[0] as BEST when they're WORST
**Fix:** Sort bids descending, asks ascending in `_parse_book_levels`

### The midpoint sizing gap
**Symptom:** Sizing uses midpoint, fill uses ask → $0.60 overshoot on $500 cap
**Fix:** Use 98% of position cap for share computation

### The "required_edge clustered on 0.49/0.499/0.998" tell
**Symptom:** Phase E viability showed p50=$0.499 across 200 markets
**Cause:** Books were backwards → midpoints pinned at 0.5 → required edge = 0.999-0.5
**Lesson:** A universal extreme result is almost always an instrumentation bug

### The async function left unawaited
**Symptom:** `'coroutine' object is not subscriptable`
**Cause:** `get_scorecard()` was made async but callers weren't updated
**Fix:** `await agent.get_scorecard()` in all callers

---

## 7. Brier score fundamentals

```
brier = mean((p - outcome)²)
```

- Range: [0, 1]
- Lower is better
- 0.25 = random guessing (p=0.50 on binary outcome)
- 0.00 = perfect prediction
- Market Brier ≈ 0.21 on our corpus (12h points)

### Brier delta
```
delta = brier_agent - brier_market
```
- Positive = agent is WORSE than market
- Negative = agent is BETTER than market
- |delta| < 0.01 with small n = noise, not edge

### Why Brier, not P&L
- P&L over ~100 trades is dominated by variance
- A lucky $50 win on one trade can mask 99 bad predictions
- Brier measures each forecast equally
- Only ~7.6% of Polymarket wallets are profitable

---

## 8. Project architecture decisions

| Decision | Rationale |
|----------|-----------|
| SQLite as source of truth | From agent-next/polymarket-paper-trader; WAL mode, 657 tests |
| Paper trading only | No private keys, no wallet, no real money — ever |
| Fake $10,000 bankroll | Round number, enough for position sizing to matter |
| 4-hour cycle cadence | Balances data freshness vs API rate limits |
| Brier as primary metric | PLAN v2 §1; P&L is secondary |
| LLM proposes, code validates | Risk limits in Python, never in prompts |
| One repo for agent + dashboard | Same-origin fetch, no CORS, single deploy |

---

## 9. Research sources

### Projects we studied
- `guberm/polymarket-bot`: AI ensemble trader, position review loop, Kelly sizing
- `agent-next/polymarket-paper-trader`: Honest fill simulation, 657 tests, SQLite
- `Benjam1nCup/Polymarket-trading-bot-python-V2`: Maker liquidity bot, YES/NO splitting
- `ImMike/polymarket-arbitrage`: Cross-platform arb (Polymarket + Kalshi)

### Reference docs
- Polymarket CLOB API V2: `clob.polymarket.com`
- Gamma API: `gamma-api.polymarket.com`
- Polymarket US Fees: `docs.polymarket.us/fees`
- ForecastBench: `forecastbench.org` (LLM calibration benchmarks)
