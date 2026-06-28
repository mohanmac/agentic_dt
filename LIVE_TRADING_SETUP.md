# LIVE TRADING SETUP GUIDE

## What Was Implemented

✓ **Live Trading Wired** - ExecutionPaperAgent now routes trades to LiveBroker when `ENABLE_LIVE_TRADING=true`
✓ **TradingScheduler Updated** - Creates and passes correct broker instance on startup
✓ **Monitoring Window** - New lightweight Streamlit dashboard showing real-time trading activity
✓ **Trade Tracking** - Storage layer now tracks completed trades for accurate monitoring
✓ **Next Trade Prediction** - Predicts when next trade will occur based on historical intervals
✓ **Session Locking** - Prevents duplicate trading sessions on multiple devices during market hours

---

## KEY FEATURE: Session Locking

### Problem Solved
If you accidentally run the trading script on multiple devices during market hours, only ONE will actually trade. The others automatically show the monitoring window instead.

### How It Works

**Device 1 (Primary):**
```bash
python -m app run --live
```
✓ Acquires session lock  
✓ Trading loop starts  
✓ Executes real trades  

**Device 2 (Secondary) - Same Time:**
```bash
python -m app run --live
```
✗ Session lock already held by Device 1  
✗ Trading prevented (no duplicate orders!)  
✓ Monitoring window launches instead  
✓ Shows live activity from Device 1  

**At Market Close (3:30 PM):**
- Session lock automatically released
- All devices reset for next trading day

### Benefits
- **Prevents accidental duplicate trading** - Only one device trades at a time
- **Safe multi-device access** - Other devices can monitor without interfering
- **Automatic cleanup** - No manual reset needed at market close
- **Per-device identification** - Logs show which device is trading

---

## SETUP STEPS

### 1. Configure Environment Variables

Create/update your `.env` file in the project root:

```
ENABLE_LIVE_TRADING=true
KITE_API_KEY=<your_zerodha_api_key>
KITE_API_SECRET=<your_zerodha_api_secret>
DAILY_CAPITAL=2000
MAX_DAILY_LOSS=200
```

### 2. Authenticate with Zerodha

Run the authentication flow (only needed once):

```bash
python -m app auth
```

This will:
- Open a browser to Zerodha login
- Redirect you back with a request token
- Exchange it for an access token
- Save token to `data/tokens.json` (secured, permission: 600)

### 3. Fund Your Trading Account

Login to Zerodha and ensure your account has at least **₹2000 INR** available for trading.

### 4. Run Live Trading

**Terminal 1 - Start main trading loop:**

```bash
python -m app run --live
```

You'll be prompted:
```
Type 'YES I UNDERSTAND' to proceed with live trading:
```

The loop will:
- Check trading hours (9:15 AM - 3:15 PM IST)
- Scan eligible stocks every 60 seconds
- Evaluate strategies
- Place real orders on Zerodha
- Monitor positions with stop-loss/target exits
- Auto-close all positions by 3:00 PM

**Terminal 2 - Open monitoring window:**

```bash
streamlit run ui/monitoring_window.py --logger.level=error
```

This opens a dashboard showing:
- **Trading Mode**: LIVE / PAPER / SAFE_MODE
- **Trades Completed Today**: Count and percentage
- **P&L**: Daily profit/loss (green = profit, red = loss)
- **Loss Budget Remaining**: Amount left before auto-halt
- **Next Trade Prediction**: Estimated time + confidence %
- **Monitoring Status**: "Code is monitoring..." with spinning indicator

---

## MONITORING WINDOW FEATURES

### Real-Time Status Indicator

```
✓ LIVE TRADING ACTIVE          (Green background)
📄 PAPER TRADING               (Blue background)
🛑 SAFE MODE - NO TRADING      (Red background)
```

### Key Metrics

| Metric | What It Shows | Action if Red |
|--------|---------------|----|
| **Trades Today** | N/M trades completed | Move to next trade if within limits |
| **Daily P&L** | Profit/Loss in rupees | May trigger SAFE_MODE if < -200 |
| **Loss Budget** | ₹ remaining before halt | Stays positive or trading stops |

### Next Trade Prediction

Shows intelligent prediction based on:
- Last trade timestamp
- Average interval between trades
- Market regime (fewer trades in sideways markets)
- Confidence percentage (30-100%)

```
Example:
Next Trade Predicted: 10:45:30 (5m 23s from now)
Confidence: 78%
Reason: Avg interval: 5 min
```

---

## HOW IT WORKS

### Execution Flow (Live Mode)

```
Market Data Collection
       ↓
Strategy Evaluation (9 strategies)
       ↓
Risk Guardrails Check (39 guardrails)
       ↓
RiskPolicyAgent Approval
       ↓
ExecutionPaperAgent Routes to:
    ├─→ LiveBroker.place_order()  [if ENABLE_LIVE_TRADING=true]
    └─→ PaperBroker.place_order() [if ENABLE_LIVE_TRADING=false]
       ↓
Order placed on Zerodha
       ↓
Position Monitoring (stop-loss/target)
       ↓
Exit Management (profit target or stop-loss)
       ↓
Trade Recording & Monitoring Update
```

