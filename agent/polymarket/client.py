"""Polymarket HTTP client — Gamma + CLOB APIs, rate-limited, retries with backoff."""

import json
import time
from typing import Any, Optional

import httpx

from agent.polymarket.models import BookLevel, Event, Market, OrderBook, PricePoint, Token

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = "hermes-pm-agent/1.0"


class PolymarketClient:
    """Read-only client for Polymarket Gamma and CLOB APIs."""

    def __init__(self, rate_limit_pause: float = 0.15, max_retries: int = 3):
        self.rate_limit_pause = rate_limit_pause
        self.max_retries = max_retries
        self._last_request = 0.0

    # ── Internal ──────────────────────────────────────────────

    async def _get(self, url: str) -> Any:
        """GET with rate limiting + retry + backoff."""
        # Rate limiting
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.rate_limit_pause:
            await _asleep(self.rate_limit_pause - elapsed)

        last_exc = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(url, headers={"User-Agent": UA})
                    resp.raise_for_status()
                    self._last_request = time.monotonic()
                    return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_exc = e
                if attempt < self.max_retries - 1:
                    await _asleep(1.0 * (2**attempt))  # exponential backoff

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _parse_json_field(val) -> list | str:
        """Parse double-encoded JSON fields from Gamma API."""
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        return val

    # ── Gamma API — Discovery ────────────────────────────────

    async def search(self, query: str) -> list[Event]:
        """Search markets by keyword."""
        data = await self._get(f"{GAMMA}/public-search?q={query}")
        return [_parse_event(e) for e in data.get("events", [])]

    async def trending(self, limit: int = 30) -> list[Event]:
        """Get top events by volume."""
        events_raw = await self._get(
            f"{GAMMA}/events?limit={limit}&active=true&closed=false&order=volume&ascending=false"
        )
        return [_parse_event(e) for e in events_raw]

    async def event_by_slug(self, slug: str) -> Optional[Event]:
        """Get a single event by slug."""
        events_raw = await self._get(f"{GAMMA}/events?slug={slug}")
        if events_raw:
            return _parse_event(events_raw[0])
        return None

    async def markets_by_tag(self, tag: str, limit: int = 50) -> list[Market]:
        """Get markets filtered by tag slug."""
        markets_raw = await self._get(
            f"{GAMMA}/markets?tag={tag}&limit={limit}&active=true&closed=false"
        )
        return [_parse_market(m) for m in markets_raw]

    async def markets_page(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        order: str = "liquidityNum",
        ascending: bool = False,
        liquidity_min: Optional[float] = None,
        volume_min: Optional[float] = None,
    ) -> list[Market]:
        """One page of the market universe.

        `trending()` returns top events by VOLUME — the most watched, most
        arbitraged markets on the platform, i.e. where edge is least likely to
        exist. Scanning only those is why the agent kept finding either no edge
        or untradeable books. This exposes the whole universe so the viable band
        between "efficient" and "untradeable" can actually be measured.
        """
        url = (
            f"{GAMMA}/markets?limit={limit}&offset={offset}"
            f"&active={str(active).lower()}&closed={str(closed).lower()}"
            f"&order={order}&ascending={str(ascending).lower()}"
        )
        if liquidity_min is not None:
            url += f"&liquidity_num_min={liquidity_min}"
        if volume_min is not None:
            url += f"&volume_num_min={volume_min}"
        raw = await self._get(url)
        if not isinstance(raw, list):
            return []
        return [_parse_market(m) for m in raw]

    async def scan_universe(
        self,
        max_markets: int = 500,
        page_size: int = 100,
        liquidity_min: Optional[float] = None,
    ) -> list[Market]:
        """Walk the full market universe, ordered by liquidity descending."""
        out: list[Market] = []
        offset = 0
        while len(out) < max_markets:
            page = await self.markets_page(
                limit=min(page_size, max_markets - len(out)),
                offset=offset,
                liquidity_min=liquidity_min,
            )
            if not page:
                break
            out.extend(page)
            offset += len(page)
        return out[:max_markets]

    # ── CLOB API — Prices & Orderbooks ───────────────────────

    async def get_book(self, token_id: str) -> OrderBook:
        """Get the full orderbook for a single outcome token."""
        data = await self._get(f"{CLOB}/book?token_id={token_id}")
        return OrderBook(
            token_id=token_id,
            bids=_parse_book_levels(data.get("bids", [])),
            asks=_parse_book_levels(data.get("asks", [])),
            last_trade_price=(
                float(data["last_trade_price"])
                if data.get("last_trade_price")
                else None
            ),
            tick_size=float(data.get("tick_size", 0.01)),
            min_order_size=float(data.get("min_order_size", 5.0)),
        )

    async def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price for a token."""
        data = await self._get(f"{CLOB}/midpoint?token_id={token_id}")
        return float(data["mid"])

    async def get_spread(self, token_id: str) -> float:
        """Get bid-ask spread for a token."""
        data = await self._get(f"{CLOB}/spread?token_id={token_id}")
        return float(data["spread"])

    async def get_price_history(
        self, condition_id: str, interval: str = "all", fidelity: int = 100
    ) -> list[PricePoint]:
        """Get historical price data for a market."""
        data = await self._get(
            f"{CLOB}/prices-history?market={condition_id}&interval={interval}&fidelity={fidelity}"
        )
        return [
            PricePoint(timestamp=pt["t"], price=float(pt["p"]))
            for pt in data.get("history", [])
        ]

    # ── Convenience ──────────────────────────────────────────

    async def fetch_market_books(self, market: Market) -> Market:
        """Populate a market's yes_book and no_book from live data."""
        if market.tokens:
            market.yes_book = await self.get_book(market.tokens[0].token_id)
            market.no_book = await self.get_book(market.tokens[1].token_id)
        return market

    async def fetch_all_market_books(self, markets: list[Market]) -> list[Market]:
        """Fetch orderbooks for all markets in parallel (fire-and-forget)."""
        import asyncio

        tasks = [self.fetch_market_books(m) for m in markets]
        await asyncio.gather(*tasks, return_exceptions=True)
        return markets


