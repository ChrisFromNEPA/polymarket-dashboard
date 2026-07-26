# Polymarket Forecasting Agent

A long-running experiment: **can an autonomous AI agent forecast prediction
markets better than the market itself?**

An agent scans live [Polymarket](https://polymarket.com) markets, estimates
probabilities, and places **paper trades with fake money**. Every forecast is
scored against what actually happened. The result will be a falsifiable answer —
including, quite possibly, "no."

**Live dashboard:** [chrisfromnepa.github.io/polymarket-dashboard](https://chrisfromnepa.github.io/polymarket-dashboard)

> ⚠️ **Fake money only.** No wallet, no private keys, no order signing, ever.
> Nothing here places a real trade. See [Anti-goals](#anti-goals).

---

## The question, and how it's scored

The goal is **not** "make money." That framing produces an agent that rationalizes
trades and a backtest that flatters itself. Only about **7.6%** of Polymarket
wallets finish profitable.

The goal is a **measurable edge that either shows up or doesn't.** So the primary
metric is not P&L — it's the **Brier score of the agent's probability estimate
versus the market price at the same moment:**

```
brier_agent  = mean((p_agent  - outcome)²)
brier_market = mean((p_market - outcome)²)
```

If `brier_agent >= brier_market`, there is **no predictive edge**, whatever the
P&L says. Over a few hundred trades P&L is dominated by variance; Brier is not.

For reference, on [ForecastBench](https://www.forecastbench.org/): human
superforecasters score ~0.096, the best LLMs ~0.122–0.136, the general public
~0.121.

---

## Current status

**Phase 2.5 — remediation. No validated edge. Results so far are not meaningful.**

Being specific, because overclaiming defeats the point:

- ✅ Data layer, fill engine, portfolio accounting, settlement, risk scaffolding,
  MCP server, and a first dashboard all exist
- ✅ The honest fill engine **caught a worthless strategy on its first live cycle**
  — exactly what it was built to do
- ⛔ Six blocking defects are open — see [`reports/review-02.md`](reports/review-02.md)
- ⛔ No backtest has run yet; the harness is designed but unbuilt
- ⛔ `brier_agent` and `brier_market` are still `null`

The first strategy (favorite-longshot) has been **demoted from "the edge" to
"the pipeline validator"** after a hard finding: on longshot markets the bid-ask
spread is wider than the statistical edge, so a few-cent bias cannot survive
crossing it. The current candidate edge is a **calibrated LLM forecaster on
long-horizon markets, executed passively.**

---

## How it works

```
   Hermes agent (cron, autonomous, Ubuntu VM)
      │  MCP tools
      ▼
   Python agent ──────────────► Polymarket public APIs
   data · fills · risk · forecaster      (Gamma, CLOB, prices-history)
      │
      │ SQLite = source of truth
      ▼ publish snapshots
   state/*.json ──► git push ──► GitHub Pages dashboard (read-only)
```

**The LLM proposes; deterministic code validates, sizes, and fills.** Risk limits
live in tested Python, never in a prompt — an LLM asked to respect a position
limit will eventually not.

Implementation is carried out by the [Hermes agent](https://github.com/nousresearch/hermes-agent)
running on an always-on Ubuntu VM. GitHub Pages only *displays* results; it can't
run the agent.

---

## Documentation

| Doc | What's in it |
|---|---|
| **[PLAN.md](PLAN.md)** | **The source of truth.** Mission, architecture, phases, forecasting stack, anti-goals |
| [docs/TESTING.md](docs/TESTING.md) | Three-track simulation design; why execution *cannot* be backtested historically |
| [docs/DASHBOARD.md](docs/DASHBOARD.md) | UI redesign around the experiment; the `state/*.json` data contract |
| [reports/STATUS.md](reports/STATUS.md) | Running build log, newest first |
| [reports/](reports/) | Per-phase reports and code reviews |

New here? Read **PLAN.md** first.

---

## Repository layout

```
index.html, css/, js/     # dashboard — GitHub Pages serves from root
agent/                    # the Python agent
  polymarket/             #   API client + typed models
  engine/                 #   fills, portfolio, settlement
  risk/                   #   position sizing and limits
  strategies/             #   pluggable strategies
  publish/                #   SQLite → state/*.json
  mcp_server.py           #   tools Hermes calls
tests/                    # pytest, incl. adversarial fill tests
state/                    # published JSON the dashboard reads
docs/, reports/           # design docs and build log
```

The agent and dashboard share one repo deliberately: the dashboard fetches
`state/*.json` as a **same-origin relative path**, so there's no CORS setup and
no second deploy target.

---

## Running it

**Dashboard** (static, no dependencies):

```bash
python3 -m http.server 8844
```

**Agent** (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
cd agent && uv sync && uv run python -m agent.main
```

**Tests:**

```bash
cd agent && uv run pytest ../tests -v
```

---

## Anti-goals

These are constraints, not preferences:

- ❌ **No real-money trading.** No wallet, no private keys, no order signing.
  (Polymarket's ToS also prohibits trading by US persons.)
- ❌ No tuning the simulator, hurdles, or thresholds against live P&L
- ❌ No LLM enforcing its own risk limits
- ❌ No reporting P&L without the paired Brier comparison
- ❌ No strategy added before the fill engine passes every adversarial test

**A negative result is a valid and useful outcome.** Quietly adjusting parameters
until the numbers look good is the primary failure mode of this entire class of
project, and most of the design exists to prevent it.

---

## License

MIT
