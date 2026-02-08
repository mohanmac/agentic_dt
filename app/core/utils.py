"""
Utility functions for logging, time validation, and helper operations.
"""
import json
import logging
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, Optional
from functools import wraps
import traceback

from app.core.config import settings


# Configure structured logging
def setup_logging():
    """Setup structured JSON logging with file and console handlers."""
    logs_dir = settings.get_logs_dir()
    
    # Create formatters
    class JSONFormatter(logging.Formatter):
        """Custom JSON formatter that excludes secrets."""
        
        SENSITIVE_KEYS = {
            'api_key', 'api_secret', 'access_token', 'password', 
            'secret', 'token', 'authorization'
        }
        
        def format(self, record):
            log_data = {
                'timestamp': datetime.now().isoformat(),
                'level': record.levelname,
                'module': record.module,
                'function': record.funcName,
                'message': record.getMessage(),
            }
            
            # Add extra fields if present
            if hasattr(record, 'extra_data'):
                # Filter out sensitive keys
                filtered_data = self._filter_sensitive(record.extra_data)
                log_data['data'] = filtered_data
            
            # Add exception info if present
            if record.exc_info:
                log_data['exception'] = traceback.format_exception(*record.exc_info)
            
            return json.dumps(log_data)
        
        def _filter_sensitive(self, data: Dict[str, Any]) -> Dict[str, Any]:
            """Remove sensitive keys from log data."""
            if not isinstance(data, dict):
                return data
            
            filtered = {}
            for key, value in data.items():
                if any(sensitive in key.lower() for sensitive in self.SENSITIVE_KEYS):
                    filtered[key] = "***REDACTED***"
                elif isinstance(value, dict):
                    filtered[key] = self._filter_sensitive(value)
                else:
                    filtered[key] = value
            return filtered
    
    # Console formatter (simpler)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    if settings.LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # File handlers
    if settings.LOG_TO_FILE:
        # Main app log (JSON)
        app_handler = logging.FileHandler(logs_dir / 'app.log')
        app_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(app_handler)
        
        # Error log (JSON)
        error_handler = logging.FileHandler(logs_dir / 'errors.log')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(error_handler)
    
    return root_logger


# Initialize logger
logger = setup_logging()


def log_event(event_type: str, data: Optional[Dict[str, Any]] = None, level: str = "INFO"):
    """
    Log a structured event.
    
    Args:
        event_type: Type of event (e.g., 'trade_intent_generated')
        data: Additional data to log
        level: Log level (INFO, WARNING, ERROR, etc.)
    """
    log_func = getattr(logger, level.lower(), logger.info)
    
    # Create log record with extra data
    extra_data = data or {}
    log_record = logging.LogRecord(
        name=logger.name,
        level=getattr(logging, level),
        pathname='',
        lineno=0,
        msg=event_type,
        args=(),
        exc_info=None
    )
    log_record.extra_data = extra_data
    
    logger.handle(log_record)


def is_trading_hours() -> tuple[bool, Optional[str]]:
    """
    Check if current time is within trading hours.
    
    Returns:
        (is_valid, reason) tuple
    """
    now = datetime.now()
    current_time = now.time()
    
    # Trading hours: 9:15 AM to 3:15 PM IST
    start_time = time(
        settings.TRADING_START_HOUR,
        settings.TRADING_START_MINUTE
    )
    end_time = time(
        settings.TRADING_END_HOUR,
        settings.TRADING_END_MINUTE
    )
    
    if current_time < start_time:
        return False, f"Market not open yet (opens at {start_time})"
    if current_time > end_time:
        return False, f"Market closed (closed at {end_time})"
    
    return True, None


def is_exit_only_time() -> bool:
    """
    Check if we're in exit-only mode (last 15 minutes of trading).
    
    Returns:
        True if in exit-only mode
    """
    now = datetime.now()
    current_time = now.time()
    
    exit_only_time = time(
        settings.EXIT_ONLY_HOUR,
        settings.EXIT_ONLY_MINUTE
    )
    
    return current_time >= exit_only_time


def format_price(price: float, decimals: int = 2) -> str:
    """Format price with rupee symbol."""
    return f"₹{price:,.{decimals}f}"


def format_pnl(pnl: float) -> str:
    """Format PnL with color indicator."""
    sign = "+" if pnl >= 0 else ""
    return f"{sign}{format_price(pnl)}"


def calculate_slippage(price: float, side: str, slippage_percent: Optional[float] = None) -> float:
    """
    Calculate slippage for paper trading.
    
    Args:
        price: Base price
        side: 'buy' or 'sell'
        slippage_percent: Slippage percentage (default from settings)
    
    Returns:
        Price with slippage applied
    """
    if slippage_percent is None:
        slippage_percent = settings.PAPER_SLIPPAGE_PERCENT
    
    slippage_factor = slippage_percent / 100.0
    
    if side.lower() == 'buy':
        # Adverse slippage for buy = higher price
        return price * (1 + slippage_factor)
    else:
        # Adverse slippage for sell = lower price
        return price * (1 - slippage_factor)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division that returns default on division by zero."""
    try:
        return numerator / denominator if denominator != 0 else default
    except (TypeError, ZeroDivisionError):
        return default


def error_handler(func):
    """Decorator for error handling and logging."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(
                f"Error in {func.__name__}: {str(e)}",
                exc_info=True,
                extra={'extra_data': {'function': func.__name__, 'error': str(e)}}
            )
            raise
    return wrapper


def validate_symbol(symbol: str) -> bool:
    """
    Validate if symbol is in allowed trading list.
    
    Args:
        symbol: Stock symbol to validate
    
    Returns:
        True if symbol is allowed
    """
    allowed_symbols = settings.get_trading_symbols()
    return symbol.upper() in [s.upper() for s in allowed_symbols]


def get_today_date_str() -> str:
    """Get today's date as YYYY-MM-DD string."""
    return datetime.now().strftime("%Y-%m-%d")


def timestamp_to_str(dt: datetime) -> str:
    """Convert datetime to ISO format string."""
    return dt.isoformat()


def str_to_timestamp(dt_str: str) -> datetime:
    """Convert ISO format string to datetime."""
    return datetime.fromisoformat(dt_str)


class TradingTimer:
    """Context manager for timing operations."""
    
    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        logger.debug(f"Starting: {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()
        
        if exc_type is None:
            logger.debug(f"Completed: {self.operation_name} ({duration:.2f}s)")
        else:
            logger.error(f"Failed: {self.operation_name} ({duration:.2f}s)")
        
        return False  # Don't suppress exceptions


# Initialize logging on module import
logger.info("Utilities module initialized", extra={'extra_data': {'log_level': settings.LOG_LEVEL}})
