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
from datetime import datetime, timezone
from typing import Optional

from agent.strategies.base import Strategy, StrategyResult, TradeProposal


@dataclass
class ForecastResult:
    """A single probability estimate with calibration metadata.

    `market_price` is deliberately NOT defaulted to a plausible-looking 0.50.
    It previously was, and because `_to_proposal` reads p_market from here, every
    proposal reported p_market=0.50 regardless of the real price — which would
    have fed 0.50 into Kelly sizing and the fair-value check. A None that raises
    is far safer than a number that silently lies.
    """
    question: str
    resolution_criteria: str = ""
    base_rate: float = 0.50  # uninformed prior
    p_raw: float = 0.50      # raw LLM estimate, BEFORE seeing p_market
    p_calibrated: float = 0.50  # after calibration
    confidence: float = 0.5  # 0-1, self-reported by the LLM — NOT a probability
    reasoning: str = ""
    market_price: Optional[float] = None  # must be supplied by the caller
    long_horizon: bool = True  # LLMs beat markets at long horizons
    # RESEARCH §2.3: a forecast that cannot cite its evidence is hallucinating.
    citations: list[str] = field(default_factory=list)
    skip: bool = False  # first-class "no opinion" — see RESEARCH §2.3


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
        """Fit calibration from (p_raw, outcome) pairs by least squares.

        ⚠️ This is a **linear probability model**, not Platt scaling. Platt fits a
        logistic on the log-odds; this fits a straight line on raw probabilities.
        It cannot express the extremization RESEARCH §2 says LLM forecasts need
        (they hedge toward the middle, and correcting that requires a log-odds
        transform). Adequate as a first pass; do not describe it as Platt scaling.
        """
        if len(p_raws) != len(outcomes):
            raise ValueError("p_raws and outcomes must be the same length")
        if len(p_raws) < self.min_samples:
            return  # not enough data

        n = len(p_raws)
        mean_p = sum(p_raws) / n
        mean_o = sum(outcomes) / n

        # Slope = Cov(p, o) / Var(p)
        cov = sum((p_raws[i] - mean_p) * (outcomes[i] - mean_o) for i in range(n))
        var = sum((p - mean_p) ** 2 for p in p_raws)

        if var <= 0:
            # All forecasts identical — there is no relationship to fit. Bail
            # entirely. Previously the slope was left stale while the intercept
            # was still updated, which silently turned calibration into a
            # constant shift toward the base rate.
            return

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
    MIN_VOLUME = 50_000
    MIN_LIQUIDITY = 10_000
    MIN_CONFIDENCE = 0.3  # don't trade low-confidence estimates

    # ── Market selection (docs/RESEARCH.md §1) ──────────────
    # The single biggest lever in the project. The agent previously traded 2028
    # nomination longshots: >800-day horizon, prices of 0.002-0.13, inside a
    # 128-outcome NegRisk event — four of five criteria violated. At $0.002 the
    # tick size is half the price; there is no room to be right in.
    MIN_HORIZON_DAYS = 7
    MAX_HORIZON_DAYS = 60
    MIN_PRICE = 0.10
    MAX_PRICE = 0.90
    EXCLUDE_NEG_RISK = True

    def __init__(self, client=None, calibration: Calibration = None):
        self.client = client
        self.calibration = calibration or Calibration()

    # ── Selection ───────────────────────────────────────────

    def market_is_eligible(self, market, p_market: Optional[float]) -> tuple[bool, str]:
        """Does this market fit the profile we can plausibly be right about?

        Returns (eligible, reason). The reason is recorded on rejection so the
        decision feed shows what was filtered and why.
        """
        if getattr(market, "closed", False):
            return False, "market closed"
        if (market.volume or 0) < self.MIN_VOLUME:
            return False, f"volume ${market.volume:,.0f} < ${self.MIN_VOLUME:,.0f}"
        if self.EXCLUDE_NEG_RISK and getattr(market, "neg_risk", False):
            return False, "NegRisk multi-outcome event (correlated, one bet not many)"

        if p_market is None:
            return False, "no market price available"
        if not (self.MIN_PRICE <= p_market <= self.MAX_PRICE):
            return False, (
                f"price {p_market:.3f} outside {self.MIN_PRICE:.2f}-{self.MAX_PRICE:.2f} "
                f"— extreme prices leave no room to be right in"
            )

        days = _days_until(getattr(market, "end_date", None))
        if days is None:
            return False, "no end_date — horizon unknown"
        if days < self.MIN_HORIZON_DAYS:
            return False, f"resolves in {days:.1f}d (< {self.MIN_HORIZON_DAYS}d) — markets aggregate news faster than we do"
        if days > self.MAX_HORIZON_DAYS:
            return False, f"resolves in {days:.0f}d (> {self.MAX_HORIZON_DAYS}d) — information decays over long horizons"

        return True, "eligible"

    async def scan(self, markets, forecaster_fn=None) -> StrategyResult:
        """Scan markets and generate LLM-based trade proposals.

        forecaster_fn: async fn(market) -> ForecastResult.
        If None, uses mechanical baseline (base rate only).
        """
        result = StrategyResult(strategy_name=self.name)

        for market in markets:
            p_market = await self._market_price(market)

            eligible, reason = self.market_is_eligible(market, p_market)
            if not eligible:
                result.markets_skipped += 1
                result.errors.append(f"skip [{market.question[:60]}]: {reason}")
                continue

            # Generate forecast. The forecaster is given the market so it can
            # read the question and resolution criteria — it must NOT be given
            # p_market before producing p_raw (PLAN §5.3). That discipline lives
            # in the forecaster_fn implementation; we attach the price afterwards.
            if forecaster_fn:
                try:
                    forecast = await forecaster_fn(market)
                except Exception as e:
                    result.markets_skipped += 1
                    result.errors.append(f"forecast failed [{market.question[:40]}]: {e}")
                    continue
            else:
                forecast = self._mechanical_forecast(market)

            result.markets_evaluated += 1

            # RESEARCH §2.3: an uncitable forecast is a hallucinating one.
            if forecaster_fn and not forecast.citations:
                result.errors.append(
                    f"discard [{market.question[:40]}]: no citations — treated as hallucination"
                )
                continue
            if forecast.skip:
                result.errors.append(f"skip [{market.question[:40]}]: forecaster declined")
                continue

            # Attach the real price. Never let the ForecastResult default stand in.
            forecast.market_price = p_market

            forecast.p_calibrated = self.calibration.calibrate(forecast.p_raw)

            proposal = self._to_proposal(market, forecast)
            if proposal:
                result.proposals.append(proposal)

        return result

    async def _market_price(self, market) -> Optional[float]:
        """Current P(Yes) for a market, from its own book."""
        mid = getattr(market, "yes_mid", None)
        if isinstance(mid, (int, float)):
            return float(mid)
        if self.client is None or not market.tokens:
            return None
        try:
            return float(await self.client.get_midpoint(market.tokens[0].token_id))
        except Exception:
            return None

    def _mechanical_forecast(self, market) -> ForecastResult:
        """Baseline forecast without LLM — uses market price as prior.

        This exists so the backtest harness can evaluate the forecaster
        structure without expensive LLM calls. The real forecast comes
        from an actual LLM call via MCP.
        """
        # An uninformed 0.50 prior. This deliberately produces NO tradeable
        # edge — it exercises the pipeline without pretending to forecast.
        # Treat any proposal it generates as a bug in the edge gate, not a signal.
        return ForecastResult(
            question=market.question,
            resolution_criteria=market.resolution_criteria or "",
            base_rate=0.50,
            p_raw=0.50,
            p_calibrated=0.50,
            confidence=0.0,  # zero: must never clear MIN_CONFIDENCE
            reasoning="Mechanical baseline — no LLM estimate available.",
            market_price=None,  # filled in by scan() from the real book
            long_horizon=True,
        )

    def _to_proposal(
        self, market, forecast: ForecastResult
    ) -> Optional[TradeProposal]:
        """Convert a forecast into a trade proposal if there's sufficient edge."""
        p_agent = forecast.p_calibrated
        p_market = forecast.market_price

        # Guard the failure this module previously had built in: a default
        # market_price of 0.50 silently substituted for the real price.
        if p_market is None:
            return None
        if p_market <= 0 or p_market >= 1:
            return None

        edge = p_agent - p_market
        abs_edge = abs(edge)

        if abs_edge < self.MIN_EDGE:
            return None

        if forecast.confidence < self.MIN_CONFIDENCE:
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


def _days_until(end_date) -> Optional[float]:
    """Days from now until an ISO timestamp, or None if unparseable."""
    if not end_date:
        return None
    try:
        end = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (end - datetime.now(timezone.utc)).total_seconds() / 86400
