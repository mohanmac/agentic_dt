# Algorithmic Trading Execution Sequence - Complete Flow

**System**: Day Trading Paper Bot with 9 Strategies + 39 Guardrails  
**Last Updated**: 7 February 2026

---

## 🔄 **COMPLETE EXECUTION SEQUENCE**

### **Overview: 7 Main Phases**

```
PHASE 1: Market Data Collection
         ↓
PHASE 2: Multi-Timeframe Analysis (1H → 15M → 5M)
         ↓
PHASE 3: Strategy Evaluation (All 9 Run in Parallel)
         ↓
PHASE 4: Ensemble Decision Making (Confluence Check)
         ↓
PHASE 5: Risk Guardrails Check (39 Guardrails Applied)
         ↓
PHASE 6: Order Execution (Paper Broker Simulation)
         ↓
PHASE 7: Position Monitoring & Exit Management
```

---

## 📊 **PHASE 1: Market Data Collection**

**Duration**: 2-5 seconds  
**Frequency**: Every 1-5 minutes (configurable)

### **Step 1.1: Fetch Live Market Data**
```python
# From Zerodha Kite API or Market Scanner
data = {
    "symbol": "HINDCOPPER",
    "ltp": 100.50,           # Last Traded Price
    "open": 99.80,
    "high": 101.20,
    "low": 99.50,
    "close": 100.50,
    "volume": 1500000,       # Current volume
    "vwap": 100.20,          # Volume Weighted Average Price
    
    # Technical Indicators (calculated)
    "ema_9": 100.10,
    "ema_21": 99.80,
    "ema_50": 99.20,
    "dma_50": 98.50,
    "dma_200": 95.00,
    "rsi": 62.5,
    "bb_upper": 102.00,
    "bb_middle": 100.00,
    "bb_lower": 98.00,
    
    # Volume Analysis
    "volume_ratio": 1.8,     # Current vol / 20-day avg
    "avg_volume_20d": 833333,
    
    # Contextual
    "opening_range_high": 100.80,
    "opening_range_low": 99.70,
    "resistance": 101.00,
    "support": 99.00
}
```

### **Step 1.2: Data Validation**
```python
# Check data quality
✓ Is price data valid? (not null, not zero)
✓ Is volume data available?
✓ Are technical indicators calculated?
✓ Is data fresh? (< 1 minute old)

If any check fails → Skip this cycle, wait for next scan
```

**Output**: Validated market snapshot ready for analysis

---

## 🎯 **PHASE 2: Multi-Timeframe Analysis**

**Duration**: < 1 second  
**Purpose**: Establish market context (top-down approach)

### **Step 2.1: 1-Hour Bias Analysis**
```python
def analyze_1h_bias(stock_data):
    """
    Determines overall market bias using longer timeframe
    """
    ltp = 100.50
    ema_50 = 99.20
    ema_200 = 95.00
    
    # Check alignment
    if ltp > ema_50 > ema_200:
        return "BULLISH"      # ✅ Uptrend
    elif ltp < ema_50 < ema_200:
        return "BEARISH"      # ❌ Downtrend
    else:
        return "SIDEWAYS"     # ⚠️ No clear trend
```

**Decision**: 
- BULLISH → Allow long strategies
- BEARISH → Force WAIT (no shorts in paper trading)
- SIDEWAYS → Prefer mean reversion strategies

### **Step 2.2: 15-Minute Trend Confirmation**
```python
def analyze_15m_trend(stock_data, bias_1h):
    """
    Confirms if shorter timeframe aligns with 1H bias
    """
    ltp = 100.50
    vwap = 100.20
    
    # Trend determination
    if ltp > vwap * 1.002:      # 0.2% above VWAP
        trend_15m = "BULLISH"
    elif ltp < vwap * 0.998:    # 0.2% below VWAP
        trend_15m = "BEARISH"
    else:
        trend_15m = "SIDEWAYS"
    
    return trend_15m
```

