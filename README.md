# DayTradingPaperBot

**Production-grade agentic paper trading system with Zerodha Kite Connect integration and Ollama-powered LLM reasoning.**

## 🎯 Overview

DayTradingPaperBot is a sophisticated algorithmic trading system that implements:

- **3-Agent Architecture**: StrategyBrainAgent, RiskPolicyAgent, and ExecutionPaperAgent work together with strict guardrails
- **Paper Trading First**: Safe simulation mode by default - no real money at risk
- **Zerodha Integration**: Secure OAuth authentication (NO password automation)
- **Local LLM Reasoning**: Uses Ollama for strategy explanations (no paid API costs)
- **Human-in-the-Loop**: Critical decisions require manual approval
- **Strict Guardrails**: Daily loss limits, mandatory stop-losses, SAFE_MODE auto-triggers

## 🏗️ Architecture

### Agent 1: StrategyBrainAgent
Evaluates 3 strategies in parallel:
1. **Momentum Breakout** - Opening range & VWAP breakouts
2. **Mean Reversion** - Bollinger Band & VWAP reversions
3. **Volatility Expansion** - Compression-expansion patterns

Generates `TradeIntent` with:
- Entry/exit prices, stop-loss (mandatory), targets
- Confidence score (0-1)
- LLM-generated rationale
- Expected risk in rupees

### Agent 2: RiskPolicyAgent
Enforces guardrails:
- ✅ Daily capital budget: ₹2000
- ✅ Max daily loss: ₹200 (10%)
- ✅ Per-trade risk limits
- ✅ Mandatory stop-loss validation
- ✅ Strategy switch controls (20min cooldown, 15% min improvement)
- ✅ SAFE_MODE auto-trigger at max loss
- ✅ HITL gating (first N trades, low confidence)

### Agent 3: ExecutionPaperAgent
Paper trading execution:
- Simulates fills with realistic slippage (0.05%)
- Applies brokerage (₹20/order)
- Manages positions and PnL
- Monitors stop-loss/target levels
- Auto-exits on triggers
- Prevents duplicate orders

## 🔒 Security Features

- **NO password storage or automation**
- **OAuth redirect flow only** - user manually logs in via browser
- **Secrets via environment variables** - never in code
- **Token storage** with restricted permissions
- **Logs exclude secrets** - automatic filtering
- **Paper mode default** - live trading requires explicit flag + confirmation

## 📋 Prerequisites

1. **Python 3.9+**
2. **Zerodha Kite Connect App**
   - Create app at: https://developers.kite.trade/
   - Get API Key and API Secret
   - Set redirect URL: `http://127.0.0.1:8000/callback`
3. **Ollama** (for LLM reasoning)
   - Install: https://ollama.ai/
   - Pull model: `ollama pull qwen2.5:7b`

## 🚀 Installation

### Step 1: Clone and Setup

```bash
cd DayTradingPaperBot

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy example env file
copy .env.example .env

# Edit .env with your credentials
notepad .env
```

**Required settings in `.env`:**
```env
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
KITE_REDIRECT_URL=http://127.0.0.1:8000/callback

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

DAILY_CAPITAL=2000
MAX_DAILY_LOSS=200
MAX_TRADES_PER_DAY=5
```

### Step 3: Start Ollama

```bash
# Start Ollama server
ollama serve

# In another terminal, pull model
ollama pull qwen2.5:7b

# Or use smaller model for low-resource systems
ollama pull llama3.2:3b
```

## 📖 Usage

### 1. Authenticate with Zerodha

```bash
# Start auth server
python -m app auth

# Visit http://127.0.0.1:8000/auth/login_url in browser
# Click the login URL
# Log in to Zerodha manually
# Authorize the app
# You'll be redirected back with success message
```

### 2. Validate System

```bash
# Check all prerequisites
python -m app validate
```

Expected output:
```
✅ Authenticated as: YOUR_NAME
✅ Ollama connected: qwen2.5:7b
✅ Database initialized
✅ API key configured
✅ All systems operational!
```

