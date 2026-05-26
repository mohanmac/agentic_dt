# A Day in the Life of Your ₹2,000 Intraday Bot

A storytelling walk-through of what happens between the moment you click **Enable bot** and the broker's automatic 3:30 PM square-off. Cast of 12 agents, each with one job, all running on their own clocks.

---

## The cast

| # | File | Character | Lives by |
|---|---|---|---|
| 1 | [agent01_data.py](app/agents/agent01_data.py) | **The Scout** | "What's the price right now?" — polls Kite quotes |
| 2 | [agent02_feature.py](app/agents/agent02_feature.py) | **The Analyst** | "What do the indicators say?" — computes RSI / EMA / VWAP / ATR |
| 3 | [agent03_trend.py](app/agents/agent03_trend.py) | **The Trend Reader** | "Which way is NIFTY bending?" — 1-hour bias filter |
| 4 | [agent04_breakout.py](app/agents/agent04_breakout.py) | **The Breakout Hunter** | "Did anyone just break out?" — opening-range breakout |
| 5 | [agent05_pullback.py](app/agents/agent05_pullback.py) | **The Patient Buyer** | "Did price tap VWAP and bounce?" — pullback setup |
| 6 | [agent06_decision.py](app/agents/agent06_decision.py) | **The Council** | "Do two of you agree?" — confluence voting |
| 7 | [agent07_risk.py](app/agents/agent07_risk.py) | **The Gatekeeper** | "Is this worth ₹200 of our capital?" — risk + spike veto |
| 8 | [agent08_execution.py](app/agents/agent08_execution.py) | **The Trader** | Places bracket order with Kite |
| 9 | [agent09_sentiment.py](app/agents/agent09_sentiment.py) | **The News Reader** | Only agent that calls the LLM (OpenAI) |
| 10 | [agent10_ml_prediction.py](app/agents/agent10_ml_prediction.py) | **The Forecaster** | Lightweight probability model |
| 11 | [agent11_monitoring.py](app/agents/agent11_monitoring.py) | **The Watchman** | Heartbeats the other 11 |
| 12 | [agent12_portfolio.py](app/agents/agent12_portfolio.py) | **The Treasurer** | Tracks funds + open positions |

---

## What "proactive" means here

Every agent has its own **background thread** (daemon) and its own **tick interval**. Nobody waits to be asked. When you click **Enable bot**, twelve clocks start at once:

| Agent | Wakes up every |
|---|---|
| Data (Scout) | 5 sec |
| Feature (Analyst) | 5 sec |
| Trend / Breakout / Pullback | 10 sec each |
| Decision / Risk / Execution | 15 sec each |
| ML Prediction | 30 sec |
| Portfolio | 30 sec |
| Monitoring | 10 sec |
| Sentiment (LLM) | 5 min |

They don't talk to each other directly. They write to a thread-safe bulletin board (`AgentBus`) and the next agent in the chain picks up what's relevant.

---

## The day, hour by hour

### Before 9:15 AM — **Pre-market, the cast is asleep**

Phase: `pre_market`. The bot is enabled but every agent's `run_once()` is a no-op because the Trading Engine reports the market is closed. Scout asks Kite for quotes anyway and gets stale ones; Analyst doesn't bother computing indicators because no new bar formed.

### 9:15 — 9:30 — **Setup phase, the engine arms itself**

Phase: `setup`. The clock crosses 9:15 IST and the Trading Engine flips its `armed` flag to `True`. Still no trades — this is the warm-up window. The Scout starts getting fresh quotes. The Analyst begins filling its first 5-minute bar. Nobody trades yet because the noisy open is coming.

### 9:30 — 10:15 — **Noisy open, observation only**

Phase: `noisy_open`. This is the most dangerous 45 minutes of the day — gap-fills, overnight news reactions, institutional opening prints. Even with all our spike filters, the bot deliberately watches but does not trade. The Decision Agent may publish candidates internally; the Risk Agent rejects them all with reason: *"Phase = noisy_open"*.

