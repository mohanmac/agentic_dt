import datetime
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random

@dataclass
class PaperOrder:
    order_id: str
    symbol: str
    transaction_type: str  # BUY or SELL
    quantity: int
    price: float
    status: str  # FILLED, REJECTED, CANCELLED
    timestamp: datetime.datetime
    brokerage_est: float = 0.0

@dataclass
class PaperPosition:
    symbol: str
    quantity: int = 0
    avg_price: float = 0.0
    ltp: float = 0.0  # Last Traded Price
    
    @property
    def unrealized_pnl(self) -> float:
        if self.quantity == 0:
            return 0.0
        return (self.ltp - self.avg_price) * self.quantity

class PaperBroker:
    def __init__(self):
        self.orders: List[PaperOrder] = []
        self.positions: Dict[str, PaperPosition] = {}
        self.balance: float = 100000.0  # Starting Paper Capital
        self.realized_pnl: float = 0.0

    def place_order(self, symbol: str, transaction_type: str, quantity: int, price: float) -> PaperOrder:
        """
        Simulates order placement with slippage and brokerage.
        """
        # 1. Simulate Slippage (0.05% to 0.1%)
        slippage_pct = random.uniform(0.0005, 0.001)
        executed_price = price * (1 + slippage_pct) if transaction_type == "BUY" else price * (1 - slippage_pct)
        executed_price = round(executed_price, 2)

        # 2. Brokerage (Simplified Zerodha: 0.03% or Rs 20 whichever is lower for intraday)
        turnover = executed_price * quantity
        brokerage = min(20.0, turnover * 0.0003)
        
        # 3. Create Order
        order = PaperOrder(
            order_id=str(uuid.uuid4())[:8],
            symbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            price=executed_price,
            status="FILLED", # Auto-fill for paper trading MVP
            timestamp=datetime.datetime.now(),
            brokerage_est=brokerage
        )
        self.orders.append(order)

        # 4. Update Positions
        self._update_position(symbol, transaction_type, quantity, executed_price)
        
        # 5. Update Balance (Simplified)
        # Note: Margin blocking logic can be added here
        
        return order

    def _update_position(self, symbol: str, transaction_type: str, quantity: int, price: float):
        if symbol not in self.positions:
            self.positions[symbol] = PaperPosition(symbol=symbol)
        
        pos = self.positions[symbol]
        
        if transaction_type == "BUY":
            # Weighted Average Price
            total_cost = (pos.quantity * pos.avg_price) + (quantity * price)
            pos.quantity += quantity
            pos.avg_price = total_cost / pos.quantity if pos.quantity > 0 else 0.0
        
        elif transaction_type == "SELL":
            # Realize PnL
            # FIFO logic is complex, using simple average price logic for MVP
            trade_pnl = (price - pos.avg_price) * quantity
            self.realized_pnl += trade_pnl
            pos.quantity -= quantity
            if pos.quantity == 0:
                pos.avg_price = 0.0

    def get_portfolio(self) -> List[PaperPosition]:
        return [p for p in self.positions.values() if p.quantity != 0]

    def get_total_pnl(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.realized_pnl + unrealized
