"""
Multi-bagger Stock Analysis & Backtesting System
Identifies stocks with 200%+ returns and finds prospects with similar patterns.

Analysis Framework:
1. Historical winners identification (200%+ returns)
2. Feature extraction from winners (what made them successful)
3. Prospect screening (current stocks with similar characteristics)
4. Pattern matching and scoring
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
import json
from pathlib import Path

try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False
    print("⚠️  KiteConnect not available, will use sample data")


@dataclass
class StockPerformance:
    """Historical stock performance metrics"""
    symbol: str
    start_price: float
    end_price: float
    return_pct: float
    period_days: int
    volatility: float
    max_drawdown: float
    sharpe_ratio: float
    
    # Fundamental characteristics at start
    market_cap_cr: Optional[float] = None  # Crores
    pe_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    roe: Optional[float] = None  # Return on Equity
    revenue_growth: Optional[float] = None
    profit_growth: Optional[float] = None
    promoter_holding: Optional[float] = None
    
    # Technical characteristics
    avg_volume: Optional[float] = None
    volume_growth: Optional[float] = None
    price_to_52w_low: Optional[float] = None
    rsi_at_start: Optional[float] = None
    
    # Sector and category
    sector: Optional[str] = None
    industry: Optional[str] = None


@dataclass
class ProspectScore:
    """Scoring for prospect stocks"""
    symbol: str
    total_score: float
    feature_scores: Dict[str, float]
    similar_to: List[str]  # Historical winners it resembles
    reasons: List[str]
    current_price: float
    market_cap_cr: float
    sector: str
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "total_score": round(self.total_score, 2),
            "feature_scores": {k: round(v, 2) for k, v in self.feature_scores.items()},
            "similar_to": self.similar_to,
            "reasons": self.reasons,
            "current_price": self.current_price,
            "market_cap_cr": self.market_cap_cr,
            "sector": self.sector
        }


class MultibaggeerAnalyzer:
    """
    Comprehensive analysis system for identifying multi-bagger stocks.
    """
    
    def __init__(self, kite: Optional[KiteConnect] = None):
        self.kite = kite
        self.historical_winners: List[StockPerformance] = []
        self.winner_patterns: Dict[str, any] = {}
        self.prospects: List[ProspectScore] = []
        
        # Analysis parameters
        self.min_return_pct = 200.0  # 200%+ returns
        self.lookback_years = 5  # Analyze last 5 years
        self.analysis_date = datetime.now()
        
    def identify_historical_winners(self, 
                                   symbols: List[str],
                                   start_date: datetime,
                                   end_date: datetime) -> List[StockPerformance]:
        """
        Identify stocks that had 200%+ returns in the given period.
        
        Args:
            symbols: List of stock symbols to analyze
            start_date: Analysis start date
            end_date: Analysis end date
            
        Returns:
            List of StockPerformance objects for winners
        """
        print(f"\n🔍 Analyzing {len(symbols)} stocks for {self.min_return_pct}%+ returns...")
        print(f"   Period: {start_date.date()} to {end_date.date()}")
        
        winners = []
        
        for symbol in symbols:
            try:
                perf = self._analyze_stock_performance(symbol, start_date, end_date)
                
                if perf and perf.return_pct >= self.min_return_pct:
                    winners.append(perf)
                    print(f"   ✅ {symbol}: +{perf.return_pct:.1f}% return")
                    
            except Exception as e:
                print(f"   ❌ {symbol}: Error - {e}")
                
        self.historical_winners = sorted(winners, key=lambda x: x.return_pct, reverse=True)
        
        print(f"\n📊 Found {len(winners)} multi-baggers (200%+ returns)")
        
        return self.historical_winners
    
    def _analyze_stock_performance(self, 
                                   symbol: str,
                                   start_date: datetime,
                                   end_date: datetime) -> Optional[StockPerformance]:
        """
        Analyze individual stock performance over period.
        """
        if self.kite:
            # Fetch real historical data
            historical_data = self._fetch_historical_data(symbol, start_date, end_date)
        else:
            # Use simulated data for demonstration
            historical_data = self._generate_sample_data(symbol, start_date, end_date)
        
        if historical_data is None or len(historical_data) < 50:
            return None
        
        # Calculate performance metrics
        start_price = historical_data.iloc[0]['close']
        end_price = historical_data.iloc[-1]['close']
        return_pct = ((end_price - start_price) / start_price) * 100
        
        if return_pct < self.min_return_pct:
            return None
        
        # Calculate volatility (annualized standard deviation)
        returns = historical_data['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) * 100  # Annualized
        
        # Calculate max drawdown
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min() * 100
        
        # Calculate Sharpe ratio (simplified, assuming 6% risk-free rate)
        excess_returns = returns.mean() * 252 - 0.06
        sharpe = excess_returns / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        # Get fundamentals (if available)
        fundamentals = self._get_fundamentals(symbol, start_date)
        
        # Get technical indicators at start
        technicals = self._get_technical_indicators(historical_data[:60])  # First 2 months
        
        period_days = (end_date - start_date).days
        
        return StockPerformance(
            symbol=symbol,
            start_price=start_price,
            end_price=end_price,
            return_pct=return_pct,
            period_days=period_days,
            volatility=volatility,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            **fundamentals,
            **technicals
        )
    
    def extract_winner_patterns(self) -> Dict[str, any]:
        """
        Extract common patterns from historical winners.
        
        Returns:
            Dictionary of pattern statistics
        """
        if not self.historical_winners:
            print("⚠️  No historical winners to analyze")
            return {}
        
        print(f"\n🔬 Extracting patterns from {len(self.historical_winners)} winners...")
        
        # Aggregate metrics
        returns = [w.return_pct for w in self.historical_winners]
        volatilities = [w.volatility for w in self.historical_winners if w.volatility]
        sharpe_ratios = [w.sharpe_ratio for w in self.historical_winners if w.sharpe_ratio]
        
        # Fundamental metrics
        market_caps = [w.market_cap_cr for w in self.historical_winners if w.market_cap_cr]
        pe_ratios = [w.pe_ratio for w in self.historical_winners if w.pe_ratio]
        roes = [w.roe for w in self.historical_winners if w.roe]
        revenue_growths = [w.revenue_growth for w in self.historical_winners if w.revenue_growth]
        
        # Sector analysis
        sectors = [w.sector for w in self.historical_winners if w.sector]
        sector_counts = pd.Series(sectors).value_counts().to_dict()
        
        self.winner_patterns = {
            "count": len(self.historical_winners),
            "avg_return": np.mean(returns),
            "median_return": np.median(returns),
            "max_return": max(returns),
            "min_return": min(returns),
            
            "volatility": {
                "avg": np.mean(volatilities) if volatilities else None,
                "range": [min(volatilities), max(volatilities)] if volatilities else None
            },
            
            "sharpe_ratio": {
                "avg": np.mean(sharpe_ratios) if sharpe_ratios else None,
                "min": min(sharpe_ratios) if sharpe_ratios else None
            },
            
            "market_cap_at_start": {
                "avg": np.mean(market_caps) if market_caps else None,
                "median": np.median(market_caps) if market_caps else None,
                "range": [min(market_caps), max(market_caps)] if market_caps else None
            },
            
            "pe_ratio_at_start": {
                "avg": np.mean(pe_ratios) if pe_ratios else None,
                "median": np.median(pe_ratios) if pe_ratios else None
            },
            
            "roe_at_start": {
                "avg": np.mean(roes) if roes else None,
                "median": np.median(roes) if roes else None
            },
            
            "revenue_growth_at_start": {
                "avg": np.mean(revenue_growths) if revenue_growths else None,
                "median": np.median(revenue_growths) if revenue_growths else None
            },
            
            "top_sectors": sector_counts,
            
            "key_characteristics": self._identify_key_characteristics()
        }
        
        self._print_pattern_summary()
        
        return self.winner_patterns
    
    def _identify_key_characteristics(self) -> List[str]:
        """Identify the most common characteristics of winners."""
        characteristics = []
        
        # Analyze what most winners have in common
        winners = self.historical_winners
        
        # Small/mid cap preference
        small_mid_caps = [w for w in winners if w.market_cap_cr and w.market_cap_cr < 50000]
        if len(small_mid_caps) / len(winners) > 0.6:
            characteristics.append("Predominantly small to mid-cap (< ₹50,000 Cr)")
        
        # Revenue growth
        high_growth = [w for w in winners if w.revenue_growth and w.revenue_growth > 20]
        if len(high_growth) / len(winners) > 0.6:
            characteristics.append("Strong revenue growth (>20% YoY)")
        
        # ROE
        high_roe = [w for w in winners if w.roe and w.roe > 15]
        if len(high_roe) / len(winners) > 0.6:
            characteristics.append("Healthy ROE (>15%)")
        
        # Volume growth
        vol_growth = [w for w in winners if w.volume_growth and w.volume_growth > 50]
        if len(vol_growth) / len(winners) > 0.5:
            characteristics.append("Increasing trading volume (>50% growth)")
        
        return characteristics
    
    def screen_prospects(self, candidate_symbols: List[str]) -> List[ProspectScore]:
        """
        Screen current stocks for similarity to historical winners.
        
        Args:
            candidate_symbols: List of stocks to evaluate
            
        Returns:
            List of ProspectScore objects, sorted by score
        """
        if not self.winner_patterns:
            print("⚠️  Run extract_winner_patterns() first")
            return []
        
        print(f"\n🎯 Screening {len(candidate_symbols)} prospect stocks...")
        
        prospects = []
        
        for symbol in candidate_symbols:
            try:
                score = self._score_prospect(symbol)
                if score and score.total_score > 50:  # Threshold
                    prospects.append(score)
                    print(f"   ✅ {symbol}: Score {score.total_score:.1f}/100")
            except Exception as e:
                print(f"   ❌ {symbol}: {e}")
        
        self.prospects = sorted(prospects, key=lambda x: x.total_score, reverse=True)
        
        print(f"\n📈 Found {len(self.prospects)} promising prospects")
        
        return self.prospects
    
    def _score_prospect(self, symbol: str) -> Optional[ProspectScore]:
        """
        Score a prospect stock based on similarity to winners.
        """
        # Get current data
        current_data = self._get_current_stock_data(symbol)
        if not current_data:
            return None
        
        feature_scores = {}
        reasons = []
        similar_to = []
        
        # Score 1: Market Cap (20 points)
        if current_data.get('market_cap_cr'):
            target_range = self.winner_patterns.get('market_cap_at_start', {}).get('range', [0, 100000])
            if target_range[0] <= current_data['market_cap_cr'] <= target_range[1]:
                feature_scores['market_cap'] = 20
                reasons.append(f"Market cap (₹{current_data['market_cap_cr']:.0f} Cr) in winner range")
            else:
                feature_scores['market_cap'] = 10
        
        # Score 2: Revenue Growth (20 points)
        if current_data.get('revenue_growth'):
            target_growth = self.winner_patterns.get('revenue_growth_at_start', {}).get('median', 20)
            if current_data['revenue_growth'] >= target_growth:
                feature_scores['revenue_growth'] = 20
                reasons.append(f"Strong revenue growth: {current_data['revenue_growth']:.1f}% YoY")
            elif current_data['revenue_growth'] >= target_growth * 0.7:
                feature_scores['revenue_growth'] = 15
            else:
                feature_scores['revenue_growth'] = 5
        
        # Score 3: ROE (15 points)
        if current_data.get('roe'):
            target_roe = self.winner_patterns.get('roe_at_start', {}).get('median', 15)
            if current_data['roe'] >= target_roe:
                feature_scores['roe'] = 15
                reasons.append(f"Healthy ROE: {current_data['roe']:.1f}%")
            elif current_data['roe'] >= target_roe * 0.7:
                feature_scores['roe'] = 10
            else:
                feature_scores['roe'] = 3
        
        # Score 4: PE Ratio (15 points)
        if current_data.get('pe_ratio'):
            target_pe = self.winner_patterns.get('pe_ratio_at_start', {}).get('median', 25)
            # Prefer moderate PE (not too high, not too low)
            if 10 <= current_data['pe_ratio'] <= target_pe * 1.2:
                feature_scores['pe_ratio'] = 15
                reasons.append(f"Reasonable valuation: PE {current_data['pe_ratio']:.1f}")
            elif current_data['pe_ratio'] < 10 or current_data['pe_ratio'] > target_pe * 2:
                feature_scores['pe_ratio'] = 5
            else:
                feature_scores['pe_ratio'] = 10
        
        # Score 5: Volume Trend (15 points)
        if current_data.get('volume_growth'):
            if current_data['volume_growth'] > 50:
                feature_scores['volume'] = 15
                reasons.append(f"Rising volume: +{current_data['volume_growth']:.1f}%")
            elif current_data['volume_growth'] > 20:
                feature_scores['volume'] = 10
            else:
                feature_scores['volume'] = 5
        
        # Score 6: Sector (15 points)
        top_sectors = self.winner_patterns.get('top_sectors', {})
        if current_data.get('sector') in top_sectors:
            sector_rank = list(top_sectors.keys()).index(current_data['sector'])
            feature_scores['sector'] = max(15 - sector_rank * 3, 5)
            reasons.append(f"Hot sector: {current_data['sector']}")
        else:
            feature_scores['sector'] = 5
        
        # Find similar winners
        for winner in self.historical_winners[:10]:  # Top 10 winners
            similarity = self._calculate_similarity(current_data, winner)
            if similarity > 0.7:
                similar_to.append(f"{winner.symbol} (+{winner.return_pct:.0f}%)")
        
        if similar_to:
            reasons.append(f"Similar to: {', '.join(similar_to[:3])}")
        
        total_score = sum(feature_scores.values())
        
        return ProspectScore(
            symbol=symbol,
            total_score=total_score,
            feature_scores=feature_scores,
            similar_to=similar_to,
            reasons=reasons,
            current_price=current_data.get('price', 0),
            market_cap_cr=current_data.get('market_cap_cr', 0),
            sector=current_data.get('sector', 'Unknown')
        )
    
    def _calculate_similarity(self, current: Dict, winner: StockPerformance) -> float:
        """Calculate similarity score between current stock and historical winner."""
        similarity_factors = []
        
        # Market cap similarity
        if current.get('market_cap_cr') and winner.market_cap_cr:
            ratio = current['market_cap_cr'] / winner.market_cap_cr
            if 0.5 <= ratio <= 2.0:
                similarity_factors.append(1.0)
            else:
                similarity_factors.append(0.5)
        
        # Revenue growth similarity
        if current.get('revenue_growth') and winner.revenue_growth:
            diff = abs(current['revenue_growth'] - winner.revenue_growth)
            similarity_factors.append(max(0, 1.0 - diff / 50))
        
        # ROE similarity
        if current.get('roe') and winner.roe:
            diff = abs(current['roe'] - winner.roe)
            similarity_factors.append(max(0, 1.0 - diff / 30))
        
        # Sector match
        if current.get('sector') == winner.sector:
            similarity_factors.append(1.0)
        
        return np.mean(similarity_factors) if similarity_factors else 0.0
    
    def _fetch_historical_data(self, symbol: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Fetch historical OHLC data from Kite API."""
        if not self.kite:
            return None
        
        try:
            instrument_token = self._get_instrument_token(symbol)
            if not instrument_token:
                return None
            
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=start_date,
                to_date=end_date,
                interval="day"
            )
            
            df = pd.DataFrame(data)
            return df
            
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return None
    
    def _generate_sample_data(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Generate sample historical data for demonstration."""
        days = (end_date - start_date).days
        dates = pd.date_range(start=start_date, end=end_date, freq='D')
        
        # Simulate different return scenarios
        np.random.seed(hash(symbol) % 2**32)
        
        # Some stocks are winners (200%+), others are not
        is_winner = np.random.random() > 0.85  # 15% are winners
        
        if is_winner:
            # Simulate multi-bagger with trend + noise
            trend_return = np.random.uniform(2.0, 5.0)  # 200-500% over period
            growth_rate = (1 + trend_return) ** (1/days) - 1
        else:
            # Regular stock
            growth_rate = np.random.uniform(-0.0005, 0.001)
        
        base_price = np.random.uniform(50, 500)
        prices = [base_price]
        
        for i in range(1, days):
            daily_return = growth_rate + np.random.normal(0, 0.02)
            new_price = prices[-1] * (1 + daily_return)
            prices.append(max(new_price, 1))  # Floor at 1
        
        df = pd.DataFrame({
            'date': dates[:len(prices)],
            'open': prices,
            'high': [p * 1.02 for p in prices],
            'low': [p * 0.98 for p in prices],
            'close': prices,
            'volume': np.random.randint(100000, 10000000, len(prices))
        })
        
        return df
    
    def _get_fundamentals(self, symbol: str, date: datetime) -> Dict:
        """Get fundamental data for stock at given date."""
        # In real implementation, fetch from financial data API
        # For now, return simulated data
        np.random.seed(hash(symbol + date.isoformat()) % 2**32)
        
        return {
            'market_cap_cr': np.random.uniform(1000, 80000),
            'pe_ratio': np.random.uniform(10, 40),
            'debt_to_equity': np.random.uniform(0.1, 1.5),
            'roe': np.random.uniform(5, 30),
            'revenue_growth': np.random.uniform(-10, 50),
            'profit_growth': np.random.uniform(-20, 60),
            'promoter_holding': np.random.uniform(40, 75),
            'sector': np.random.choice(['Technology', 'Pharma', 'Auto', 'FMCG', 'Banking']),
            'industry': np.random.choice(['Software', 'Hardware', 'Services', 'Manufacturing'])
        }
    
    def _get_technical_indicators(self, df: pd.DataFrame) -> Dict:
        """Calculate technical indicators from OHLC data."""
        if df is None or len(df) < 14:
            return {}
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # Volume metrics
        avg_volume = df['volume'].mean()
        
        return {
            'avg_volume': avg_volume,
            'volume_growth': np.random.uniform(-20, 100),  # Simulated
            'rsi_at_start': rsi.iloc[-1] if not rsi.empty else None
        }
    
    def _get_current_stock_data(self, symbol: str) -> Optional[Dict]:
        """Get current stock data for screening."""
        # In real implementation, fetch live data
        # For now, simulate
        np.random.seed(hash(symbol) % 2**32)
        
        return {
            'symbol': symbol,
            'price': np.random.uniform(100, 1000),
            'market_cap_cr': np.random.uniform(1000, 80000),
            'pe_ratio': np.random.uniform(10, 40),
            'roe': np.random.uniform(5, 30),
            'revenue_growth': np.random.uniform(-10, 50),
            'volume_growth': np.random.uniform(-20, 100),
            'sector': np.random.choice(['Technology', 'Pharma', 'Auto', 'FMCG', 'Banking', 'Metals'])
        }
    
    def _get_instrument_token(self, symbol: str) -> Optional[int]:
        """Get instrument token for symbol."""
        # Would need to fetch from instruments list
        return None
    
    def _print_pattern_summary(self):
        """Print summary of winner patterns."""
        patterns = self.winner_patterns
        
        print("\n" + "="*80)
        print("📊 MULTI-BAGGER PATTERN ANALYSIS")
        print("="*80)
        
        print(f"\n✅ Analyzed {patterns['count']} winners ({self.min_return_pct}%+ returns)")
        print(f"   Average Return: {patterns['avg_return']:.1f}%")
        print(f"   Median Return: {patterns['median_return']:.1f}%")
        print(f"   Best Return: {patterns['max_return']:.1f}%")
        
        if patterns.get('market_cap_at_start'):
            mc = patterns['market_cap_at_start']
            print(f"\n💰 Market Cap at Start:")
            print(f"   Median: ₹{mc['median']:.0f} Cr")
            print(f"   Range: ₹{mc['range'][0]:.0f} - ₹{mc['range'][1]:.0f} Cr")
        
        if patterns.get('revenue_growth_at_start'):
            rg = patterns['revenue_growth_at_start']
            print(f"\n📈 Revenue Growth at Start:")
            print(f"   Average: {rg['avg']:.1f}% YoY")
            print(f"   Median: {rg['median']:.1f}% YoY")
        
        if patterns.get('roe_at_start'):
            roe = patterns['roe_at_start']
            print(f"\n💎 ROE at Start:")
            print(f"   Average: {roe['avg']:.1f}%")
            print(f"   Median: {roe['median']:.1f}%")
        
        if patterns.get('top_sectors'):
            print(f"\n🎯 Top Performing Sectors:")
            for sector, count in list(patterns['top_sectors'].items())[:5]:
                print(f"   {sector}: {count} winners")
        
        if patterns.get('key_characteristics'):
            print(f"\n🔑 Key Characteristics:")
            for char in patterns['key_characteristics']:
                print(f"   • {char}")
        
        print("\n" + "="*80)
    
    def generate_report(self, output_file: str = "multibagger_analysis_report.json"):
        """Generate comprehensive analysis report."""
        report = {
            "analysis_date": self.analysis_date.isoformat(),
            "parameters": {
                "min_return_pct": self.min_return_pct,
                "lookback_years": self.lookback_years
            },
            "historical_winners": [
                {
                    "symbol": w.symbol,
                    "return_pct": round(w.return_pct, 2),
                    "start_price": round(w.start_price, 2),
                    "end_price": round(w.end_price, 2),
                    "market_cap_cr": w.market_cap_cr,
                    "sector": w.sector,
                    "revenue_growth": w.revenue_growth,
                    "roe": w.roe
                }
                for w in self.historical_winners[:20]  # Top 20
            ],
            "winner_patterns": self.winner_patterns,
            "prospects": [p.to_dict() for p in self.prospects[:50]],  # Top 50
            "top_prospects": [
                {
                    "rank": i+1,
                    "symbol": p.symbol,
                    "score": p.total_score,
                    "reasons": p.reasons,
                    "similar_to": p.similar_to
                }
                for i, p in enumerate(self.prospects[:10])  # Top 10
            ]
        }
        
        output_path = Path(__file__).parent.parent / "data" / output_file
        output_path.parent.mkdir(exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n✅ Report saved to: {output_path}")
        
        return report


def main():
    """Run multi-bagger analysis."""
    print("="*80)
    print("🚀 MULTI-BAGGER STOCK ANALYSIS SYSTEM")
    print("="*80)
    
    # Sample NSE stocks for analysis (expand this list)
    nse_universe = [
        # Large caps (some became multi-baggers from lower levels)
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "HINDUNILVR", "ITC",
        
        # Mid caps with potential
        "ADANIENT", "ADANIPORTS", "TATASTEEL", "JSWSTEEL", "BAJFINANCE",
        "BAJAJFINSV", "MARUTI", "M&M", "TITAN", "NESTLEIND",
        
        # Small/Mid caps - known multi-baggers
        "DIVISLAB", "DMART", "PAGEIND", "PIDILITIND", "GODREJCP",
        "BERGEPAINT", "ASIANPAINT", "BRITANNIA", "DABUR", "MARICO",
        
        # Technology sector
        "WIPRO", "TECHM", "HCLTECH", "LTIM", "PERSISTENT",
        
        # Pharma sector
        "SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA",
        
        # Auto sector
        "TATAMOTORS", "EICHERMOT", "BALKRISIND", "MRF", "APOLLOTYRE",
        
        # Emerging sectors
        "ZOMATO", "NYKAA", "POLICYBZR", "PAYTM", "DELHIVERY"
    ]
    
    # Initialize analyzer
    analyzer = MultibaggeerAnalyzer()
    
    # Step 1: Identify historical winners (last 5 years)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5*365)
    
    print(f"\n📅 Analysis Period: {start_date.date()} to {end_date.date()}")
    
    winners = analyzer.identify_historical_winners(
        symbols=nse_universe,
        start_date=start_date,
        end_date=end_date
    )
    
    if not winners:
        print("\n⚠️  No multi-baggers found in simulation. Run with real data for actual analysis.")
        return
    
    # Step 2: Extract patterns from winners
    patterns = analyzer.extract_winner_patterns()
    
    # Step 3: Screen prospects
    # Add more candidate stocks here
    candidate_prospects = [
        # Add 100+ stocks from NSE to screen
        "HINDCOPPER", "MCX", "LAURUSLABS", "NAVINFLUOR", "RADICO",
        "SUPREMEIND", "RELAXO", "SYMPHONY", "VGUARD", "CROMPTON",
        "WHIRLPOOL", "VOLTAS", "BLUESTARCO", "CUMMINSIND", "THERMAX",
        "ABB", "SIEMENS", "HAVELLS", "POLYCAB", "KEI"
    ] + nse_universe  # Include all analyzed stocks
    
    prospects = analyzer.screen_prospects(candidate_prospects)
    
    # Step 4: Generate report
    report = analyzer.generate_report()
    
    # Print top prospects
    print("\n" + "="*80)
    print("🎯 TOP 10 PROSPECT STOCKS")
    print("="*80)
    
    for i, prospect in enumerate(prospects[:10], 1):
        print(f"\n{i}. {prospect.symbol} - Score: {prospect.total_score:.1f}/100")
        print(f"   💰 Current Price: ₹{prospect.current_price:.2f}")
        print(f"   📊 Market Cap: ₹{prospect.market_cap_cr:.0f} Cr")
        print(f"   🏭 Sector: {prospect.sector}")
        print(f"   ✅ Reasons:")
        for reason in prospect.reasons:
            print(f"      • {reason}")
        if prospect.similar_to:
            print(f"   🎯 Similar to: {', '.join(prospect.similar_to[:3])}")
    
    print("\n" + "="*80)
    print("✅ Analysis Complete!")
    print("="*80)
    
    print("\n💡 Next Steps:")
    print("   1. Review the full report in data/multibagger_analysis_report.json")
    print("   2. Conduct deeper fundamental analysis on top prospects")
    print("   3. Monitor these stocks for entry opportunities")
    print("   4. Set up alerts for price/volume breakouts")
    print("   5. Backtest specific strategies on these stocks")
    
    return analyzer


if __name__ == "__main__":
    analyzer = main()
