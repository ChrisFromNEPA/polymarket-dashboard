"""Portfolio engine — positions, cash, P&L tracking.

Single source of truth for the paper trading portfolio.
All mutations are explicit and auditable.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Position:
    """An open position in a single outcome token."""
    token_id: str
    outcome: str  # "Yes" or "No"
    shares: float
    avg_entry_price: float  # volume-weighted average
    market_question: str = ""
    condition_id: str = ""
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_entry_price

    @property
    def key(self) -> str:
        return f"{self.token_id}:{self.outcome}"


@dataclass
class Trade:
    """A single executed trade."""
    time: str
    action: str  # "BUY" or "SELL"
    outcome: str  # "Yes" or "No"
    token_id: str
    price: float
    shares: float
    cost: float  # positive = cash outflow (buy), negative = cash inflow (sell)
    fee: float = 0.0
    market_question: str = ""
    condition_id: str = ""
    reason: str = ""


class PortfolioEngine:
    """Tracks cash, positions, and trade history."""

    def __init__(self, starting_cash: float = 10_000.0):
        self.cash = starting_cash
        self.starting_cash = starting_cash
        self.positions: dict[str, Position] = {}  # keyed by token_id:outcome
        self.trades: list[Trade] = []

    def _pos_key(self, token_id: str, outcome: str) -> str:
        return f"{token_id}:{outcome}"

    # ── Position Management ──────────────────────────────────

    def add_position(
        self,
        token_id: str,
        outcome: str,
        shares: float,
        price: float,
        market_question: str = "",
        condition_id: str = "",
    ) -> Position:
        """Add to an existing position or create a new one.

        Called after a BUY fill. Deducts cash.
        """
        cost = shares * price
        self.cash -= cost

        key = self._pos_key(token_id, outcome)
        if key in self.positions:
            pos = self.positions[key]
            total_shares = pos.shares + shares
            pos.avg_entry_price = (
                (pos.avg_entry_price * pos.shares + price * shares) / total_shares
            )
            pos.shares = total_shares
        else:
            pos = Position(
                token_id=token_id,
                outcome=outcome,
                shares=shares,
                avg_entry_price=price,
                market_question=market_question,
                condition_id=condition_id,
            )
            self.positions[key] = pos

        self.trades.append(Trade(
            time=datetime.now(timezone.utc).isoformat(),
            action="BUY",
            outcome=outcome,
            token_id=token_id,
            price=price,
            shares=shares,
            cost=cost,
            market_question=market_question,
            condition_id=condition_id,
        ))

        return pos

    def reduce_position(
        self,
        token_id: str,
        outcome: str,
        shares: float,
        price: float,
        reason: str = "",
    ) -> tuple[float, float]:
        """Sell shares from an existing position. Returns (realized_pnl, remaining_shares).

        Raises ValueError if position doesn't exist or has insufficient shares.
        """
        key = self._pos_key(token_id, outcome)
        pos = self.positions.get(key)

        if pos is None:
            raise ValueError(f"No position for {key}")
        if pos.shares < shares:
            raise ValueError(
                f"Insufficient shares: have {pos.shares}, trying to sell {shares}"
            )

        revenue = shares * price
        cost_basis = pos.avg_entry_price * shares
        realized_pnl = revenue - cost_basis

        self.cash += revenue
        pos.shares -= shares

        self.trades.append(Trade(
            time=datetime.now(timezone.utc).isoformat(),
            action="SELL",
            outcome=outcome,
            token_id=token_id,
            price=price,
            shares=shares,
            cost=-revenue,  # negative = cash inflow
            market_question=pos.market_question,
            condition_id=pos.condition_id,
            reason=reason,
        ))

        # Remove empty positions
        if pos.shares <= 0:
            del self.positions[key]
            remaining = 0.0
        else:
            remaining = pos.shares

        return realized_pnl, remaining

    def settle_position(self, token_id: str, outcome: str, resolved_value: float) -> float:
        """Settle a position at resolution — $1 for correct, $0 for incorrect.

        Returns realized P&L.
        """
        key = self._pos_key(token_id, outcome)
        pos = self.positions.get(key)
        if pos is None:
            return 0.0

        revenue = pos.shares * resolved_value
        cost_basis = pos.shares * pos.avg_entry_price
        realized_pnl = revenue - cost_basis

        self.cash += revenue

        self.trades.append(Trade(
            time=datetime.now(timezone.utc).isoformat(),
            action="SETTLE",
            outcome=outcome,
            token_id=token_id,
            price=resolved_value,
            shares=pos.shares,
            cost=-revenue,
            market_question=pos.market_question,
            condition_id=pos.condition_id,
            reason=f"settled at ${resolved_value}",
        ))

        del self.positions[key]
        return realized_pnl

    # ── Valuation ────────────────────────────────────────────

    def get_position_value(self, token_id: str, outcome: str, mark_price: float) -> float:
        """Value a position at the given mark price."""
        key = self._pos_key(token_id, outcome)
        pos = self.positions.get(key)
        if pos is None:
            return 0.0
        return pos.shares * mark_price

    def get_unrealized_pnl(self, token_id: str, outcome: str, mark_price: float) -> float:
        """Unrealized P&L for a position."""
        key = self._pos_key(token_id, outcome)
        pos = self.positions.get(key)
        if pos is None:
            return 0.0
        current_value = pos.shares * mark_price
        return current_value - pos.cost_basis

    def get_total_equity(self, marks: dict[str, float]) -> float:
        """Total portfolio value = cash + sum of position values at given marks.

        marks: {token_id:outcome -> mark_price}
        """
        positions_value = 0.0
        for key, pos in self.positions.items():
            mark = marks.get(key, pos.avg_entry_price)  # default to cost
            positions_value += pos.shares * mark
        return self.cash + positions_value

    def get_realized_pnl(self) -> float:
        """Sum of realized P&L from all SELL and SETTLE trades."""
        pnl = 0.0
        for t in self.trades:
            if t.action in ("SELL", "SETTLE"):
                # For SELL: cost is negative (cash inflow), pnl = revenue - cost_basis
                # We track this via the trade record; for simplicity, sum the
                # difference between what we paid and what we got
                pass
        # Simpler: equity - starting_cash
        # But this includes unrealized. Let's compute from trades only.
        # Realized = total cash inflows from sells/settles - total cash outflows from buys
        total_buys = sum(t.cost for t in self.trades if t.action == "BUY")
        total_sells = sum(-t.cost for t in self.trades if t.action in ("SELL", "SETTLE"))
        return total_sells - total_buys

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def open_position_count(self) -> int:
        return len(self.positions)
