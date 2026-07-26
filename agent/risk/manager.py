"""Risk manager — validates, sizes, and gates all trade proposals.

Guardrails are enforced in code, never trusted to the LLM.
An LLM asked to respect a position limit will eventually not.
"""

from dataclasses import dataclass, field
from typing import Optional

from agent.engine.portfolio import PortfolioEngine
from agent.strategies.base import TradeProposal


@dataclass
class RiskDecision:
    """Outcome of risk evaluation for a trade proposal."""
    approved: bool
    proposal: TradeProposal
    sized_shares: float = 0.0  # Shares to trade after Kelly sizing
    kelly_fraction: float = 0.0
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


class RiskManager:
    """Quarter-Kelly sizing, position limits, circuit breaker."""

    # ── Configurable parameters ──
    KELLY_FRACTION = 0.25        # Quarter-Kelly (conservative)
    MAX_POSITION_PCT = 0.05      # Max 5% of bankroll per position
    MAX_CORRELATED_PCT = 0.15    # Max 15% across correlated cluster
    MAX_DAILY_TRADES = 20        # Cap on trades per day
    CIRCUIT_BREAKER_DRAWDOWN = 0.20  # Halt at 20% drawdown
    MIN_BANKROLL = 500.0         # Below this, stop trading
    MIN_SHARES = 1.0             # Minimum trade size
    PER_MARKET_COOLDOWN = 4      # Hours before re-trading same market

    def __init__(self, portfolio: PortfolioEngine):
        self.portfolio = portfolio
        self.daily_trade_count = 0
        self.last_trade_times: dict[str, str] = {}  # condition_id -> ISO timestamp

    # ── Main evaluation ──────────────────────────────────────

    def evaluate(self, proposal: TradeProposal, marks: dict[str, float] = None) -> RiskDecision:
        """Full risk evaluation for a trade proposal.

        Returns a RiskDecision with approval status, sizing, and reasoning.
        marks: current marks for existing positions (for proper equity calc).
        """
        warnings = []
        if marks is None:
            marks = {}

        # ── True equity (Defect 3 fix) ──
        current_equity = self.portfolio.get_total_equity(marks)
        drawdown = 1.0 - (current_equity / self.portfolio.starting_cash)
        if drawdown >= self.CIRCUIT_BREAKER_DRAWDOWN:
            return RiskDecision(
                approved=False,
                proposal=proposal,
                reason=f"Circuit breaker: {drawdown:.1%} drawdown >= {self.CIRCUIT_BREAKER_DRAWDOWN:.0%} limit",
            )

        # ── Minimum bankroll ──
        if current_equity < self.MIN_BANKROLL:
            return RiskDecision(
                approved=False,
                proposal=proposal,
                reason=f"Bankroll ${current_equity:.0f} below minimum ${self.MIN_BANKROLL:.0f}",
            )

        # ── Daily trade cap ──
        if self.daily_trade_count >= self.MAX_DAILY_TRADES:
            return RiskDecision(
                approved=False,
                proposal=proposal,
                reason=f"Daily trade cap ({self.MAX_DAILY_TRADES}) reached",
            )

        # ── Per-market cooldown ──
        if proposal.condition_id in self.last_trade_times:
            from datetime import datetime, timezone
            last = self.last_trade_times[proposal.condition_id]
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                if hours_since < self.PER_MARKET_COOLDOWN:
                    return RiskDecision(
                        approved=False,
                        proposal=proposal,
                        reason=f"Cooldown: {hours_since:.1f}h since last trade on this market (< {self.PER_MARKET_COOLDOWN}h)",
                    )
            except (ValueError, TypeError):
                pass  # Can't parse timestamp — allow trade

        # ── Kelly sizing ──
        kelly = self._kelly_criterion(
            p_agent=proposal.agent_probability,
            p_market=proposal.market_probability,
            direction=proposal.direction,
            outcome=proposal.outcome,
        )

        if kelly <= 0:
            return RiskDecision(
                approved=False,
                proposal=proposal,
                reason=f"No positive edge: Kelly fraction = {kelly:.4f}",
            )

        # Quarter-Kelly
        sized_fraction = kelly * self.KELLY_FRACTION

        # Convert to shares: bankroll * fraction / price_per_share
        # Use the correct price: YES trades at p_market, NO trades at (1-p_market)
        if proposal.outcome == "Yes":
            entry_price = proposal.market_probability
        else:
            entry_price = 1.0 - proposal.market_probability

        sized_shares = (current_equity * sized_fraction) / entry_price if entry_price > 0 else 0

        # ── Position size cap ──
        max_shares = (current_equity * self.MAX_POSITION_PCT) / entry_price
        if sized_shares > max_shares:
            warnings.append(
                f"Position capped at {self.MAX_POSITION_PCT:.0%} of bankroll "
                f"({max_shares:.0f} shares, Kelly wanted {sized_shares:.0f})"
            )
            sized_shares = max_shares

        # ── Minimum shares ──
        if sized_shares < self.MIN_SHARES:
            return RiskDecision(
                approved=False,
                proposal=proposal,
                reason=f"Size {sized_shares:.2f} shares below minimum {self.MIN_SHARES}",
                sized_shares=sized_shares,
                kelly_fraction=kelly,
            )

        # ── Invariant: reject if execution price > fair value ──
        # (from review-02: \"Reject any trade where execution_price is worse than fair_value\")
        fair_value = (
            proposal.agent_probability if proposal.outcome == "Yes"
            else 1.0 - proposal.agent_probability
        )
        if proposal.direction == "BUY" and entry_price > fair_value:
            return RiskDecision(
                approved=False,
                proposal=proposal,
                reason=(
                    f"Execution price (${entry_price:.4f}) exceeds fair value "
                    f"(${fair_value:.4f}). Paying above your own estimate is never justified."
                ),
                sized_shares=sized_shares,
                kelly_fraction=kelly,
            )
        if proposal.direction == "SELL" and entry_price < fair_value:
            return RiskDecision(
                approved=False,
                proposal=proposal,
                reason=(
                    f"Execution price (${entry_price:.4f}) below fair value "
                    f"(${fair_value:.4f}). Selling below your own estimate is never justified."
                ),
                sized_shares=sized_shares,
                kelly_fraction=kelly,
            )

        # ── Approved ──
        sized_shares = round(sized_shares)
        if sized_shares < self.MIN_SHARES:
            sized_shares = self.MIN_SHARES

        self.daily_trade_count += 1
        from datetime import datetime, timezone
        self.last_trade_times[proposal.condition_id] = (
            datetime.now(timezone.utc).isoformat()
        )

        return RiskDecision(
            approved=True,
            proposal=proposal,
            sized_shares=sized_shares,
            kelly_fraction=kelly,
            reason=f"Approved: {sized_shares:.0f} shares at {self.KELLY_FRACTION:.0%}-Kelly (full Kelly = {kelly:.4f})",
            warnings=warnings,
        )

    # ── Kelly criterion ──────────────────────────────────────

    def _kelly_criterion(
        self,
        p_agent: float,
        p_market: float,
        direction: str,
        outcome: str,
    ) -> float:
        """Full Kelly fraction for a binary bet.

        For a contract at price c with agent probability p:
          If buying YES:  f* = (p - c) / (1 - c)
          If selling YES: f* = (c - p) / c

        Reference: PLAN.md §Phase 5
        """
        p = p_agent
        c = p_market

        if direction == "BUY" and outcome == "Yes":
            # We think YES is more likely than market says
            if c >= 1.0:
                return 0.0
            return (p - c) / (1.0 - c)
        elif direction == "SELL" and outcome == "Yes":
            # We think YES is less likely than market says
            if c <= 0.0:
                return 0.0
            return (c - p) / c
        elif direction == "BUY" and outcome == "No":
            # Buying NO = selling YES at implied price (1-c)
            # p_agent_NO = 1 - p_agent, p_market_NO = 1 - p_market
            c_no = 1.0 - c
            p_no = 1.0 - p
            if c_no >= 1.0:
                return 0.0
            return (p_no - c_no) / (1.0 - c_no)
        elif direction == "SELL" and outcome == "No":
            # Selling NO = buying YES at implied price
            c_no = 1.0 - c
            p_no = 1.0 - p
            if c_no <= 0.0:
                return 0.0
            return (c_no - p_no) / c_no

        return 0.0

    def reset_daily(self):
        """Reset daily trade counter (call at start of new day)."""
        self.daily_trade_count = 0
