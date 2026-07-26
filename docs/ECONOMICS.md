# Economics — what has to be true for this to make money

**Version:** 1.0 · 2026-07-26
**Status:** design — implement as PLAN.md Phase E (blocking, before more strategy work)
**Why this exists:** the project measures forecasting quality rigorously and has
never once asked whether a profitable configuration exists.

---

## 1. The alignment problem, stated plainly

The goal is **an agent that makes money on prediction markets**. What has been
built is **an apparatus for detecting self-deception**. Those overlap, but they
are not the same thing, and the difference now matters.

Current state, honestly:

| Built | Status |
|---|---|
| Honest fill engine | ✅ Excellent — caught a worthless strategy immediately |
| Backtest harness + controls | ✅ Built |
| Integrity checking | ✅ Built |
| Execution-price invariant | ✅ Just fixed |
| Book recorder | ✅ Running |
| **A strategy with any edge** | ❌ **None** |
| **Evidence that profit is possible at all** | ❌ **Never measured** |

We have a very good truth-detector pointed at nothing. Every defensive component
works. No offensive component exists.

### The specific error

**Brier score was made the objective. Brier is a diagnostic.**

They come apart in both directions:

- **Better Brier, no money.** Brier averages forecast quality over *all* markets.
  Profit comes from *selectively* trading the few where edge exceeds costs. An
  agent can be better-calibrated than the market everywhere and still never find
  a tradeable spread.
- **Worse Brier, money.** An agent that is badly calibrated on 95% of markets but
  strongly right on 5% it actually trades will print money while scoring poorly.

The research this plan cites says so directly: *high probabilistic calibration
does not guarantee superior trading returns.* We quoted that and then built the
whole scoreboard around calibration anyway.

**Correct hierarchy:**

1. **Objective:** risk-adjusted profit after realistic costs
2. **Diagnostic:** Brier vs. market — explains *whether* profit came from skill
3. **Guardrail:** integrity, honest fills — stops us fooling ourselves

Brier stays. It stops being the headline.

### The second error

**"Expect zero trades" was treated as success.** It is the correct *behaviour*
given the invariant, but it is a **dead end as an outcome**. An agent that never
trades cannot make money. If every book we look at prices worse than our own fair
value, then the configuration we chose cannot work, and the response is to change
the configuration — not to admire the discipline of abstaining.

---

## 2. The profit equation

Everything reduces to this. Per trade:

```
expected_profit = (fair_value − execution_price) × shares          [BUY]
net_edge        = |p_agent − p_market| − half_spread − fees − slippage
```

And over a period:

```
return_on_capital = (net_edge_per_trade × avg_position_size × trade_count)
                    / capital_at_risk
```

Four levers, and we have been ignoring three:

| Lever | Current state |
|---|---|
| **net_edge** | Unknown — no validated strategy |
| **trade_count** | Currently **zero** — every candidate fails the cost test |
| **position_size** | Quarter-Kelly, capped 5% — fine |
| **costs** | Now honestly modelled — and they are eating everything |

The binding constraint today is not forecast quality. **It is that
`half_spread > edge` on every market we have looked at.** That is an execution and
market-selection problem, not a forecasting problem — and no amount of calibration
work will fix it.

---

## 3. Why market selection is currently backwards

The runner scans `client.trending(limit=15)` — markets sorted by **volume**.

Those are the most watched, most arbitraged, most efficient markets on the
platform. They are where edge is *least* likely to exist. And when the agent then
reached for less-covered markets (2028 nomination longshots), it found books so
thin that the spread was 10× any plausible edge.

This is the central tension:

```
        efficient, tight spreads          neglected, wide spreads
        ├────────────────────────────────────────────────────────┤
        no edge to find                    edge exists but
        (costs low, edge ~0)               costs exceed it
                         ↑
                  the viable band —
                  never measured
```

**We have never checked whether a viable middle band exists.** That is the single
most important unanswered question in the project, and it is answerable in days
with data we already collect.

---

## 4. Phase E — the viability study (blocking)

Before any further strategy work, answer: **is there any configuration in which
this makes money?**

### E1. Map the opportunity set

Using the Book Recorder data plus a fresh scan of the full market universe (not
just trending), measure for every active market:

- `half_spread` at realistic size (walk the book for $50, $200, $1000)
- 24h volume, current liquidity, days to resolution
- category, whether `negRisk`

Publish the **joint distribution of spread against market segment**. We currently
have exactly one data point on this — "99.8% spreads" — from a sample that was
never validated.

### E2. Establish the edge budget

For each segment, compute the **minimum edge required to break even**:

```
required_edge = half_spread + fees + slippage_buffer
```

This gives a concrete target. If a segment requires 8¢ of edge, and no plausible
forecaster beats the market by 8¢, that segment is dead — permanently, regardless
of model quality. Cross it off and stop looking at it.

### E3. Overlay achievable edge

From the Phase 3 corpus, measure how far the market price was from truth,
bucketed by the same segments:

- distribution of `|p_market − outcome|` by segment and horizon
- how much of that gap is *knowable in advance* rather than hindsight

Overlay E2 and E3. **The viable band is where achievable edge exceeds required
edge.** If the bands do not overlap anywhere, the honest conclusion is that this
cannot be profitable as a taker — go to §5.

### E4. Deliverable

A single table:

