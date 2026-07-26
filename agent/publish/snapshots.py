"""Publishing layer — writes state snapshots for GitHub Pages dashboard."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class Publisher:
    """Writes agent state to state/ JSON files for the dashboard."""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def publish_portfolio(self, snapshot: dict) -> str:
        """Write portfolio.json."""
        return self._write("portfolio.json", snapshot)

    def publish_scorecard(self, scorecard: dict) -> str:
        """Write scorecard.json."""
        return self._write("scorecard.json", scorecard)

    def publish_decisions(self, decisions: list[dict]) -> str:
        """Write decisions.json — includes rejected trades and why."""
        return self._write("decisions.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "decisions": decisions,
        })

    def publish_equity(self, equity_points: list[dict]) -> str:
        """Write equity.json — time series for charting."""
        return self._write("equity.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "points": equity_points,
        })

    def publish_trades(self, trades: list[dict]) -> str:
        """Write trades.json — append-only executed trades."""
        existing = self._read("trades.json")
        if isinstance(existing, dict):
            existing_trades = existing.get("trades", [])
        else:
            existing_trades = []
        existing_trades.extend(trades)
        return self._write("trades.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "trades": existing_trades[-500:],  # keep last 500
        })

    def publish_all(self, agent) -> list[str]:
        """Publish full state snapshot from an AutonomousAgent."""
        files_written = []

        # Portfolio
        portfolio_snapshot = agent.get_portfolio_snapshot()
        files_written.append(self.publish_portfolio(portfolio_snapshot))

        # Equity point
        equity = self._read("equity.json")
        points = equity.get("points", []) if isinstance(equity, dict) else []
        points.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "cash": portfolio_snapshot["cash"],
            "pnl": portfolio_snapshot["pnl"],
            "pnl_pct": portfolio_snapshot["pnl_pct"],
        })
        files_written.append(self._write("equity.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "points": points[-200:],  # last 200 points
        }))

        return files_written

    def _write(self, filename: str, data: dict) -> str:
        """Write JSON to state directory. Returns the file path."""
        filepath = self.state_dir / filename
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return str(filepath)

    def _read(self, filename: str) -> dict | None:
        """Read JSON from state directory, or None."""
        filepath = self.state_dir / filename
        if not filepath.exists():
            return None
        try:
            with open(filepath) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
