import pandas as pd
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class StockCandidate:
    symbol: str
    price: float
    market_cap_cr: float
    volume: int
    delivery_pct: float
    revenue_growth_qtr: float
    profit_growth_yoy: float
    dma_50: float
    dma_200: float
    rsi: float
    is_nifty50: bool = False
    is_bank_nifty: bool = False

class MarketScanner:
    def __init__(self):
        # Hardcoded exclusions for safety, ideally these come from a live list
        self.nifty50_symbols = {
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", 
            "KOTAKBANK", "LTIM", "LT", "AXISBANK", "HCLTECH", "ULTRACEMCO", "BAJFINANCE",
            # ... (Full list would be fetched dynamically or populated)
        }
    
    def is_emerging_stock(self, stock: StockCandidate) -> tuple[bool, str]:
        """
        Applies MANDATORY filters to classify as 'Emerging Low-Cost'.
        """
        # 1. Exclusion Checks
        if stock.symbol in self.nifty50_symbols or stock.is_nifty50:
            return False, "Excluded: NIFTY 50"
        if stock.is_bank_nifty: # simple check, ideally check set
            return False, "Excluded: BANK NIFTY"
        
        # 2. Price Filters (₹20 - ₹10000)
        if not (20 <= stock.price <= 10000):
            return False, f"Price ₹{stock.price} out of range (20-10000)"
            
        # 3. Market Cap (300Cr - 50000Cr)
        if not (300 <= stock.market_cap_cr <= 50000):
            return False, f"Market Cap {stock.market_cap_cr}Cr out of range (300-50000)"
            
        # 4. Liquidity
        if stock.volume < 100000:
            return False, f"Low Volume: {stock.volume}"
        if stock.delivery_pct < 30:
            return False, f"Low Delivery %: {stock.delivery_pct}"

        # 5. Growth (Sample logic, usually requires fundamental data)
        if stock.revenue_growth_qtr < 10:
            return False, "Revenue Growth < 10%"
        
        # 6. Technical Trend
        if stock.price <= stock.dma_50:
             return False, "Price below 50 DMA"
        if stock.dma_50 <= stock.dma_200:
            return False, "50 DMA below 200 DMA (Downtrend)"
        if not (45 <= stock.rsi <= 65):
            return False, f"RSI {stock.rsi} not in favorable range (45-65)"

        return True, "Qualified"

    def scan_market(self, universe: List[StockCandidate]) -> List[StockCandidate]:
        """
        Scans a list of candidates and returns only those that pass ALL filters.
        """
        qualified = []
        for stock in universe:
            passed, reason = self.is_emerging_stock(stock)
            if passed:
                qualified.append(stock)
        return qualified