### 3. Run Paper Trading

```bash
# Start paper trading loop
python -m app run --paper
```

The bot will:
- Fetch market data every 1 minute
- Evaluate strategies for configured symbols
- Generate trade intents
- Apply risk guardrails
- Execute in paper mode
- Monitor positions for SL/target hits

### 4. Launch Dashboard

```bash
# In a separate terminal
python -m app dashboard
```

Dashboard features:
- 📊 Real-time P&L and metrics
- 💼 Open positions table
- 📋 Trade history
- ✅ HITL approval panel
- ⚙️ System controls

Access at: http://localhost:8501

### 5. Monitor and Approve Trades

In the dashboard:
1. Go to **HITL Approvals** tab
2. Review pending trade intents
3. Read LLM rationale and risk metrics
4. Click **Approve** or **Reject**

## 🎛️ CLI Commands

```bash
# Authentication
python -m app auth                    # Start auth server

# Trading
python -m app run --paper             # Paper trading (default)
python -m app run --live              # Live trading (requires confirmation)

# Dashboard
python -m app dashboard               # Launch Streamlit UI

# Utilities
python -m app validate                # Check system status
python -m app reset                   # Reset daily state
```

## 📊 Example Trade Intent Output

```json
{
  "strategy_id": "momentum_breakout",
  "symbol": "RELIANCE",
  "side": "buy",
  "entry_type": "market",
  "quantity": 10,
  "stop_loss_price": 2400.00,
  "target_price": 2500.00,
  "confidence_score": 0.78,
  "rationale": "Momentum Breakout: Price broke above opening range high (2445.50); Price +0.85% from VWAP; Above-average volume confirms breakout; Trending regime (trending_up); High liquidity\n\nAnalysis: This setup shows strong momentum with price breaking above the opening range on increased volume. The VWAP breakout confirms buyer strength. Risk is well-defined at ₹50 per share with a 1:2 risk-reward ratio. Key risk: If volume dries up or price falls back below VWAP, the breakout may fail.",
  "expected_risk_rupees": 150.00,
  "invalidation_conditions": [
    "Price falls back below VWAP (₹2448.75)",
    "Volume drops significantly",
    "Regime changes to ranging/whipsaw"
  ]
}
```

## 🛡️ Guardrails in Action

### Daily Loss Limit
```
Daily State: Trades=3/5, PnL=₹-180.50, Budget=₹19.50, SAFE_MODE=false

[New trade with expected risk ₹50]
❌ REJECTED: Trade risk (₹50.00) exceeds remaining budget (₹19.50)
```

### SAFE_MODE Trigger
```
Position exited (stop_loss): RELIANCE - PnL: ₹-25.00
Daily PnL: ₹-200.50

🚨 SAFE_MODE TRIGGERED: Daily loss limit reached
Flattening all positions...
Blocking new trades...
```

### Strategy Switch Control
```
Strategy switch detected: momentum_breakout -> mean_reversion
❌ REJECTED: Strategy switch cooldown active (15 min remaining)
```

### HITL Approval
```
Trade Intent: mean_reversion SELL INFY
Confidence: 0.65 (below threshold 0.70)
✅ HITL REQUIRED: Low confidence (0.65 < 0.70)
Trade pending human approval in dashboard
```

## 📁 Project Structure

```
DayTradingPaperBot/
├── app/
│   ├── __init__.py
│   ├── __main__.py              # CLI entry point
│   ├── main.py                  # FastAPI auth server
│   ├── agents/
│   │   ├── strategy_brain.py    # Agent 1: Strategy evaluation
│   │   ├── risk_policy.py       # Agent 2: Risk guardrails
│   │   └── execution_paper.py   # Agent 3: Paper execution
│   └── core/
│       ├── config.py             # Configuration management
│       ├── schemas.py            # Pydantic data models
│       ├── storage.py            # SQLite persistence
│       ├── utils.py              # Logging & utilities
│       ├── zerodha_auth.py       # OAuth authentication
│       ├── market_data.py        # Market data & indicators
│       ├── ollama_client.py      # LLM integration
│       └── scheduler.py          # Trading loop orchestrator
├── ui/
│   └── dashboard.py              # Streamlit dashboard
├── data/                         # SQLite DB & tokens (gitignored)
├── logs/                         # Application logs (gitignored)
├── tests/                        # Unit tests
├── .env.example                  # Environment template
├── .gitignore                    # Security exclusions
├── requirements.txt              # Python dependencies
└── README.md                     # This file
```

