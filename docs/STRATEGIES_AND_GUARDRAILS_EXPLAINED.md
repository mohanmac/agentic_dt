# Trading Strategies & Risk Guardrails - Simple Explanation

## Complete System Overview (9 Strategies + 39 Guardrails)

This document explains all 48 checks that every trade goes through in simple, everyday language.

---

| # | Name | What It Does (Simple Terms) | What Happens When It Matches |
|---|------|------------------------------|------------------------------|
| **TRADING STRATEGIES (9)** | | | |
| 1 | **Momentum Strategy** | Looks for stocks moving up fast like a rocket | Bot buys when price is climbing strongly with high volume |
| 2 | **Scalping Strategy** | Catches small quick profits in minutes | Bot makes fast trades to grab 0.5-1% profit and exits immediately |
| 3 | **VWAP Pullback Strategy** | Waits for price to dip below average, then bounce back | Bot buys when price temporarily drops below VWAP then recovers |
| 4 | **Breakout Strategy** | Watches for stock breaking above resistance like breaking a ceiling | Bot buys when price crosses above recent high with strong volume |
| 5 | **Mean Reversion Strategy** | Bets that extreme moves will correct themselves | Bot buys oversold stocks expecting them to bounce back to normal |
| 6 | **RSI Reversal Strategy** | Finds stocks that dropped too much and are due to recover | Bot buys when RSI shows stock is oversold (<30) and turning up |
| 7 | **MA Crossover Trend Strategy** | Detects when short-term trend crosses above long-term trend | Bot buys when fast moving average crosses above slow moving average |
| 8 | **Institutional Flow Strategy** | Follows "smart money" (big investors) buying patterns | Bot buys during 10:30-11:30 AM or 1:30-2:30 PM when institutions are active |
| 9 | **Stop Hunt Protection Strategy** | Avoids times when big players deliberately trigger stop losses | Bot skips trading during 9:15-9:30 AM to avoid manipulation traps |
| **CAPITAL & RISK GUARDRAILS (8)** | | | |
| 10 | **Max Capital Per Trade** | Limits how much money you risk on one trade | Trade rejected if it needs more than ₹3,000 |
| 11 | **Max Loss Per Day** | Sets daily loss limit like a spending budget | Trading stops if total losses exceed ₹300 for the day |
| 12 | **Per-Trade Max Loss** | Limits loss on each trade to 50% of allocated money | Trade rejected if potential loss is more than ₹500 |
| 13 | **Absolute Max Risk** | Hard limit on loss amount per trade | Trade blocked if potential loss exceeds ₹100 |
| 14 | **Paper Brokerage Cost** | Accounts for trading fees (₹20 per order) | Every trade cost includes ₹20 brokerage in profit calculation |
| 15 | **Capital Exhaustion Check** | Prevents trading when funds run low | Trading stops if available capital drops below ₹600 |
| 16 | **Minimum Trade Size** | Ensures trade is worth the brokerage cost | Trade rejected if value is less than ₹500 (not worth ₹20 fee) |
| 17 | **Reserve Fund Protection** | Keeps emergency buffer untouched | Always maintains ₹2,000 reserve, never trades with it |
| **POSITION & EXPOSURE GUARDRAILS (5)** | | | |
| 18 | **Max Trades Per Day** | Limits number of trades like daily transaction limit | No more than 5 trades allowed per day |
| 19 | **Max Open Positions** | Limits how many stocks you can hold at once | Cannot buy new stock if already holding 3 stocks |
| 20 | **Max Position Size** | Limits investment in single stock (40% of capital) | Cannot invest more than ₹4,000 in one stock |
| 21 | **Max Portfolio Exposure** | Limits total invested amount (80% of capital) | Cannot have more than ₹8,000 total invested across all stocks |
| 22 | **Max Sector Exposure** | Prevents over-investing in one industry | Cannot invest more than 30% in same sector (e.g., metals) |
| **TIME-BASED GUARDRAILS (5)** | | | |
| 23 | **Avoid First 15 Minutes** | Skips trading during market opening chaos | No trades between 9:15-9:30 AM due to volatility |
| 24 | **Avoid Last 30 Minutes** | Skips trading near market closing time | No new trades after 3:00 PM to avoid closing rush |
| 25 | **Minimum Hold Time** | Prevents panic selling too quickly | Cannot sell stock before holding for 30 minutes |
| 26 | **Maximum Position Age** | Forces exit if holding too long | Auto-sells if holding same stock for more than 4 hours |
| 27 | **Force Exit By 3:00 PM** | Ensures all positions closed before market closes | All stocks automatically sold by 3:00 PM (square-off) |
| **DRAWDOWN & STREAK GUARDRAILS (4)** | | | |
| 28 | **Max Drawdown (15%)** | Stops trading if losses exceed 15% of starting capital | Trading halts if you lose ₹1,500 from ₹10,000 starting amount |
| 29 | **Max Consecutive Losses** | Stops trading after 3 losses in a row | Trading paused if 3 trades in a row resulted in losses |
| 30 | **Trailing Stop Activation** | Locks in profits once stock moves up 5% | When stock gains 5%, stop-loss moves up to protect profit |
| 31 | **Trailing Stop Distance** | Keeps stop-loss 2% below highest price | Stop-loss stays 2% below peak price as stock climbs |
| **MARKET FILTER GUARDRAILS (4)** | | | |
| 32 | **Max VIX Threshold** | Avoids trading when market fear is high | No trades if VIX (fear index) is above 30 |
| 33 | **Max Spread Limit** | Avoids stocks with large buy-sell price gap | Trade rejected if bid-ask spread exceeds 0.5% |
| 34 | **Minimum Volume** | Ensures stock has enough buyers/sellers | Trade rejected if volume is less than 1.5x average |
| 35 | **Maximum Gap Protection** | Avoids stocks that opened with huge price jump | No trades if stock opened more than 3% away from yesterday's close |
| **ORDER SAFETY GUARDRAILS (2)** | | | |
| 36 | **Max Orders Per Minute** | Prevents accidental rapid-fire orders | Cannot place more than 2 orders within 1 minute |
| 37 | **Max Price Deviation** | Ensures order price is close to market price | Order rejected if price differs more than 0.5% from last traded price |
| **STRATEGY REQUIREMENT GUARDRAILS (4)** | | | |
| 38 | **Minimum Confluence** | Requires multiple strategies to agree | Trade needs at least 3 out of 9 strategies voting "BUY" |
| 39 | **Minimum Signal Score** | Ensures trade quality is high enough | Trade needs combined strategy score of at least 80/100 |
| 40 | **Strategy Switch Cooldown** | Prevents frequent strategy changes | Must wait 20 minutes before switching active strategies |
| 41 | **Minimum Improvement Required** | New strategy must be significantly better | New strategy must be 15% better to replace current one |
| **HUMAN-IN-THE-LOOP TRIGGERS (3)** | | | |
| 42 | **First Two Trades Approval** | Requires your confirmation for first 2 trades | Bot asks for your approval before placing first 2 trades of the day |
| 43 | **Low Confidence Alert** | Warns when bot is uncertain | Bot asks for confirmation if confidence is below 70% |
| 44 | **Strategy Switch Notification** | Alerts when bot changes strategy | Bot notifies you when it switches from one strategy to another |
| **MULTI-TIMEFRAME GUARDRAILS (2)** | | | |
| 45 | **1-Hour Bias Alignment** | Checks if hourly trend supports the trade | Trade rejected if 1-hour chart shows opposite trend |
| 46 | **15-Minute Trend Alignment** | Checks if 15-min trend supports the trade | Trade rejected if 15-minute chart doesn't confirm trend |
| **SAFE MODE GUARDRAILS (2)** | | | |
| 47 | **Auto Safe Mode Trigger** | Emergency brake when things go wrong | Auto-activates when daily loss limit reached or 3 consecutive losses |
| 48 | **Manual Reset Required** | Prevents bot from auto-resuming after failures | You must manually reset system after safe mode trigger |