**Gate Check**:
```python
# CRITICAL: Multi-Timeframe Gates
gate_bias_ok = (bias_1h != "BEARISH")
gate_trend_ok = (trend_15m != "BEARISH")

if not gate_bias_ok or not gate_trend_ok:
    FORCE_WAIT = True           # Block all strategies
    reason = "MTF alignment failed"
```

**Output**: 
- 1H Bias: BULLISH/BEARISH/SIDEWAYS
- 15M Trend: BULLISH/BEARISH/SIDEWAYS
- Gate Status: OPEN or CLOSED

---

## 🧠 **PHASE 3: Strategy Evaluation (All 9 Strategies)**

**Duration**: < 1 second  
**Execution**: Parallel evaluation

### **How It Works**:
All 9 strategies receive the SAME market data and analyze independently:

```python
# Strategy Engine loops through all strategies
for strategy in self.strategies:  # 9 strategies
    
    # 1. Check if strategy is valid for current regime
    current_regime = "TRENDING"  # Based on 15M trend
    
    if current_regime not in strategy.valid_regimes:
        continue  # Skip this strategy
    
    # 2. Strategy analyzes market data
    signal = strategy.analyze(stock_data)
    
    # 3. Store result
    strategy_results.append({
        "name": strategy.name,
        "action": signal.signal_type,    # BUY/SELL/WAIT
        "confidence": signal.confidence,  # 0-100
        "entry_price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "target": signal.target,
        "reason": signal.reason
    })
```

### **Example Evaluation Output**:

```
Time: 10:40 AM
Symbol: HINDCOPPER at ₹100.50
1H Bias: BULLISH
15M Trend: BULLISH
Gates: OPEN ✅

Strategy Results:
┌─────────────────────────┬────────┬────────┬────────────────────────┐
│ Strategy                │ Action │ Conf % │ Reason                 │
├─────────────────────────┼────────┼────────┼────────────────────────┤
│ 1. Momentum             │ BUY    │ 85%    │ Price > VWAP, Vol 1.8x │
│ 2. Scalping             │ WAIT   │ 0%     │ No EMA cross           │
│ 3. VWAP Pullback        │ WAIT   │ 0%     │ No pullback            │
│ 4. Breakout             │ BUY    │ 80%    │ Above resistance       │
│ 5. Mean Reversion       │ WAIT   │ 0%     │ DISABLED (trending)    │
│ 6. RSI Reversal         │ WAIT   │ 0%     │ RSI not oversold       │
│ 7. MA Crossover         │ BUY    │ 88%    │ Golden Cross active    │
│ 8. Institutional Flow   │ BUY    │ 90%    │ In inst. window + vol  │
│ 9. Stop Hunt Protection │ BUY    │ 85%    │ Breakout confirmed     │
└─────────────────────────┴────────┴────────┴────────────────────────┘

Strategies Agreeing for BUY: 5/9
Strategies Saying WAIT: 4/9
Average Confidence (BUY): 85.6%
```

**Output**: 9 independent signals with confidence scores

---

## ⚖️ **PHASE 4: Ensemble Decision Making**

**Duration**: < 0.5 seconds  
**Purpose**: Combine signals using confluence logic

### **Step 4.1: Count Agreeing Strategies**
```python
MIN_STRATEGIES_FOR_BUY = 3  # Confluence requirement

buy_count = 0
wait_count = 0
total_confidence = 0

for result in strategy_results:
    if result["action"] == "BUY":
        buy_count += 1
        total_confidence += result["confidence"]
    else:
        wait_count += 1

average_confidence = total_confidence / buy_count if buy_count > 0 else 0
```

