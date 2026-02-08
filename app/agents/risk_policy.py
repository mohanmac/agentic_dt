"""
Agent 2: RiskPolicyAgent
Enforces guardrails, validates trades, and manages risk limits.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from app.core.schemas import (
    TradeIntent, RiskApproval, DailyState, StrategyType, TradeSide
)
from app.core.config import settings
from app.core.storage import storage
from app.core.utils import logger, log_event, get_today_date_str


class RiskPolicyAgent:
    """
    Risk management agent that enforces all trading guardrails.
    
    Responsibilities:
    - Daily capital and loss budget tracking
    - Per-trade risk validation
    - Mandatory stop-loss enforcement
    - Strategy switch controls
    - SAFE_MODE triggering
    - HITL approval gating
    """
    
    def __init__(self):
        self.daily_capital = settings.DAILY_CAPITAL
        self.max_daily_loss = settings.MAX_DAILY_LOSS
        self.max_trades_per_day = settings.MAX_TRADES_PER_DAY
        self.per_trade_max_loss_pct = settings.PER_TRADE_MAX_LOSS_PERCENT
        
        self.hitl_first_n_trades = settings.REQUIRE_HITL_FIRST_N_TRADES
        self.hitl_confidence_threshold = settings.HITL_CONFIDENCE_THRESHOLD
        
        self.strategy_switch_cooldown = timedelta(minutes=settings.STRATEGY_SWITCH_COOLDOWN_MINUTES)
        self.strategy_switch_min_improvement = settings.STRATEGY_SWITCH_MIN_IMPROVEMENT
    
    def approve(self, intent: TradeIntent, intent_id: Optional[int] = None) -> RiskApproval:
        """
        Evaluate trade intent against all guardrails.
        
        Args:
            intent: Trade intent to evaluate
            intent_id: Database ID of intent (if saved)
        
        Returns:
            RiskApproval decision
        """
        logger.info(f"Evaluating trade intent: {intent.strategy_id.value} {intent.side.value} {intent.symbol}")
        
        # Get current daily state
        daily_state = storage.get_or_create_daily_state()
        
        # Update unrealized PnL from positions
        self._update_unrealized_pnl(daily_state)
        
        # Initialize approval
        approval = RiskApproval(
            intent_id=intent_id,
            approved=True,  # Start optimistic
            guardrail_flags={},
            safe_mode_active=daily_state.safe_mode,
            remaining_loss_budget=daily_state.loss_budget_remaining,
            trades_today=daily_state.trades_count,
            current_strategy=daily_state.active_strategy
        )
        
        # Run all guardrail checks
        checks = [
            self._check_safe_mode(daily_state, approval),
            self._check_stop_loss(intent, approval),
            self._check_daily_loss_budget(intent, daily_state, approval),
            self._check_per_trade_risk(intent, daily_state, approval),
            self._check_max_trades(daily_state, approval),
            self._check_strategy_switch(intent, daily_state, approval),
            self._check_symbol_validity(intent, approval),
            self._check_liquidity(intent, approval)
        ]
        
        # If any check failed, reject
        if not all(checks):
            approval.approved = False
            log_event("trade_intent_rejected", {
                "symbol": intent.symbol,
                "strategy": intent.strategy_id.value,
                "reason": approval.rejection_reason,
                "guardrails": approval.guardrail_flags
            })
            return approval
        
        # Check HITL requirements
        self._check_hitl_requirements(intent, daily_state, approval)
        
        # Adjust quantity based on risk limits
        self._adjust_quantity(intent, daily_state, approval)
        
        # Log approval
        if approval.approved:
            log_event("trade_intent_approved", {
                "symbol": intent.symbol,
                "strategy": intent.strategy_id.value,
                "quantity": approval.adjusted_quantity or intent.quantity,
                "hitl_required": approval.hitl_required,
                "expected_risk": intent.expected_risk_rupees
            })
        
        return approval
    
    def _check_safe_mode(self, daily_state: DailyState, approval: RiskApproval) -> bool:
        """Check if SAFE_MODE is active."""
        if daily_state.safe_mode:
            approval.approved = False
            approval.rejection_reason = "SAFE_MODE active - max daily loss reached"
            approval.guardrail_flags['safe_mode'] = True
            logger.warning("Trade rejected: SAFE_MODE active")
            return False
        return True
    
    def _check_stop_loss(self, intent: TradeIntent, approval: RiskApproval) -> bool:
        """Validate mandatory stop-loss."""
        if intent.stop_loss_price is None:
            approval.approved = False
            approval.rejection_reason = "Mandatory stop-loss missing"
            approval.guardrail_flags['missing_stop_loss'] = True
            logger.error("Trade rejected: No stop-loss specified")
            return False
        
        # Validate stop-loss is on correct side
        if intent.side == TradeSide.BUY and intent.stop_loss_price >= intent.entry_price:
            approval.approved = False
            approval.rejection_reason = "Stop-loss for BUY must be below entry price"
            approval.guardrail_flags['invalid_stop_loss'] = True
            logger.error("Trade rejected: Invalid stop-loss for BUY")
            return False
        
        if intent.side == TradeSide.SELL and intent.stop_loss_price <= intent.entry_price:
            approval.approved = False
            approval.rejection_reason = "Stop-loss for SELL must be above entry price"
            approval.guardrail_flags['invalid_stop_loss'] = True
            logger.error("Trade rejected: Invalid stop-loss for SELL")
            return False
        
        return True
    
    def _check_daily_loss_budget(self, intent: TradeIntent, daily_state: DailyState, approval: RiskApproval) -> bool:
        """Check if daily loss budget allows this trade."""
        if daily_state.loss_budget_remaining <= 0:
            approval.approved = False
            approval.rejection_reason = f"Daily loss budget exhausted (₹{daily_state.loss_budget_remaining:.2f} remaining)"
            approval.guardrail_flags['loss_budget_exhausted'] = True
            logger.warning("Trade rejected: Loss budget exhausted")
            
            # Trigger SAFE_MODE
            if not daily_state.safe_mode:
                daily_state.safe_mode = True
                storage.save_daily_state(daily_state)
                log_event("safe_mode_triggered", {
                    "reason": "loss_budget_exhausted",
                    "total_pnl": daily_state.total_pnl
                }, level="WARNING")
            
            return False
        
        # Check if expected risk exceeds remaining budget
        if intent.expected_risk_rupees > daily_state.loss_budget_remaining:
            approval.approved = False
            approval.rejection_reason = f"Trade risk (₹{intent.expected_risk_rupees:.2f}) exceeds remaining budget (₹{daily_state.loss_budget_remaining:.2f})"
            approval.guardrail_flags['risk_exceeds_budget'] = True
            logger.warning("Trade rejected: Risk exceeds remaining budget")
            return False
        
        return True
    
    def _check_per_trade_risk(self, intent: TradeIntent, daily_state: DailyState, approval: RiskApproval) -> bool:
        """Check per-trade risk limits."""
        # Calculate max allowed risk per trade
        remaining_trades = daily_state.max_trades - daily_state.trades_count
        if remaining_trades <= 0:
            remaining_trades = 1  # At least allow current trade
        
        max_risk_per_trade = (daily_state.loss_budget_remaining * self.per_trade_max_loss_pct / 100.0)
        
        # Also cap at absolute value
        max_risk_per_trade = min(max_risk_per_trade, 100.0)  # Max ₹100 per trade
        
        if intent.expected_risk_rupees > max_risk_per_trade:
            approval.approved = False
            approval.rejection_reason = f"Per-trade risk (₹{intent.expected_risk_rupees:.2f}) exceeds limit (₹{max_risk_per_trade:.2f})"
            approval.guardrail_flags['per_trade_risk_exceeded'] = True
            logger.warning(f"Trade rejected: Per-trade risk limit exceeded")
            return False
        
        approval.guardrail_flags['max_risk_per_trade'] = max_risk_per_trade
        return True
    
    def _check_max_trades(self, daily_state: DailyState, approval: RiskApproval) -> bool:
        """Check if max trades per day reached."""
        if daily_state.trades_count >= daily_state.max_trades:
            approval.approved = False
            approval.rejection_reason = f"Max trades per day ({daily_state.max_trades}) reached"
            approval.guardrail_flags['max_trades_reached'] = True
            logger.warning("Trade rejected: Max trades per day reached")
            return False
        
        return True
    
    def _check_strategy_switch(self, intent: TradeIntent, daily_state: DailyState, approval: RiskApproval) -> bool:
        """Check strategy switch controls."""
        current_strategy = daily_state.active_strategy
        new_strategy = intent.strategy_id
        
        # If no active strategy, allow any strategy
        if current_strategy is None:
            return True
        
        # If same strategy, no switch
        if current_strategy == new_strategy:
            return True
        
        # Strategy switch detected
        logger.info(f"Strategy switch detected: {current_strategy.value} -> {new_strategy.value}")
        
        # Check cooldown
        if daily_state.strategy_switched_at:
            time_since_switch = datetime.now() - daily_state.strategy_switched_at
            if time_since_switch < self.strategy_switch_cooldown:
                remaining = self.strategy_switch_cooldown - time_since_switch
                approval.approved = False
                approval.rejection_reason = f"Strategy switch cooldown active ({remaining.seconds // 60} min remaining)"
                approval.guardrail_flags['strategy_switch_cooldown'] = True
                logger.warning("Trade rejected: Strategy switch cooldown active")
                return False
        
        # Check confidence improvement (this is simplified - in real scenario we'd compare with previous strategy's last confidence)
        # For now, require minimum confidence for switch
        if intent.confidence_score < (0.6 + self.strategy_switch_min_improvement):
            approval.approved = False
            approval.rejection_reason = f"Strategy switch requires confidence >= {0.6 + self.strategy_switch_min_improvement:.2f}"
            approval.guardrail_flags['strategy_switch_confidence_low'] = True
            logger.warning("Trade rejected: Insufficient confidence for strategy switch")
            return False
        
        # Strategy switch requires HITL approval
        approval.hitl_required = True
        approval.hitl_reason = f"Strategy switch: {current_strategy.value} -> {new_strategy.value}"
        approval.guardrail_flags['strategy_switch'] = True
        
        logger.info("Strategy switch allowed but requires HITL approval")
        return True
    
    def _check_symbol_validity(self, intent: TradeIntent, approval: RiskApproval) -> bool:
        """Check if symbol is in allowed trading list."""
        allowed_symbols = settings.get_trading_symbols()
        
        if intent.symbol not in allowed_symbols:
            approval.approved = False
            approval.rejection_reason = f"Symbol {intent.symbol} not in allowed trading list"
            approval.guardrail_flags['invalid_symbol'] = True
            logger.warning(f"Trade rejected: Symbol {intent.symbol} not allowed")
            return False
        
        return True
    
    def _check_liquidity(self, intent: TradeIntent, approval: RiskApproval) -> bool:
        """Check liquidity (placeholder - would use real liquidity data)."""
        # In real implementation, check average volume, bid-ask spread, etc.
        # For now, just pass
        return True
    
    def _check_hitl_requirements(self, intent: TradeIntent, daily_state: DailyState, approval: RiskApproval):
        """Check if HITL approval is required."""
        # First N trades require approval
        if daily_state.trades_count < self.hitl_first_n_trades:
            approval.hitl_required = True
            approval.hitl_reason = f"First {self.hitl_first_n_trades} trades require approval (trade #{daily_state.trades_count + 1})"
        
        # Low confidence trades require approval
        if intent.confidence_score < self.hitl_confidence_threshold:
            approval.hitl_required = True
            if approval.hitl_reason:
                approval.hitl_reason += f"; Low confidence ({intent.confidence_score:.2f} < {self.hitl_confidence_threshold})"
            else:
                approval.hitl_reason = f"Low confidence ({intent.confidence_score:.2f} < {self.hitl_confidence_threshold})"
        
        if approval.hitl_required:
            logger.info(f"HITL approval required: {approval.hitl_reason}")
            approval.guardrail_flags['hitl_required'] = True
    
    def _adjust_quantity(self, intent: TradeIntent, daily_state: DailyState, approval: RiskApproval):
        """Adjust quantity to fit risk limits."""
        # Calculate max quantity based on risk budget
        max_risk = approval.guardrail_flags.get('max_risk_per_trade', daily_state.loss_budget_remaining)
        
        # Risk per share
        entry_price = intent.entry_price or 0  # Will be filled at market price
        risk_per_share = abs(entry_price - intent.stop_loss_price) if entry_price else abs(intent.stop_loss_price * 0.01)
        
        if risk_per_share > 0:
            max_quantity = int(max_risk / risk_per_share)
            
            if max_quantity < intent.quantity:
                approval.adjusted_quantity = max(1, max_quantity)  # At least 1 share
                logger.info(f"Quantity adjusted: {intent.quantity} -> {approval.adjusted_quantity} (risk limit)")
                approval.guardrail_flags['quantity_adjusted'] = True
    
    def _update_unrealized_pnl(self, daily_state: DailyState):
        """Update unrealized PnL from open positions."""
        positions = storage.get_all_positions()
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        
        # Update daily state
        daily_state.update_pnl(unrealized=unrealized_pnl)
        storage.save_daily_state(daily_state)
    
    def trigger_safe_mode(self, reason: str):
        """Manually trigger SAFE_MODE."""
        daily_state = storage.get_or_create_daily_state()
        daily_state.safe_mode = True
        storage.save_daily_state(daily_state)
        
        log_event("safe_mode_triggered", {
            "reason": reason,
            "total_pnl": daily_state.total_pnl,
            "loss_budget_remaining": daily_state.loss_budget_remaining
        }, level="WARNING")
        
        logger.warning(f"SAFE_MODE triggered: {reason}")
    
    def reset_daily_state(self):
        """Reset daily state (for new trading day)."""
        today = get_today_date_str()
        
        # Create fresh daily state
        new_state = DailyState(
            date=today,
            loss_budget_remaining=self.max_daily_loss,
            max_daily_loss=self.max_daily_loss,
            max_trades=self.max_trades_per_day
        )
        
        storage.save_daily_state(new_state)
        
        log_event("daily_state_reset", {
            "date": today,
            "capital": self.daily_capital,
            "max_loss": self.max_daily_loss
        })
        
        logger.info(f"Daily state reset for {today}")


# Global risk policy agent instance
risk_policy = RiskPolicyAgent()
