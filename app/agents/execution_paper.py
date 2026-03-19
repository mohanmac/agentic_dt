"""
Agent 3: ExecutionPaperAgent
Handles both paper and live trading execution through broker abstraction.
Simulates order fills with realistic slippage, manages positions, and monitors stop-loss/targets.
"""
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.core.schemas import (
    TradeIntent, RiskApproval, PaperOrder, Position,
    OrderStatus, TradeSide, OrderType, StrategyType
)
from app.core.config import settings
from app.core.storage import storage
from app.core.market_data import market_data
from app.core.utils import logger, log_event, calculate_slippage


class ExecutionPaperAgent:
    """
    Execution agent for paper and live trading.
    
    Responsibilities:
    - Route execution to paper or live broker
    - Manage paper portfolio and positions
    - Monitor stop-loss and target levels
    - Calculate PnL
    - Prevent duplicate orders
    """
    
    def __init__(self, broker=None):
        """
        Initialize execution agent with optional broker instance.
        
        Args:
            broker: Broker instance (PaperBroker or LiveBroker). 
                   If None, creates appropriate broker based on settings.
        """
        self.slippage_percent = settings.PAPER_SLIPPAGE_PERCENT
        self.brokerage_per_order = settings.PAPER_BROKERAGE_PER_ORDER
        self.enable_live_trading = settings.ENABLE_LIVE_TRADING
        
        # Set broker - use provided or create default
        if broker:
            self.broker = broker
        else:
            if settings.ENABLE_LIVE_TRADING:
                from app.core.live_broker import LiveBroker
                self.broker = LiveBroker()
                self.broker_type = "LIVE"
                logger.info("✓ ExecutionPaperAgent initialized with LiveBroker")
            else:
                from app.core.paper_broker import PaperBroker
                self.broker = PaperBroker()
                self.broker_type = "PAPER"
                logger.info("✓ ExecutionPaperAgent initialized with PaperBroker")
        
        # Track execution mode
        self.broker_type = "LIVE" if settings.ENABLE_LIVE_TRADING else "PAPER"
        
        # Track recent order hashes to prevent duplicates
        self.recent_order_hashes: Dict[str, datetime] = {}
    
    def execute(self, intent: TradeIntent, approval: RiskApproval) -> Optional[PaperOrder]:
        """
        Execute trade intent (paper or live).
        
        Args:
            intent: Approved trade intent
            approval: Risk approval with adjusted quantity
        
        Returns:
            PaperOrder if executed, None if failed
        """
        if not approval.approved:
            logger.error("Cannot execute unapproved trade intent")
            return None
        
        # Check for duplicate
        if self._is_duplicate(intent):
            logger.warning(f"Duplicate order detected for {intent.symbol}, skipping")
            return None
        
        # Get quantity (use adjusted if available)
        quantity = approval.adjusted_quantity or intent.quantity
        
        # Get current market price
        try:
            ltp_data = market_data.get_ltp([intent.symbol])
            current_ltp = ltp_data.get(intent.symbol)
            
            if current_ltp is None:
                logger.error(f"Could not fetch LTP for {intent.symbol}")
                return None
        
        except Exception as e:
            logger.error(f"Error fetching LTP: {e}")
            return None
        
        # Route to appropriate broker
        if self.broker_type == "LIVE":
            order = self._execute_live(intent, quantity, current_ltp)
        else:
            order = self._execute_paper(intent, quantity, current_ltp)
        
        if order and order.status == OrderStatus.FILLED:
            # Update position
            self._update_position(order, intent)
            
            # Update daily state
            self._update_daily_state(intent)
            
            log_event(f"{self.broker_type.lower()}_order_filled", {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": order.quantity,
                "fill_price": order.fill_price if hasattr(order, 'fill_price') else "PENDING",
                "broker": self.broker_type
            })
        
        # Save order to database
        storage.save_paper_order(order)
        
        # Track completion for monitoring
        storage.record_trade_completion(intent.symbol, quantity, order.order_id if order else None)
        
        return order
    
    def _execute_paper(self, intent: TradeIntent, quantity: int, ltp: float) -> Optional[PaperOrder]:
        """Execute trade on paper broker (simulation)."""
        return self._simulate_fill(intent, quantity, ltp)
    
    def _execute_live(self, intent: TradeIntent, quantity: int, ltp: float) -> Optional[PaperOrder]:
        """
        Execute trade on live broker (real Zerodha orders).
        Maps TradeIntent to Zerodha order format and returns PaperOrder wrapper.
        """
        try:
            # Map side
            transaction_type = "BUY" if intent.side == TradeSide.BUY else "SELL"
            
            # Map order type
            order_type = "LIMIT" if intent.entry_type == OrderType.LIMIT else "MARKET"
            
            # Determine price
            price = intent.entry_price if order_type == "LIMIT" else ltp
            
            # Place order via live broker
            logger.info(f"Placing LIVE order: {transaction_type} {quantity} {intent.symbol} @ ₹{price:.2f}")
            
            order = self.broker.place_order(
                symbol=intent.symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                price=price,
                order_type=order_type,
                strategy_name=intent.strategy_id.value if hasattr(intent.strategy_id, 'value') else str(intent.strategy_id)
            )
            
            logger.info(f"✓ LIVE order placed: {order.order_id}")
            return order
            
        except Exception as e:
            logger.error(f"Live order execution failed: {e}")
            log_event("live_order_failed", {
                "symbol": intent.symbol,
                "error": str(e),
                "broker": "zerodha"
            }, level="ERROR")
            return None
    
    def _simulate_fill(self, intent: TradeIntent, quantity: int, ltp: float) -> PaperOrder:
        """
        Simulate order fill with slippage and brokerage.
        
        Args:
            intent: Trade intent
            quantity: Order quantity
            ltp: Last traded price
        
        Returns:
            PaperOrder with fill details
        """
        order_id = str(uuid.uuid4())
        
        # Determine fill price based on order type
        if intent.entry_type == OrderType.MARKET:
            # Market order - fill immediately with slippage
            fill_price = calculate_slippage(ltp, intent.side.value, self.slippage_percent)
            slippage = abs(fill_price - ltp)
            status = OrderStatus.FILLED
            fill_timestamp = datetime.now()
        
        elif intent.entry_type == OrderType.LIMIT:
            # Limit order - fill only if price is favorable
            limit_price = intent.entry_price
            
            if intent.side == TradeSide.BUY and ltp <= limit_price:
                fill_price = min(ltp, limit_price)
                slippage = 0.0
                status = OrderStatus.FILLED
                fill_timestamp = datetime.now()
            elif intent.side == TradeSide.SELL and ltp >= limit_price:
                fill_price = max(ltp, limit_price)
                slippage = 0.0
                status = OrderStatus.FILLED
                fill_timestamp = datetime.now()
            else:
                # Price not reached, order pending
                fill_price = None
                slippage = None
                status = OrderStatus.PENDING
                fill_timestamp = None
        
        else:  # STOP or STOP_LIMIT
            # For simplicity, treat as market order for now
            fill_price = calculate_slippage(ltp, intent.side.value, self.slippage_percent)
            slippage = abs(fill_price - ltp)
            status = OrderStatus.FILLED
            fill_timestamp = datetime.now()
        
        # Create paper order
        order = PaperOrder(
            order_id=order_id,
            intent_id=intent.market_snapshot_id,  # Link to intent if saved
            symbol=intent.symbol,
            side=intent.side,
            quantity=quantity,
            order_type=intent.entry_type,
            limit_price=intent.entry_price,
            status=status,
            fill_price=fill_price,
            fill_timestamp=fill_timestamp,
            slippage=slippage,
            brokerage=self.brokerage_per_order if status == OrderStatus.FILLED else None,
            simulated_ltp=ltp
        )
        
        logger.info(f"Paper order simulated: {order.side.value} {order.quantity} {order.symbol} @ ₹{fill_price:.2f} (LTP: ₹{ltp:.2f}, slippage: ₹{slippage:.2f})")
        
        return order
    
    def _update_position(self, order: PaperOrder, intent: TradeIntent):
        """
        Update position after order fill.
        
        Args:
            order: Filled paper order
            intent: Original trade intent
        """
        # Get existing position
        position = storage.get_position(order.symbol)
        
        if position is None:
            # Create new position
            position = Position(
                symbol=order.symbol,
                quantity=order.quantity if order.side == TradeSide.BUY else -order.quantity,
                avg_price=order.fill_price,
                current_price=order.fill_price,
                entry_order_id=order.order_id,
                stop_loss_price=intent.stop_loss_price,
                target_price=intent.target_price,
                strategy=intent.strategy_id
            )
            
            logger.info(f"New position opened: {position.quantity} {position.symbol} @ ₹{position.avg_price:.2f}")
        
        else:
            # Update existing position
            if order.side == TradeSide.BUY:
                # Adding to long or reducing short
                new_quantity = position.quantity + order.quantity
                
                if position.quantity >= 0:  # Was long or flat
                    # Average up
                    total_cost = (position.avg_price * position.quantity) + (order.fill_price * order.quantity)
                    position.avg_price = total_cost / new_quantity if new_quantity != 0 else order.fill_price
                
                position.quantity = new_quantity
            
            else:  # SELL
                # Adding to short or reducing long
                new_quantity = position.quantity - order.quantity
                
                if position.quantity <= 0:  # Was short or flat
                    # Average down
                    total_cost = (position.avg_price * abs(position.quantity)) + (order.fill_price * order.quantity)
                    position.avg_price = total_cost / abs(new_quantity) if new_quantity != 0 else order.fill_price
                
                position.quantity = new_quantity
            
            position.last_updated = datetime.now()
            
            logger.info(f"Position updated: {position.quantity} {position.symbol} @ ₹{position.avg_price:.2f}")
        
        # Save position
        if position.quantity == 0:
            # Position closed
            storage.delete_position(position.symbol)
            logger.info(f"Position closed: {position.symbol}")
        else:
            storage.save_position(position)
    
    def _update_daily_state(self, intent: TradeIntent):
        """Update daily state after trade execution."""
        daily_state = storage.get_or_create_daily_state()
        
        # Increment trade count
        daily_state.trades_count += 1
        
        # Update active strategy
        daily_state.active_strategy = intent.strategy_id
        
        # If strategy switched, record timestamp
        if daily_state.active_strategy != intent.strategy_id:
            daily_state.strategy_switched_at = datetime.now()
        
        storage.save_daily_state(daily_state)
    
    def monitor_positions(self) -> List[Dict[str, Any]]:
        """
        Monitor all open positions for stop-loss and target hits.
        
        Returns:
            List of exit actions taken
        """
        positions = storage.get_all_positions()
        
        if not positions:
            return []
        
        # Get current prices
        symbols = [p.symbol for p in positions]
        try:
            ltp_data = market_data.get_ltp(symbols)
        except Exception as e:
            logger.error(f"Error fetching LTP for position monitoring: {e}")
            return []
        
        exit_actions = []
        
        for position in positions:
            current_price = ltp_data.get(position.symbol)
            
            if current_price is None:
                logger.warning(f"No LTP data for {position.symbol}, skipping monitoring")
                continue
            
            # Update position PnL
            position.update_pnl(current_price)
            storage.save_position(position)
            
            # Check stop-loss
            if position.stop_loss_price:
                if position.quantity > 0 and current_price <= position.stop_loss_price:
                    # Long position hit stop-loss
                    exit_actions.append(self._exit_position(position, current_price, "stop_loss"))
                
                elif position.quantity < 0 and current_price >= position.stop_loss_price:
                    # Short position hit stop-loss
                    exit_actions.append(self._exit_position(position, current_price, "stop_loss"))
            
            # Check target
            if position.target_price:
                if position.quantity > 0 and current_price >= position.target_price:
                    # Long position hit target
                    exit_actions.append(self._exit_position(position, current_price, "target"))
                
                elif position.quantity < 0 and current_price <= position.target_price:
                    # Short position hit target
                    exit_actions.append(self._exit_position(position, current_price, "target"))
        
        return exit_actions
    
    def _exit_position(self, position: Position, exit_price: float, reason: str) -> Dict[str, Any]:
        """
        Exit a position at given price.
        
        Args:
            position: Position to exit
            exit_price: Exit price
            reason: Exit reason (stop_loss, target, manual)
        
        Returns:
            Exit action details
        """
        # Create exit order
        exit_side = TradeSide.SELL if position.quantity > 0 else TradeSide.BUY
        exit_quantity = abs(position.quantity)
        
        # Apply slippage
        fill_price = calculate_slippage(exit_price, exit_side.value, self.slippage_percent)
        
        # Create paper order for exit
        exit_order = PaperOrder(
            order_id=str(uuid.uuid4()),
            symbol=position.symbol,
            side=exit_side,
            quantity=exit_quantity,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            fill_price=fill_price,
            fill_timestamp=datetime.now(),
            slippage=abs(fill_price - exit_price),
            brokerage=self.brokerage_per_order,
            simulated_ltp=exit_price
        )
        
        storage.save_paper_order(exit_order)
        
        # Calculate realized PnL
        if position.quantity > 0:  # Was long
            realized_pnl = (fill_price - position.avg_price) * exit_quantity - (self.brokerage_per_order * 2)
        else:  # Was short
            realized_pnl = (position.avg_price - fill_price) * exit_quantity - (self.brokerage_per_order * 2)
        
        # Update daily state with realized PnL
        daily_state = storage.get_or_create_daily_state()
        daily_state.update_pnl(realized=realized_pnl)
        storage.save_daily_state(daily_state)
        
        # Delete position
        storage.delete_position(position.symbol)
        
        log_event("position_exited", {
            "symbol": position.symbol,
            "reason": reason,
            "quantity": exit_quantity,
            "entry_price": position.avg_price,
            "exit_price": fill_price,
            "realized_pnl": realized_pnl
        })
        
        logger.info(f"Position exited ({reason}): {position.symbol} - PnL: ₹{realized_pnl:+.2f}")
        
        return {
            "symbol": position.symbol,
            "reason": reason,
            "exit_price": fill_price,
            "realized_pnl": realized_pnl,
            "order_id": exit_order.order_id
        }
    
    def flatten_all_positions(self, reason: str = "safe_mode"):
        """
        Close all open positions (for SAFE_MODE or end of day).
        
        Args:
            reason: Reason for flattening
        """
        positions = storage.get_all_positions()
        
        if not positions:
            logger.info("No positions to flatten")
            return
        
        # Get current prices
        symbols = [p.symbol for p in positions]
        try:
            ltp_data = market_data.get_ltp(symbols)
        except Exception as e:
            logger.error(f"Error fetching LTP for flattening: {e}")
            return
        
        for position in positions:
            current_price = ltp_data.get(position.symbol)
            
            if current_price:
                self._exit_position(position, current_price, reason)
            else:
                logger.warning(f"Could not flatten {position.symbol} - no LTP data")
        
        log_event("positions_flattened", {
            "reason": reason,
            "count": len(positions)
        }, level="WARNING")
        
        logger.warning(f"All positions flattened: {reason}")
    
    def _is_duplicate(self, intent: TradeIntent) -> bool:
        """
        Check if this intent is a duplicate of a recent order.
        
        Args:
            intent: Trade intent to check
        
        Returns:
            True if duplicate
        """
        # Create hash of intent
        intent_hash = f"{intent.symbol}_{intent.side.value}_{intent.strategy_id.value}_{intent.entry_price}"
        
        # Check if we've seen this recently (within 5 minutes)
        if intent_hash in self.recent_order_hashes:
            last_time = self.recent_order_hashes[intent_hash]
            if (datetime.now() - last_time).seconds < 300:  # 5 minutes
                return True
        
        # Record this intent
        self.recent_order_hashes[intent_hash] = datetime.now()
        
        # Clean up old hashes (older than 10 minutes)
        cutoff = datetime.now()
        self.recent_order_hashes = {
            h: t for h, t in self.recent_order_hashes.items()
            if (cutoff - t).seconds < 600
        }
        
        return False


# Global execution paper agent instance
execution_paper = ExecutionPaperAgent()