### **Step 4.2: Apply Confluence Rules**
```python
# Rule 1: Minimum strategies must agree
if buy_count < MIN_STRATEGIES_FOR_BUY:
    ENSEMBLE_VERDICT = "WAIT"
    reason = f"Only {buy_count}/9 strategies agree (need {MIN_STRATEGIES_FOR_BUY})"

# Rule 2: Average confidence must be high enough
elif average_confidence < 70:
    ENSEMBLE_VERDICT = "WAIT"
    reason = f"Low confidence ({average_confidence:.1f}% < 70%)"

# Rule 3: Check for conflicting signals
elif buy_count == wait_count:
    ENSEMBLE_VERDICT = "WAIT"
    reason = "Split decision, no clear consensus"

# All checks passed
else:
    ENSEMBLE_VERDICT = "BUY"
    reason = f"{buy_count} strategies agree at {average_confidence:.1f}% confidence"
```

### **Step 4.3: Calculate Bull/Bear Dominance**
```python
# Calculate market sentiment
bull_signals = buy_count
total_signals = len(strategy_results)

bull_dominance = (bull_signals / total_signals) * 100
bear_dominance = 100 - bull_dominance

# Example: 5 BUY signals out of 9 strategies
# Bull Dominance = 5/9 = 55.6%
```

**Output**:
```python
ensemble_decision = {
    "verdict": "BUY",
    "confidence": 85.6,
    "agreeing_strategies": 5,
    "total_strategies": 9,
    "bull_dominance": 55.6,
    "bear_dominance": 44.4,
    "reason": "Strong momentum with institutional flow"
}
```

---

## 🛡️ **PHASE 5: Risk Guardrails Check (39 Guardrails)**

**Duration**: < 1 second  
**Purpose**: Validate trade against ALL safety constraints

### **This is the CRITICAL PHASE - NO BYPASS ALLOWED**

```python
# Even if ensemble says BUY, must pass ALL guardrails
if ensemble_decision["verdict"] == "BUY":
    
    # Generate Trade Intent
    trade_intent = TradeIntent(
        symbol="HINDCOPPER",
        side="BUY",
        entry_price=100.50,
        stop_loss_price=96.98,    # 3.5% stop
        target_price=108.54,      # 8% target
        quantity=30,               # Based on position sizing
        strategy_id="institutional_flow",
        confidence_score=0.856,
        expected_risk_rupees=105.60
    )
    
    # Pass to Risk Policy Agent
    approval = risk_policy.approve(trade_intent)
```

### **Guardrail Check Sequence** (In Order):

#### **Category 1: Mandatory Hard Constraints (3 checks)**
```python
✓ 1. Max Stop Loss Check
    if stop_loss > 10%:
        REJECT("Stop loss exceeds 10% hard limit")

✓ 2. Slippage Buffer Validation
    adjusted_entry = entry_price + (entry_price * 0.001)  # 0.1%
    if adjusted_entry makes R:R < 1.0:
        REJECT("Poor risk:reward after slippage")

✓ 3. Abrupt Move Filter
    if price_gap > 2%:
        WARN("Abrupt move detected, reduce size")
```

#### **Category 2: Capital & Loss Limits (6 checks)**
```python
✓ 4. Max Capital Per Trade
    if trade_value > ₹3,000:
        REJECT("Exceeds max capital per trade")

✓ 5. Daily Loss Budget
    if daily_pnl < -200:
        REJECT("Daily loss limit reached")
        TRIGGER_SAFE_MODE()

✓ 6. Per-Trade Risk Percentage
    risk = abs(entry - stop_loss) * quantity
    if risk > (remaining_budget * 0.50):
        REJECT("Risk exceeds 50% of remaining budget")

✓ 7. Absolute Max Risk
    if risk > ₹100:
        REDUCE_QUANTITY()  # Automatically adjust

✓ 8. Remaining Loss Budget
    if expected_risk > loss_budget_remaining:
        REJECT("Would exceed remaining daily budget")

✓ 9. Brokerage Cost Factor
    total_cost = trade_value + (₹20 * 2)  # Entry + Exit
    if total_cost > available_capital:
        REJECT("Insufficient capital for brokerage")
```