## 🧪 Testing

### Unit Tests for Risk Guardrails

```bash
# Run tests
pytest tests/test_risk_policy.py -v
```

Test coverage:
- ✅ Daily loss limit enforcement
- ✅ Per-trade risk calculation
- ✅ Mandatory stop-loss validation
- ✅ Strategy switch controls
- ✅ HITL gating logic
- ✅ SAFE_MODE triggering

## ⚠️ Important Notes

### Paper Trading
- **Default mode** - safe for testing
- Uses simulated fills with realistic slippage
- No real money involved
- Full PnL tracking and audit trail

### Live Trading
- **Disabled by default** in configuration
- Requires `ENABLE_LIVE_TRADING=true` in `.env`
- Requires explicit `--live` flag
- Requires interactive confirmation
- **Test thoroughly in paper mode first!**

### Daily Workflow
1. Start Ollama: `ollama serve`
2. Authenticate: `python -m app auth` (once per day)
3. Run trading: `python -m app run --paper`
4. Monitor dashboard: `python -m app dashboard`
5. Approve HITL trades as needed
6. End of day: Positions auto-flatten at 3:15 PM

### Token Refresh
- Access tokens expire daily
- Re-authenticate each trading day
- Run `python -m app auth` to refresh

## 🐛 Troubleshooting

### "Not authenticated" error
```bash
# Re-run auth flow
python -m app auth
```

### "Ollama not available" error
```bash
# Start Ollama server
ollama serve

# Pull model
ollama pull qwen2.5:7b
```

### "No market data" error
- Check Zerodha API status
- Verify symbols in `TRADING_SYMBOLS` config
- Ensure trading hours (9:15 AM - 3:30 PM IST)

### Database locked error
- Only one trading loop instance at a time
- Close other instances
- Delete `data/*.db-journal` if stuck

## 📈 Performance Tips

### Low-Resource Systems
```env
# Use smaller LLM model
OLLAMA_MODEL=llama3.2:3b

# Reduce symbols
TRADING_SYMBOLS=RELIANCE,TCS
```

### High-Frequency Trading
```python
# In scheduler.py, reduce loop interval
self.loop_interval = 30  # 30 seconds instead of 60
```

## 🔐 Security Best Practices

1. **Never commit `.env` file** - contains secrets
2. **Never share access tokens** - regenerate if exposed
3. **Use strong API secret** - from Zerodha dashboard
4. **Restrict file permissions** on `data/tokens.json`
5. **Review logs** for any secret leakage
6. **Test in paper mode** before live trading

## 📜 License

This project is for educational purposes. Use at your own risk.

## 🤝 Contributing

Contributions welcome! Please:
1. Test thoroughly in paper mode
2. Add unit tests for new features
3. Update documentation
4. Follow existing code style

## 📞 Support

For issues:
1. Check troubleshooting section
2. Run `python -m app validate`
3. Review logs in `logs/` directory
4. Check Zerodha API status

## 🎓 Learning Resources

- [Zerodha Kite Connect Docs](https://kite.trade/docs/connect/v3/)
- [Ollama Documentation](https://ollama.ai/docs)
- [Technical Analysis Basics](https://www.investopedia.com/technical-analysis-4689657)

---

**⚠️ DISCLAIMER**: This software is for educational and research purposes only. Trading involves substantial risk of loss. The authors are not responsible for any financial losses incurred through the use of this software. Always test thoroughly in paper mode before considering live trading.
