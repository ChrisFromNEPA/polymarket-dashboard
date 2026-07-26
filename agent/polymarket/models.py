"""Polymarket data models — typed, validated, no ambiguity."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Token:
    """One outcome token (YES or NO) for a market."""
    token_id: str
    outcome: str  # "Yes" or "No"


@dataclass
class BookLevel:
    """A single level in the orderbook."""
    price: float
    size: float


@dataclass
class OrderBook:
    """Full orderbook for a single outcome token.

    **Invariant: levels are always BEST-FIRST.**
        bids — descending (highest/best bid at index 0)
        asks — ascending  (lowest/best ask at index 0)

    Enforced in __post_init__ rather than trusted to callers, because
    Polymarket's API returns the opposite order (bids ascending, asks
    descending) and reading index 0 as "best" silently picks the WORST price on
    both sides. That one mistake caused the $0.999 fills, the phantom "99.8%
    spreads", the 0.5 midpoints, and the Phase E "taker is dead" verdict.
    Anything that walks these lists depends on this ordering.
    """
    token_id: str
    bids: list[BookLevel] = field(default_factory=list)
    asks: list[BookLevel] = field(default_factory=list)
    last_trade_price: Optional[float] = None
    tick_size: float = 0.01
    min_order_size: float = 5.0

    def __post_init__(self):
        self.bids = sorted(self.bids, key=lambda l: l.price, reverse=True)
        self.asks = sorted(self.asks, key=lambda l: l.price)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        bb = self.best_bid
        ba = self.best_ask
        if bb is not None and ba is not None:
            return (bb + ba) / 2
        return self.last_trade_price

    @property
    def spread(self) -> Optional[float]:
        bb = self.best_bid
        ba = self.best_ask
        if bb is not None and ba is not None and bb > 0:
            return ba - bb
        return None


@dataclass
class Market:
    """A single binary market on Polymarket."""
    question: str
    slug: str
    condition_id: str
    tokens: list[Token]  # [YES, NO]
    volume: float = 0.0
    liquidity: float = 0.0
    active: bool = True
    closed: bool = False
    neg_risk: bool = False
    end_date: Optional[str] = None
    # Resolution criteria text from the market description
    resolution_criteria: Optional[str] = None
    # Live orderbooks, populated on demand
    yes_book: Optional[OrderBook] = None
    no_book: Optional[OrderBook] = None

    @property
    def yes_token_id(self) -> str:
        return self.tokens[0].token_id

    @property
    def no_token_id(self) -> str:
        return self.tokens[1].token_id

    @property
    def yes_mid(self) -> Optional[float]:
        return self.yes_book.mid if self.yes_book else None

    @property
    def no_mid(self) -> Optional[float]:
        return self.no_book.mid if self.no_book else None


@dataclass
class Event:
    """A grouping of related markets."""
    title: str
    slug: str
    volume: float = 0.0
    markets: list[Market] = field(default_factory=list)


@dataclass
class PricePoint:
    """A single historical price data point."""
    timestamp: int  # Unix seconds
    price: float
