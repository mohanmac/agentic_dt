"""
Unit tests for RiskPolicyAgent guardrails.
"""
import pytest
from datetime import datetime, timedelta

from app.core.schemas import TradeIntent, DailyState, StrategyType, TradeSide, OrderType
from app.agents.risk_policy import RiskPolicyAgent
from app.core.storage import storage


class TestRiskPolicyAgent:
    """Test suite for RiskPolicyAgent guardrails."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.risk_agent = RiskPolicyAgent()
        
        # Create test trade intent
        self.test_intent = TradeIntent(
            strategy_id=StrategyType.MOMENTUM_BREAKOUT,
            symbol="RELIANCE",
            side=TradeSide.BUY,
            entry_type=OrderType.MARKET,
            quantity=10,
            stop_loss_price=2400.00,
            target_price=2500.00,
            confidence_score=0.75,
            rationale="Test trade",
            expected_risk_rupees=50.00,
            entry_price=2450.00
        )
    
    def test_mandatory_stop_loss(self):
        """Test that trades without stop-loss are rejected."""
        # Create intent without stop-loss
        intent = TradeIntent(
            strategy_id=StrategyType.MOMENTUM_BREAKOUT,
            symbol="RELIANCE",
            side=TradeSide.BUY,
            entry_type=OrderType.MARKET,
            quantity=10,
            stop_loss_price=None,  # Missing stop-loss
            confidence_score=0.75,
            rationale="Test",
            expected_risk_rupees=50.00,
            entry_price=2450.00
        )
        
        approval = self.risk_agent.approve(intent)
        
        assert not approval.approved
        assert "stop-loss" in approval.rejection_reason.lower()
    
    def test_invalid_stop_loss_side(self):
        """Test that stop-loss on wrong side is rejected."""
        # BUY with stop-loss above entry
        intent = TradeIntent(
            strategy_id=StrategyType.MOMENTUM_BREAKOUT,
            symbol="RELIANCE",
            side=TradeSide.BUY,
            entry_type=OrderType.MARKET,
            quantity=10,
            stop_loss_price=2500.00,  # Above entry (wrong!)
            confidence_score=0.75,
            rationale="Test",
            expected_risk_rupees=50.00,
            entry_price=2450.00
        )
        
        approval = self.risk_agent.approve(intent)
        
        assert not approval.approved
        assert "stop-loss" in approval.rejection_reason.lower()
    
    def test_daily_loss_budget(self):
        """Test daily loss budget enforcement."""
        # Create daily state with exhausted budget
        daily_state = DailyState(
            date=datetime.now().strftime("%Y-%m-%d"),
            loss_budget_remaining=0.0,
            max_daily_loss=200.0,
            max_trades=5
        )
        storage.save_daily_state(daily_state)
        
        approval = self.risk_agent.approve(self.test_intent)
        
        assert not approval.approved
        assert "budget" in approval.rejection_reason.lower()
    
    def test_max_trades_per_day(self):
        """Test max trades per day limit."""
        # Create daily state with max trades reached
        daily_state = DailyState(
            date=datetime.now().strftime("%Y-%m-%d"),
            loss_budget_remaining=200.0,
            max_daily_loss=200.0,
            trades_count=5,  # Max reached
            max_trades=5
        )
        storage.save_daily_state(daily_state)
        
        approval = self.risk_agent.approve(self.test_intent)
        
        assert not approval.approved
        assert "max trades" in approval.rejection_reason.lower()
    
    def test_safe_mode_blocks_trades(self):
        """Test that SAFE_MODE blocks all trades."""
        # Create daily state with SAFE_MODE active
        daily_state = DailyState(
            date=datetime.now().strftime("%Y-%m-%d"),
            loss_budget_remaining=0.0,
            max_daily_loss=200.0,
            safe_mode=True,
            max_trades=5
        )
        storage.save_daily_state(daily_state)
        
        approval = self.risk_agent.approve(self.test_intent)
        
        assert not approval.approved
        assert approval.safe_mode_active
        assert "SAFE_MODE" in approval.rejection_reason
    
    def test_hitl_required_for_low_confidence(self):
        """Test HITL requirement for low confidence trades."""
        # Create intent with low confidence
        intent = TradeIntent(
            strategy_id=StrategyType.MOMENTUM_BREAKOUT,
            symbol="RELIANCE",
            side=TradeSide.BUY,
            entry_type=OrderType.MARKET,
            quantity=10,
            stop_loss_price=2400.00,
            confidence_score=0.65,  # Below threshold (0.70)
            rationale="Test",
            expected_risk_rupees=50.00,
            entry_price=2450.00
        )
        
        # Reset daily state
        daily_state = DailyState(
            date=datetime.now().strftime("%Y-%m-%d"),
            loss_budget_remaining=200.0,
            max_daily_loss=200.0,
            max_trades=5
        )
        storage.save_daily_state(daily_state)
        
        approval = self.risk_agent.approve(intent)
        
        assert approval.hitl_required
        assert "confidence" in approval.hitl_reason.lower()
    
    def test_hitl_required_for_first_n_trades(self):
        """Test HITL requirement for first N trades."""
        # Reset daily state with 0 trades
        daily_state = DailyState(
            date=datetime.now().strftime("%Y-%m-%d"),
            loss_budget_remaining=200.0,
            max_daily_loss=200.0,
            trades_count=0,  # First trade
            max_trades=5
        )
        storage.save_daily_state(daily_state)
        
        approval = self.risk_agent.approve(self.test_intent)
        
        assert approval.hitl_required
        assert "first" in approval.hitl_reason.lower()
    
    def test_valid_trade_approved(self):
        """Test that valid trade is approved."""
        # Reset daily state
        daily_state = DailyState(
            date=datetime.now().strftime("%Y-%m-%d"),
            loss_budget_remaining=200.0,
            max_daily_loss=200.0,
            trades_count=3,  # Past HITL requirement
            max_trades=5
        )
        storage.save_daily_state(daily_state)
        
        approval = self.risk_agent.approve(self.test_intent)
        
        # Should be approved (may require HITL but not rejected)
        assert approval.approved or approval.hitl_required


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