# ── Parsing helpers ──────────────────────────────────────────


def _parse_event(raw: dict) -> Event:
    """Parse a raw Gamma event dict into an Event model."""
    markets = []
    for m in raw.get("markets", []):
        if not m.get("closed", False):
            markets.append(_parse_market(m))

    return Event(
        title=raw.get("title", ""),
        slug=raw.get("slug", ""),
        volume=float(raw.get("volume", 0)),
        markets=markets,
    )


def _parse_market(raw: dict) -> Market:
    """Parse a raw Gamma market dict into a Market model.

    Each market has TWO outcome tokens (YES and NO). We model them separately
    because each has its own orderbook with its own bid/ask structure.
    """
    outcomes = PolymarketClient._parse_json_field(raw.get("outcomes", []))
    clob_tokens = PolymarketClient._parse_json_field(raw.get("clobTokenIds", []))

    tokens = []
    if isinstance(outcomes, list) and isinstance(clob_tokens, list):
        for outcome, token_id in zip(outcomes, clob_tokens):
            tokens.append(Token(token_id=str(token_id), outcome=str(outcome)))

    # Ensure exactly 2 tokens
    if len(tokens) < 2:
        # Fallback: create synthetic Yes/No tokens
        tokens = [
            Token(token_id=str(clob_tokens[0]) if clob_tokens else "", outcome="Yes"),
            Token(token_id=str(clob_tokens[1]) if len(clob_tokens) > 1 else "", outcome="No"),
        ]

    return Market(
        question=raw.get("question", ""),
        slug=raw.get("slug", ""),
        condition_id=raw.get("conditionId", ""),
        tokens=tokens[:2],
        volume=float(raw.get("volume", 0)),
        liquidity=float(raw.get("liquidity", 0)),
        active=raw.get("active", True),
        closed=raw.get("closed", False),
        neg_risk=raw.get("negRisk", False),
        end_date=raw.get("endDate"),
        resolution_criteria=raw.get("description"),
    )


def _parse_book_levels(raw_levels: list[dict]) -> list[BookLevel]:
    """Parse raw orderbook levels."""
    return [
        BookLevel(price=float(lvl["price"]), size=float(lvl["size"]))
        for lvl in raw_levels
        if lvl.get("price") and lvl.get("size")
    ]


async def _asleep(seconds: float):
    """Async sleep."""
    import asyncio

    await asyncio.sleep(seconds)