#### **Category 3: Position & Exposure (5 checks)**
```python
✓ 10. Max Trades Per Day
    if trades_today >= 5:
        REJECT("Max daily trades reached")

✓ 11. Max Open Positions
    if open_positions >= 3:
        REJECT("Max concurrent positions reached")

✓ 12. Max Position Size
    position_value = ₹3,000
    total_capital = ₹9,000
    if (position_value / total_capital) > 0.40:
        REJECT("Position too large (>40% of capital)")

✓ 13. Max Portfolio Exposure
    deployed_capital = ₹6,000
    if (deployed_capital / total_capital) > 0.70:
        REJECT("Portfolio over-exposed (>70%)")

✓ 14. Max Sector Exposure
    # Check correlation between open positions
    if correlated_exposure > 50%:
        REJECT("Too much sector concentration")
```

#### **Category 4: Time-Based Guardrails (5 checks)**
```python
✓ 15. Avoid First 15 Minutes
    current_time = 10:40 AM
    if time_since_open < 15 minutes:
        REJECT("In noise period (9:15-9:30)")

✓ 16. Avoid Last 15 Minutes
    if time_until_close < 15 minutes:
        REJECT("Too close to market close")

✓ 17. Min Hold Time Between Trades
    last_trade_time = 10:30 AM
    if (current_time - last_trade_time) < 5 minutes:
        REJECT("Trade too soon after last one")

✓ 18. Force Exit Time
    if current_time >= 3:00 PM:
        FORCE_EXIT_ALL_POSITIONS()

✓ 19. Preferred Entry Window (Soft)
    if current_time in [10:30-11:30 or 1:30-2:30]:
        BOOST_CONFIDENCE(+5%)  # Institutional window
```

#### **Category 5: Drawdown & Streak Protection (4 checks)**
```python
✓ 20. Max Drawdown from Peak
    peak_capital = ₹10,000
    current_capital = ₹8,500
    drawdown = (10000 - 8500) / 10000 = 15%
    if drawdown >= 15%:
        TRIGGER_SAFE_MODE()

✓ 21. Consecutive Loss Limit
    if consecutive_losses >= 3:
        HALT_TRADING("Max consecutive losses")

✓ 22. Trailing Stop Activation
    if unrealized_profit >= 2%:
        ACTIVATE_TRAIL_STOP()

✓ 23. Trailing Stop Distance
    enabled_trail_at = ₹102
    current_price = ₹108
    peak_price = ₹108
    trail_stop = peak * 0.99 = ₹106.92
```

#### **Category 6: Market Condition Filters (4 checks)**
```python
✓ 24. VIX Threshold
    india_vix = 28
    if india_vix > 30:
        PAUSE_NEW_TRADES("High volatility")

✓ 25. Spread Width Check
    bid = ₹100.40
    ask = ₹100.60
    spread = (ask - bid) / bid = 0.2%
    if spread > 0.5%:
        REJECT("Spread too wide - illiquid")

✓ 26. Volume Confirmation
    current_volume = 1,500,000
    avg_volume = 833,333
    ratio = 1.8x
    if ratio < 1.5:
        REJECT("Insufficient volume")

✓ 27. Gap Handling
    gap = (open - prev_close) / prev_close
    if gap > 5%:
        APPLY_SPECIAL_RULES()
        REDUCE_POSITION_SIZE()
```

#### **Category 7: Order Execution Safeguards (2 checks)**
```python
✓ 28. Order Rate Limiting
    orders_this_minute = 2
    if orders_this_minute >= 10:
        REJECT("Too many orders per minute")

✓ 29. Price Deviation Check
    signal_generated_at = 10:39:58 AM (₹100.50)
    execution_time = 10:40:02 AM (₹101.20)
    price_moved = (101.20 - 100.50) / 100.50 = 0.7%
    if price_moved > 1.0%:
        REJECT("Price moved too much, signal stale")
```

