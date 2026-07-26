#!/usr/bin/env python3
"""MCP server for the Polymarket autonomous trading agent.

Exposes tools that Hermes can call via cron:
  - run_cycle: Run one full agent cycle (scan → evaluate → risk → fill)
  - get_portfolio: Current portfolio snapshot
  - get_scorecard: Agent performance metrics
  - get_decisions: Recent decisions (including rejected trades)
  - get_equity: Equity curve
  - reset_agent: Reset portfolio to starting cash

Usage:
    python3 agent/mcp_server.py              # Start MCP server on stdio
    python3 agent/mcp_server.py --run-once   # Run one cycle and exit

Register with Hermes:
    hermes mcp add polymarket-agent -- agent/.venv/bin/python agent/mcp_server.py
"""

import asyncio
import json
import sys
from datetime import datetime, timezone

from agent.runner import AutonomousAgent
from agent.publish.snapshots import Publisher


# Global agent instance — initialized on first use
_agent: AutonomousAgent = None
_run_history: list = []
_publisher: Publisher = None


def get_agent() -> AutonomousAgent:
    global _agent
    if _agent is None:
        _agent = AutonomousAgent(starting_cash=10_000)
    return _agent


def get_publisher() -> Publisher:
    global _publisher
    if _publisher is None:
        _publisher = Publisher(state_dir="state")
    return _publisher


# ── MCP Tools ──────────────────────────────────────────────

async def tool_run_cycle(max_markets: int = 100) -> dict:
    """Run one full agent trading cycle against live Polymarket data.

    Scans markets, evaluates strategy, sizes positions, executes fills,
    and publishes state snapshots for the dashboard.

    Args:
        max_markets: Maximum markets to scan (default 100)
    """
    agent = get_agent()
    result = await agent.run_cycle(max_markets=max_markets)
    _run_history.append(result)

    # Publish state
    pub = get_publisher()
    pub.publish_all(agent)
    pub.publish_decisions(agent.get_decisions_log(_run_history[-5:]))
    pub.publish_scorecard(agent.get_scorecard(_run_history[-20:]))

    return {
        "cycle_time": result.time,
        "markets_scanned": result.markets_scanned,
        "proposals_generated": result.proposals_generated,
        "proposals_approved": result.proposals_approved,
        "trades_executed": result.trades_executed,
        "cash": result.cash,
        "open_positions": result.open_positions,
        "errors": result.errors,
        "decisions": [
            {
                "market": d.proposal.market_question[:80],
                "direction": d.proposal.direction,
                "outcome": d.proposal.outcome,
                "p_market": round(d.proposal.market_probability, 4),
                "p_agent": round(d.proposal.agent_probability, 4),
                "approved": d.risk_decision.approved,
                "filled": d.filled,
                "fill_price": round(d.fill_price, 4) if d.filled else None,
                "fill_shares": d.fill_shares,
                "reason": d.risk_decision.reason if not d.filled else "filled",
            }
            for d in result.decisions
        ],
    }


async def tool_get_portfolio() -> dict:
    """Get current portfolio snapshot — cash, positions, recent trades."""
    agent = get_agent()
    return agent.get_portfolio_snapshot()


async def tool_get_scorecard() -> dict:
    """Get agent performance metrics — Brier score, P&L, trade counts."""
    agent = get_agent()
    return agent.get_scorecard(_run_history[-20:])


async def tool_get_decisions(limit: int = 20) -> dict:
    """Get recent agent decisions — including rejected trades and reasons."""
    agent = get_agent()
    decisions = agent.get_decisions_log(_run_history[-5:])
    return {
        "total_decisions": len(decisions),
        "decisions": decisions[-limit:],
    }


async def tool_get_equity() -> dict:
    """Get equity curve for charting."""
    pub = get_publisher()
    data = pub._read("equity.json")
    return data or {"points": []}


async def tool_reset_agent(starting_cash: float = 10_000.0) -> dict:
    """Reset the agent's portfolio to starting cash. WARNING: discards all positions."""
    global _agent, _run_history
    from agent.engine.portfolio import PortfolioEngine

    _agent = AutonomousAgent(starting_cash=starting_cash)
    _run_history = []

    # Reset state files
    pub = get_publisher()
    pub.publish_portfolio({"cash": starting_cash, "pnl": 0.0, "positions": [], "recent_trades": []})
    pub.publish_equity([])
    pub.publish_scorecard({"status": "reset"})
    pub.publish_decisions([])

    return {
        "status": "reset",
        "starting_cash": starting_cash,
        "message": f"Portfolio reset to ${starting_cash:,.2f}. All positions cleared.",
    }


# ── Tool registry ──────────────────────────────────────────

TOOLS = {
    "run_cycle": tool_run_cycle,
    "get_portfolio": tool_get_portfolio,
    "get_scorecard": tool_get_scorecard,
    "get_decisions": tool_get_decisions,
    "get_equity": tool_get_equity,
    "reset_agent": tool_reset_agent,
}


# ── MCP protocol handler ───────────────────────────────────

async def handle_request(request: dict) -> dict:
    """Handle a JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "polymarket-agent",
                    "version": "1.0.0",
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": func.__doc__.split("\n")[0] if func.__doc__ else "",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                k: {"type": "number" if v in (int, float) else "string"}
                                for k, v in func.__annotations__.items()
                                if k != "return"
                            },
                        },
                    }
                    for name, func in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        try:
            result = await TOOLS[tool_name](**arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


async def main_stdio():
    """Run MCP server on stdin/stdout (JSON-RPC line protocol)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = await handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            continue


async def run_once():
    """Run one cycle and print results."""
    print(f"Running agent cycle at {datetime.now(timezone.utc).isoformat()}...")
    result = await tool_run_cycle()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if "--run-once" in sys.argv:
        asyncio.run(run_once())
    else:
        asyncio.run(main_stdio())
