"""Autonomous trading agent runner.

Ties together the full pipeline:
  scan markets → strategy evaluates → risk validates & sizes
  → fill engine executes → portfolio updates → publish snapshots

This is the main entry point for both manual runs and cron-driven autonomy.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.engine.fills import FillEngine
from agent.engine.portfolio import PortfolioEngine
from agent.polymarket.client import PolymarketClient
from agent.risk.manager import RiskDecision, RiskManager
from agent.strategies.base import StrategyResult, TradeProposal
from agent.strategies.longshot import FavoriteLongshotStrategy


@dataclass
class AgentDecision:
    """A single decision — what the agent did or didn't do."""
    time: str
    proposal: TradeProposal
    risk_decision: RiskDecision
    filled: bool = False
    fill_price: float = 0.0
    fill_shares: float = 0.0
    fill_cost: float = 0.0
    error: str = ""


@dataclass
class AgentRunResult:
    """Result of one full agent cycle."""
    time: str
    decisions: list[AgentDecision] = field(default_factory=list)
    markets_scanned: int = 0
    proposals_generated: int = 0
    proposals_approved: int = 0
    trades_executed: int = 0
    errors: list[str] = field(default_factory=list)
    portfolio_value: float = 0.0
    cash: float = 0.0
    open_positions: int = 0