#### **Category 8: Strategy Requirements (4 checks)**
```python
✓ 30. Min Confluence
    agreeing_strategies = 5
    if agreeing_strategies < 3:
        REJECT("Insufficient strategy agreement")

✓ 31. Min Signal Score
    ensemble_confidence = 85.6
    if ensemble_confidence < 80:
        REJECT("Signal not strong enough")

✓ 32. Strategy Switch Cooldown
    last_strategy = "momentum"
    new_strategy = "institutional_flow"
    time_since_switch = 25 minutes
    if time_since_switch < 20 minutes:
        REJECT("Strategy switch too soon")

✓ 33. Strategy Switch Improvement
    if switching_strategy:
        if new_confidence < (old_confidence + 15%):
            REJECT("Not enough improvement to switch")
```

#### **Category 9: HITL Triggers (3 checks)**
```python
✓ 34. First N Trades
    trades_today = 1
    if trades_today < 2:
        REQUIRE_HITL_APPROVAL()
        PAUSE_EXECUTION()

✓ 35. Low Confidence Threshold
    if confidence < 70%:
        REQUIRE_HITL_APPROVAL()

✓ 36. Strategy Switch
    if strategy_changed:
        REQUIRE_HITL_APPROVAL()
        NOTIFY_HUMAN()
```

#### **Category 10: Multi-Timeframe Gates (2 checks)**
```python
✓ 37. 1H Bias Alignment
    if bias_1h == "BEARISH":
        REJECT("1H timeframe bearish")

✓ 38. 15M Trend Alignment
    if trend_15m == "BEARISH":
        REJECT("15M timeframe bearish")
```

#### **Category 11: Safe Mode (2 checks)**
```python
✓ 39. Safe Mode Status
    if safe_mode_active:
        REJECT_ALL_TRADES()
        REQUIRE_MANUAL_RESET()
```

### **Final Approval Decision**:
```python
if all_39_guardrails_passed:
    approval = RiskApproval(
        approved=True,
        adjusted_quantity=30,  # May be reduced for risk
        hitl_required=True,    # If trades < 2
        safe_mode_active=False,
        remaining_loss_budget=₹195,
        guardrail_flags={"all_clear": True}
    )
else:
    approval = RiskApproval(
        approved=False,
        rejection_reason="Guardrail #15 failed: Too close to open",
        guardrail_flags={"time_violation": True}
    )
```

**Output**: Approved or Rejected with specific reason

---

## 📝 **PHASE 6: Order Execution**

**Duration**: 0.5-2 seconds (paper), 1-5 seconds (live)

### **If Approved**:
```python
if approval.approved:
    
    # 6.1: Check HITL Requirement
    if approval.hitl_required:
        # Store trade intent for human approval
        pending_approvals.append({
            "intent_id": 12345,
            "symbol": "HINDCOPPER",
            "action": "BUY",
            "quantity": 30,
            "entry": 100.50,
            "stop": 96.98,
            "target": 108.54,
            "reason": "First trade of the day",
            "status": "PENDING_HITL"
        })
        
        # Send notification
        NOTIFY_USER("Trade requires your approval")
        
        # Wait for human input
        PAUSE_EXECUTION()
    
    # 6.2: Execute Order (Paper Broker)
    else:
        order = broker.place_order(
            symbol="HINDCOPPER",
            side="BUY",
            quantity=30,
            order_type="MARKET",
            price=None,  # Market order
            stop_loss=96.98,
            target=108.54
        )
        
        # 6.3: Simulate Execution
        fill_price = 100.50 + (100.50 * 0.001)  # Add slippage
        fill_price = 100.60  # Final fill
        
        # 6.4: Apply Brokerage
        brokerage = ₹20
        
        # 6.5: Create Position
        position = Position(
            symbol="HINDCOPPER",
            side="BUY",
            quantity=30,
            entry_price=100.60,
            current_price=100.60,
            stop_loss=96.98,
            target=108.54,
            unrealized_pnl=0.00,
            strategy="institutional_flow",
            entry_time="10:40:05"
        )
        
        # 6.6: Update Daily Stats
        daily_stats.total_trades += 1
        daily_stats.deployed_capital += 3018  # ₹3018 invested
        
        # 6.7: Log Trade
        log_event("trade_executed", {
            "symbol": "HINDCOPPER",
            "action": "BUY",
            "quantity": 30,
            "fill_price": 100.60,
            "expected_risk": 105.60,
            "expected_reward": 238.20
        })
```

