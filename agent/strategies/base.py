"""Strategy protocol — every strategy implements this interface.

Each strategy proposes trades; the risk manager validates, sizes, and
the fill engine executes. The LLM proposes; the deterministic engine
validates. Guardrails are enforced in code.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradeProposal:
    """A proposed trade from a strategy — NOT yet executed.

    The risk manager may reject, resize, or approve this proposal.
    """
    token_id: str
    outcome: str  # "Yes" or "No"
    direction: str  # "BUY" or "SELL"
    market_question: str
    condition_id: str
    market_probability: float  # p_market — current market-implied probability
    agent_probability: float   # p_agent — strategy's probability estimate
    confidence: float  # 0.0–1.0, how confident the strategy is in this edge
    strategy_name: str
    reasoning: str = ""
    # Both outcome token IDs — needed when converting SELL YES → BUY NO
    yes_token_id: str = ""
    no_token_id: str = ""

    @property
    def edge(self) -> float:
        """Absolute edge: |p_agent - p_market|"""
        return abs(self.agent_probability - self.market_probability)

    @property
    def edge_direction(self) -> float:
        """Signed edge: p_agent - p_market. Positive = undervalued (should buy)."""
        return self.agent_probability - self.market_probability

    @property
    def key(self) -> str:
        return f"{self.token_id}:{self.outcome}:{self.direction}"


@dataclass
class StrategyResult:
    """Output from a strategy scan."""
    strategy_name: str
    proposals: list[TradeProposal] = field(default_factory=list)
    markets_evaluated: int = 0
    markets_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class Strategy:
    """Abstract base for all trading strategies."""

    name: str = "base"

    async def scan(self, markets) -> StrategyResult:
        """Scan markets and generate trade proposals."""
        raise NotImplementedError
