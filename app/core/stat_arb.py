"""
Statistical Arbitrage & Pairs Trading Logic.
Uses statsmodels to identify cointegration and calculate z-scores for mean reversion.
"""
import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint, adfuller
from typing import Tuple, Optional

class StatArbEngine:
    """Engine for statistical arbitrage calculations."""
    
    @staticmethod
    def calculate_hedge_ratio(series_y: pd.Series, series_x: pd.Series) -> float:
        """
        Calculate hedge ratio (beta) using OLS regression.
        Spread = Y - (Beta * X)
        """
        if len(series_y) != len(series_x):
            min_len = min(len(series_y), len(series_x))
            series_y = series_y.iloc[-min_len:]
            series_x = series_x.iloc[-min_len:]
            
        x_add_const = sm.add_constant(series_x)
        model = sm.OLS(series_y, x_add_const).fit()
        beta = model.params[1] # Slope
        return float(beta)
        
    @staticmethod
    def calculate_spread(series_y: pd.Series, series_x: pd.Series, beta: float) -> pd.Series:
        """Calculate the spread series."""
        return series_y - (beta * series_x)
        
    @staticmethod
    def calculate_zscore(spread: pd.Series, window: int = 20) -> float:
        """
        Calculate Z-Score of the current spread value relative to rolling mean/std.
        """
        if len(spread) < window:
            return 0.0
            
        rolling_mean = spread.rolling(window=window).mean()
        rolling_std = spread.rolling(window=window).std()
        
        current_spread = spread.iloc[-1]
        current_mean = rolling_mean.iloc[-1]
        current_std = rolling_std.iloc[-1]
        
        if current_std == 0:
            return 0.0
            
        z_score = (current_spread - current_mean) / current_std
        return float(z_score)
        
    @staticmethod
    def check_cointegration(series_y: pd.Series, series_x: pd.Series) -> Tuple[bool, float]:
        """
        Check if two series are cointegrated using Engle-Granger test.
        Returns (is_cointegrated, p_value)
        """
        if len(series_y) != len(series_x):
             min_len = min(len(series_y), len(series_x))
             series_y = series_y.iloc[-min_len:]
             series_x = series_x.iloc[-min_len:]
             
        score, p_value, _ = coint(series_y, series_x)
        is_cointegrated = p_value < 0.05
        return is_cointegrated, p_value

    @staticmethod
    def get_market_beta(stock_returns: pd.Series, market_returns: pd.Series) -> float:
        """Get beta relative to market index."""
        covariance = stock_returns.cov(market_returns)
        variance = market_returns.var()
        if variance == 0: return 1.0
        return covariance / variance
