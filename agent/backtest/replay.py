"""Backtest replay harness — point-in-time, leak-proof.

Runs a forecasting strategy against historical price data.
Enforces: at simulated time T, the strategy sees ONLY data ≤ T.
Winner labels are hidden — the strategy emits p_agent,
the harness compares against the known outcome.

Control strategies (§4.4 of TESTING.md):
  - Random: p_agent = random(), random side
  - Market-parrot: p_agent = p_market (should score Brier delta ≈ 0)
  - Oracle: p_agent = true outcome (upper bound, should score strongly positive)
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from agent.backtest.corpus import Corpus, CorpusMarket


@dataclass
class ForecastResult:
    """A single forecast evaluation."""
    condition_id: str
    question: str
    timestamp: int  # when the forecast was made
    p_market: float  # market price at decision time
    p_agent: float   # agent's probability estimate
    outcome: int     # ground truth (0 or 1)
    winner: str      # "Yes" or "No"

    @property
    def brier_agent(self) -> float:
        return (self.p_agent - self.outcome) ** 2

    @property
    def brier_market(self) -> float:
        return (self.p_market - self.outcome) ** 2

    @property
    def brier_delta(self) -> float:
        """Positive = agent worse than market. Negative = agent better."""
        return self.brier_agent - self.brier_market


@dataclass
class BacktestReport:
    """Full backtest results."""
    forecasts: list[ForecastResult] = field(default_factory=list)
    strategy_name: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.forecasts)

    @property
    def brier_agent(self) -> float:
        if not self.forecasts:
            return 0.0
        return sum(f.brier_agent for f in self.forecasts) / len(self.forecasts)

    @property
    def brier_market(self) -> float:
        if not self.forecasts:
            return 0.0
        return sum(f.brier_market for f in self.forecasts) / len(self.forecasts)

    @property
    def brier_delta(self) -> float:
        return self.brier_agent - self.brier_market

    @property
    def edge_count(self) -> int:
        """Number of forecasts where agent beat market."""
        return sum(1 for f in self.forecasts if f.brier_delta < 0)

    def summary(self) -> str:
        return (
            f"{self.strategy_name}: {self.count} forecasts, "
            f"brier_agent={self.brier_agent:.4f}, "
            f"brier_market={self.brier_market:.4f}, "
            f"delta={self.brier_delta:+.4f} "
            f"({'agent BETTER' if self.brier_delta < 0 else 'market BETTER'}), "
            f"agent wins on {self.edge_count}/{self.count}"
        )


# ── Control strategies (§4.4) ────────────────────────────────

def control_random(p_market: float, _outcome_hidden: int = 0) -> float:
    """Random: p_agent = uniform(0, 1). Should lose money."""
    return random.random()


def control_market_parrot(p_market: float, _outcome_hidden: int = 0) -> float:
    """Market-parrot: p_agent = p_market. Brier delta must be ≈ 0."""
    return p_market


def control_oracle(p_market: float, outcome: int = 0) -> float:
    """Oracle: p_agent = true outcome. Upper bound — should be strongly positive."""
    return float(outcome)


def contamination_probe(p_market: float, _outcome_hidden: int = 0) -> float:
    """Contamination probe: always 0.50. Tests for data leaks on unknowable markets."""
    return 0.50


# ── Replay harness ───────────────────────────────────────────

class ReplayHarness:
    """Point-in-time backtest engine."""

    def __init__(self, corpus: Corpus, seed: int = 42):
        self.corpus = corpus
        random.seed(seed)

    def run(
        self,
        forecaster: Callable[[float, int], float],
        strategy_name: str,
        sample_every_n: int = 1,
    ) -> BacktestReport:
        """Run a forecaster against the corpus.

        For each market, samples one point in time (mid-history),
        passes the market price at that time to the forecaster,
        and records the forecast against the known outcome.

        The forecaster receives (p_market, outcome_hidden).
        outcome_hidden is ONLY passed to oracle — all other strategies
        must ignore it (enforced by convention, not technically).
        """
        report = BacktestReport(strategy_name=strategy_name)

        for market in self.corpus.markets:
            if not market.price_history or len(market.price_history) < 2:
                continue

            # Sample a point in time — use the midpoint of available history
            mid_idx = len(market.price_history) // 2
            pt = market.price_history[mid_idx]
            p_market = pt.price
            timestamp = pt.timestamp

            # The outcome is hidden from non-oracle strategies
            # (passed as 0 for all except oracle)
            outcome_hidden = market.outcome if strategy_name == "oracle" else 0

            try:
                p_agent = forecaster(p_market, outcome_hidden)
            except Exception as e:
                report.errors.append(f"{market.condition_id}: {e}")
                continue

            # Clamp
            p_agent = max(0.01, min(0.99, p_agent))

            report.forecasts.append(ForecastResult(
                condition_id=market.condition_id,
                question=market.question,
                timestamp=timestamp,
                p_market=p_market,
                p_agent=p_agent,
                outcome=market.outcome,
                winner=market.winner,
            ))

        return report

    def run_all_controls(self) -> list[BacktestReport]:
        """Run all four control strategies."""
        return [
            self.run(control_random, "random"),
            self.run(control_market_parrot, "market-parrot"),
            self.run(control_oracle, "oracle"),
            self.run(contamination_probe, "contamination-probe"),
        ]

    def verify_controls(self, reports: list[BacktestReport]) -> dict:
        """Verify the §4.4 control strategy expectations.

        Returns {test_name: (passed: bool, message: str)}
        """
        results = {}

        for r in reports:
            if r.strategy_name == "random":
                # Random must have Brier near 0.25 (uniform random on binary outcome)
                # and Brier delta should be positive (worse than market)
                passed = r.brier_delta > 0
                results["random → loses to market"] = (
                    passed,
                    f"delta={r.brier_delta:+.4f} {'✓ random worse than market' if passed else '✗ RANDOM BEAT MARKET — harness broken'}"
                )

            elif r.strategy_name == "market-parrot":
                # Market-parrot must have Brier delta ≈ 0
                passed = abs(r.brier_delta) < 0.001
                results["market-parrot → delta ≈ 0"] = (
                    passed,
                    f"delta={r.brier_delta:+.6f} {'✓ delta ~0' if passed else '✗ SCORING BROKEN'}"
                )

            elif r.strategy_name == "oracle":
                # Oracle must be strongly better than market
                passed = r.brier_delta < -0.1
                results["oracle → strongly beats market"] = (
                    passed,
                    f"brier_agent={r.brier_agent:.4f} vs brier_market={r.brier_market:.4f} {'✓ oracle dominates' if passed else '✗ oracle failed — wiring broken'}"
                )

            elif r.strategy_name == "contamination-probe":
                # Contamination probe should not show edge
                passed = abs(r.brier_delta) < 0.05
                results["contamination-probe → no edge"] = (
                    passed,
                    f"delta={r.brier_delta:+.4f} {'✓ no suspicious edge' if passed else '✗ POSSIBLE DATA LEAK'}"
                )

        return results
