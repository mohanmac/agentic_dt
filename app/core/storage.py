"""
SQLite-based storage layer for persisting trading data.
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from contextlib import contextmanager

from app.core.config import settings
from app.core.schemas import (
    MarketSnapshot, TradeIntent, RiskApproval, PaperOrder,
    Position, DailyState, StrategyType, OrderStatus, TradeSide
)
from app.core.utils import logger, get_today_date_str


class Storage:
    """SQLite storage manager for all trading data."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.get_db_file()
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}", exc_info=True)
            raise
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Market snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    ltp REAL NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    vwap REAL,
                    regime TEXT,
                    trend_direction TEXT,
                    volatility_percentile REAL,
                    liquidity_score REAL,
                    metrics_json TEXT
                )
            """)
            
            # Trade intents table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_intents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    entry_price REAL,
                    quantity INTEGER NOT NULL,
                    stop_loss_price REAL NOT NULL,
                    target_price REAL,
                    confidence_score REAL NOT NULL,
                    rationale TEXT,
                    expected_risk_rupees REAL NOT NULL,
                    invalidation_conditions TEXT,
                    market_snapshot_id INTEGER,
                    status TEXT DEFAULT 'pending'
                )
            """)
            
            # Risk approvals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    adjusted_quantity INTEGER,
                    rejection_reason TEXT,
                    guardrail_flags TEXT,
                    safe_mode_active INTEGER DEFAULT 0,
                    hitl_required INTEGER DEFAULT 0,
                    hitl_reason TEXT,
                    hitl_status TEXT DEFAULT 'pending',
                    remaining_loss_budget REAL,
                    trades_today INTEGER,
                    current_strategy TEXT,
                    FOREIGN KEY (intent_id) REFERENCES trade_intents(id)
                )
            """)
            
            # Paper orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_orders (
                    order_id TEXT PRIMARY KEY,
                    intent_id INTEGER,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    order_type TEXT NOT NULL,
                    limit_price REAL,
                    stop_price REAL,
                    status TEXT NOT NULL,
                    fill_price REAL,
                    fill_timestamp TEXT,
                    slippage REAL,
                    brokerage REAL,
                    simulated_ltp REAL,
                    FOREIGN KEY (intent_id) REFERENCES trade_intents(id)
                )
            """)
            
            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    avg_price REAL NOT NULL,
                    current_price REAL,
                    unrealized_pnl REAL DEFAULT 0,
                    entry_order_id TEXT,
                    stop_loss_price REAL,
                    target_price REAL,
                    strategy TEXT,
                    opened_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL
                )
            """)
            
            # Daily state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_state (
                    date TEXT PRIMARY KEY,
                    realized_pnl REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    loss_budget_remaining REAL NOT NULL,
                    max_daily_loss REAL NOT NULL,
                    safe_mode INTEGER DEFAULT 0,
                    active_strategy TEXT,
                    strategy_switched_at TEXT,
                    trades_count INTEGER DEFAULT 0,
                    max_trades INTEGER NOT NULL,
                    hitl_approvals_pending INTEGER DEFAULT 0,
                    hitl_approvals_given INTEGER DEFAULT 0
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_time ON market_snapshots(symbol, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_intents_timestamp ON trade_intents(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_timestamp ON paper_orders(timestamp)")
            
            logger.info("Database initialized", extra={'extra_data': {'db_path': str(self.db_path)}})
    
    # Market Snapshots
    def save_market_snapshot(self, snapshot: MarketSnapshot) -> int:
        """Save market snapshot and return ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Serialize additional metrics
            metrics = {
                'sma_20': snapshot.sma_20,
                'sma_50': snapshot.sma_50,
                'bb_upper': snapshot.bb_upper,
                'bb_middle': snapshot.bb_middle,
                'bb_lower': snapshot.bb_lower,
                'bb_width': snapshot.bb_width,
                'atr': snapshot.atr,
                'opening_range_high': snapshot.opening_range_high,
                'opening_range_low': snapshot.opening_range_low,
                'avg_volume_20d': snapshot.avg_volume_20d
            }
            
            cursor.execute("""
                INSERT INTO market_snapshots (
                    timestamp, symbol, ltp, open, high, low, close, volume,
                    vwap, regime, trend_direction, volatility_percentile,
                    liquidity_score, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.timestamp.isoformat(),
                snapshot.symbol,
                snapshot.ltp,
                snapshot.open,
                snapshot.high,
                snapshot.low,
                snapshot.close,
                snapshot.volume,
                snapshot.vwap,
                snapshot.regime.value,
                snapshot.trend_direction,
                snapshot.volatility_percentile,
                snapshot.liquidity_score,
                json.dumps(metrics)
            ))
            
            return cursor.lastrowid
    
    # Trade Intents
    def save_trade_intent(self, intent: TradeIntent) -> int:
        """Save trade intent and return ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO trade_intents (
                    timestamp, strategy_id, symbol, side, entry_type,
                    entry_price, quantity, stop_loss_price, target_price,
                    confidence_score, rationale, expected_risk_rupees,
                    invalidation_conditions, market_snapshot_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                intent.timestamp.isoformat(),
                intent.strategy_id.value,
                intent.symbol,
                intent.side.value,
                intent.entry_type.value,
                intent.entry_price,
                intent.quantity,
                intent.stop_loss_price,
                intent.target_price,
                intent.confidence_score,
                intent.rationale,
                intent.expected_risk_rupees,
                json.dumps(intent.invalidation_conditions),
                intent.market_snapshot_id,
                'pending'
            ))
            
            return cursor.lastrowid
    
    def update_intent_status(self, intent_id: int, status: str):
        """Update trade intent status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE trade_intents SET status = ? WHERE id = ?",
                (status, intent_id)
            )
    
    # Risk Approvals
    def save_approval(self, approval: RiskApproval) -> int:
        """Save risk approval decision."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO approvals (
                    intent_id, timestamp, approved, adjusted_quantity,
                    rejection_reason, guardrail_flags, safe_mode_active,
                    hitl_required, hitl_reason, hitl_status,
                    remaining_loss_budget, trades_today, current_strategy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                approval.intent_id,
                approval.timestamp.isoformat(),
                1 if approval.approved else 0,
                approval.adjusted_quantity,
                approval.rejection_reason,
                json.dumps(approval.guardrail_flags),
                1 if approval.safe_mode_active else 0,
                1 if approval.hitl_required else 0,
                approval.hitl_reason,
                approval.hitl_status,
                approval.remaining_loss_budget,
                approval.trades_today,
                approval.current_strategy.value if approval.current_strategy else None
            ))
            
            return cursor.lastrowid
    
    def update_hitl_status(self, approval_id: int, status: str):
        """Update HITL approval status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE approvals SET hitl_status = ? WHERE id = ?",
                (status, approval_id)
            )
    
    # Paper Orders
    def save_paper_order(self, order: PaperOrder):
        """Save paper order."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO paper_orders (
                    order_id, intent_id, timestamp, symbol, side, quantity,
                    order_type, limit_price, stop_price, status, fill_price,
                    fill_timestamp, slippage, brokerage, simulated_ltp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id,
                order.intent_id,
                order.timestamp.isoformat(),
                order.symbol,
                order.side.value,
                order.quantity,
                order.order_type.value,
                order.limit_price,
                order.stop_price,
                order.status.value,
                order.fill_price,
                order.fill_timestamp.isoformat() if order.fill_timestamp else None,
                order.slippage,
                order.brokerage,
                order.simulated_ltp
            ))
    
    # Positions
    def save_position(self, position: Position):
        """Save or update position."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO positions (
                    symbol, quantity, avg_price, current_price, unrealized_pnl,
                    entry_order_id, stop_loss_price, target_price, strategy,
                    opened_at, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.symbol,
                position.quantity,
                position.avg_price,
                position.current_price,
                position.unrealized_pnl,
                position.entry_order_id,
                position.stop_loss_price,
                position.target_price,
                position.strategy.value if position.strategy else None,
                position.opened_at.isoformat(),
                position.last_updated.isoformat()
            ))
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position by symbol."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            
            if row:
                return Position(
                    symbol=row['symbol'],
                    quantity=row['quantity'],
                    avg_price=row['avg_price'],
                    current_price=row['current_price'],
                    unrealized_pnl=row['unrealized_pnl'],
                    entry_order_id=row['entry_order_id'],
                    stop_loss_price=row['stop_loss_price'],
                    target_price=row['target_price'],
                    strategy=StrategyType(row['strategy']) if row['strategy'] else None,
                    opened_at=datetime.fromisoformat(row['opened_at']),
                    last_updated=datetime.fromisoformat(row['last_updated'])
                )
            return None
    
    def get_all_positions(self) -> List[Position]:
        """Get all open positions."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE quantity != 0")
            rows = cursor.fetchall()
            
            positions = []
            for row in rows:
                positions.append(Position(
                    symbol=row['symbol'],
                    quantity=row['quantity'],
                    avg_price=row['avg_price'],
                    current_price=row['current_price'],
                    unrealized_pnl=row['unrealized_pnl'],
                    entry_order_id=row['entry_order_id'],
                    stop_loss_price=row['stop_loss_price'],
                    target_price=row['target_price'],
                    strategy=StrategyType(row['strategy']) if row['strategy'] else None,
                    opened_at=datetime.fromisoformat(row['opened_at']),
                    last_updated=datetime.fromisoformat(row['last_updated'])
                ))
            
            return positions
    
    def delete_position(self, symbol: str):
        """Delete position (when closed)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
    
    # Daily State
    def get_or_create_daily_state(self, date: Optional[str] = None) -> DailyState:
        """Get or create daily state for given date."""
        if date is None:
            date = get_today_date_str()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_state WHERE date = ?", (date,))
            row = cursor.fetchone()
            
            if row:
                return DailyState(
                    date=row['date'],
                    realized_pnl=row['realized_pnl'],
                    unrealized_pnl=row['unrealized_pnl'],
                    total_pnl=row['total_pnl'],
                    loss_budget_remaining=row['loss_budget_remaining'],
                    max_daily_loss=row['max_daily_loss'],
                    safe_mode=bool(row['safe_mode']),
                    active_strategy=StrategyType(row['active_strategy']) if row['active_strategy'] else None,
                    strategy_switched_at=datetime.fromisoformat(row['strategy_switched_at']) if row['strategy_switched_at'] else None,
                    trades_count=row['trades_count'],
                    max_trades=row['max_trades'],
                    hitl_approvals_pending=row['hitl_approvals_pending'],
                    hitl_approvals_given=row['hitl_approvals_given']
                )
            else:
                # Create new daily state
                state = DailyState(
                    date=date,
                    loss_budget_remaining=settings.MAX_DAILY_LOSS,
                    max_daily_loss=settings.MAX_DAILY_LOSS,
                    max_trades=settings.MAX_TRADES_PER_DAY
                )
                self.save_daily_state(state)
                return state
    
    def save_daily_state(self, state: DailyState):
        """Save or update daily state."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO daily_state (
                    date, realized_pnl, unrealized_pnl, total_pnl,
                    loss_budget_remaining, max_daily_loss, safe_mode,
                    active_strategy, strategy_switched_at, trades_count,
                    max_trades, hitl_approvals_pending, hitl_approvals_given
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state.date,
                state.realized_pnl,
                state.unrealized_pnl,
                state.total_pnl,
                state.loss_budget_remaining,
                state.max_daily_loss,
                1 if state.safe_mode else 0,
                state.active_strategy.value if state.active_strategy else None,
                state.strategy_switched_at.isoformat() if state.strategy_switched_at else None,
                state.trades_count,
                state.max_trades,
                state.hitl_approvals_pending,
                state.hitl_approvals_given
            ))
    
    def calculate_total_pnl(self) -> tuple[float, float, float]:
        """
        Calculate total PnL from positions.
        
        Returns:
            (realized_pnl, unrealized_pnl, total_pnl)
        """
        positions = self.get_all_positions()
        unrealized = sum(p.unrealized_pnl for p in positions)
        
        # Get realized PnL from today's state
        state = self.get_or_create_daily_state()
        realized = state.realized_pnl
        
        return realized, unrealized, realized + unrealized


# Global storage instance
storage = Storage()