**Output**: Open position with active monitoring

---

## 👁️ **PHASE 7: Position Monitoring & Exit Management**

**Duration**: Continuous (every 10-30 seconds while position open)

### **Monitoring Loop**:
```python
while position.is_open:
    
    # 7.1: Fetch Current Price
    current_price = get_live_price("HINDCOPPER")
    
    # 7.2: Update Position Metrics
    position.current_price = current_price
    position.unrealized_pnl = (current_price - entry_price) * quantity
    position.unrealized_pnl_percent = ((current_price / entry_price) - 1) * 100
    
    # 7.3: Update Peak Price (for trailing stop)
    if current_price > position.peak_price:
        position.peak_price = current_price
    
    # 7.4: Check Exit Conditions (In Priority Order)
    
    # EXIT 1: Stop Loss Hit
    if current_price <= position.stop_loss:
        EXIT_POSITION("Stop loss hit")
        realized_pnl = -105.60  # Max loss
        break
    
    # EXIT 2: Target Hit
    if current_price >= position.target:
        EXIT_POSITION("Target achieved")
        realized_pnl = +238.20  # Full profit
        break
    
    # EXIT 3: Trailing Stop
    if position.trailing_stop_active:
        trail_stop = position.peak_price * 0.99  # 1% trail
        if current_price <= trail_stop:
            EXIT_POSITION("Trailing stop triggered")
            realized_pnl = (current_price - entry) * quantity
            break
    
    # EXIT 4: Time-Based Force Exit
    current_time = get_current_time()
    if current_time >= "15:00:00":
        EXIT_POSITION("End of day force exit")
        realized_pnl = position.unrealized_pnl
        break
    
    # EXIT 5: Structure Break
    if current_price < vwap:
        if position.strategy == "vwap_pullback":
            EXIT_POSITION("VWAP support broken")
            realized_pnl = position.unrealized_pnl
            break
    
    # EXIT 6: Volume Divergence
    if price_up but volume_down:
        EXIT_POSITION("Volume divergence detected")
        realized_pnl = position.unrealized_pnl
        break
    
    # EXIT 7: MTF Alignment Break
    if bias_1h changes to "BEARISH":
        EXIT_POSITION("Multi-timeframe alignment broken")
        realized_pnl = position.unrealized_pnl
        break
    
    # 7.5: Update Trailing Stop Logic
    pnl_percent = position.unrealized_pnl_percent
    
    if pnl_percent >= 2.0 and not position.trailing_stop_active:
        # Activate trailing stop
        position.trailing_stop_active = True
        position.stop_loss = position.entry_price  # Move to breakeven
        log_event("trailing_stop_activated")
    
    if pnl_percent >= 5.0:
        # Tighten trail
        position.stop_loss = position.peak_price * 0.99
    
    if pnl_percent >= 8.0:
        # Very tight trail
        position.stop_loss = position.peak_price * 0.995
    
    # 7.6: Partial Exits (Scale Out)
    if pnl_percent >= 3.0 and not position.partial_exit_1_done:
        # Exit 30% at first target
        exit_quantity = int(quantity * 0.30)
        PARTIAL_EXIT(exit_quantity, "Target 1: +3%")
        position.quantity -= exit_quantity
        position.partial_exit_1_done = True
    
    if pnl_percent >= 6.0 and not position.partial_exit_2_done:
        # Exit 50% more at second target
        exit_quantity = int(quantity * 0.50)
        PARTIAL_EXIT(exit_quantity, "Target 2: +6%")
        position.quantity -= exit_quantity
        position.partial_exit_2_done = True
    
    # 7.7: Wait for next price update
    sleep(10 seconds)
```

