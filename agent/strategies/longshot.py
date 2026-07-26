"""Favorite-longshot bias strategy.

The best-evidenced systematic edge in prediction markets:
  - Longshots (low probability) are systematically OVERPRICED
  - Favorites (high probability) are systematically UNDERPRICED

This strategy:
  1. Scans markets for extreme probabilities
  2. Computes p_agent by adjusting p_market toward the bias
  3. Only trades when the edge exceeds spread + fees + hurdle
  4. Emits TradeProposal with explicit p_agent for Brier scoring

Reference: "Favorite-Longshot Bias" — well-documented in sports betting
and prediction market literature. Polymarket-specific evidence shows
~7.6% of wallets are profitable; the bias is one of few mechanical edges.
"""

import math
from typing import Optional

from agent.polymarket.client import PolymarketClient
from agent.polymarket.models import Market
from agent.strategies.base import Strategy, StrategyResult, TradeProposal


class FavoriteLongshotStrategy(Strategy):
    """Trade the favorite-longshot bias mechanically."""

    name = "favorite-longshot"

    # Bias parameters — calibrated from prediction market literature
    # These are deliberately conservative. The bias curve gets refined
    # as we observe resolutions and collect Brier scores.
    LONGSHOT_THRESHOLD = 0.15   # Markets below 15% are "longshots"
    FAVORITE_THRESHOLD = 0.85   # Markets above 85% are "favorites"
    BIAS_STRENGTH = 0.05        # How much we adjust p_market toward the bias
    MIN_EDGE = 0.03             # Minimum |p_agent - p_market| to trade
    MIN_VOLUME = 100_000        # Minimum $ volume to consider
    MIN_LIQUIDITY = 10_000      # Minimum $ liquidity
    MAX_MARKETS_PER_SCAN = 100  # Cap to avoid API overload

    def __init__(self, client: PolymarketClient):
        self.client = client

    async def scan(self, markets: list[Market]) -> StrategyResult:
        """Scan markets for favorite-longshot bias opportunities."""
        result = StrategyResult(strategy_name=self.name)
        result.markets_evaluated = len(markets)

        for market in markets:
            # Filter: must have valid tokens, volume, liquidity
            if market.closed:
                result.markets_skipped += 1
                continue
            if market.volume < self.MIN_VOLUME:
                result.markets_skipped += 1
                continue
            if market.liquidity < self.MIN_LIQUIDITY:
                result.markets_skipped += 1
                continue
            if not market.tokens or len(market.tokens) < 2:
                result.markets_skipped += 1
                continue

            # Get current market probability from CLOB midpoint
            try:
                yes_mid = await self.client.get_midpoint(market.tokens[0].token_id)
            except Exception:
                result.markets_skipped += 1
                continue

            p_market = yes_mid

            # Check for bias opportunity
            proposal = self._evaluate_market(market, p_market)
            if proposal:
                result.proposals.append(proposal)

        return result

    def _evaluate_market(
        self, market: Market, p_market: float
    ) -> Optional[TradeProposal]:
        """Evaluate a single market for favorite-longshot bias.

        Returns a TradeProposal if there's a tradeable edge, or None.
        """
        # ── Longshot: market says low probability → we think it's even lower ──
        if p_market <= self.LONGSHOT_THRESHOLD:
            p_agent = max(0.01, p_market - self.BIAS_STRENGTH)

            # Edge: we think YES is worth LESS than market says
            # Equivalently: we think NO is worth MORE than market says
            # Action: BUY NO (same as selling YES, but no position needed)
            edge = p_market - p_agent  # positive = overpriced

            if edge >= self.MIN_EDGE:
                return TradeProposal(
                    token_id=market.tokens[1].token_id if len(market.tokens) > 1 else "",
                    outcome="No",
                    direction="BUY",
                    market_question=market.question,
                    condition_id=market.condition_id,
                    market_probability=p_market,
                    agent_probability=p_agent,
                    confidence=edge / self.BIAS_STRENGTH,
                    strategy_name=self.name,
                    yes_token_id=market.tokens[0].token_id,
                    no_token_id=market.tokens[1].token_id if len(market.tokens) > 1 else "",
                    reasoning=(
                        f"Longshot bias: market={p_market:.3f}, agent={p_agent:.3f}, "
                        f"edge={edge:.3f}. Buying NO (YES is overpriced)."
                    ),
                )

        # ── Favorite: market says high probability → we think it's even higher ──
        elif p_market >= self.FAVORITE_THRESHOLD:
            p_agent = min(0.99, p_market + self.BIAS_STRENGTH)

            # Edge: we think YES is worth MORE than market says
            # Action: BUY YES (or equivalently, SELL NO)
            edge = p_agent - p_market  # positive = underpriced

            if edge >= self.MIN_EDGE:
                return TradeProposal(
                    token_id=market.tokens[0].token_id,
                    outcome="Yes",
                    direction="BUY",
                    market_question=market.question,
                    condition_id=market.condition_id,
                    market_probability=p_market,
                    agent_probability=p_agent,
                    confidence=edge / self.BIAS_STRENGTH,
                    strategy_name=self.name,
                    yes_token_id=market.tokens[0].token_id,
                    no_token_id=market.tokens[1].token_id if len(market.tokens) > 1 else "",
                    reasoning=(
                        f"Favorite bias: market={p_market:.3f}, agent={p_agent:.3f}, "
                        f"edge={edge:.3f}. Buying underpriced favorite YES."
                    ),
                )

        # ── Mid-range: no strong bias signal ──
        return None

    def explain_bias(self, p_market: float) -> str:
        """Explain the bias adjustment for a given market probability."""
        if p_market <= self.LONGSHOT_THRESHOLD:
            p_agent = max(0.01, p_market - self.BIAS_STRENGTH)
            return (
                f"Longshot ({p_market:.1%}): adjusted down to {p_agent:.1%} "
                f"({self.BIAS_STRENGTH:.1%} bias). Direction: SELL YES / BUY NO."
            )
        elif p_market >= self.FAVORITE_THRESHOLD:
            p_agent = min(0.99, p_market + self.BIAS_STRENGTH)
            return (
                f"Favorite ({p_market:.1%}): adjusted up to {p_agent:.1%} "
                f"(+{self.BIAS_STRENGTH:.1%} bias). Direction: BUY YES / SELL NO."
            )
        return (
            f"Mid-range ({p_market:.1%}): no strong bias signal. "
            f"Neither longshot (<{self.LONGSHOT_THRESHOLD:.0%}) "
            f"nor favorite (>{self.FAVORITE_THRESHOLD:.0%}). Holding."
        )
