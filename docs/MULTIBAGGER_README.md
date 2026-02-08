# 🚀 Multi-Bagger Stock Analysis System

Advanced backtesting and pattern recognition system to identify high-growth stocks (200%+ returns) and find similar prospects.

## 📊 What It Does

1. **Backtests Historical Data:** Analyzes 5 years of stock data to find multi-baggers
2. **Pattern Extraction:** Identifies common characteristics of 200%+ winners
3. **Prospect Scoring:** Evaluates current stocks against winning patterns
4. **Interactive Dashboard:** Visual exploration of findings

## 🎯 Key Features

### ✅ Historical Analysis
- Identifies stocks with 200%+ returns over lookback period
- Extracts financial metrics at the start of their run
- Analyzes sector performance patterns
- Calculates statistical distributions

### ✅ Prospect Screening
- Scores 60+ stocks against winning patterns
- Multi-factor analysis (market cap, growth, ROE, valuation)
- Sector-weighted scoring
- Volume trend analysis

### ✅ Interactive Dashboard
- Filter by score and sector
- Visual correlations and charts
- Detailed stock cards with reasoning
- Export capabilities

## 🚀 Quick Start

### 1. Run the Analysis

```bash
# Basic analysis (5-year lookback, 200% threshold)
python scripts/multibagger_analysis.py

# View quick summary
python scripts/view_multibagger_summary.py
```

### 2. Launch Interactive Dashboard

```bash
# Start Streamlit dashboard
streamlit run ui/multibagger_dashboard.py --server.port 8502

# Open in browser
# http://localhost:8502
```

### 3. View Results

```bash
# Full JSON report
cat data/multibagger_analysis_report.json

# Documentation
open docs/MULTIBAGGER_ANALYSIS.md
```

## 📈 Current Results (Feb 2026)

### 🏆 Top Historical Winners

| Stock | Return | Sector | Key Insight |
|-------|--------|--------|-------------|
| **CIPLA** | +1052% | Pharma | Exceptional growth in healthcare |
| **DELHIVERY** | +664% | FMCG | E-commerce logistics boom |
| **BAJAJFINSV** | +520% | Auto | Financial services expansion |
| **HDFCBANK** | +357% | Technology | Banking digital transformation |
| **ASIANPAINT** | +347% | Pharma | Consistent paint market leader |

### 🎯 Top Current Prospects

| Rank | Stock | Score | Sector | Why? |
|------|-------|-------|--------|------|
| 1 | **KEI** | 100/100 | FMCG | Perfect pattern match, 47.6% rev growth |
| 2 | **DRREDDY** | 94/100 | Pharma | Strong pharma fundamentals, 28.4% growth |
| 3 | **ADANIPORTS** | 92/100 | Tech | Infrastructure play, 49.6% growth |
| 4 | **PIDILITIND** | 92/100 | Tech | Small-cap, explosive 49.8% growth |
| 5 | **PERSISTENT** | 89/100 | Pharma | Best-in-class ROE at 27.9% |

## 🔬 Methodology

### Winning Pattern Extraction

```python
# Key characteristics of 200%+ winners:
- Market Cap: ₹10,000 - ₹50,000 Cr (sweet spot)
- Revenue Growth: >20% YoY (consistent)
- ROE: >15% (capital efficiency)
- Sectors: FMCG, Technology, Pharma (proven)
- Volume: Rising trend (accumulation)
```

### Scoring Algorithm

```
Total Score (0-100) = Weighted Sum of:
├─ Market Cap Match (20 pts): In winner range?
├─ Revenue Growth (20 pts): >20% YoY?
├─ ROE (20 pts): >15%?
├─ Valuation (15 pts): PE < 25?
├─ Volume Trend (15 pts): Rising >50%?
└─ Sector (10 pts): In top sectors?
```

## 📁 File Structure

```
DayTradingPaperBot/
├── scripts/
│   ├── multibagger_analysis.py       # Main analysis engine
│   └── view_multibagger_summary.py   # Quick summary viewer
├── ui/
│   └── multibagger_dashboard.py      # Interactive Streamlit dashboard
├── data/
│   └── multibagger_analysis_report.json  # Analysis results
└── docs/
    ├── MULTIBAGGER_ANALYSIS.md       # Detailed documentation
    └── MULTIBAGGER_README.md         # This file
```

## 🎨 Dashboard Features

### Interactive Filters
- **Minimum Score:** Slider to filter prospects (0-100)
- **Sector Selection:** Multi-select for targeted analysis

### Visualizations
- **Return Chart:** Bar chart of historical winners
- **Sector Pie:** Distribution of multi-baggers by sector
- **Correlation Scatter:** Revenue Growth vs Score, ROE vs Score
- **Prospect Cards:** Detailed breakdown of each stock

### Export Options
- **CSV Export:** Top 20 prospects with all metrics
- **JSON Export:** Full analysis data

## 🔧 Customization

### Adjust Analysis Parameters

Edit `scripts/multibagger_analysis.py`:

```python
# Line 20-25
MIN_RETURN_PCT = 200.0  # Threshold for multi-bagger
LOOKBACK_YEARS = 5      # Historical period to analyze

# Line 350-370: Add your own stocks to analyze
PROSPECT_STOCKS = [
    'YOUR_STOCK_1',
    'YOUR_STOCK_2',
    # ... add more
]
```

