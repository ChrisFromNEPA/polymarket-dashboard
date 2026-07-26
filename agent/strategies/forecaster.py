"""LLM Forecaster — structured probability estimation.

Based on the superforecaster methodology from the literature
(PLAN v2 §1): base rate → evidence → probability → confidence.

The forecaster produces p_agent estimates with explicit reasoning.
Post-hoc calibration adjusts raw probabilities using historical
reliability curves.

For backtesting, a mechanical baseline is used (no actual LLM calls).
For live trading, the forecaster is called via the MCP server.
"""

from dataclasses import dataclass, field
from typing import Optional

from agent.strategies.base import Strategy, StrategyResult, TradeProposal


@dataclass
class ForecastResult:
    """A single probability estimate with calibration metadata."""
    question: str
    resolution_criteria: str = ""
    base_rate: float = 0.50  # uninformed prior
    p_raw: float = 0.50      # raw LLM estimate
    p_calibrated: float = 0.50  # after calibration
    confidence: float = 0.5  # 0-1, how confident the LLM is
    reasoning: str = ""
    market_price: float = 0.50
    long_horizon: bool = True  # LLMs beat markets at long horizons


@dataclass
class Calibration:
    """Post-hoc probability calibration using Platt scaling / isotonic regression.

    Maps raw probabilities to calibrated probabilities based on
    historical resolution data. Initially uses identity mapping;
    updates as markets resolve.
    """
    intercept: float = 0.0
    slope: float = 1.0
    min_samples: int = 20

    def calibrate(self, p_raw: float) -> float:
        """Apply calibration: p_cal = clamp(slope * p_raw + intercept, 0.01, 0.99)."""
        calibrated = self.slope * p_raw + self.intercept
        return max(0.01, min(0.99, calibrated))

    def fit(self, p_raws: list[float], outcomes: list[int]):
        """Fit calibration from (p_raw, outcome) pairs using simple linear regression."""
        if len(p_raws) < self.min_samples:
            return  # not enough data

        n = len(p_raws)
        mean_p = sum(p_raws) / n
        mean_o = sum(outcomes) / n

        # Slope = Cov(p, o) / Var(p)
        cov = sum((p_raws[i] - mean_p) * (outcomes[i] - mean_o) for i in range(n))
        var = sum((p - mean_p) ** 2 for p in p_raws)
        if var > 0:
            self.slope = cov / var
        self.intercept = mean_o - self.slope * mean_p


class ForecasterStrategy(Strategy):
    """LLM-based forecasting strategy.

    For live trading: calls the LLM (Hermes) to estimate probabilities.
    For backtesting: uses a calibrated baseline.

    The strategy produces TradeProposals with p_agent estimates
    that are independent of p_market (unlike the mechanical
    favorite-longshot, which was a deterministic transform).
    """

    name = "llm-forecaster"

    # Thresholds
    MIN_EDGE = 0.05      # minimum |p_agent - p_market| to consider trading
    MIN_VOLUME = 100_000
    MIN_LIQUIDITY = 10_000
    LONG_HORIZON_DAYS = 30  # markets resolving in >30 days = long horizon
    MIN_CONFIDENCE = 0.3  # don't trade low-confidence estimates

    def __init__(self, calibration: Calibration = None):
        self.calibration = calibration or Calibration()

    async def scan(self, markets, forecaster_fn=None) -> StrategyResult:
        """Scan markets and generate LLM-based trade proposals.

        forecaster_fn: async fn(market) -> ForecastResult.
        If None, uses mechanical baseline (base rate only).
        """
        result = StrategyResult(strategy_name=self.name)

        for market in markets:
            if market.closed or market.volume < self.MIN_VOLUME:
                result.markets_skipped += 1
                continue

            # Generate forecast
            if forecaster_fn:
                try:
                    forecast = await forecaster_fn(market)
                except Exception:
                    result.markets_skipped += 1
                    continue
            else:
                # Mechanical baseline: use market price as base rate
                forecast = self._mechanical_forecast(market)

            result.markets_evaluated += 1

            # Apply calibration
            forecast.p_calibrated = self.calibration.calibrate(forecast.p_raw)

            # Check if we should trade
            proposal = self._to_proposal(market, forecast)
            if proposal:
                result.proposals.append(proposal)

        return result

    def _mechanical_forecast(self, market) -> ForecastResult:
        """Baseline forecast without LLM — uses market price as prior.

        This exists so the backtest harness can evaluate the forecaster
        structure without expensive LLM calls. The real forecast comes
        from an actual LLM call via MCP.
        """
        # Without an LLM, our best estimate is the market price
        # The edge comes from calibration, not from deviation
        return ForecastResult(
            question=market.question,
            resolution_criteria=market.resolution_criteria or "",
            base_rate=0.50,
            p_raw=0.50,  # uninformed prior
            p_calibrated=0.50,
            confidence=0.3,
            reasoning="Mechanical baseline — no LLM estimate available.",
            market_price=0.50,
            long_horizon=True,
        )

    def _to_proposal(
        self, market, forecast: ForecastResult
    ) -> Optional[TradeProposal]:
        """Convert a forecast into a trade proposal if there's sufficient edge."""
        p_agent = forecast.p_calibrated
        p_market = forecast.market_price

        if p_market <= 0 or p_market >= 1:
            return None

        edge = p_agent - p_market
        abs_edge = abs(edge)

        if abs_edge < self.MIN_EDGE:
            return None

        if forecast.confidence < self.MIN_CONFIDENCE:
            return None

        if abs_edge < self.MIN_EDGE:
            return None

        # Determine direction
        if edge > 0:
            direction = "BUY"
            outcome = "Yes"
        else:
            direction = "BUY"
            outcome = "No"

        return TradeProposal(
            token_id=market.tokens[0].token_id if outcome == "Yes"
                     else (market.tokens[1].token_id if len(market.tokens) > 1 else ""),
            outcome=outcome,
            direction=direction,
            market_question=market.question,
            condition_id=market.condition_id,
            market_probability=p_market,
            agent_probability=p_agent,
            confidence=forecast.confidence,
            strategy_name=self.name,
            yes_token_id=market.tokens[0].token_id if market.tokens else "",
            no_token_id=market.tokens[1].token_id if len(market.tokens) > 1 else "",
            reasoning=forecast.reasoning,
        )

    def fit_calibration(self, p_raws: list[float], outcomes: list[int]):
        """Update calibration from observed resolutions."""
        self.calibration.fit(p_raws, outcomes)
