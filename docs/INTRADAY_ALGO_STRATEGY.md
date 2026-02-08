# Intraday Algorithmic Trading Strategy - Market Intelligence Driven

**Report Date**: 7 February 2026  
**Market Regime**: Markup/Expansion Phase (78% probability)  
**Bull Dominance**: 79% (Bulls in Control)  
**Institutional Flow**: Accumulation (73% probability)

---

## 🎯 CORE STRATEGY: Momentum Following with Institutional Bias

### A. Strategy Selection & Weighting

Based on 2-year historical performance:

| Strategy | Win Rate | Status | Weight |
|----------|----------|--------|--------|
| **Momentum Breakout** | 58% | ✅ PRIMARY | 40% |
| **VWAP Pullback** | 65% | ✅ SECONDARY | 30% |
| **Gap & Go** | N/A | ✅ ACTIVE | 20% |
| **Mean Reversion** | 35% | ❌ DISABLED | 0% |
| **Bollinger Squeeze** | N/A | ⚠️ CAUTION | 10% |

**Implementation**:
```python
STRATEGY_WEIGHTS = {
    "momentum_breakout": 0.40,
    "vwap_crossover": 0.30,
    "gap_and_go": 0.20,
    "bollinger_squeeze": 0.10,
    "mean_reversion": 0.00  # DISABLED IN TRENDING MARKETS
}

# Only trade when min 3 strategies agree (confluence)
MIN_STRATEGY_CONFLUENCE = 3
```

---

## ⏰ B. Optimal Intraday Entry Windows

### **PRIMARY ZONE: Late Morning Accumulation**
- **Time**: 10:30 AM - 11:30 AM
- **Reason**: Institutional volume anomaly detected (1.5x avg)
- **Action**: Prioritize entries during this window

### **SECONDARY ZONE: Post-Lunch Continuation**
- **Time**: 1:30 PM - 2:30 PM  
- **Reason**: Trend continuation after lunchtime consolidation

### **AVOID ZONES**
- ❌ 9:15 AM - 9:30 AM (High noise, stop hunts)
- ❌ 3:00 PM - 3:30 PM (Exit only)

**Implementation**:
```python
PREFERRED_ENTRY_HOURS = [(10, 30), (11, 30), (13, 30), (14, 30)]
AVOID_ENTRY_HOURS = [(9, 15), (9, 30), (15, 0), (15, 30)]
```

---

## 💰 C. Position Sizing for Expansion Phase

### **Trending Market Adjustments**

Given Market in Expansion (78% confidence):

| Parameter | Conservative | Expansion Mode | Reasoning |
|-----------|-------------|----------------|-----------|
| **Capital/Trade** | ₹2,000 | **₹3,000** | Capture larger moves |
| **Max Positions** | 2 | **3** | Multiple momentum plays |
| **Max Trades/Day** | 5 | **3-4** | Quality > Quantity |
| **Per-Trade Risk** | 2% | **3-4%** | Wider stops needed |

**Stop Loss Strategy**:
```python
# Expansion Phase Stop Loss Logic
INITIAL_STOP_DISTANCE = 0.035  # 3.5% for trending
TRAIL_STOP_ACTIVATION = 0.02   # Activate at 2% profit
TRAIL_STOP_DISTANCE = 0.01     # Trail 1% behind peak

# Hard Constraint
MAX_STOP_LOSS = 0.10  # Still 10% max
```

---

## 📊 D. Momentum Strategy Configuration

### **Entry Criteria (ALL must be TRUE)**

1. **Institutional Confirmation**
   - Price > VWAP (bullish structure detected)
   - Volume > 1.5x 20-day average
   - Ask-side absorption at resistance

2. **Technical Alignment**
   - Price > EMA 9 > EMA 21 > EMA 50 (Full Bull Stack)
   - RSI > 50 (no bearish divergence)
   - Higher Highs + Higher Lows on 15m & 1H

3. **Multi-Timeframe Confluence**
   - 1H Bias: BULLISH
   - 15m Trend: BULLISH
   - 5m Entry: Breakout above consolidation

**Entry Types**:
```python
# 1. Breakout Entry (Momentum)
if (price > resistance) and (volume > 1.5 * avg_volume):
    if (price > vwap) and (rsi > 50):
        ENTRY = "BREAKOUT_LONG"
        TARGET = entry + (entry * 0.08)  # 8% target
        STOP = entry - (entry * 0.035)   # 3.5% stop

# 2. VWAP Pullback Entry
if (price < vwap * 1.005) and (price > vwap * 0.995):
    if (trend_15m == "BULLISH") and (volume_surge):
        ENTRY = "VWAP_PULLBACK"
        TARGET = entry + (entry * 0.05)  # 5% target
        STOP = vwap * 0.97               # Below VWAP

# 3. Gap & Go (Morning Only)
if (time < 10:00) and (gap_percent > 2.0):
    if (volume > 2.0 * avg_volume) and (price_holding_above_open):
        ENTRY = "GAP_AND_GO"
        TARGET = entry + (gap_size * 1.5)
        STOP = opening_price
```