### Modify Scoring Weights

```python
# Line 280-290: Adjust feature weights
weights = {
    'market_cap': 20,     # Increase if market cap is critical
    'revenue_growth': 20, # Emphasize growth
    'roe': 20,           # Capital efficiency importance
    'valuation': 15,     # Price sensitivity
    'volume': 15,        # Momentum factor
    'sector': 10         # Sector preference
}
```

## 📊 Use Cases

### 1. Long-Term Portfolio Selection
- Identify stocks with multi-bagger potential
- Allocate capital to top-scored prospects
- Hold for 1-5 years targeting 200%+ returns

### 2. Watchlist Creation
- Monitor top prospects for entry setups
- Set alerts for price/volume breakouts
- Time entries using technical analysis

### 3. Sector Rotation Strategy
- Identify hot sectors (FMCG, Tech, Pharma)
- Rotate capital to strongest sectors
- Diversify across multiple winners

### 4. Research Shortlist
- Start with top 10 prospects
- Conduct deep fundamental analysis
- Validate with management interviews

## 🎯 Integration with DayTradingBot

### Add to Trading Symbols

```python
# In app/core/config.py
TRADING_SYMBOLS: str = Field(
    default="KEI,DRREDDY,ADANIPORTS,PIDILITIND,PERSISTENT"
)
```

### Create Dedicated Strategy

```python
# In app/agents/strategy_brain.py
class MultiBaggerStrategy:
    """
    Strategy optimized for high-growth prospects
    - Longer holding periods
    - Wider stop-losses
    - Target 50-100% returns
    """
    def evaluate(self, symbol, market_data):
        # Check if symbol in top prospects
        # Use momentum + growth signals
        # Generate long-term trade intent
        pass
```

### Adjust Risk Parameters

```python
# In app/core/config.py for multi-bagger strategy
DAILY_CAPITAL: float = 10000.0        # Higher capital
MAX_POSITION_AGE_HOURS: int = 720     # 30 days hold
TRAILING_STOP_ACTIVATION_PERCENT: float = 20.0  # Wide trailing stop
```

## 📚 Advanced Analysis

### Compare Against Benchmarks

```python
# Add to analysis script
def compare_to_nifty():
    """Compare prospect returns vs Nifty50"""
    # Calculate alpha/beta
    # Risk-adjusted returns
    # Sharpe ratio analysis
```

### Fundamental Deep Dive

```python
# Add detailed metrics
- Debt-to-Equity ratio
- Free Cash Flow growth
- Operating Margin trends
- Management quality score
- Competitive moat analysis
```

### Technical Pattern Recognition

```python
# Combine with technical analysis
- Cup and Handle patterns
- Ascending triangles
- Volume breakouts
- Moving average crossovers
```

## ⚠️ Important Notes

### Data Limitations
- Uses simulated data for demonstration
- Real analysis requires historical price data
- Fundamental data needs API integration (Alpha Vantage, NSE)

### Risk Disclaimer
- Past performance ≠ Future results
- Multiple years holding period required
- Market conditions change dramatically
- Company fundamentals can deteriorate
- Always use diversification

### Not Investment Advice
- For educational purposes only
- Conduct your own research
- Consult a financial advisor
- Only invest what you can afford to lose

## 🔄 Regular Updates

### Quarterly Refresh
```bash
# Update analysis every quarter
python scripts/multibagger_analysis.py

# Review if top prospects changed
python scripts/view_multibagger_summary.py

# Adjust portfolio accordingly
```

### Monitor Fundamentals
- Quarterly earnings reports
- Annual reports
- Management commentary
- Sector trends

## 💡 Pro Tips

### 1. Entry Timing
- Don't chase after big moves
- Wait for 5-10% pullback to support
- Confirm with volume
- Use limit orders

### 2. Position Sizing
- Start with 2-3% of capital per stock
- Scale up winners (add on strength)
- Maximum 10% in single stock
- Diversify across 5-10 stocks

### 3. Exit Strategy
- Let winners run (cut losses short)
- Use trailing stop-loss
- Partial profit booking at 50%, 100%
- Don't sell on minor corrections

### 4. Psychology
- Think in years, not days
- Ignore daily volatility
- Focus on business fundamentals
- Be patient and disciplined

## 🚀 Next Steps

1. ✅ **Explore Dashboard:** `streamlit run ui/multibagger_dashboard.py --server.port 8502`
2. ✅ **Pick Top 5:** Focus research on highest-scored prospects
3. ✅ **Deep Dive:** Read annual reports, listen to earnings calls
4. ✅ **Paper Trade:** Test strategies in simulation first
5. ✅ **Build Watchlist:** Set alerts for entry opportunities
6. ✅ **Be Patient:** Multi-baggers take time to develop

## 📞 Support & Questions

- **Documentation:** `docs/MULTIBAGGER_ANALYSIS.md`
- **Code:** `scripts/multibagger_analysis.py`
- **Data:** `data/multibagger_analysis_report.json`

---

**Remember:** The best multi-bagger is the one you hold through volatility. 📈

*"The stock market is a device for transferring money from the impatient to the patient."* - Warren Buffett
