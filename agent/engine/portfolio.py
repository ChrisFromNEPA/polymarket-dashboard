"""Portfolio engine — positions, cash, P&L tracking, exit rules.

Single source of truth for the paper trading portfolio.
All mutations are explicit and auditable.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    EDGE_GONE = "edge_gone"
    MANUAL = "manual"
    SETTLEMENT = "settlement"


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
    # Strategy's fair value estimate at entry — used for edge-gone detection
    fair_estimate_at_entry: float = 0.0
    # Strategy that opened this position
    strategy_name: str = ""

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

    # ── Position exits (from guberm/polymarket-bot research) ──

    def generate_exit_signals(
        self,
        current_prices: dict[str, float],
        stop_loss_pct: float = 0.25,
        take_profit_price: float = 0.95,
        exit_edge_buffer: float = 0.05,
    ) -> list[dict]:
        """Check all positions for exit conditions.

        Returns list of exit signals: {position, reason, current_price, pnl, pnl_pct}
        Checks in priority order: stop-loss > take-profit > edge-gone.

        From guberm/polymarket-bot: "Tier 1 — free rule-based exit checks"
        """
        signals = []

        for pos in self.positions.values():
            price = current_prices.get(pos.key, pos.avg_entry_price)

            # Skip unsellable positions
            if price < 0.01:
                continue  # penny stock — unsellable
            if pos.shares < 5.0:
                continue  # below CLOB minimum

            pnl = pos.shares * (price - pos.avg_entry_price)
            pnl_pct = (price - pos.avg_entry_price) / pos.avg_entry_price if pos.avg_entry_price > 0 else 0.0

            # Stop-loss: price dropped too far from entry
            if pnl_pct < -stop_loss_pct:
                signals.append({
                    "position": pos,
                    "reason": ExitReason.STOP_LOSS,
                    "current_price": price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                })
                continue

            # Take-profit: price near certainty
            if price >= take_profit_price:
                signals.append({
                    "position": pos,
                    "reason": ExitReason.TAKE_PROFIT,
                    "current_price": price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                })
                continue

            # Edge-gone: market moved past our original fair estimate
            if pos.fair_estimate_at_entry > 0:
                # fair_for_side: what we estimated the correct price for our side was
                if pos.outcome == "Yes":
                    fair_for_side = pos.fair_estimate_at_entry
                else:
                    fair_for_side = 1.0 - pos.fair_estimate_at_entry

                if price > fair_for_side + exit_edge_buffer:
                    signals.append({
                        "position": pos,
                        "reason": ExitReason.EDGE_GONE,
                        "current_price": price,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                    })
                    continue

        return signals

    def get_review_candidates(self, current_prices: dict[str, float], threshold_pct: float = 0.10) -> list:
        """Positions that moved significantly and should be re-evaluated.

        From guberm/polymarket-bot: "Tier 2 — re-estimation candidates"
        """
        candidates = []
        for pos in self.positions.values():
            if pos.avg_entry_price <= 0:
                continue
            price = current_prices.get(pos.key, pos.avg_entry_price)
            price_move = abs(price - pos.avg_entry_price) / pos.avg_entry_price
            if price_move >= threshold_pct:
                candidates.append(pos)
        candidates.sort(key=lambda p: p.cost_basis, reverse=True)
        return candidates

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
