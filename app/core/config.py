"""
Configuration management for DayTradingPaperBot.
Loads all settings from environment variables with validation.
"""
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import List
import os
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Zerodha Kite Connect
    KITE_API_KEY: str = Field(..., description="Zerodha API Key")
    KITE_API_SECRET: str = Field(..., description="Zerodha API Secret")
    KITE_REDIRECT_URL: str = Field(default="http://127.0.0.1:8000/callback")
    
    # Ollama Configuration
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")
    OLLAMA_MODEL: str = Field(default="qwen2.5:7b")

    # Google Gemini Configuration
    GOOGLE_API_KEY: str = Field(default="", description="Google API Key for Gemini")
    GOOGLE_MODEL: str = Field(default="gemini-1.5-pro", description="Gemini model name")
    
    # LLM Provider Selection
    LLM_PROVIDER: str = Field(default="ollama", description="LLM provider: 'ollama' or 'google'")
    
    # Trading Configuration
    DAILY_CAPITAL: float = Field(default=2000.0, description="Daily trading capital in INR")
    MAX_DAILY_LOSS: float = Field(default=300.0, description="Maximum daily loss in INR")
    MAX_TRADES_PER_DAY: int = Field(default=5, description="Maximum number of trades per day")
    PER_TRADE_MAX_LOSS_PERCENT: float = Field(default=50.0, description="Max % of remaining loss budget per trade")
    PER_TRADE_MAX_LOSS_ABSOLUTE: float = Field(default=500.0, description="Absolute max loss per trade in INR")
    MIN_CAPITAL_THRESHOLD: float = Field(default=600.0, description="Stop trading if capital drops below this")
    
    # Trading Hours (IST)
    TRADING_START_HOUR: int = Field(default=9)
    TRADING_START_MINUTE: int = Field(default=15)
    TRADING_END_HOUR: int = Field(default=15)
    TRADING_END_MINUTE: int = Field(default=15)
    EXIT_ONLY_HOUR: int = Field(default=15)
    EXIT_ONLY_MINUTE: int = Field(default=0)
    
    # Feature Flags
    ENABLE_LIVE_TRADING: bool = Field(default=False, description="Enable live trading (DANGEROUS)")
    REQUIRE_HITL_FIRST_N_TRADES: int = Field(default=2, description="First N trades require HITL approval")
    HITL_CONFIDENCE_THRESHOLD: float = Field(default=0.7, description="Confidence below this requires HITL")
    STRATEGY_SWITCH_COOLDOWN_MINUTES: int = Field(default=20)
    STRATEGY_SWITCH_MIN_IMPROVEMENT: float = Field(default=0.15, description="Min confidence improvement to switch")
    
    # Paper Trading Simulation
    PAPER_SLIPPAGE_PERCENT: float = Field(default=0.05, description="Slippage % for paper trades")
    PAPER_BROKERAGE_PER_ORDER: float = Field(default=20.0, description="Brokerage in INR per order")
    
    # Additional Guardrails - Position & Exposure
    MAX_POSITION_SIZE_PERCENT: float = Field(default=40.0, description="Max % of capital in single stock")
    MAX_PORTFOLIO_EXPOSURE_PERCENT: float = Field(default=70.0, description="Max % of capital deployed")
    MAX_SECTOR_EXPOSURE_PERCENT: float = Field(default=50.0, description="Max % in correlated stocks")
    MAX_OPEN_POSITIONS: int = Field(default=2, description="Max concurrent positions")
    
    # Time-Based Guardrails
    AVOID_FIRST_MINUTES: int = Field(default=15, description="Avoid trading first N minutes")
    AVOID_LAST_MINUTES: int = Field(default=15, description="Avoid trading last N minutes")
    MIN_HOLD_TIME_MINUTES: int = Field(default=5, description="Min time between trades on same symbol")
    MAX_POSITION_AGE_HOURS: int = Field(default=4, description="Force review after N hours")
    FORCE_EXIT_TIME_HOUR: int = Field(default=15, description="Force close all by this hour")
    FORCE_EXIT_TIME_MINUTE: int = Field(default=0, description="Force close all by this minute")
    
    # Drawdown & Streak Protection
    MAX_DRAWDOWN_PERCENT: float = Field(default=15.0, description="Max drawdown from peak")
    MAX_CONSECUTIVE_LOSSES: int = Field(default=3, description="Stop after N consecutive losses")
    TRAILING_STOP_ACTIVATION_PERCENT: float = Field(default=2.0, description="Activate trailing stop at % profit")
    TRAILING_STOP_DISTANCE_PERCENT: float = Field(default=1.0, description="Trail stop at % from peak")
    
    # Market Condition Filters
    MAX_VIX_THRESHOLD: float = Field(default=30.0, description="Pause trading if VIX > threshold")
    MAX_SPREAD_PERCENT: float = Field(default=0.5, description="Max bid-ask spread %")
    MIN_VOLUME_MULTIPLIER: float = Field(default=1.5, description="Require volume > N * average")
    MAX_GAP_PERCENT: float = Field(default=5.0, description="Special handling for gaps > %")
    
    # Order Execution Safeguards
    MAX_ORDERS_PER_MINUTE: int = Field(default=10, description="Rate limit orders")
    MAX_PRICE_DEVIATION_PERCENT: float = Field(default=1.0, description="Reject if price moved > %")
    ORDER_TIMEOUT_SECONDS: int = Field(default=30, description="Cancel unfilled orders after N seconds")
    
    # Hard Constraints
    MAX_STOP_LOSS_PERCENT: float = Field(default=10.0, description="Hard stop loss limit")
    SLIPPAGE_BUFFER_PERCENT: float = Field(default=0.1, description="Fixed slippage buffer")
    ABRUPT_MOVE_THRESHOLD_PERCENT: float = Field(default=2.0, description="Filter abrupt moves")
    
    # Logging
    LOG_LEVEL: str = Field(default="INFO")
    LOG_TO_CONSOLE: bool = Field(default=True)
    LOG_TO_FILE: bool = Field(default=True)
    
    # Trading Parameters
    TRADING_SYMBOLS: str = Field(default="HINDCOPPER,MCX,LAURUSLABS,NAVINFLUOR,RADICO")
    MAX_TRADES_PER_DAY: int = Field(default=5)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
    
    @validator("MAX_DAILY_LOSS")
    def validate_max_loss(cls, v, values):
        """Ensure max daily loss is reasonable."""
        if "DAILY_CAPITAL" in values and v > values["DAILY_CAPITAL"]:
            raise ValueError("MAX_DAILY_LOSS cannot exceed DAILY_CAPITAL")
        return v
    
    @validator("HITL_CONFIDENCE_THRESHOLD")
    def validate_confidence_threshold(cls, v):
        """Ensure confidence threshold is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("HITL_CONFIDENCE_THRESHOLD must be between 0 and 1")
        return v
    
    def get_trading_symbols(self) -> List[str]:
        """Parse trading symbols from comma-separated string."""
        return [s.strip() for s in self.TRADING_SYMBOLS.split(",") if s.strip()]
    
    def get_project_root(self) -> Path:
        """Get project root directory."""
        return Path(__file__).parent.parent.parent
    
    def get_data_dir(self) -> Path:
        """Get data directory path."""
        data_dir = self.get_project_root() / "data"
        data_dir.mkdir(exist_ok=True)
        return data_dir
    
    def get_logs_dir(self) -> Path:
        """Get logs directory path."""
        logs_dir = self.get_project_root() / "logs"
        logs_dir.mkdir(exist_ok=True)
        return logs_dir
    
    def get_token_file(self) -> Path:
        """Get token storage file path."""
        return self.get_data_dir() / "tokens.json"
    
    def get_db_file(self) -> Path:
        """Get database file path."""
        return self.get_data_dir() / "paper_ledger.db"


# Global settings instance
settings = Settings()


# Validate critical settings on import
def validate_settings():
    """Validate critical settings and warn about security issues."""
    if settings.ENABLE_LIVE_TRADING:
        print("⚠️  WARNING: LIVE TRADING IS ENABLED! Real money at risk!")
        print("⚠️  Ensure you have tested thoroughly in paper mode first.")
    
    if not settings.KITE_API_KEY or settings.KITE_API_KEY == "your_api_key_here":
        print("⚠️  WARNING: KITE_API_KEY not configured properly!")
        print("   Please set KITE_API_KEY in .env file")
    
    if not settings.KITE_API_SECRET or settings.KITE_API_SECRET == "your_api_secret_here":
        print("⚠️  WARNING: KITE_API_SECRET not configured properly!")
        print("   Please set KITE_API_SECRET in .env file")
    
    print(f"✓ Configuration loaded successfully")
    print(f"  - Trading Mode: {'LIVE' if settings.ENABLE_LIVE_TRADING else 'PAPER'}")
    print(f"  - Daily Capital: ₹{settings.DAILY_CAPITAL}")
    print(f"  - Max Daily Loss: ₹{settings.MAX_DAILY_LOSS}")
    print(f"  - Ollama Model: {settings.OLLAMA_MODEL}")
    print(f"  - Trading Symbols: {', '.join(settings.get_trading_symbols())}")


if __name__ == "__main__":
    validate_settings()
