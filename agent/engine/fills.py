"""Fill engine — honest fills, zero fabricated liquidity.

Two modes:
  - strict:  Walk the live orderbook level by level. Never fill at mid.
             Used for adversarial tests to prove the engine isn't cheating.
  - realistic: Use CLOB /price endpoint for executable fills on thin books.
               Used for strategy backtesting. Still conservative — assumes
               crossing the spread on every trade.
"""

from dataclasses import dataclass
from typing import Optional

from agent.polymarket.client import PolymarketClient
from agent.polymarket.models import BookLevel, Market, OrderBook


@dataclass
class FillResult:
    """Outcome of a fill attempt."""
    filled: bool
    token_id: str
    side: str  # "buy" or "sell"
    filled_size: float  # shares actually filled
    requested_size: float  # shares requested
    avg_price: float  # volume-weighted average fill price
    total_cost: float  # avg_price * filled_size (positive = cash out)
    fee: float = 0.0
    slippage_bps: float = 0.0  # basis points slippage vs midpoint
    reason: str = ""  # "filled", "partial — insufficient depth", "rejected — no book"

    @property
    def effective_price(self) -> float:
        """Price including fees."""
        if self.filled_size == 0:
            return 0.0
        return (self.total_cost + self.fee) / self.filled_size

    @property
    def fee_pct(self) -> float:
        """Fee as percentage of total cost."""
        return (self.fee / self.total_cost * 100) if self.total_cost > 0 else 0.0


def calculate_fee(fee_rate_bps: int, price: float, cost: float) -> float:
    """Exact Polymarket fee formula.

    From polymarket-paper-trader (agent-next):
        fee = (bps / 10000) * min(price, 1 - price) * size

    The fee is proportional to how close the price is to 0.50 (max uncertainty).
    At extreme prices (near 0 or 1) the fee approaches zero.
    Minimum fee of 0.0001 when fee_rate_bps > 0.
    """
    if fee_rate_bps == 0:
        return 0.0
    fee = (fee_rate_bps / 10_000) * min(price, 1.0 - price) * cost
    if fee > 0.0:
        fee = max(fee, 0.0001)
    return fee


class FillEngine:
    """Deterministic fill simulation — strict book-walking only.

    Walks the live orderbook level by level, consuming size at each price.
    Never fills at mid. Never synthesizes liquidity. Never assumes a
    \"better price would be available\" — if the book is thin, the fill
    is honest about it.

    This is the ONLY fill path. There is no \"realistic\" mode —
    fabricating fills that the book doesn't support is how simulators lie.
    """

    def __init__(self, client: PolymarketClient, fee_rate: float = 0.0):
        self.client = client
        self.fee_rate = fee_rate  # e.g. 0.005 = 0.5%

    # ── Public API ───────────────────────────────────────────

    async def market_buy(
        self, token_id: str, size: float, book: Optional[OrderBook] = None
    ) -> FillResult:
        """Buy shares at market — walk the ask side of the book."""
        return await self._market_order(token_id, size, "buy", book)

    async def market_sell(
        self, token_id: str, size: float, book: Optional[OrderBook] = None
    ) -> FillResult:
        """Sell shares at market — walk the bid side of the book."""
        return await self._market_order(token_id, size, "sell", book)

    async def get_best_bid(self, token_id: str, book: Optional[OrderBook] = None) -> float:
        """Get the best executable bid price (what you can sell at)."""
        if book is None:
            book = await self.client.get_book(token_id)

        if book.bids:
            return book.bids[0].price

        if book.last_trade_price is not None:
            return book.last_trade_price

        return 0.0

    async def get_best_ask(self, token_id: str, book: Optional[OrderBook] = None) -> float:
        """Get the best executable ask price (what you can buy at)."""
        if book is None:
            book = await self.client.get_book(token_id)

        if book.asks:
            return book.asks[0].price

        if book.last_trade_price is not None:
            return book.last_trade_price

        return 1.0

    async def get_mark_price(self, token_id: str) -> float:
        """Get the mark price for valuing a position.

        Uses CLOB /midpoint which returns a proper probability estimate
        even when the orderbook is thin.
        """
        return await self.client.get_midpoint(token_id)

    # ── Internal ─────────────────────────────────────────────

    async def _market_order(
        self, token_id: str, size: float, side: str, book: Optional[OrderBook] = None
    ) -> FillResult:
        """Core market order logic — shared by buy and sell."""
        if size <= 0:
            return FillResult(
                filled=False, token_id=token_id, side=side,
                filled_size=0, requested_size=size, avg_price=0.0, total_cost=0.0,
                reason="rejected — size must be positive",
            )

        # Fetch book if not provided
        if book is None:
            try:
                book = await self.client.get_book(token_id)
            except Exception as e:
                return FillResult(
                    filled=False, token_id=token_id, side=side,
                    filled_size=0, requested_size=size, avg_price=0.0, total_cost=0.0,
                    reason=f"rejected — book fetch failed: {e}",
                )

        # Get the side we're crossing
        levels: list[BookLevel] = book.asks if side == "buy" else book.bids

        if not levels:
            return FillResult(
                filled=False, token_id=token_id, side=side,
                filled_size=0, requested_size=size, avg_price=0.0, total_cost=0.0,
                reason="rejected — no book levels on this side",
            )

        # Walk the book
        remaining = size
        total_cost = 0.0
        filled_size = 0.0

        for level in levels:
            if remaining <= 0:
                break
            taken = min(remaining, level.size)
            total_cost += taken * level.price
            filled_size += taken
            remaining -= taken

        if filled_size == 0:
            return FillResult(
                filled=False, token_id=token_id, side=side,
                filled_size=0, requested_size=size, avg_price=0.0, total_cost=0.0,
                reason="rejected — book has zero depth",
            )

        avg_price = total_cost / filled_size if filled_size > 0 else 0.0
        fee = calculate_fee(int(self.fee_rate * 10000), avg_price, total_cost)

        # Slippage vs midpoint
        slippage_bps = 0.0
        if book.bids and book.asks:
            mid = (book.bids[0].price + book.asks[0].price) / 2
            if mid > 0:
                if side == "buy":
                    slippage_bps = (avg_price - mid) / mid * 10_000
                else:
                    slippage_bps = (mid - avg_price) / mid * 10_000

        reason = "filled" if remaining <= 0 else f"partial — {filled_size:.1f}/{size:.1f} filled, insufficient depth"

        return FillResult(
            filled=True,
            token_id=token_id,
            side=side,
            filled_size=filled_size,
            requested_size=size,
            avg_price=avg_price,
            total_cost=total_cost,
            fee=fee,
            slippage_bps=slippage_bps,
            reason=reason,
        )