### **Exit Execution**:
```python
def EXIT_POSITION(reason):
    # 1. Get exit price
    exit_price = get_live_price("HINDCOPPER")
    
    # 2. Apply slippage
    exit_price_with_slippage = exit_price - (exit_price * 0.001)
    
    # 3. Calculate realized P&L
    gross_pnl = (exit_price - entry_price) * quantity
    brokerage = ₹20 * 2  # Entry + Exit
    net_pnl = gross_pnl - brokerage
    
    # 4. Update daily stats
    daily_stats.total_pnl += net_pnl
    daily_stats.loss_budget_remaining -= max(0, -net_pnl)
    
    if net_pnl < 0:
        daily_stats.consecutive_losses += 1
    else:
        daily_stats.consecutive_losses = 0
    
    # 5. Check for safe mode trigger
    if daily_stats.loss_budget_remaining <= 0:
        TRIGGER_SAFE_MODE()
    
    # 6. Log exit
    log_event("position_closed", {
        "symbol": "HINDCOPPER",
        "entry": 100.60,
        "exit": exit_price,
        "pnl": net_pnl,
        "pnl_percent": ((exit_price / entry_price) - 1) * 100,
        "hold_time_minutes": 45,
        "reason": reason
    })
    
    # 7. Close position
    position.is_open = False
    position.exit_price = exit_price
    position.realized_pnl = net_pnl
    position.exit_time = current_time
    position.exit_reason = reason
```

**Output**: Closed position with realized P&L

---

## 🔄 **COMPLETE TIMING BREAKDOWN**

### **Single Trading Cycle**:
```
Phase 1: Data Collection        → 2-5 seconds
Phase 2: MTF Analysis           → 0.5 seconds
Phase 3: Strategy Evaluation    → 1 second
Phase 4: Ensemble Decision      → 0.5 seconds
Phase 5: Guardrail Checks       → 1 second
Phase 6: Order Execution        → 1 second
──────────────────────────────────────────────
TOTAL: Entry Decision           → 6-9 seconds

Phase 7: Position Monitoring    → Every 10-30 seconds
         Until exit (avg 30-120 minutes)
```

### **Daily Timeline Example**:
```
9:15 AM: Market Opens
         ↓
9:15-9:30 AM: WAIT (Guardrail #15 blocks all trades)
         ↓
9:30 AM: First scan cycle begins
         → Data collection
         → MTF analysis: 1H BULLISH, 15M BULLISH ✓
         → 9 strategies evaluate
         → Only 2 say BUY (need 3) → WAIT
         ↓
10:00 AM: Second scan cycle
         → 9 strategies evaluate
         → 3 say BUY (meets threshold) → Proceed
         → Guardrails check: 38/39 pass
         → Guardrail #34 fails: First trade needs HITL
         → Trade pending human approval
         ↓
10:05 AM: Human approves trade
         → Order executed at ₹100.60
         → Position opened
         ↓
10:05-11:45 AM: Position monitoring (100 cycles)
         → Price: ₹100.60 → ₹104.50 → ₹107.20 → ₹108.50
         → Trailing stop activated at ₹102.00 (+2%)
         → Partial exit 30% at ₹103.60 (+3%)
         → Partial exit 50% at ₹106.60 (+6%)
         ↓
11:45 AM: Target hit at ₹108.50 (+8%)
         → Exit remaining 20%
         → Position closed
         → Net P&L: +₹238.20 (after brokerage)
         ↓
12:00 PM: Third scan cycle
         → MTF still BULLISH
         → 5 strategies say BUY
         → Guardrails pass (no HITL needed for 2nd trade)
         → New trade executed
         ↓
... continues until 3:00 PM
         ↓
3:00 PM: Force exit all positions
         Daily stats updated
         Safe mode check
         Next day preparation
```