This is where The Breakout Hunter records the **first-15-minute high** of each stock — that's the threshold for an Opening Range Breakout later in the session.

### 10:15 — 14:45 — **The active phase, the only time we trade**

Phase: `active`. **This is the only window when real orders may be placed.** Here's a typical 30-second slice of what happens:

1. *(t=0s)* **The Scout** polls Kite for quotes on the top ~40 NIFTY 500 symbols and writes them to `bus["market_data"]`.
2. *(t=0s)* **The Analyst** sees fresh data, computes per-symbol features: RSI, EMA20, EMA50, VWAP, ATR, volume ratio. Writes to `bus["features"]`.
3. *(t=10s)* **The Trend Reader** checks if NIFTY's 1-hour trend is bullish AND each stock's close is above its 20-bar EMA. If both, it votes BUY. Writes to `bus["signal_trend"]`.
4. *(t=10s)* **The Breakout Hunter** asks: did this stock just close above its first-15-minute high on above-average volume? If yes, it votes BUY with an entry / stop / target. Writes to `bus["signal_breakout"]`.
5. *(t=10s)* **The Patient Buyer** asks: did price pull back to VWAP and bounce with a bullish candle? If yes, vote BUY. Writes to `bus["signal_pullback"]`.
6. *(t=15s)* **The Council** reads all three signal panels. If at least **two** of the three say BUY for the same symbol AND the combined confidence is ≥ 75, it short-lists that symbol with an entry/stop/target. Writes to `bus["decision"]`.
7. *(t=15s)* **The Gatekeeper** sweeps each decision:
   - Is the SL distance < 10%? Is target ≥ 10%?
   - Is the position size ≤ 35% of session capital (~ ₹700 of ₹2,000)?
   - Is this the 1st, 2nd, … 5th trade of the day? (Cap = 5/day)
   - Have we lost > ₹60 today? (3% of ₹2,000 → safe mode)
   - **Institutional spike veto:** Is the last bar's volume > 5× average AND price moved > 1.5× ATR? If yes → reject (probable fake breakout from a block trade). Writes rejection to `bus["risk_alerts"]` (you see it in the sidebar).
   - If all checks pass → `bus["approved_decision"]`.
8. *(t=15s)* **The Trader** reads approved decisions. Only acts if you have toggled **Auto-execute** ON in the sidebar. Places a Kite bracket order (entry limit + stop-loss + target, all on one call), marks the symbol as `executed_today` so re-ticks don't double-fire.
9. *(throughout)* **The News Reader** wakes up every 5 minutes, calls OpenAI once per symbol with watchlist headlines, and adjusts its sentiment score. The Council's score formula folds that in as a soft +/-10% nudge.
10. *(throughout)* **The Forecaster** (pure Python sigmoid over the feature vector) writes a 0–100 upside probability. Folded in as a soft +/-15% nudge.
11. *(throughout)* **The Watchman** checks every other agent's heartbeat and writes a health snapshot. The Treasurer polls positions + funds every 30 seconds for the sidebar tile.

Repeat this cycle every 15 seconds until 14:45.

### 14:45 — 15:25 — **Closing phase, no new entries**

Phase: `closing`. The Gatekeeper begins rejecting *every* new decision with reason *"Closing window — no new entries"*. Existing positions stay open. The Trader is idle for new orders but still tracks fills on open ones. The bot is winding down on its own.

### 15:25 — 15:30 — **Final close**

Phase: `final_close`. Anything that didn't hit its bracket target/stop gets caught here. Because all entries were placed as MIS (intraday) orders with a Kite bracket order wrapper, **Zerodha's broker-side auto-square-off** closes the position at market price by 15:30 IST. We don't have to do anything — the broker does it. You'll see the P&L roll into your funds tile around 15:35.

### After 15:30 — **Market closed**

Phase: `closed`. Threads keep ticking but every agent's `run_once()` short-circuits — nothing to do. The Treasurer keeps refreshing your funds tile so you see end-of-day balance. You can disable the bot or leave it running; either way it won't trade until 10:15 AM tomorrow.

