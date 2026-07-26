# Research — where edge comes from, and how to capture it

**Version:** 1.0 · 2026-07-26
**Complements:** [`KNOWLEDGE.md`](KNOWLEDGE.md) (API/technical reference) and
[`ECONOMICS.md`](ECONOMICS.md) (unit economics)
**Purpose:** the strategy-side knowledge base. What the field has learned about
making money on prediction markets, and what it means for this agent.

Every claim here is sourced. When a source contradicts our code, that is recorded
as an open action rather than quietly resolved.

---

## 1. 🔴 The most important finding: we are trading the wrong markets

Published guidance on LLM prediction-market bots converges on a market filter:

| Criterion | Recommended | What the agent traded |
|---|---|---|
| Resolution window | **7–60 days** | 2028 election — **>800 days** ❌ |
| Price range | **$0.10–$0.90** | 0.002 – 0.13 — **extreme** ❌ |
| Structure | **Binary; skip multi-outcome initially** | NegRisk, 128 candidates ❌ |
| Volume | ≥ $50k | ✅ met |
| Avoid | niche markets, no historical analog | 2028 primary longshots ❌ |

**Every one of the four positions violated four of the five criteria.**

The reasoning is sound and independent of any one source:

- **Extreme prices lack edge.** At $0.002 a market is already saying "essentially
  never." An LLM cannot meaningfully distinguish 0.2% from 0.4%, and the tick
  size (0.001) is half the price. There is no room to be right in.
- **Long horizons dilute information.** Edge comes from knowing something the
  market has not priced. Over 800 days almost any information decays.
- **Multi-outcome events are correlated.** 128 candidates for one nomination is
  one bet, not 128 — which is precisely the cluster-cap failure we already logged.

The counter-finding from our own Phase E — that these markets have **1-tick
spreads** and cost ~0.0005 to enter — is real but insufficient. Cheap to trade is
not the same as possible to be right about. **Low cost plus no edge is still no
profit.**

**Action:** market selection must filter to 7–60 day horizon, $0.10–$0.90 price,
binary structure. This is a bigger lever than any model improvement.

---

## 2. LLM forecaster design

### 2.1 Calibration reality — plan for this, don't discover it

> Claude's "high confidence" predictions resolve correctly **~64% of the time,
> not 90%.**

This is the single most useful number for sizing. It means:

- **Confidence scores are not probabilities.** Never feed a stated confidence
  into Kelly directly.
- **Quarter-Kelly is not conservatism, it is correction.** Full Kelly on a
  confidence that is 26 points optimistic is a fast route to ruin.
- Realistic win rate on well-priced markets is **55–65%**. Edge comes from beating
  the implied probability, not from a high hit rate — a 55% win rate at good
  prices beats 70% at bad ones.

Published realized edge for careful implementations: **8–12% annualised.** That
brackets our >8% target in ECONOMICS.md §7, which suggests the target is
demanding but not fantasy.

### 2.2 Prompt architecture

Four mandatory sections:

1. **Role** — probabilistic forecaster; base-rate reasoning; explicit warning
   against overconfidence
2. **Market context** — title, **full resolution criteria**, YES/NO prices, book
   depth, price history
3. **Evidence** — news briefs with **source tags**, supplied in-prompt
4. **Output schema** — strict JSON: `probability` (0–1), `confidence`,
   `key_drivers`, `risks`, `action` ∈ {buy_yes, buy_no, **skip**}

### 2.3 Three rules that prevent hallucination

1. **Always supply the news. Never ask the model to recall events.** Recall is
   where fabrication enters.
2. **Require citation.** The model must name which supplied evidence supports its
   conclusion. **If it cannot cite, it is hallucinating** — discard the forecast.
3. **Make `skip` a first-class output.** Without it, a model asked for a
   probability will always produce one, however thin the signal.

Rule 2 is the strongest single defence and is cheap to implement: reject any
forecast whose citations do not resolve to supplied evidence IDs.

⚠️ This complements but does not replace PLAN §5.3's **market-blind first pass** —
the model must produce `p_raw` *before* seeing `p_market`, or `p_agent` collapses
into a transform of the market price. That was Defect 1.

### 2.4 Model routing

| Tier | Model | Use | Share |
|---|---|---|---|
| Screen | Haiku 4.5 | filter 1000+ markets | bulk |
| Analyse | Sonnet 4.6 | probability estimation | ~90% |
| Escalate | Opus 4.7 | high-conviction only | 5–10/day |

**Cost rule: inference must never exceed 5% of bet size.** A $50 position supports
at most $2.50 of queries. Unbounded inference spend destroys the economics of
small positions faster than bad forecasts do.

This is directly relevant to us: Hermes can route across providers, so the tiering
is implementable today.

---

## 3. Fee economics

### 3.1 The formula — and a bug in ours

**Official (Polymarket US, effective 2026-07-01):**

```
fee = Θ × C × p × (1 − p)
```

| Role | Θ | Max (at p = 0.50) |
|---|---|---|
| Taker | 0.06 | $1.50 per 100 contracts |
| **Maker** | **−0.0125** | **−$0.31 per 100 contracts** |

**Makers are paid, not charged.** The rebate applies at the point of trade.

🔴 **Bug in `agent/engine/fills.py::calculate_fee`.** It computes

```python
fee = (bps / 10_000) * min(price, 1 - price) * cost
```

`min(p, 1−p) × p` is **not** `p × (1−p)`. They agree for p ≥ 0.5 and diverge
below it:

| p | Correct `p(1−p)` | Ours `min(p,1−p)·p` | Error |
|---|---|---|---|
| 0.80 | 0.160 | 0.160 | ✅ |
| 0.50 | 0.250 | 0.250 | ✅ |
| 0.20 | 0.160 | 0.040 | **4× understated** |
| 0.05 | 0.0475 | 0.0025 | **19× understated** |

Currently harmless only because `fee_rate` defaults to 0. It must be fixed before
fees are enabled, and it understates cost precisely on the cheap contracts the
agent has been buying.

### 3.2 Two venues, two schedules

- **Polymarket US (QCX):** the Θ formula above.
- **Offshore (what our API reads):** Fee Structure V2 (2026-03-30), by category —
  crypto 0.07, sports 0.05 (raised from 0.03 in July 2026), finance/politics/tech
  0.04, economics/culture/weather 0.05. **Geopolitics and world events are
  permanently fee-free.** Maker rebates return 20–25% of taker fees, paid daily
  (15% sports, 20% crypto, 25% default).

**Two implications:**
1. **Fee-free geopolitical/world-event markets are the cheapest taker venue on the
   platform.** Combined with 1-tick spreads, taker execution there is close to
   free — this deserves testing before assuming maker is required.
2. Fees scale with `p(1−p)`, so they **vanish at extreme prices**. Extreme markets
   are cheap to trade and impossible to be right about; mid-range markets are
   where both edge and fees live.

---

## 4. Prior art

### 4.1 Open-source bots worth studying

| Project | Lang | Strategy | Why it matters here |
|---|---|---|---|
| **Poly-Market-Maker** | Python | Market making + inventory mgmt | **Most relevant to Phase M.** Production-grade inventory handling |
| polymarket-arb-bot | TS | YES/NO sum < $1 arb | Simple, rarely profitable — confirms structural arb is picked over |
| Gamma-Trader | Python | Twitter/news sentiment | Event-driven edge; needs paid X API |
| polybot-cli | Go | Sniping, <100ms | Latency ceiling reference |
| Polymarket-RL-Agent | Python | PPO reinforcement learning | Interesting, hard to interpret — not our path |
| **Resolution-Hunter** | Python | Buy pre-resolution below $1.00 | **Cheap, understandable settlement edge — worth evaluating** |
| OpenPM-Bot | TS | Modular framework | Architecture reference |

Also catalogued in PLAN §2: `Polymarket/agents` (archived), `artvandelay/polymarket-agents`,
`warproxxx/poly_data`, `guberm/polymarket-bot`, `agent-next/polymarket-paper-trader`.

### 4.2 Two candidate strategies we have not considered

- **Resolution/settlement edge.** Buy markets trading below $1.00 that are
  effectively already decided, and hold to settlement. Low capital, low gas,
  understandable. Risks: capital locked for days–weeks, ambiguous resolutions,
  oracle delay. **This is testable with our existing engine.**
- **Fee-free geopolitical markets.** Zero taker fee plus 1-tick spreads may make
  taker viable without Phase M at all.

---

## 5. The competitive reality

- **~92% of Polymarket traders lose money** (consistent with the ~7.6%
  profitable-wallet figure in PLAN §1).
- By 2026 the easy edges are arbitraged away. Remaining advantage is in
  **prompt quality, context, and execution speed** — not in having an LLM at all.
- Prices move **5–10¢ within minutes** on news. Anything latency-sensitive is a
  race we will lose; our edge must be in *judgement over hours*, not *speed over
  seconds*. This reinforces PLAN §5.1's long-horizon preference — with §1's
  correction that "long" means weeks, not years.

---

## 6. Actions arising

| # | Action | Where | Priority |
|---|---|---|---|
| 1 | Market filter: 7–60d horizon, $0.10–$0.90, binary only | `strategies/`, scan | 🔴 highest |
| 2 | Fix `calculate_fee` to `Θ·C·p·(1−p)` | `engine/fills.py` | 🔴 before fees on |
| 3 | Citation-required forecaster output; reject uncitable | forecaster | 🔴 |
| 4 | `skip` as first-class action | forecaster | 🟠 |
| 5 | Model tiering (Haiku→Sonnet→Opus), inference ≤5% of bet | forecaster | 🟠 |
| 6 | Tighten position cap 5% → 2%; target 10–20 uncorrelated | `risk/manager.py` | 🟠 |
| 7 | Test fee-free geopolitical markets as taker venue | Phase E follow-up | 🟠 |
| 8 | Evaluate resolution/settlement edge strategy | new strategy | 🟡 |
| 9 | Study Poly-Market-Maker before building Phase M | Phase M | 🟡 |

---

## 7. Sources

- [AI Trading Ranked — Claude bots for Polymarket](https://ai-trading-ranked.com/posts/claude-ai-trading-bots-polymarket-2026)
- [AI Trading Ranked — 7 open-source Polymarket bots](https://ai-trading-ranked.com/posts/polymarket-trading-bot-open-source-github)
- [Polymarket US fee schedule](https://docs.polymarket.us/fees)
- [Polymarket maker rebates](https://polymarkets.co.il/en/guide/polymarket-maker-rebates/)
- [ForecastBench](https://www.forecastbench.org/) · [AIA Forecaster](https://arxiv.org/pdf/2511.07678)
- [Systematic Edges in Prediction Markets](https://quantpedia.com/systematic-edges-in-prediction-markets/)
- [NegRisk docs](https://docs.polymarket.com/advanced/neg-risk) · [prices-history](https://docs.polymarket.com/api-reference/markets/get-prices-history)

**Note on sourcing:** §1 and §2 draw on published practitioner guidance, not peer
review. Treat the specific numbers (64% confidence accuracy, 8–12% returns) as
well-informed estimates to be **verified against our own resolutions**, not
established fact. That verification is what the Brier diagnostic is for.