---

## 🛡️ E. Risk Management in Trending Markets

### **Dynamic Stop Loss Adjustment**

```python
def calculate_stop_loss(entry_price, strategy, market_regime):
    """
    Trending markets need wider stops to avoid stop-hunting
    """
    if market_regime == "EXPANSION":
        if strategy == "MOMENTUM_BREAKOUT":
            # Wider stop for momentum
            stop = entry_price * (1 - 0.04)  # 4%
        elif strategy == "VWAP_PULLBACK":
            # Tighter stop near VWAP
            stop = vwap * 0.97  # 3% below VWAP
    else:
        # Range-bound: Tighter stops
        stop = entry_price * (1 - 0.02)  # 2%
    
    # Never exceed hard limit
    stop = max(stop, entry_price * (1 - 0.10))
    return stop
```

### **Trailing Stop Logic**

```python
def update_trailing_stop(entry, current_price, peak_price, pnl_percent):
    """
    Lock in profits as trend extends
    """
    if pnl_percent >= 2.0:  # 2% profit
        # Move stop to breakeven
        new_stop = entry
    
    if pnl_percent >= 5.0:  # 5% profit
        # Trail 1% behind peak
        new_stop = peak_price * 0.99
    
    if pnl_percent >= 8.0:  # 8% profit
        # Tighten trail to 0.5%
        new_stop = peak_price * 0.995
    
    return new_stop
```

---

## 🚨 F. Exit Rules for Expansion Phase

### **Profit Targets** (Trending vs Range)

| Market Type | Target 1 | Target 2 | Target 3 |
|-------------|----------|----------|----------|
| **Expansion** | 3% | 6% | 10% |
| **Range-bound** | 1.5% | 3% | 5% |

### **Exit Triggers**

1. **Profit Target Hit**: Scale out (50% at T1, 30% at T2, 20% at T3)
2. **Stop Loss Hit**: Exit 100% immediately
3. **Time-Based**: Force exit by 3:00 PM (no overnight risk)
4. **Structure Break**:
   - Price closes below VWAP on 15m (warning)
   - EMA stack breaks (price < EMA 9) → Exit
5. **Volume Divergence**: Price up but volume declining → Reduce 50%
6. **Institutional Reversal**: Detect bid-side pressure → Exit

**Implementation**:
```python
# Exit Logic
def should_exit(position, current_price, time):
    pnl = (current_price - position.entry) / position.entry
    
    # 1. Profit Targets
    if pnl >= 0.10:
        return "EXIT", "Target 3 reached (10%)"
    if pnl >= 0.06:
        return "PARTIAL_EXIT", "Target 2 reached (6%) - Exit 50%"
    if pnl >= 0.03:
        return "PARTIAL_EXIT", "Target 1 reached (3%) - Exit 30%"
    
    # 2. Stop Loss
    if current_price <= position.stop_loss:
        return "EXIT", "Stop Loss Hit"
    
    # 3. Time-based
    if time.hour >= 15:
        return "EXIT", "End of day force exit"
    
    # 4. Technical Break
    if current_price < vwap and position.strategy == "VWAP_PULLBACK":
        return "EXIT", "VWAP support broken"
    
    # 5. Structure Break
    if not is_bullish_structure(current_price):
        return "EXIT", "Bullish structure broken"
    
    return "HOLD", "All systems green"
```

---

## 📋 G. Daily Pre-Market Checklist

### **Before 9:00 AM**

- [ ] Check overall market sentiment (Nifty/Sensex trend)
- [ ] Verify VIX levels (if > 30, reduce position sizes)
- [ ] Scan for stocks with pre-market volume > 1.5x avg
- [ ] Identify stocks near key breakout levels
- [ ] Review overnight institutional activity (F&O data)
- [ ] Confirm VWAP levels and opening range

### **9:15 AM - 9:30 AM (Observation)**

- [ ] Do NOT enter trades (noise period)
- [ ] Mark opening range High/Low
- [ ] Observe which stocks gap up with volume
- [ ] Note institutional interest (large orders)

### **9:30 AM+ (Action)**

- [ ] Wait for first signal confirmation
- [ ] Ensure min 3 strategies in confluence
- [ ] Verify HITL approval for first 2 trades
- [ ] Monitor risk metrics continuously

---

## 🤖 H. Algorithmic Implementation Checklist

### **Code Changes Required**