| Segment | Median half-spread | Required edge | Achievable edge (p50/p90) | Viable? | Est. trades/mo |
|---|---|---|---|---|---|
| Top-100 by volume | | | | | |
| Mid-liquidity, >30d | | | | | |
| Thin longshots | | | | | |
| Sports, near-term | | | | | |

Plus a **go / no-go recommendation with numbers attached.**

---

## 5. Maker execution — probably the actual unlock

If §4 shows required edge exceeds achievable edge as a **taker**, that is not the
end. It means we are paying the spread when we should be **earning** it.

- **Taker:** cross the spread, pay `half_spread` per trade. Currently fatal.
- **Maker:** post a limit order at or inside our fair value and wait. Cost becomes
  *negative* — we collect spread instead of paying it. Trade-off: uncertain fills
  and adverse selection.

`docs/TESTING.md` §5.7 already flags passive execution as the default, and
PLAN.md §5.7 repeats it, but **the fill engine only supports market orders.** The
single highest-leverage engineering task in the project is limit-order support.

### The honesty requirement

Paper-trading maker fills is where simulators lie hardest. A resting order fills
**preferentially when you are wrong** — informed flow picks you off; uninformed
flow leaves you unfilled. A naive simulator that fills every resting order when
price touches it will manufacture spectacular fake returns.

Required model:
1. Fill only when later trade prints **cross** the level (already specified in
   TESTING.md, still unimplemented).
2. Apply **adverse-selection haircut**: measure, from recorded book data, the
   price drift in the N minutes *after* a fill at that level. If price
   systematically moves against filled orders, that drift is a real cost.
3. Model **queue position** — being at a price level does not mean being first.

Without 1–3, do not report maker P&L at all.

---

## 6. Venue reality — the thing "make money" actually depends on

⚠️ **This changes what the project can be.**

Polymarket's offshore platform — the one behind `gamma-api.polymarket.com` and
`clob.polymarket.com`, which this agent reads — **excludes US persons by its
Terms of Service**, following the 2022 CFTC settlement. Circumventing that (VPN
etc.) breaches the ToS and forfeits any recourse.

However, the picture changed materially:

- Polymarket acquired CFTC-licensed **QCEX** for $112M (July 2025), creating
  **QCX LLC, dba "Polymarket US"** — a CFTC-regulated Designated Contract Market.
- US traders have access via **Polymarket US**, fully collateralised, no leverage.
- A CFTC application concerning the main platform was filed 2026-04-28, and a new
  CFTC probe opened June 2026. **The situation is still in flux.**

**Implication for this project:** we are modelling the *offshore* venue's books,
but any real execution by a US person would happen on **Polymarket US**, which may
have a different market set, different liquidity, different fees, and a different
API. Edge measured on one venue does not automatically transfer to the other.

**Required actions:**
1. Phase E must confirm **which venue's order books we are actually recording**,
   and whether Polymarket US exposes an API.
2. If they differ, either re-point the data layer at the tradeable venue, or state
   explicitly that this is a research exercise on untradeable data.
3. Consider **Kalshi** — CFTC-regulated since 2020, unambiguously legal for US
   persons, with a public API. If the edge is real, it likely transfers, and
   cross-venue price differences are themselves a classic edge source.

This is not legal advice. Verify current status before any real-money step.

---

## 7. Financial targets and kill criteria

The project has run this long with no definition of success or failure.

### Success (paper)
- Positive net P&L after modelled costs over ≥200 trades
- `brier_agent < brier_market` on traded markets (skill, not luck)
- Positive expectancy in ≥2 independent market segments
- Max drawdown < 15%

### Minimum viable economics
- **≥ 20 qualifying trades/month.** Below this, no sample and no compounding.
- **≥ 2¢ net edge per share after all costs.**
- **> 8% annualised** on capital at risk — below that, the effort is not worth it.

### Kill criteria — state these now, honour them later
Abandon or fundamentally redesign if:
1. Phase E finds **no segment** where achievable edge exceeds required edge, as
   both taker and maker.
2. After 3 months, qualifying trades/month < 5 — the strategy is untestable in
   any reasonable timeframe.
3. Realistic maker fill modelling erases the maker advantage.
4. `brier_agent ≥ brier_market` after 200 resolutions — no forecasting skill.

**A clean "this does not work, here is the evidence" is a successful outcome.** It
is far more valuable than a system that trades indefinitely without edge.

---

## 8. Revised priority order

What actually moves toward the goal, most important first:

1. **Phase E viability study** — is profit possible? (days, blocking)
2. **Limit-order support + honest maker fills** — likely the only viable execution
3. **Market selection rebuild** — hunt the viable band, stop scanning trending
4. **Replace the longshot strategy** — structurally incapable of edge (`edge` is
   an algebraic constant), not fixable by tuning
5. **Live LLM forecaster** on segments E proved viable
6. Calibration, ensembling — only once something trades

Note what moved **down**: calibration and ensembling are excellent work and
premature. They refine a signal we have not yet shown can be traded profitably.

---

## 9. What stays exactly as it is

The epistemic infrastructure is genuinely good and must not be relaxed to make
numbers look better:

- Honest fills, walking real book depth
- The execution-price invariant — never pay above your own fair value
- Integrity checks at zero errors
- Brier vs. market, retained as the **diagnostic**
- Control strategies gating the backtest
- Contamination controls

**None of this loosens.** The pressure that arrives with a profit objective is
exactly the pressure these were built to resist. Adding a money target is not
permission to soften the measurement.