class AutonomousAgent:
    """The full autonomous trading agent."""

    def __init__(
        self,
        client: PolymarketClient = None,
        portfolio: PortfolioEngine = None,
        fill_mode: str = "realistic",
        starting_cash: float = 10_000.0,
    ):
        self.client = client or PolymarketClient()
        self.portfolio = portfolio or PortfolioEngine(starting_cash=starting_cash)
        self.fill_engine = FillEngine(self.client, mode=fill_mode)
        self.risk_manager = RiskManager(self.portfolio)
        self.strategy = FavoriteLongshotStrategy(self.client)

    # ── Main cycle ───────────────────────────────────────────

    async def run_cycle(self, max_markets: int = 100) -> AgentRunResult:
        """Run one full cycle: scan → evaluate → risk → fill → record."""
        now = datetime.now(timezone.utc).isoformat()
        result = AgentRunResult(time=now)

        # 1. Scan markets
        try:
            events = await self.client.trending(limit=15)
        except Exception as e:
            result.errors.append(f"Failed to fetch markets: {e}")
            return result

        all_markets = []
        for event in events:
            all_markets.extend(event.markets)
        all_markets = all_markets[:max_markets]
        result.markets_scanned = len(all_markets)

        # 2. Strategy evaluation
        try:
            strategy_result = await self.strategy.scan(all_markets)
            result.proposals_generated = len(strategy_result.proposals)
        except Exception as e:
            result.errors.append(f"Strategy scan failed: {e}")
            return result

        # 3. Risk evaluate each proposal
        for proposal in strategy_result.proposals:
            risk = self.risk_manager.evaluate(proposal)
            decision = AgentDecision(
                time=now,
                proposal=proposal,
                risk_decision=risk,
            )

            if not risk.approved:
                result.decisions.append(decision)
                continue

            result.proposals_approved += 1

            # 4. Execute fill
            # If we're SELLing a position we don't own, convert to BUY NO
            actual_direction = proposal.direction
            actual_token = proposal.token_id
            actual_outcome = proposal.outcome

            if proposal.direction == "SELL":
                # Check if we own the position
                pos_key = f"{proposal.token_id}:{proposal.outcome}"
                if pos_key not in self.portfolio.positions:
                    # Don't own it — convert to BUY the opposite outcome
                    actual_direction = "BUY"
                    actual_outcome = "No" if proposal.outcome == "Yes" else "Yes"
                    # Use the correct token for the opposite outcome
                    actual_token = (
                        proposal.no_token_id if proposal.outcome == "Yes"
                        else proposal.yes_token_id
                    )
                    if not actual_token:
                        actual_token = proposal.token_id  # fallback
                    decision.proposal.reasoning += (
                        f" (Converted SELL {proposal.outcome} → BUY {actual_outcome}: "
                        f"no existing position to sell)"
                    )

            try:
                if actual_direction == "BUY":
                    fill = await self.fill_engine.market_buy(
                        actual_token, risk.sized_shares
                    )
                else:
                    fill = await self.fill_engine.market_sell(
                        actual_token, risk.sized_shares
                    )

                if fill.filled:
                    # 5. Update portfolio
                    if actual_direction == "BUY":
                        self.portfolio.add_position(
                            token_id=actual_token,
                            outcome=actual_outcome,
                            shares=fill.filled_size,
                            price=fill.avg_price,
                            market_question=proposal.market_question,
                            condition_id=proposal.condition_id,
                        )
                    else:
                        self.portfolio.reduce_position(
                            token_id=actual_token,
                            outcome=actual_outcome,
                            shares=fill.filled_size,
                            price=fill.avg_price,
                            reason=proposal.reasoning,
                        )

                    decision.filled = True
                    decision.fill_price = fill.avg_price
                    decision.fill_shares = fill.filled_size
                    decision.fill_cost = fill.total_cost
                    result.trades_executed += 1
                else:
                    decision.error = f"Fill rejected: {fill.reason}"

            except Exception as e:
                decision.error = f"Fill error: {e}"

            result.decisions.append(decision)

        # Final state
        result.cash = self.portfolio.cash
        result.open_positions = self.portfolio.open_position_count
        result.portfolio_value = self.portfolio.cash  # simplified

        return result

    # ── Reporting ────────────────────────────────────────────

    def get_scorecard(self, results: list[AgentRunResult]) -> dict:
        """Generate a scorecard from run history.

        Returns data suitable for scorecard.json publishing.
        """
        total_trades = sum(r.trades_executed for r in results)
        total_proposals = sum(r.proposals_generated for r in results)
        total_approved = sum(r.proposals_approved for r in results)

        # Brier scores require market resolution — placeholder until
        # we have enough resolved markets
        return {
            "total_cycles": len(results),
            "total_proposals": total_proposals,
            "total_approved": total_approved,
            "total_trades": total_trades,
            "approval_rate": total_approved / max(total_proposals, 1),
            "current_cash": self.portfolio.cash,
            "starting_cash": self.portfolio.starting_cash,
            "total_pnl": self.portfolio.cash - self.portfolio.starting_cash,
            "open_positions": self.portfolio.open_position_count,
            "total_trade_count": self.portfolio.total_trades,
            "strategy": self.strategy.name,
            "brier_agent": None,  # populated when markets resolve
            "brier_market": None,
        }

    def get_portfolio_snapshot(self) -> dict:
        """Current portfolio state for publishing."""
        return {
            "cash": self.portfolio.cash,
            "starting_cash": self.portfolio.starting_cash,
            "pnl": self.portfolio.cash - self.portfolio.starting_cash,
            "pnl_pct": (self.portfolio.cash / self.portfolio.starting_cash - 1) * 100,
            "positions": [
                {
                    "token_id": pos.token_id,
                    "outcome": pos.outcome,
                    "shares": pos.shares,
                    "avg_entry_price": pos.avg_entry_price,
                    "market_question": pos.market_question,
                    "condition_id": pos.condition_id,
                    "opened_at": pos.opened_at,
                }
                for pos in self.portfolio.positions.values()
            ],
            "recent_trades": [
                {
                    "time": t.time,
                    "action": t.action,
                    "outcome": t.outcome,
                    "price": t.price,
                    "shares": t.shares,
                    "cost": t.cost,
                    "market_question": t.market_question,
                }
                for t in self.portfolio.trades[-20:]  # last 20
            ],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_decisions_log(self, results: list[AgentRunResult]) -> list[dict]:
        """All decisions including rejected ones — key observability."""
        decisions = []
        for run in results:
            for d in run.decisions:
                decisions.append({
                    "time": d.time,
                    "market": d.proposal.market_question[:120],
                    "direction": d.proposal.direction,
                    "outcome": d.proposal.outcome,
                    "p_market": d.proposal.market_probability,
                    "p_agent": d.proposal.agent_probability,
                    "strategy": d.proposal.strategy_name,
                    "approved": d.risk_decision.approved,
                    "sized_shares": d.risk_decision.sized_shares,
                    "risk_reason": d.risk_decision.reason,
                    "filled": d.filled,
                    "fill_price": d.fill_price,
                    "error": d.error,
                })
        return decisions
