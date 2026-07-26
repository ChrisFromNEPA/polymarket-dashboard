# Polymarket Forecasting Agent

**An autonomous AI agent that forecasts prediction markets and trades paper money — a long-running experiment to answer one question: can an LLM beat the market?**

[![Dashboard](https://img.shields.io/badge/dashboard-live-blue)](https://chrisfromnepa.github.io/polymarket-dashboard)
[![Tests](https://img.shields.io/badge/tests-45%2F45-green)](tests/)
[![Phase](https://img.shields.io/badge/phase-trading-yellow)](reports/STATUS.md)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

**Live dashboard:** [chrisfromnepa.github.io/polymarket-dashboard](https://chrisfromnepa.github.io/polymarket-dashboard)

> ⚠️ **Fake money only.** No wallet, no private keys, no order signing — ever. Nothing here places a real trade.

---

## What this is

An agent that runs autonomously, scanning live [Polymarket](https://polymarket.com) markets, estimating probabilities, and placing **paper trades with $10,000 fake money**. Every forecast is scored against what actually happened. The result will be a falsifiable answer — including, quite possibly, "this does not work."

**The goal is an agent that makes money.** Proven first on paper, with costs modelled honestly enough that the result would survive contact with real execution.

Three metrics, in strict order:

| | Metric | Role |
|---|---|---|
| **Objective** | Risk-adjusted profit after realistic costs | What we are trying to achieve |
| **Diagnostic** | Brier score vs. the market price | Separates skill from luck — profit without it won't persist |
| **Guardrail** | Honest fills, integrity checks | Stops us fooling ourselves |

Brier is essential but it is *not* the target. An agent can be better calibrated
than the market everywhere and still never find a tradeable price. Both numbers
get reported together, always.

For context, on [ForecastBench](https://www.forecastbench.org/): human superforecasters score ~0.096, the best LLMs ~0.122–0.136, the general public ~0.121. And for scale of the challenge: **roughly 92% of Polymarket traders lose money.**

---

## Current status

**✅ Trading live with paper money.** 45/45 tests pass. Agent runs every 4 hours via cron, publishes state to GitHub Pages.

- 🟢 Fill engine: honest book-walking, exact fee formula, slippage tracking
- 🟢 Risk manager: Quarter-Kelly sizing, position caps, fair-value invariant, circuit breaker
- 🟢 Portfolio: VWAP positions, exit rules (stop-loss/take-profit/edge-gone)
- 🟢 Backtest harness: 62-market corpus, 4 control strategies all pass
- 🟢 Dashboard: Brier hero, calibration chart, decision feed, positions with marks
- 🟡 Strategy: favorite-longshot (pipeline validator — confirmed zero edge)
- ⏳ Forecaster: LLM probability estimation module built, awaiting live integration
- ⏳ Maker execution: limit orders planned (makers earn a **negative** fee — see below)

**Known-wrong right now, being fixed:**
- 🔴 **Market selection.** The agent is trading 2028-election longshots: >800-day
  horizon, prices at $0.002–$0.13, inside a 128-outcome NegRisk event. Published
  guidance says target **7–60 days, $0.10–$0.90, binary only** — we violate four
  of five criteria. See [docs/RESEARCH.md](docs/RESEARCH.md) §1.
- 🔴 **Fee formula** uses `min(p, 1−p)` where the real formula is `p × (1−p)` —
  understates fees ~4× at p=0.20. Harmless only because fees are currently off.

**Turning point:** a two-week bug had the orderbook read backwards (Polymarket
returns levels worst-first), making every fill land at $0.999 and every spread
look like 99.8%. Fixed — real spreads are **one tick**. See
[reports/review-04.md](reports/review-04.md).

---

## How it works

```
Hermes agent (cron, autonomous, Ubuntu VM)
   │  MCP tools
   ▼
Python agent ──────────────────► Polymarket public APIs
data · fills · risk · forecaster         (Gamma, CLOB, prices-history)
   │
   │ publish snapshots
   ▼
state/*.json ──► git push ──► GitHub Pages dashboard (read-only)
```

**The LLM proposes; deterministic code validates, sizes, and fills.** Risk limits live in tested Python, never in a prompt — an LLM asked to respect a position limit will eventually not.

The agent runs on [Hermes](https://github.com/nousresearch/hermes-agent) (DeepSeek v4-pro) on an always-on Ubuntu VM. GitHub Pages only *displays* results.

---

## Repository layout

```
index.html, css/, js/     # Dashboard — GitHub Pages serves from root
agent/                    # Python agent
  polymarket/             #   Async API client + typed models
  engine/                 #   Fill engine, portfolio, settlement
  risk/                   #   Position sizing and limits
  strategies/             #   Pluggable strategies
  backtest/               #   Corpus + replay harness
  publish/                #   State → JSON snapshots
  viability.py            #   Phase E cost study
  run_cycle.py            #   One-shot cron runner
  book_recorder.py        #   L2 orderbook snapshot recorder
tests/                    # pytest, 45 tests incl. adversarial + viability
state/                    # Published JSON the dashboard reads
docs/, reports/           # Design docs and build log
```

---

## Quick start

**Dashboard** (static, no dependencies):
```bash
python3 -m http.server 8844
# Open http://localhost:8844
```

**Agent** (Python 3.11+, [uv](https://docs.astral.sh/uv/)):
```bash
cd agent && uv sync
```

**Run one cycle:**
```bash
PYTHONPATH=. agent/.venv/bin/python agent/run_cycle.py
```

**Reset and run fresh:**
```bash
PYTHONPATH=. agent/.venv/bin/python agent/run_cycle.py --reset
```

**Tests:**
```bash
PYTHONPATH=. agent/.venv/bin/python -m pytest tests/ -v
```

---

## Key technical facts

**Polymarket CLOB (Central Limit Order Book):**
- Tick size: 0.001 ($0.001 per share)
- Books are off-chain; settlement on Polygon
- `/book` endpoint returns levels **worst-first** (bids ascending, asks descending)
- This was a critical bug: we read bids[0]/asks[0] as BEST for weeks, causing all fills at $0.999
- Corrected May 2026 — see `reports/review-04.md`

**Fee structure (2026):**
- Formula: **`fee = Θ × contracts × p × (1 − p)`** — so fees **vanish at extreme
  prices** and peak at $0.50
- **Taker Θ = 0.06** (max $1.50 per 100 contracts) · **Maker Θ = −0.0125** —
  makers are **paid $0.31 per 100 contracts**, applied at the point of trade
- Offshore venue uses a category schedule instead: crypto 0.07, sports 0.05,
  politics/finance/tech 0.04, and **geopolitics/world events are fee-free**
- **Two consequences:** maker execution is strictly better where you can get
  filled, and fee-free geopolitical markets may make *taker* viable without it

**NegRisk markets:**
- Multi-outcome events where only one outcome can resolve Yes
- Political primaries are the main example (128 candidates, one winner)
- Positions in the same NegRisk event are **correlated** — risk manager must group them

**Market resolution:**
- UMA Optimistic Oracle resolves markets
- Resolution process: proposal → challenge window → settlement
- Resolved tokens pay $1.00 (Yes) or $0.00 (No)

---

## Documentation

| Doc | What's in it |
|-----|-------------|
| **[PLAN.md](PLAN.md)** | Mission, architecture, phases, anti-goals |
| **[docs/RESEARCH.md](docs/RESEARCH.md)** | **Where edge comes from** — market selection, LLM forecaster design, fee economics, prior art |
| **[docs/KNOWLEDGE.md](docs/KNOWLEDGE.md)** | Technical reference: APIs, market structure, pitfalls |
| [docs/ECONOMICS.md](docs/ECONOMICS.md) | Unit economics, viability study, kill criteria |
| [docs/TESTING.md](docs/TESTING.md) | Three-track simulation design |
| [docs/DASHBOARD.md](docs/DASHBOARD.md) | Dashboard data contract and design |
| [reports/WORK-ORDER.md](reports/WORK-ORDER.md) | **Current ordered task list** |
| [reports/STATUS.md](reports/STATUS.md) | Running build log |
| [reports/](reports/) | Per-phase reports and code reviews |

New here? **PLAN.md** (why) → **RESEARCH.md** (where edge is) → **KNOWLEDGE.md**
(how the API works). Working on it? Start at **WORK-ORDER.md**.

---

## Roadmap

Ordered by what actually moves toward the goal. Full detail in
[ECONOMICS.md §8](docs/ECONOMICS.md).

| Stage | Goal | Status |
|---|---|---|
| **Foundation** | Honest fills, integrity, backtest controls | ✅ done |
| **Viability** | Is profit possible? Cost study across the universe | ✅ redone post-fix — 99.7% of markets cost ≤2¢ |
| **Market selection** | Trade 7–60d, $0.10–$0.90, binary only | 🔴 next — biggest single lever |
| **Forecaster v1** | Retrieval + structured output + citation requirement | ⏳ |
| **Calibration** | Extremization / Platt against real resolutions | ⏳ |
| **Maker execution** | Limit orders, adverse-selection modelling | ⏳ |
| **Long run** | 200+ resolutions, Brier vs market, weekly reports | ⏳ |

**Success:** ≥20 qualifying trades/month, ≥2¢ net edge, >8% annualised, and
`brier_agent < brier_market` over 200+ resolutions.

**Kill criteria are written down** ([ECONOMICS.md §7](docs/ECONOMICS.md)) and will
be honoured. A clean *"this doesn't work, here's the evidence"* is a successful
outcome.

---

## Related open-source projects we studied

| Project | What it does | What we learned |
|---------|-------------|-----------------|
| [guberm/polymarket-bot](https://github.com/guberm/polymarket-bot) | AI ensemble trader with Kelly sizing | Position review loop, ghost position detection, exit rules |
| [agent-next/polymarket-paper-trader](https://github.com/agent-next/polymarket-paper-trader) | Paper trading with realistic fill simulation | Exact fee formula, FOK/FAK orders, SQLite source of truth, 657 tests |
| [Benjam1nCup/Polymarket-trading-bot-python-V2](https://github.com/Benjam1nCup/Polymarket-trading-bot-python-V2) | Maker liquidity bot for short-interval markets | USDC → YES/NO splitting, balanced limit orders |
| [predict-raven](https://github.com/Alchemist-X/predict-raven) | LLM forecasting agent, Brier-scored | Market-blind forecasting, transparent scoring |
| [artvandelay/polymarket-agents](https://github.com/artvandelay/polymarket-agents) | MCP server + bot, Claude, SQLite | Closest architectural prior art |
| [Polymarket/agents](https://github.com/Polymarket/agents) *(archived)* | Official framework, RAG + superforecasting | Prompt design; don't depend on it |
| [warproxxx/poly_data](https://github.com/warproxxx/poly_data) | Historical market/trade retriever | Backtest corpus source |
| Poly-Market-Maker | Market making with inventory mgmt | Reference for Phase M |
| Resolution-Hunter | Buy below $1.00 pre-settlement | Untested strategy worth evaluating |

Strategy findings from these are distilled in **[docs/RESEARCH.md](docs/RESEARCH.md)**.

---

## Anti-goals

- ❌ **No real-money trading.** No wallet, no private keys, no order signing.
- ❌ No tuning the simulator against live P&L
- ❌ No LLM enforcing its own risk limits
- ❌ No reporting P&L without Brier comparison
- ❌ No strategy added before fill engine passes adversarial tests

**A negative result is a valid and useful outcome.** Quietly adjusting parameters until numbers look good is the primary failure mode of this class of project.

---

## License

MIT