---

## So — does it monitor till 3:30 PM?

**Yes, continuously.** The 12 daemon threads tick non-stop from the moment you enable the bot until you disable it. But "monitor" and "trade" are different:

- **Scanning (read-only)** happens during *every* phase the market is open
- **Trading (placing real orders)** happens *only* in the **active phase (10:15 – 14:45 IST)**
- **Square-off** is automatic via the broker's bracket-order MIS contract — by 15:30 every open position is flat

If you walk away after enabling the bot at 9:00 AM, you'll come back at 4:00 PM to a fully closed-out portfolio.

---

## Indicators each strategy actually looks at

| Strategy | Indicator stack |
|---|---|
| **Trend (agent03)** | NIFTY 1-hour close trend (bullish/bearish) + symbol's close vs 20-bar EMA |
| **Breakout (agent04)** | First-15-min high of the day + current close + 5-min volume vs 20-bar avg volume |
| **Pullback (agent05)** | VWAP (volume-weighted average price) + last 3-bar candle pattern + ATR for stop placement |
| **Momentum (folded into Council)** | RSI > 60 + price > 20MA + volume > 2× avg + RS-vs-NIFTY check |
| **Sentiment (agent09)** | News headlines per symbol, scored -1 to +1 by OpenAI (gpt-4o-mini) |
| **ML Prediction (agent10)** | Sigmoid over normalised (RSI, EMA-gap, VWAP-gap, volume ratio, RS-vs-NIFTY) |
| **Risk overlay (agent07)** | ATR + 1-bar volume spike for the institutional fake-breakout veto |

---

## What success looks like with ₹2,000

The math, with the hard rules baked in:
- **Max position size** = 35% × ₹2,000 = ₹700 per trade
- **Max trades/day** = 5
- **Target floor** = +10% per trade
- **Stop loss cap** = -10% per trade (engine caps at 9.5%)
- **Daily loss cap** = ₹60 (3% of ₹2,000) → triggers safe mode

A green day with 3 winning trades each hitting +10% on a ₹700 ticket = ₹210 profit ≈ **10% of session capital**.
A red day with 3 losers hitting -3% each = ₹63 → bot halts via the 3% daily loss rule.

This is by design. The 12 agents are biased toward **few, high-conviction trades** rather than churning the entire active window.

---

## How to actually drive it

1. Make sure your Kite account has ≥ ₹2,000 in equity segment cash + login is fresh (token expires daily).
2. Open the dashboard.
3. Click **Enable bot** in the sidebar. The orchestrator starts all 12 daemon threads.
4. Optional: flip **Auto-execute orders** ON. Without this, the bot scans and shows candidates but you place orders manually from the Signals tab.
5. Watch the *Agent system (12)* panel — each agent shows a green/grey dot for status. Click the *card* link next to any agent to see its capability JSON at `http://127.0.0.1:8000/agents/agentNN_name/card.json` (when running locally).
6. Top status strip shows phase, equity, trades used, risk used, square-off countdown. The 🔥 **KILL ALL** button is always there as a panic stop — disables the bot AND cancels every open Kite order in one click.
7. At 15:30, MIS auto-square-off runs. By 15:35 you see settled P&L in the funds tile.

---

## What's *not* in this story (deferred)

- **Live auto-refreshing agent pulse** — temporarily disabled on cloud (it broke the first render). Refresh the page to see updated agent statuses.
- **Real OpenAI cost per trade** — agent09 runs every 5 minutes regardless of trading, so token usage is roughly ~20-50 tokens × 1 call × 12 cycles/hour × 4-5 active hours ≈ a few thousand tokens per session, well under $0.02 on gpt-4o-mini.
- **News feed for sentiment** — currently empty unless you populate `bus["news:<SYMBOL>"]`. Sentiment agent silently scores 0.0 with no headlines, which is the correct neutral default.

When in doubt: hit **🔥 KILL ALL**. It costs nothing and resets you to a flat, idle state.
