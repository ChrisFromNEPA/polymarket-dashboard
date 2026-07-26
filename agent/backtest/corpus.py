"""Backtest corpus — loads and manages resolved market data.

Immutable once built. Point-in-time discipline enforced:
  - At simulated time T, the agent sees ONLY data timestamped ≤ T.
  - Winner labels are hidden from the strategy.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent.polymarket.models import PricePoint


@dataclass
class CorpusMarket:
    """A single resolved market for backtesting."""
    question: str
    condition_id: str
    slug: str
    winner: str  # "Yes" or "No"
    volume: float
    token_id_yes: str
    token_id_no: str
    price_history: list[PricePoint]  # sorted by timestamp ascending
    neg_risk: bool = False

    @property
    def outcome(self) -> int:
        """Ground truth: 1 if Yes won, 0 if No won."""
        return 1 if self.winner == "Yes" else 0

    @property
    def time_range(self) -> tuple[int, int]:
        """First and last timestamp in price history."""
        if not self.price_history:
            return (0, 0)
        return (self.price_history[0].timestamp, self.price_history[-1].timestamp)

    def get_price_at(self, timestamp: int) -> Optional[float]:
        """Get the market price at or before a given timestamp.

        Returns the most recent price ≤ timestamp, or None if before first data.
        This is the core point-in-time function — never leaks future data.
        """
        if not self.price_history:
            return None

        best = None
        for pt in self.price_history:
            if pt.timestamp <= timestamp:
                best = pt.price
            else:
                break
        return best


class Corpus:
    """Immutable collection of resolved markets for backtesting."""

    def __init__(self, filepath: str = "state/corpus.json"):
        self.filepath = Path(filepath)
        self.markets: list[CorpusMarket] = []
        self._by_condition: dict[str, CorpusMarket] = {}

    def load(self) -> int:
        """Load corpus from JSON. Returns count of markets loaded."""
        with open(self.filepath) as f:
            data = json.load(f)

        for m in data:
            cm = CorpusMarket(
                question=m["question"],
                condition_id=m["condition_id"],
                slug=m["slug"],
                winner=m["winner"],
                volume=m["volume"],
                token_id_yes=m["token_id_yes"],
                token_id_no=m["token_id_no"],
                price_history=[
                    PricePoint(timestamp=pt["t"], price=pt["p"])
                    for pt in m.get("price_history", [])
                ],
                neg_risk=m.get("neg_risk", False),
            )
            cm.price_history.sort(key=lambda p: p.timestamp)
            self.markets.append(cm)
            self._by_condition[cm.condition_id] = cm

        return len(self.markets)

    def get(self, condition_id: str) -> Optional[CorpusMarket]:
        return self._by_condition.get(condition_id)

    @property
    def count(self) -> int:
        return len(self.markets)

    @property
    def winners_yes(self) -> int:
        return sum(1 for m in self.markets if m.winner == "Yes")

    @property
    def winners_no(self) -> int:
        return sum(1 for m in self.markets if m.winner == "No")