### Safety Features

1. **SAFE_MODE Auto-Trigger**
   - Triggered when daily loss exceeds ₹200 (or `MAX_DAILY_LOSS`)
   - Halts all new trades
   - Monitoring window shows red
   - Manual reset required

2. **Position Monitoring**
   - Stop-loss checked every minute
   - Target profit auto-exits
   - Force exit at 3:00 PM

3. **Risk Guardrails** (All enforced for LIVE trades too)
   - Max position size per trade
   - Daily loss limits
   - Strategy switch controls
   - Order rate limiting
   - Low confidence HITL

---

## IMPORTANT WARNINGS

⚠️ **REAL MONEY AT RISK**
- Every trade places a REAL order on Zerodha
- Capital is deployed from your funded account
- Losses are real, not simulated

⚠️ **TESTING FIRST**
- Run in PAPER mode first to verify strategies
- Check market conditions & trends
- Validate guardrails work correctly

⚠️ **MONITORING REQUIRED**
- Keep monitoring window open
- Check for SAFE_MODE triggers
- Monitor P&L regularly

---

## TROUBLESHOOTING

### "Authentication failed" error
**Fix:**
```bash
rm data/tokens.json          # Remove old token
python -m app auth          # Re-authenticate
```

### "No orders placed" in live trading
**Check:**
1. Is monitoring window showing "LIVE TRADING ACTIVE"?
2. Is capital budget remaining > 0?
3. Are strategies finding opportunities? (check logs)
4. Is SAFE_MODE active? (red indicator)

### "Orders rejected by guardrails"
**Likely causes:**
- Stop-loss too far > 10% (hard limit)
- Daily loss budget exhausted
- Already at max trades per day
- price outside ±1% of LTP

### Window not updating
**Fix:**
```bash
streamlit run ui/monitoring_window.py --logger.level=error --client.showErrorDetails=false
```

### "Trading session already active on device X"
This is expected behavior! **Do NOT kill the message.** Instead:

1. **This is GOOD** - It means session locking is working
2. **Monitoring window will launch automatically** in Terminal 2
3. **Use it to view the active session** from Device X
4. **At 3:30 PM**, session lock is released automatically
5. **Tomorrow, start a new session normally**

If you truly need to force a session from a different device:
```bash
# Delete old lock (ONLY if you're sure previous device is not running)
python -c "from app.core.storage import storage; storage.release_session_lock()"

# Then start trading
python -m app run --live
```

---

## COMMAND REFERENCE

```bash
# Authentication (one-time)
python -m app auth

# Paper trading (safe mode)
python -m app run --paper

# Live trading (REAL MONEY)
python -m app run --live

# Reset daily state
python -m app reset

# Monitoring window
streamlit run ui/monitoring_window.py --logger.level=error

# Verify implementation
python verify_live_trading.py

# Test session locking
python test_session_locking.py

# Force release session lock (use cautiously!)
python -c "from app.core.storage import storage; storage.release_session_lock()"
```

---

## FILES MODIFIED/CREATED

### Modified
- `app/agents/execution_paper.py` - Added broker routing logic
- `app/core/scheduler.py` - Initialize broker based on mode + session locking
- `app/core/storage.py` - Added monitoring methods

### Created
- `ui/monitoring_window.py` - Lightweight monitoring dashboard
- `verify_live_trading.py` - Setup verification script

---

## CAPITAL ALLOCATION (₹2000)

With your ₹2000, the system enforces:

| Limit | Amount | Purpose |
|-------|--------|---------|
| **Daily Capital** | ₹2000 | Total capital available |
| **Max Loss/Day** | ₹200 (10%) | Triggers SAFE_MODE |
| **Position Size** | ₹800 max (40%) | Per stock limit |
| **Per Trade Risk** | ₹100 max | Stop-loss distance |
| **Reserve Fund** | ₹1000 min | Dry powder for contingency |

**Example Trade:**
- Entry: ₹100 @ ₹100 → 10 quantity
- Stop: ₹96.50 (3.5% loss)
- Max loss: ₹35 (+ ₹40 brokerage × 2 = ₹75 total risk)
- Target: ₹110 (10% gain = ₹100 profit)
- Ratio: 1:1.33 risk/reward

---

## NEXT STEPS

1. ✓ Run verification: `python verify_live_trading.py`
2. ✓ Set up .env with credentials
3. ✓ Run: `python -m app auth`
4. ✓ Fund account with ₹2000+
5. ✓ Test in paper mode first: `python -m app run --paper`
6. ✓ Start live trading: `python -m app run --live`
7. ✓ Open monitoring: `streamlit run ui/monitoring_window.py --logger.level=error`

---

**Questions?** Check logs in `logs/` directory for detailed error messages.