1. **Disable Mean Reversion in Trending Markets**
   ```python
   # In strategy_engine.py
   if market_regime == "EXPANSION" or bull_dominance > 70:
       DISABLED_STRATEGIES = ["mean_reversion", "rsi_oversold"]
   ```

2. **Add Preferred Entry Windows**
   ```python
   # In risk_policy.py
   def is_preferred_entry_time(current_time):
       hour = current_time.hour
       minute = current_time.minute
       
       # Late morning institutional zone
       if (hour == 10 and minute >= 30) or (hour == 11 and minute <= 30):
           return True, "INSTITUTIONAL_ZONE"
       
       # Post-lunch continuation
       if (hour == 13 and minute >= 30) or (hour == 14 and minute <= 30):
           return True, "CONTINUATION_ZONE"
       
       return False, "NEUTRAL"
   ```

3. **Dynamic Position Sizing**
   ```python
   # In risk_engine.py
   def calculate_position_size(signal, market_regime):
       base_capital = 2000
       
       if market_regime == "EXPANSION" and signal.confidence > 0.75:
           # Increase size for high-confidence trending setups
           capital = base_capital * 1.5  # ₹3,000
       else:
           capital = base_capital
       
       return capital
   ```

4. **Trailing Stop Implementation**
   ```python
   # In paper_broker.py
   def update_trailing_stops():
       for position in open_positions:
           pnl_pct = position.unrealized_pnl_percent
           
           if pnl_pct >= 2.0 and position.stop_loss < position.entry:
               # Move to breakeven
               position.stop_loss = position.entry
               log("Trailing stop activated - breakeven")
           
           if pnl_pct >= 5.0:
               # Trail 1% behind peak
               position.stop_loss = position.peak_price * 0.99
               log("Trailing stop tightened - 1% trail")
   ```

---

## 📊 I. Performance Monitoring

### **Key Metrics to Track**

1. **Win Rate by Strategy** (Target: >55% for momentum)
2. **Average Win vs Average Loss** (Target: >1.5:1 R:R)
3. **Profit Factor** (Target: >2.0)
4. **Max Drawdown** (Limit: <10% of daily capital)
5. **Entry Time Distribution** (Validate 10:30-11:30 performs best)
6. **Exit Efficiency** (% of profits captured vs theoretical max)

### **Daily Review Questions**

- Did we follow the institutional accumulation window?
- Were stop losses appropriate for trending market?
- Did we avoid mean reversion traps?
- Was confluence requirement met (3+ strategies)?
- Did trailing stops protect profits effectively?

---

## ⚠️ J. Risk Warnings & Scenarios

### **Scenario 1: Institutional Reversal**
**Warning Signs**:
- Sudden volume spike with price rejection
- VWAP acting as resistance instead of support
- RSI bearish divergence forming

**Action**: Exit 50% immediately, trail remaining 50% tightly

### **Scenario 2: Volatility Expansion Gone Wrong**
**Warning Signs**:
- Gap > 5% gets filled rapidly
- Volume dries up after breakout
- Stop-hunt wicks appear

**Action**: Exit at breakeven; wait for re-entry

### **Scenario 3: Late Day Trap**
**Warning Signs**:
- Entering after 2:30 PM
- Low volume moves
- Approaching 3:00 PM cutoff

**Action**: Avoid new entries; manage exits only

---

## 🎯 K. Expected Performance

### **Conservative Estimates** (Expansion Phase)

- **Win Rate**: 55-60% (momentum-focused)
- **Average Win**: 4-6%
- **Average Loss**: 2-3%
- **Profit Factor**: 2.0-2.5
- **Daily Target**: ₹300-500 (on ₹2000 capital base)
- **Max Drawdown**: <₹200 (daily loss limit)

### **Risk-Adjusted Return**

```
Expected Daily Return = (Win% × Avg Win) - (Loss% × Avg Loss)
                      = (0.58 × 0.05) - (0.42 × 0.025)
                      = 0.029 - 0.0105
                      = 1.85% per trade

With 3-4 trades/day = 5.5% - 7.4% daily return potential
On ₹2000 capital = ₹110-148/day expected
```

---

## 📝 Summary Action Items

### **IMMEDIATE (Today)**
1. ✅ Disable mean reversion strategy
2. ✅ Increase max capital per trade to ₹3,000
3. ✅ Set preferred entry window (10:30-11:30 AM)
4. ✅ Configure trailing stops (2% activation)
5. ✅ Increase max positions to 3

### **ONGOING (Daily)**
1. Monitor institutional flow indicators
2. Track performance by entry time window
3. Adjust stop distances based on volatility
4. Review and refine confluence requirements
5. Log all exits for pattern analysis

---

**Document Version**: 1.0  
**Last Updated**: 7 February 2026, 23:15  
**Next Review**: End of trading day (3:30 PM)