---

## 🎯 **KEY TAKEAWAYS**

### **1. Sequential but Efficient**
- Phases must execute IN ORDER (cannot skip)
- Each phase has specific responsibilities
- Total decision time: 6-9 seconds

### **2. Guardrails are Non-Negotiable**
- ALL 39 guardrails checked EVERY trade
- ONE failure = trade rejected
- No way to bypass (by design)

### **3. Strategies Run in Parallel**
- All 9 strategies see same data simultaneously
- Independent analysis (no influence between strategies)
- Results combined only in Phase 4

### **4. Multiple Layers of Protection**
- Strategy level (individual risk checks)
- Ensemble level (confluence requirements)
- Guardrail level (comprehensive safety)
- Execution level (slippage, brokerage)
- Monitoring level (continuous risk management)

### **5. Human-in-the-Loop When Needed**
- High-risk situations require approval
- But doesn't delay other monitoring
- System continues to protect open positions

---

## 📊 **Sequence Diagram (Visual)**

```
User
 │
 │  ← ← ← ← ← ← ← ← ← ← ← ← ← ← ←
 ↓                                ↑
Market Scanner                    │
 │                                │
 ├─→ Phase 1: Collect Data        │
 │   └─→ Fetch price, volume, indicators
 │                                │
 ├─→ Phase 2: MTF Analysis        │
 │   ├─→ 1H Bias (BULLISH)        │
 │   ├─→ 15M Trend (BULLISH)       │
 │   └─→ Gate Check (PASS)        │
 │                                │
 ├─→ Phase 3: Strategy Eval       │
 │   ├─→ Strategy 1: BUY (85%)    │
 │   ├─→ Strategy 2: WAIT (0%)    │
 │   ├─→ Strategy 3: WAIT (0%)    │
 │   ├─→ Strategy 4: BUY (80%)    │
 │   ├─→ Strategy 5: WAIT (0%)    │
 │   ├─→ Strategy 6: WAIT (0%)    │
 │   ├─→ Strategy 7: BUY (88%)    │
 │   ├─→ Strategy 8: BUY (90%) ⭐  │
 │   └─→ Strategy 9: BUY (85%) ⭐  │
 │                                │
 ├─→ Phase 4: Ensemble            │
 │   ├─→ Count: 5 BUY, 4 WAIT     │
 │   ├─→ Confluence: ✓ (need 3)   │
 │   ├─→ Confidence: 85.6%        │
 │   └─→ VERDICT: BUY             │
 │                                │
 ├─→ Phase 5: Guardrails (39)     │
 │   ├─→ Check #1-10: ✓ PASS      │
 │   ├─→ Check #11-20: ✓ PASS     │
 │   ├─→ Check #21-30: ✓ PASS     │
 │   ├─→ Check #31-34: ⚠️ HITL    │
 │   └─→ Check #35-39: ✓ PASS     │
 │         │                      │
 │         └─→ HITL Required ─────┤
 │             (Human Approval)    │
 │                                │
 ├─→ Phase 6: Execute Order       │
 │   ├─→ Place Order              │
 │   ├─→ Fill at ₹100.60          │
 │   ├─→ Create Position           │
 │   └─→ Start Monitoring          │
 │                                │
 └─→ Phase 7: Monitor Position    │
     ├─→ Update P&L (every 10s)   │
     ├─→ Check exits (7 types)    │
     ├─→ Trail stop management    │
     ├─→ Partial exits            │
     └─→ Final exit ─────────────→┘
         (Close position, update stats)
```

---

**Document Version**: 1.0  
**Last Updated**: 7 February 2026  
**Purpose**: Technical reference for algorithmic execution flow
