import datetime
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class RiskConfig:
    max_capital_per_trade: float = 2000.0
    max_loss_per_day: float = 300.0
    per_trade_max_loss_absolute: float = 500.0
    min_capital_threshold: float = 600.0
    max_trades_per_day: int = 5
    max_open_positions: int = 2
    
    # Position & Exposure Limits
    max_position_size_percent: float = 40.0
    max_portfolio_exposure_percent: float = 70.0
    max_sector_exposure_percent: float = 50.0
    
    # Time-Based Guardrails
    avoid_first_minutes: int = 15
    avoid_last_minutes: int = 15
    min_hold_time_minutes: int = 5
    max_position_age_hours: int = 4
    
    # Drawdown & Streak Protection
    max_drawdown_percent: float = 15.0
    max_consecutive_losses: int = 3
    trailing_stop_activation_percent: float = 2.0
    trailing_stop_distance_percent: float = 1.0
    
    # Market Condition Filters
    max_vix_threshold: float = 30.0
    max_spread_percent: float = 0.5
    min_volume_multiplier: float = 1.5
    max_gap_percent: float = 5.0
    
    # Order Execution Safeguards
    max_orders_per_minute: int = 10
    max_price_deviation_percent: float = 1.0
    
    # Hard Constraints
    max_stop_loss_percent: float = 10.0
    slippage_buffer_percent: float = 0.1
    abrupt_move_threshold_percent: float = 2.0

@dataclass
class DailyStats:
    date: datetime.date
    total_trades: int = 0
    total_pnl: float = 0.0
    current_capital: float = 2000.0  # Track available capital
    is_trading_halted: bool = False
    peak_capital: float = 0.0
    consecutive_losses: int = 0
    last_order_time: datetime.datetime = None
    orders_this_minute: int = 0

class RiskEngine:
    def __init__(self, config: RiskConfig = RiskConfig()):
        self.config = config
        self.daily_stats = DailyStats(date=datetime.date.today())

    def reset_daily_stats(self):
        """Call this at the start of a new trading day"""
        self.daily_stats = DailyStats(date=datetime.date.today())

    def update_after_trade(self, pnl: float):
        """Update stats after a trade closes"""
        self.daily_stats.total_pnl += pnl
        self.daily_stats.current_capital += pnl  # Update available capital
        
        # Check if we hit max loss
        if self.daily_stats.total_pnl <= -self.config.max_loss_per_day:
            self.daily_stats.is_trading_halted = True
            return False, "Max daily loss breach! Trading halted."
        
        # Check if capital exhausted
        if self.daily_stats.current_capital < self.config.min_capital_threshold:
            self.daily_stats.is_trading_halted = True
            return False, f"Capital exhausted! Available ₹{self.daily_stats.current_capital:.2f} < minimum ₹{self.config.min_capital_threshold}."
            
        return True, "OK"

    def can_place_trade(self, estimated_cost: float) -> tuple[bool, str]:
        """
        Validate if a new trade can be placed based on hard guardrails.
        """
        # 1. Check Daily Halt
        if self.daily_stats.is_trading_halted:
            return False, "Trading is halted due to risk breach."

        # 2. Check Max Trades
        if self.daily_stats.total_trades >= self.config.max_trades_per_day:
            return False, f"Max daily trades ({self.config.max_trades_per_day}) reached."

        # 3. Check Capital per Trade
        if estimated_cost > self.config.max_capital_per_trade:
            return False, f"Order value ₹{estimated_cost} exceeds limit ₹{self.config.max_capital_per_trade}."
        
        # 4. Check Per-Trade Max Loss (Absolute)
        estimated_loss = estimated_cost * 0.10  # Assume 10% max stop loss
        if estimated_loss > self.config.per_trade_max_loss_absolute:
            return False, f"Potential loss ₹{estimated_loss:.2f} exceeds per-trade limit ₹{self.config.per_trade_max_loss_absolute}."
        
        # 5. Check Capital Exhaustion
        if self.daily_stats.current_capital < self.config.min_capital_threshold:
            return False, f"Capital exhausted. Available ₹{self.daily_stats.current_capital:.2f} < minimum ₹{self.config.min_capital_threshold}."

        return True, "Risk Check Passed"

    def record_trade_entry(self):
        """Call this when a trade actually enters to increment count"""
        self.daily_stats.total_trades += 1
