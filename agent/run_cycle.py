#!/usr/bin/env python3
"""Autonomous agent cycle — run, publish, commit, push.

One-shot script for cron-driven autonomy. Runs one full agent cycle
against live Polymarket data, publishes state snapshots, and optionally
commits + pushes to GitHub so the dashboard stays live.

Usage:
    python3 agent/run_cycle.py                    # Run cycle, publish state
    python3 agent/run_cycle.py --commit           # Also git commit + push
    python3 agent/run_cycle.py --forecaster       # Use LLM forecaster (needs API key)
    python3 agent/run_cycle.py --reset            # Reset portfolio first
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.runner import AutonomousAgent
from agent.publish.snapshots import Publisher
from agent.engine.portfolio import PortfolioEngine


async def run_cycle(commit: bool = False, reset: bool = False):
    """Run one complete agent cycle."""
    print(f"=== Polymarket Agent Cycle ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Initialize agent
    agent = AutonomousAgent(starting_cash=10_000)

    if reset:
        print("Resetting portfolio...")
        agent.portfolio = PortfolioEngine(starting_cash=10_000)
        # Clear state files
        pub = Publisher()
        pub.publish_portfolio({"cash": 10000, "starting_cash": 10000, "pnl": 0.0,
                               "pnl_pct": 0.0, "positions": [], "recent_trades": [],
                               "total_equity": 10000, "positions_value": 0.0})
        pub.publish_equity([{"time": datetime.now(timezone.utc).isoformat(),
                             "cash": 10000, "positions_value": 0.0,
                             "total_equity": 10000, "pnl": 0.0, "pnl_pct": 0.0}])
        # verdict stays null until something actually resolves — a stored verdict
        # with zero evidence is a trap for anything else reading this file.
        pub.publish_scorecard({"n_resolved": 0, "verdict": None})
        pub.publish_decisions([])
        pub.publish_calibration([])
        pub.publish_resolutions([])
        pub.publish_meta({"mode": "paper", "cycles_total": 0})
        print("Portfolio reset to $10,000\n")

    # Run cycle
    print("Running agent cycle...")
    result = await agent.run_cycle(max_markets=100)

    # Publish state
    print("Publishing state...")
    pub = Publisher()
    run_history = [result]
    await pub.publish_all(agent, run_history)
    pub.publish_decisions(agent.get_decisions_log(run_history))
    pub.publish_scorecard(await agent.get_scorecard(run_history))
    pub.publish_meta({
        "mode": "paper",
        "cycles_total": 1,
        "last_cycle_at": datetime.now(timezone.utc).isoformat(),
    })

    # Summary
    print(f"\n=== Cycle Complete ===")
    print(f"Markets scanned:    {result.markets_scanned}")
    print(f"Proposals:          {result.proposals_generated}")
    print(f"Approved:           {result.proposals_approved}")
    print(f"Trades executed:    {result.trades_executed}")
    print(f"Cash:               ${agent.portfolio.cash:,.2f}")

    if agent.portfolio.positions:
        marks = {}
        positions_value = 0.0
        for key, pos in agent.portfolio.positions.items():
            try:
                mark = await agent.client.get_midpoint(pos.token_id)
            except:
                mark = pos.avg_entry_price
            marks[key] = mark
            positions_value += pos.shares * mark
        total_equity = agent.portfolio.cash + positions_value
        print(f"Positions:          {len(agent.portfolio.positions)}")
        print(f"Total equity:       ${total_equity:,.2f}")
    else:
        print(f"Positions:          0")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for e in result.errors:
            print(f"  {e}")
    else:
        print("Errors:             0")

    # Git commit + push
    if commit:
        print("\nCommitting state to GitHub...")
        state_files = "state/meta.json state/portfolio.json state/scorecard.json " \
                      "state/calibration.json state/decisions.json state/equity.json " \
                      "state/resolutions.json"
        try:
            subprocess.run(["git", "add"] + state_files.split(), check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m",
                 f"cycle: {result.trades_executed} trades, "
                 f"equity=${agent.portfolio.cash:,.0f}, "
                 f"{len(agent.portfolio.positions)} positions"],
                check=True, capture_output=True,
            )
            subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
            print("✅ Committed and pushed to GitHub")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Git failed: {e.stderr.decode() if e.stderr else e}")

    return result


if __name__ == "__main__":
    commit = "--commit" in sys.argv
    reset = "--reset" in sys.argv

    asyncio.run(run_cycle(commit=commit, reset=reset))
