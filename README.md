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

An agent that runs autonomously, scanning live [Polymarket](https://polymarket.com) markets, estimating probabilities, and placing **paper trades with $10,000 fake money**. Every forecast is scored against what actually happened. The result will be a falsifiable answer — including, quite possibly, "no detectable edge."

**This is not a trading bot. It's a forecasting experiment.** The primary metric is **Brier score** (how well-calibrated the agent's probabilities are), not P&L. Over a few hundred trades, P&L is mostly variance. Brier measures actual skill.

For context, on [ForecastBench](https://www.forecastbench.org/): human superforecasters score ~0.096, the best LLMs ~0.122–0.136, the general public ~0.121.

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
- ⏳ Maker execution: limit orders planned (Polymarket makers pay zero fees)

**First cycles are running. The experiment has begun.**

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
- **Makers pay zero fees** and earn daily rebates
- Takers pay fees by category; tiered rebate program launched May 29, 2026
- Geopolitical/world event markets are fee-free
- **This strongly favors maker execution** (Phase M)

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
| **[KNOWLEDGE.md](docs/KNOWLEDGE.md)** | Technical reference: APIs, fees, markets, pitfalls |
| [docs/TESTING.md](docs/TESTING.md) | Three-track simulation design |
| [docs/DASHBOARD.md](docs/DASHBOARD.md) | Dashboard data contract and design |
| [docs/ECONOMICS.md](docs/ECONOMICS.md) | Why taker vs maker, cost-of-entry study |
| [reports/STATUS.md](reports/STATUS.md) | Running build log |
| [reports/](reports/) | Per-phase reports and code reviews |

New here? Read **PLAN.md**, then **KNOWLEDGE.md**.

---

## Related open-source projects we studied

| Project | What it does | What we learned |
|---------|-------------|-----------------|
| [guberm/polymarket-bot](https://github.com/guberm/polymarket-bot) | AI ensemble trader with Kelly sizing | Position review loop, ghost position detection, exit rules |
| [agent-next/polymarket-paper-trader](https://github.com/agent-next/polymarket-paper-trader) | Paper trading with realistic fill simulation | Exact fee formula, FOK/FAK orders, SQLite source of truth, 657 tests |
| [Benjam1nCup/Polymarket-trading-bot-python-V2](https://github.com/Benjam1nCup/Polymarket-trading-bot-python-V2) | Maker liquidity bot for short-interval markets | USDC → YES/NO splitting, balanced limit orders |
| [predict-raven](https://github.com/Alchemist-X/predict-raven) | LLM forecasting agent, Brier-scored | Market-blind forecasting, transparent scoring |

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