---

## How The System Works

### Step 1: Strategy Evaluation
- Every 5 minutes, all **9 strategies** analyze each stock
- Each strategy votes: BUY, SELL, or WAIT
- At least **3 strategies must vote BUY** to proceed

### Step 2: Guardrail Validation
- Trade proposal goes through all **39 guardrails**
- If ANY guardrail says NO, trade is blocked
- Trade only executes if ALL 39 checks pass

### Step 3: Execution & Monitoring
- Trade executed at market price (with slippage buffer)
- Position monitored every 5 minutes
- Auto-exit at stop-loss, target, or 3:30 PM

---

## Visual Flow

```
Stock Data → 9 Strategies Analyze → Minimum 3 Vote BUY
                                           ↓
                                    39 Guardrails Check
                                           ↓
                                   All Must Pass (✓)
                                           ↓
                                     Execute Trade
                                           ↓
                               Continuous Monitoring
                                           ↓
                         Exit: Stop-Loss / Target / 3:30 PM
```

---

## Key Takeaways

1. **9 Strategies** = Different ways to identify good trades
2. **39 Guardrails** = Safety checks to prevent bad trades
3. **Total 48 Checks** = Every trade must pass all of them
4. **Result** = Only high-quality, low-risk trades get executed

**Think of it like airport security:** 
- 9 Strategies = Different officers looking for opportunities
- 39 Guardrails = Security checkpoints you must pass through
- Only passengers (trades) that clear ALL checks get on the plane (market)

---

*Last Updated: February 7, 2026*
