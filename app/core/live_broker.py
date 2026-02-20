
import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

from app.core.zerodha_auth import zerodha_auth
from app.core.zerodha_auth import zerodha_auth
from app.core.utils import logger
from app.core.execution_algo import ExecutionAlgo

# Re-use Paper data classes for compatibility where possible, 
# or map Kite responses to them.
from app.core.paper_broker import PaperOrder, PaperPosition

class LiveBroker:
    def __init__(self):
        self.kite = zerodha_auth.get_kite_instance()
        # Cache for performance, though live broker should fetch fresh data often
        self._orders_cache = []
        self._positions_cache = {}
        self.algo_engine = ExecutionAlgo()

    def process_algo_orders(self):
        """
        Process pending sliced orders (HFT-Lite).
        """
        if not self.algo_engine.active_slices:
            return
            
        try:
            # We need current market data to check VWAP condition
            active_symbols = list(set(data["symbol"] for data in self.algo_engine.active_slices.values()))
            if not active_symbols:
                return

            # Fetch quote for valid VWAP comparison
            # Format for Kite: "NSE:SYMBOL"
            kite_symbols = [f"NSE:{sym}" for sym in active_symbols]
            quotes = self.kite.quote(kite_symbols)
            
            for parent_id in list(self.algo_engine.active_slices.keys()):
                slice_data = self.algo_engine.active_slices[parent_id]
                symbol = slice_data["symbol"]
                
                # Get Market Data
                q = quotes.get(f"NSE:{symbol}")
                if not q: continue
                
                ltp = q['last_price']
                vwap = q['average_price']
                
                # Check Algorithm
                qty_to_fill = self.algo_engine.get_next_slice(parent_id, ltp, vwap)
                
                if qty_to_fill and qty_to_fill > 0:
                    logger.info(f"HFT-Lite: Executing slice of {qty_to_fill} for {symbol} (LTP: {ltp} < VWAP: {vwap})")
                    self.place_order(symbol, "BUY", qty_to_fill, ltp, "LIMIT", strategy_name="ALGO_SLICE")
                    
        except Exception as e:
            logger.error(f"Algo execution error: {e}")

    def place_order(self, symbol: str, transaction_type: str, quantity: int, price: float, order_type: str = "LIMIT", strategy_name: str = None) -> Optional[PaperOrder]:
        """
        Places a REAL order via Zerodha Kite Connect.
        """
        # HFT-Lite Logic: Slice Institutional Flow Orders
        if strategy_name == "InstitutionalFlow" and quantity > 100:
             # Create parent order ID (virtual)
             parent_id = f"SLICE_{symbol}_{int(datetime.datetime.now().timestamp())}"
             self.algo_engine.create_sliced_order(parent_id, symbol, quantity, slice_count=10)
             logger.info(f"Initialized HFT Slicing for {symbol}: {quantity} Qty")
             
             return PaperOrder(
                order_id=parent_id,
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                price=price,
                status="SLICING", # Custom status
                timestamp=datetime.datetime.now(),
                brokerage_est=0.0
            )

        try:
            self.kite = zerodha_auth.get_kite_instance()
            
            variation = self.kite.VARIETY_REGULAR
            exchange = self.kite.EXCHANGE_NSE
            
            t_type = self.kite.TRANSACTION_TYPE_BUY if transaction_type == "BUY" else self.kite.TRANSACTION_TYPE_SELL
            o_type = self.kite.ORDER_TYPE_LIMIT if order_type == "LIMIT" else self.kite.ORDER_TYPE_MARKET
            
            order_id = self.kite.place_order(
                variety=variation,
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=t_type,
                quantity=quantity,
                product=self.kite.PRODUCT_MIS, # Intraday by default for this bot
                order_type=o_type,
                price=price if order_type == "LIMIT" else None,
                validity=self.kite.VALIDITY_DAY
            )
            
            logger.info(f"Live Order Placed: {order_id}")
            
            # Return a "PaperOrder" like object for UI compatibility
            # We don't have all details yet (like status), but we provide what we have.
            return PaperOrder(
                order_id=str(order_id),
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                price=price,
                status="PENDING", # Zerodha will update this
                timestamp=datetime.datetime.now(),
                brokerage_est=0.0 # Calculate later
            )
            
        except Exception as e:
            logger.error(f"Live Order placement failed: {e}")
            raise e

    def get_portfolio(self) -> List[PaperPosition]:
        """
        Fetches live positions from Zerodha.
        """
        try:
            self.kite = zerodha_auth.get_kite_instance()
            positions_resp = self.kite.positions()
            net_positions = positions_resp.get("net", [])
            
            portfolio = []
            for p in net_positions:
                # Map to PaperPosition for UI compatibility
                # PaperPosition(symbol, quantity, avg_price, ltp)
                pos = PaperPosition(
                    symbol=p['tradingsymbol'],
                    quantity=p['quantity'],
                    avg_price=p['average_price'],
                    ltp=p['last_price']
                )
                portfolio.append(pos)
                
            return portfolio
            
        except Exception as e:
            logger.error(f"Failed to fetch live portfolio: {e}")
            return []

    def get_total_pnl(self) -> float:
        """
        Calculates total PnL from live positions.
        """
        try:
            portfolio = self.get_portfolio()
            total_pnl = 0.0
            for p in portfolio:
                total_pnl += (p.ltp - p.avg_price) * p.quantity
            return total_pnl
        except Exception:
            return 0.0

    @property
    def orders(self) -> List[PaperOrder]:
        """
        Fetches live order book.
        """
        try:
            self.kite = zerodha_auth.get_kite_instance()
            k_orders = self.kite.orders()
            
            mapped_orders = []
            for o in k_orders:
                # Map Kite order to PaperOrder
                mapped = PaperOrder(
                    order_id=o['order_id'],
                    symbol=o['tradingsymbol'],
                    transaction_type=o['transaction_type'],
                    quantity=o['quantity'],
                    price=o['price'] if o['price'] else 0.0,
                    status=o['status'],
                    timestamp=o['order_timestamp'],
                    brokerage_est=0.0
                )
                mapped_orders.append(mapped)
            return mapped_orders
        except Exception as e:
            logger.error(f"Failed to fetch live orders: {e}")
            return []
    
    @property
    def realized_pnl(self) -> float:
        # Live broker might not easily track realized PnL from simple API without processing tradebook
        # Returning 0 or simple calc for now
        return 0.0 

