"""Settlement engine — polls market resolution and settles positions to $1/$0.

Polymarket markets resolve via UMA's Optimistic Oracle. Once resolved,
the conditionId's outcome is available through the Gamma API.
"""

from dataclasses import dataclass
from typing import Optional

from agent.polymarket.client import PolymarketClient


@dataclass
class SettlementResult:
    """Outcome of a settlement check."""
    condition_id: str
    resolved: bool
    outcome: Optional[str] = None  # "Yes" or "No"
    yes_value: float = 0.0  # $1 if resolved Yes, $0 otherwise
    no_value: float = 0.0


class SettlementEngine:
    """Checks market resolution and settles positions."""

    def __init__(self, client: PolymarketClient):
        self.client = client

    async def check_resolution(self, condition_id: str) -> SettlementResult:
        """Check if a market has resolved.

        Uses the Gamma API market data. A resolved market has closed=True
        and the outcomePrices reflect the final state: ["1.0", "0.0"] for Yes,
        or ["0.0", "1.0"] for No.

        Note: This is a polling approach. In production you'd want a more
        robust method (e.g., checking UMA's oracle directly).
        """
        try:
            # Gamma /markets endpoint with conditionId filter would be ideal,
            # but we can use the slug-based lookup or the prices-history endpoint.
            # The simplest signal: /prices-history returns data that jumps to
            # 0 or 1 at resolution time.

            # For now, use the Gamma API. We need the market's slug.
            # Let's use a broader approach: fetch the market by searching
            # for its conditionId via the CLOB /markets endpoint.
            markets = await self.client._get(
                f"https://clob.polymarket.com/markets?limit=500"
            )

            # Find our market
            market_data = None
            for m in markets.get("data", []):
                if m.get("condition_id") == condition_id:
                    market_data = m
                    break

            if market_data is None:
                return SettlementResult(
                    condition_id=condition_id, resolved=False
                )

            # Check if closed
            closed = market_data.get("closed", False)
            if not closed:
                return SettlementResult(
                    condition_id=condition_id, resolved=False
                )

            # Resolved — determine outcome from token prices
            tokens = market_data.get("tokens", [])
            yes_value = 0.0
            no_value = 0.0

            for token in tokens:
                price = float(token.get("price", 0))
                outcome = token.get("outcome", "")
                if outcome == "Yes":
                    yes_value = price
                elif outcome == "No":
                    no_value = price

            # A resolved market has one token at ~$1 and the other at ~$0
            resolved_outcome = "Yes" if yes_value > 0.5 else "No"

            return SettlementResult(
                condition_id=condition_id,
                resolved=True,
                outcome=resolved_outcome,
                yes_value=yes_value,
                no_value=no_value,
            )

        except Exception:
            # Market not found or API error — assume not resolved
            return SettlementResult(
                condition_id=condition_id, resolved=False
            )

    async def find_resolved_markets(self, condition_ids: list[str]) -> dict[str, SettlementResult]:
        """Check multiple markets for resolution.

        Returns: {condition_id: SettlementResult}
        """
        results = {}
        for cid in condition_ids:
            results[cid] = await self.check_resolution(cid)
        return results

    @staticmethod
    def settle_position_value(outcome: str, resolved_outcome: str) -> float:
        """Convert a resolution outcome to a dollar value for a position.

        If you hold YES and the market resolved Yes → $1.
        If you hold YES and the market resolved No → $0.
        If you hold NO and the market resolved Yes → $0.
        If you hold NO and the market resolved No → $1.
        """
        if outcome == resolved_outcome:
            return 1.0
        return 0.0
