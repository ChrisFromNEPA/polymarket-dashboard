"""Publishing layer — writes state snapshots for GitHub Pages dashboard.

D0 contract (docs/DASHBOARD.md §4): emits meta.json, calibration.json,
resolutions.json, and extends scorecard/equity/decisions/portfolio with
all fields the dashboard needs.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class Publisher:
    """Writes agent state to state/ JSON files for the dashboard."""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    # ── D0: all required state files ────────────────────────

    def publish_meta(self, meta: dict) -> str:
        """Write meta.json — agent health and status."""
        defaults = {
            "last_cycle_at": None,
            "next_cycle_eta": None,
            "mode": "paper",
            "agent_version": "",
            "cycles_total": 0,
            "errors_last_24h": 0,
            "recorder_gap_minutes_24h": 0,
        }
        defaults.update(meta)
        defaults["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self._write("meta.json", defaults)

    def publish_portfolio(self, snapshot: dict) -> str:
        """Write portfolio.json with mark prices and fair estimates."""
        snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self._write("portfolio.json", snapshot)

    def publish_scorecard(self, scorecard: dict) -> str:
        """Write scorecard.json with Brier delta, CI, verdict."""
        defaults = {
            "n_resolved": 0,
            "brier_agent": None,
            "brier_market": None,
            "brier_delta": None,
            "brier_delta_ci95": None,
            "verdict": None,
            "ece": None,
            "by_strategy": {},
            "benchmarks": {
                "always_favorite": None,
                "market_parrot": None,
            },
        }
        defaults.update(scorecard)

        # A verdict is a claim about evidence. Never assert one without any.
        if not defaults.get("n_resolved"):
            defaults["verdict"] = None

        defaults["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self._write("scorecard.json", defaults)

    def publish_calibration(self, bins: list[dict]) -> str:
        """Write calibration.json — reliability diagram data."""
        return self._write("calibration.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "bins": bins,
        })

    def publish_resolutions(self, items: list[dict]) -> str:
        """Write resolutions.json — every settled forecast, scored."""
        return self._write("resolutions.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        })

    def publish_decisions(self, decisions: list[dict]) -> str:
        """Write decisions.json with action, reject_reason, edge fields."""
        return self._write("decisions.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "decisions": decisions,
        })

    def publish_equity(self, points: list[dict]) -> str:
        """Write equity.json — total_equity, positions_value, execution_quality."""
        return self._write("equity.json", {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "execution_quality": "modeled",
            "points": points,
        })

    # ── Publish all from agent ──────────────────────────────

    async def publish_all(self, agent, run_history: list = None) -> list[str]:
        """Publish full state snapshot from an AutonomousAgent."""
        files = []

        # Meta
        meta = {
            "last_cycle_at": datetime.now(timezone.utc).isoformat(),
            "mode": "paper",
            "cycles_total": len(run_history) if run_history else 0,
        }
        files.append(self.publish_meta(meta))

        # Portfolio (extended with marks) — now async
        snapshot = await agent.get_portfolio_snapshot()
        files.append(self.publish_portfolio(snapshot))

        # Equity (with total_equity)
        existing = self._read("equity.json")
        points = existing.get("points", []) if isinstance(existing, dict) else []
        # Downsample: keep raw ≤ 7d, hourly ≤ 90d, daily beyond
        points = self._downsample_equity(points)
        points.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "cash": snapshot["cash"],
            "positions_value": snapshot.get("positions_value", 0.0),
            "total_equity": snapshot.get("total_equity", snapshot["cash"]),
            "pnl": snapshot["pnl"],
            "pnl_pct": snapshot["pnl_pct"],
        })
        files.append(self.publish_equity(points[-200:]))

        # Scorecard
        scorecard = agent.get_scorecard(run_history or [])
        files.append(self.publish_scorecard(scorecard))

        # Decisions
        if run_history:
            decisions = agent.get_decisions_log(run_history[-5:])
            files.append(self.publish_decisions(decisions))

        # Calibration (placeholder — populated when we have enough resolutions)
        files.append(self.publish_calibration([]))

        # Resolutions (placeholder)
        files.append(self.publish_resolutions([]))

        return files

    # ── Downsampling ────────────────────────────────────────

    def _downsample_equity(self, points: list[dict]) -> list[dict]:
        """Downsample equity points: raw ≤ 7d, hourly ≤ 90d, daily beyond."""
        if len(points) <= 200:
            return points
        now = datetime.now(timezone.utc)
        result = []
        for pt in points:
            try:
                t = datetime.fromisoformat(pt["time"].replace("Z", "+00:00"))
                age_days = (now - t).total_seconds() / 86400
                if age_days <= 7:
                    result.append(pt)
                elif age_days <= 90 and (len([p for p in result if p.get("_bucket") == "hourly"]) % 4 == 0):
                    pt["_bucket"] = "hourly"
                    result.append(pt)
                elif age_days > 90 and (len([p for p in result if p.get("_bucket") == "daily"]) % 24 == 0):
                    pt["_bucket"] = "daily"
                    result.append(pt)
            except (ValueError, TypeError):
                result.append(pt)
        return result

    # ── I/O ─────────────────────────────────────────────────

    def _write(self, filename: str, data: dict) -> str:
        """Write JSON to state directory. Returns the file path."""
        filepath = self.state_dir / filename
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return str(filepath)

    def _read(self, filename: str) -> Optional[dict]:
        """Read JSON from state directory, or None."""
        filepath = self.state_dir / filename
        if not filepath.exists():
            return None
        try:
            with open(filepath) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
