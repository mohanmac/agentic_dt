"""
Execution Algorithm Module.
Handles logic for slicing large orders (HFT-Lite) to minimize market impact.
"""
from typing import List, Optional
import datetime
from app.core.schemas import OrderType, TradeSide

class ExecutionAlgo:
    """Algorithm for smart order execution."""
    
    def __init__(self):
        self.active_slices = {} # {order_id: {remaining_qty: int, slice_size: int, strategy: str}}
        
    def create_sliced_order(self, parent_order_id: str, symbol: str, total_qty: int, slice_count: int = 10):
        """Register a parent order to be sliced."""
        slice_size = max(1, total_qty // slice_count)
        self.active_slices[parent_order_id] = {
            "symbol": symbol,
            "total_qty": total_qty,
            "remaining_qty": total_qty,
            "slice_size": slice_size,
            "filled_qty": 0,
            "status": "ACTIVE"
        }
        
    def get_next_slice(self, parent_order_id: str, current_ltp: float, vwap: float) -> Optional[int]:
        """
        Determine if next slice should be executed.
        Rule: Execute only if Price < VWAP (for BUY) or Price > VWAP (for SELL).
        Here we assume BUY for now as per strategy focus.
        """
        order_info = self.active_slices.get(parent_order_id)
        if not order_info or order_info["remaining_qty"] <= 0:
            return None
            
        # VWAP Logic: For BUY, we want price below VWAP
        if current_ltp < vwap:
            qty_to_fill = min(order_info["slice_size"], order_info["remaining_qty"])
            order_info["remaining_qty"] -= qty_to_fill
            order_info["filled_qty"] += qty_to_fill
            return qty_to_fill
            
        return None
