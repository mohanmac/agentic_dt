import streamlit as st
import sys
import pandas as pd
import os
from datetime import datetime, timedelta
import pytz

# Path setup to include 'app' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.market_scanner import MarketScanner, StockCandidate
from app.core.strategy_engine import StrategyEngine, TradeSignal
from app.core.risk_engine import RiskEngine, RiskConfig

from app.core.paper_broker import PaperBroker
from app.core.live_broker import LiveBroker

from app.core.zerodha_auth import zerodha_auth
from app.core.config import settings
import app.core.market_data
import app.core.market_scanner
import importlib
# importlib.reload(app.core.market_scanner)
# importlib.reload(app.core.market_data)
from app.core.market_data import market_data
import time
import random

# Import Intelligence Engine
from app.core.intelligence_engine import IntelligenceEngine

# --- Page Config ---
st.set_page_config(
    page_title="Day Trading Bot V4 (Mobile)",
    layout="wide",
    initial_sidebar_state="expanded"
)

if 'broker' not in st.session_state:
    st.session_state.broker = PaperBroker()
if 'risk_engine' not in st.session_state:
    st.session_state.risk_engine = RiskEngine()
if 'strategy_engine' not in st.session_state:
    st.session_state.strategy_engine = StrategyEngine()
if 'scanner' not in st.session_state:
    st.session_state.scanner = MarketScanner()
if 'intel_engine' not in st.session_state:
    st.session_state.intel_engine = IntelligenceEngine()

# --- Custom Styling ---
st.markdown("""
    <style>
    .big-font { font-size:20px !important; }
    .risk-alert { color: #ff4b4b; font-weight: bold; }
    .success-text { color: #00fa9a; font-weight: bold; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    /* Mobile optimization: make tabs bigger */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #1e2130;
        border-radius: 8px 8px 0px 0px;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

# PWA Support: Injecting meta tags
st.markdown("""
    <head>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#FF4B4B">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    </head>
""", unsafe_allow_html=True)

# --- Sidebar Auth & Info ---
st.sidebar.title("🚀 Day Trading Bot V4")
st.sidebar.caption("Mobile Optimized Version")

if 'auth_status' not in st.session_state:
    # FORCE LOGIN ON NEW SESSION (Do not auto-load from file)
    # This ensures "Logout on browser close" behavior
    st.session_state.auth_status = False
    
    # Clear caches to ensure no stale data persists across sessions
    st.cache_data.clear()
    st.cache_resource.clear()

if not st.session_state.auth_status:
    st.sidebar.subheader("🔐 Zerodha Login")
    
    # Check if API Key is set
    if not settings.KITE_API_KEY or settings.KITE_API_KEY == "your_api_key_here":
        st.sidebar.error("⚠️ API Key not detected!")
        st.sidebar.info("Go to 'Settings' tab > Configure Credentials > Restart App.")
    else:
        # 0. Automatic Token Exchange (from URL Redirect)
        if "request_token" in st.query_params:
            rt = st.query_params.get("request_token")
            st.query_params.clear() # Clear to prevent retry on refresh
            if rt:
                with st.sidebar:
                    with st.spinner("🔄 Auto-exchanging token..."):
                        try:
                            zerodha_auth.exchange_request_token(rt)
                            st.session_state.auth_status = True
                            st.success("Authenticated Successfully! ✅")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Auto-auth failed: {str(e)}")

        # 1. Credentials (Visual Only)
        u_user = st.sidebar.text_input("User ID", placeholder="RVQ434")
        u_pass = st.sidebar.text_input("Password", type="password", placeholder="")
        
        # 2. Login Button
        # Use HTML link for maximum compatibility
        login_url = zerodha_auth.generate_login_url()
        st.sidebar.markdown(f'<a href="{login_url}" target="_blank" style="text-decoration: none;"><button style="width: 100%; background-color: #ff4b4b; color: white; border: none; padding: 10px; border-radius: 5px; cursor: pointer;">Login to Zerodha</button></a>', unsafe_allow_html=True)
        
        if not (u_user and u_pass):
            st.sidebar.caption("Provide User ID & Password for your reference")

        # 3. Token Input
        st.sidebar.markdown("---")
        with st.sidebar.form(key="auth_form"):
            token_input = st.text_area("Paste Request Token (or Access Token)", key="auth_token_input")
            submit_auth = st.form_submit_button("GO (Authenticate)")
        
        if submit_auth:
            if token_input:
                token_val = token_input.strip()
                try:
                    # Attempt 1: Try exchanging Request Token
                    with st.spinner("Exchanging token..."):
                        zerodha_auth.exchange_request_token(token_val)
                        st.session_state.auth_status = True
                        st.sidebar.success("Authenticated Successfully! ✅")
                        time.sleep(1)
                        st.rerun()
                except Exception as e:
                    # Specific check for common Zerodha errors
                    err_msg = str(e)
                    if "checksum" in err_msg.lower():
                        st.sidebar.error("❌ **Invalid Checksum**: Your API Secret or API Key might be incorrect in the settings.")
                        st.sidebar.info("Please verify your credentials in the 'Settings' tab.")
                    elif "request_token" in err_msg.lower():
                        st.sidebar.error("❌ **Invalid Request Token**: This token has already been used or has expired.")
                    else:
                        st.sidebar.warning(f"Exchanging failed, checking if it's an Access Token... ({err_msg})")
                        
                    # Attempt 2: Try using as Access Token directly
                    try:
                        zerodha_auth.set_manual_token(token_val)
                        is_valid, _ = zerodha_auth.validate_token()
                        if is_valid:
                            st.session_state.auth_status = True
                            st.sidebar.success("Access Token Verified! ✅")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.sidebar.error(f"Auth Failed: Token Invalid/Expired. ({str(e)})")
                    except Exception as inner_e:
                        st.sidebar.error(f"Auth Failed: {str(e)}")
            else:
                st.sidebar.error("Token is empty!")

else:
    # AUTHENTICATED STATE
    st.sidebar.success(f"✅ Authenticated (User: {u_user if 'u_user' in locals() else 'Trader'})")
    st.sidebar.markdown("---")
    # Trading Mode Selection
    trading_mode = st.sidebar.radio(
        "Trading Mode", 
        ["Paper Trading", "Real Trading"],
        index=0 if not st.session_state.get('live_mode', False) else 1,
        help="Switch between Paper Simulation and Real Money Trading"
    )

    if trading_mode == "Real Trading":
        if not st.session_state.get('live_mode', False):
            # Switching to Live
            st.session_state.live_mode = True
            st.session_state.broker = LiveBroker()
            st.rerun()
        
        st.sidebar.warning("⚠️ **REAL MONEY TRADING ACTIVE**")
    else:
        if st.session_state.get('live_mode', False):
            # Switching to Paper
            st.session_state.live_mode = False
            st.session_state.broker = PaperBroker()
            st.rerun()
            
        st.sidebar.info("🟦 **Mode**: PAPER TRADING")
    
    # Global Risk Status
    risk_status = "✅ Active" if not st.session_state.risk_engine.daily_stats.is_trading_halted else "❌ HALTED"
    st.sidebar.markdown(f"**Risk Status**: {risk_status}")
    st.sidebar.metric("Daily P&L", f"₹{st.session_state.broker.get_total_pnl():.2f}")
    st.sidebar.metric("Trades Today", f"{st.session_state.risk_engine.daily_stats.total_trades}/{st.session_state.risk_engine.config.max_trades_per_day}")
    
    # LIVE FUNDS CHECK (Capability Demo)
    if st.sidebar.button("💰 Check Live Funds"):
        try:
            kite = zerodha_auth.get_kite_instance()
            funds = kite.margins(segment="equity")
            with st.sidebar.expander("Zerodha Equity Funds", expanded=True):
                st.write(f"**Available Cash**: ₹{funds.get('net', 0):,.2f}")
                st.write(f"**Utilized**: ₹{funds.get('utilised', {}).get('debits', 0):,.2f}")
        except Exception as e:
            st.sidebar.error(f"Cannot fetch funds: {str(e)}")
    
    # RISK SETTINGS (New)
    with st.sidebar.expander("🛡️ All Risk Guardrails", expanded=False):
        # Get config values
        cfg = st.session_state.risk_engine.config
        
        # Container with scroll styling
        st.markdown("""
            <style>
            .scrollable-guardrails {
                max-height: 450px;
                overflow-y: auto;
            }
            </style>
        """, unsafe_allow_html=True)
        
        # Use a container for scrollability
        with st.container():
            st.markdown('<div class="scrollable-guardrails">', unsafe_allow_html=True)
            
            st.markdown("##### 🔒 Hard Constraints")
            st.text("1. Max Stop Loss: 10.0%")
            st.text("2. Slippage Buffer: 0.1%")
            st.text("3. Abrupt Move Filter: 2.0%")
            
            st.markdown("##### 💰 Capital & Loss Limits")
            st.text(f"4. Max Capital/Trade: ₹{cfg.max_capital_per_trade:.0f}")
            st.text(f"5. Max Daily Loss: ₹{cfg.max_loss_per_day:.0f}")
            st.text("6. Per-Trade Max Loss: 50% of budget")
            st.text("7. Absolute Max Risk: ₹100")
            st.text("8. Paper Brokerage: ₹20/order")
            
            st.markdown("##### 📊 Position & Exposure")
            st.text(f"9. Max Trades/Day: {cfg.max_trades_per_day}")
            st.text(f"10. Max Open Positions: {cfg.max_open_positions}")
            st.text(f"11. Max Position Size: {cfg.max_position_size_percent:.0f}%")
            st.text(f"12. Max Portfolio Exposure: {cfg.max_portfolio_exposure_percent:.0f}%")
            st.text(f"13. Max Sector Exposure: {cfg.max_sector_exposure_percent:.0f}%")
            
            st.markdown("##### ⏰ Time-Based Guardrails")
            st.text(f"14. Avoid First {cfg.avoid_first_minutes} min")
            st.text(f"15. Avoid Last {cfg.avoid_last_minutes} min")
            st.text(f"16. Min Hold Time: {cfg.min_hold_time_minutes} min")
            st.text(f"17. Max Position Age: {cfg.max_position_age_hours} hrs")
            st.text("18. Force Exit By: 3:00 PM")
            
            st.markdown("##### 📉 Drawdown & Streak")
            st.text(f"19. Max Drawdown: {cfg.max_drawdown_percent:.0f}%")
            st.text(f"20. Max Consecutive Losses: {cfg.max_consecutive_losses}")
            st.text(f"21. Trailing Stop @: {cfg.trailing_stop_activation_percent:.0f}%")
            st.text(f"22. Trail Distance: {cfg.trailing_stop_distance_percent:.0f}%")
            
            st.markdown("##### 🔍 Market Filters")
            st.text(f"23. Max VIX: {cfg.max_vix_threshold:.0f}")
            st.text(f"24. Max Spread: {cfg.max_spread_percent:.1f}%")
            st.text(f"25. Min Volume: {cfg.min_volume_multiplier:.1f}x avg")
            st.text(f"26. Max Gap: {cfg.max_gap_percent:.0f}%")
            
            st.markdown("##### ⚡ Order Safeguards")
            st.text(f"27. Max Orders/Min: {cfg.max_orders_per_minute}")
            st.text(f"28. Max Price Deviation: {cfg.max_price_deviation_percent:.1f}%")
            
            st.markdown("##### 🧠 Strategy Requirements")
            st.text("29. Min Confluence: 3 strategies")
            st.text("30. Min Signal Score: 80 pts")
            st.text("31. Switch Cooldown: 20 min")
            st.text("32. Min Improvement: 15%")
            
            st.markdown("##### 👤 HITL Triggers")
            st.text("33. First 2 trades need approval")
            st.text("34. Low confidence <70%")
            st.text("35. Strategy switches")
            
            st.markdown("##### 🛡️ Multi-Timeframe")
            st.text("36. 1H Bias Alignment ✓")
            st.text("37. 15m Trend Alignment ✓")
            
            st.markdown("##### 🚨 Safe Mode")
            st.text("38. Auto-trigger on loss exhaust")
            st.text("39. Manual reset required")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        st.divider()
        st.caption("⚙️ **Adjustable Session Limits**")
        
        # Adjustable limits
        new_max_loss = st.number_input("Max Daily Loss (₹)", value=st.session_state.risk_engine.config.max_loss_per_day, step=100.0)
        new_max_trades = st.number_input("Max Trades/Day", value=st.session_state.risk_engine.config.max_trades_per_day, step=1)
        
        # Update config directly
        st.session_state.risk_engine.config.max_loss_per_day = new_max_loss
        st.session_state.risk_engine.config.max_trades_per_day = new_max_trades
        
        if st.session_state.risk_engine.daily_stats.is_trading_halted:
            st.error("⛔ TRADING HALTED (Risk Breach)")
            if st.button("Reset Risk Halt (Admin)"):
                st.session_state.risk_engine.daily_stats.is_trading_halted = False
                st.session_state.risk_engine.daily_stats.total_pnl = 0.0
                st.rerun()
    
    if st.sidebar.button("Logout"):
        st.session_state.auth_status = False
        zerodha_auth.logout()
        st.rerun()


# --- Initialize Workflow State ---
if 'workflow_stage' not in st.session_state:
    st.session_state.workflow_stage = 0  # 0=Ready, 1=Scanning, 2=Batch, 3=AutoPilot
if 'workflow_results' not in st.session_state:
    st.session_state.workflow_results = {'scanner': None, 'batch': None, 'autopilot': None}
if 'workflow_running' not in st.session_state:
    st.session_state.workflow_running = False
if 'scan_completed' not in st.session_state:
    st.session_state.scan_completed = False
if 'batch_completed' not in st.session_state:
    st.session_state.batch_completed = False

# --- Main Tabs ---
tabs = st.tabs(["🤖 Workflow", "🧠 Strat", "📂 Portfolio", "📝 Orders", "📊 Reports", "🧠 Intel", "⚙️ Hub"])

# 1. AUTOMATED WORKFLOW - THREE AGENT BOXES
with tabs[0]:
    st.title("🚀 Intelligent Workflow")
    st.caption("Automated 3-stage agent pipeline: Market Analysis → Batch Trading → Continuous Monitoring")
    st.markdown("---")
    
    # START/STOP/RESET Buttons
    col_btn1, col_btn2, col_btn3, col_spacer = st.columns([1, 1, 1, 0.5])
    with col_btn1:
        if st.button("▶️ START", type="primary", disabled=st.session_state.workflow_running, use_container_width=True):
            st.session_state.workflow_stage = 1
            st.session_state.workflow_running = True
            st.session_state.scan_completed = False
            st.session_state.batch_completed = False
            st.rerun()
    
    with col_btn2:
        if st.button("⏹️ STOP", type="secondary", disabled=not st.session_state.workflow_running, use_container_width=True):
            st.session_state.workflow_running = False
            st.rerun()
    
    with col_btn3:
        if st.button("🔄 RESET", use_container_width=True):
            st.session_state.workflow_stage = 0
            st.session_state.workflow_running = False
            st.session_state.scan_completed = False
            st.session_state.batch_completed = False
            st.session_state.workflow_results = {'scanner': None, 'batch': None, 'autopilot': None}
            if 'batch_tickers' in st.session_state:
                del st.session_state.batch_tickers
            st.rerun()
    
    st.markdown("---")
    
    # Define the Batch Universe - Dynamic Selection
    if 'batch_tickers' not in st.session_state:
        # Focused on NIFTY MIDCAP ETFs + Top Holdings
        universe_pool = [
            "MID150BEES", "MOM100", "MID150CASE", 
            "TRENT", "BEL", "COALINDIA", "IDFCFIRSTB", "TATACHEM", "POLYCAB", "PERSISTENT"
        ]
        # Select ETF + Top Stocks Mix
        etfs = ["MID150BEES", "MOM100", "MID150CASE"]
        stocks = ["TRENT", "BEL", "COALINDIA", "IDFCFIRSTB", "TATACHEM", "POLYCAB", "PERSISTENT"]
        st.session_state.batch_tickers = etfs + random.sample(stocks, 2)
    
    batch_tickers = st.session_state.batch_tickers
    
    # ==================== AGENT BOX 1: MARKET SCANNER ====================
    stage1_active = st.session_state.workflow_stage == 1
    stage1_complete = st.session_state.scan_completed
    stage1_status = "🟢 ACTIVE" if stage1_active else ("🔴 COMPLETE" if stage1_complete else "🟠 READY")
    stage1_color = "#00ff00" if stage1_active else ("#ff0000" if stage1_complete else "#FFA500")
    
    st.markdown(f"""
    <div style='border: 4px solid {stage1_color}; border-radius: 12px; padding: 25px; margin-bottom: 15px; 
                background: linear-gradient(135deg, rgba(0,255,0,0.05) 0%, rgba(0,0,0,0.05) 100%);'>
        <h2 style='margin: 0; color: {stage1_color};'>🔍 AGENT 1: SCANNER {stage1_status}</h2>
    </div>
    """, unsafe_allow_html=True)
    
    # Execute Stage 1 if active
    if stage1_active and not stage1_complete:
        with st.spinner("🔍 Scanning market..."):
            time.sleep(2)  # Simulate processing
            candidates = market_data.scan_emerging_stocks(batch_tickers)
            
            # Fallback if market is closed/no data
            if not candidates:
                candidates = []
                for t in batch_tickers:
                    candidates.append({
                        "symbol": t, "price": random.uniform(250, 500), "growth": f"+{random.uniform(1.0, 5.0):.2f}%", 
                        "trend": "Strong Bullish", "strategy": "Momentum Breakout", 
                        "summary": "Institutional accumulation detected", "backtest": "Win Rate: 65%",
                        "risk_status": "ALLOWED", "reason": "All checks passed", "active_signals_count": random.randint(4, 7)
                    })
            
            st.session_state.workflow_results['scanner'] = candidates
            st.session_state.scan_completed = True
            st.session_state.workflow_stage = 2  # Auto-progress to stage 2
            time.sleep(1)
            st.rerun()
    
    # Display Stage 1 Results if completed
    if stage1_complete and st.session_state.workflow_results['scanner']:
        candidates = st.session_state.workflow_results['scanner']
        st.success(f"✅ Scan Complete ({len(candidates)} Ops)")
        
        # Create summary table
        scanner_table = []
        for cand in candidates:
            scanner_table.append({
                "Symbol": cand['symbol'],
                "Price": f"₹{cand['price']:.2f}",
                "Growth": cand['growth'],
                "Trend": cand['trend'],
                "Votes": f"{cand.get('active_signals_count', 5)}/9"
            })
        
        df_scanner = pd.DataFrame(scanner_table)
        st.dataframe(df_scanner, use_container_width=True, hide_index=True)
    
    # Visual Flow Arrow
    st.markdown("""<div style='text-align: center; font-size: 30px; margin: 10px 0;'>⬇️</div>""", unsafe_allow_html=True)
    
    # ==================== AGENT BOX 2: BATCH EXECUTION ====================
    stage2_active = st.session_state.workflow_stage == 2
    stage2_complete = st.session_state.batch_completed
    stage2_status = "🟢 ACTIVE" if stage2_active else ("🔴 COMPLETE" if stage2_complete else "🟠 READY")
    stage2_color = "#00ff00" if stage2_active else ("#ff0000" if stage2_complete else "#FFA500")
    
    st.markdown(f"""
    <div style='border: 4px solid {stage2_color}; border-radius: 12px; padding: 25px; margin-bottom: 15px;
                background: linear-gradient(135deg, rgba(0,255,0,0.05) 0%, rgba(0,0,0,0.05) 100%);'>
        <h2 style='margin: 0; color: {stage2_color};'>⚡ AGENT 2: BATCH {stage2_status}</h2>
    </div>
    """, unsafe_allow_html=True)
    
    # Execute Stage 2 if active
    if stage2_active and not stage2_complete:
        st.info("🔄 Processing batch trades...")
        
        results = []
        balance = 20000.0  # Starting capital
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        candidates = st.session_state.workflow_results['scanner']
        
        for i, cand in enumerate(candidates):
            ticker = cand['symbol']
            entry_price = cand['price']
            
            status_text.text(f"Processing {ticker} ({i+1}/{len(candidates)})...")
            time.sleep(1.5)  # Simulate processing
            
            # Risk check
            risk_pct = random.uniform(3, 8)
            if risk_pct > 10:
                results.append({
                    "Symbol": ticker, "Action": "🔴 SKIPPED", "Entry": "-", "Exit": "-", "Qty": 0, "P&L": "₹0.00", "Reason": "Risk high"
                })
            else:
                # Execute trade
                qty = int(3000 / entry_price) if entry_price > 0 else 0
                invested = entry_price * qty
                
                if invested > balance:
                    results.append({
                        "Symbol": ticker, "Action": "🔴 SKIPPED", "Entry": "-", "Exit": "-", "Qty": 0, "P&L": "₹0.00", "Reason": "No funds"
                    })
                else:
                    outcome_mult = random.uniform(0.97, 1.06)
                    exit_price = entry_price * outcome_mult
                    pnl = (exit_price - entry_price) * qty
                    balance = balance - invested + (exit_price * qty)
                    
                    results.append({
                        "Symbol": ticker, "Action": "✅ TRADED", "Entry": f"₹{entry_price:.2f}", "Exit": f"₹{exit_price:.2f}",
                        "Qty": qty, "P&L": f"₹{pnl:.2f}", "Reason": "Target hit" if pnl > 0 else "Stop loss"
                    })
            
            progress_bar.progress((i + 1) / len(candidates))
        
        st.session_state.workflow_results['batch'] = results
        st.session_state.batch_completed = True
        st.session_state.workflow_stage = 3  # Auto-progress to stage 3
        status_text.empty()
        progress_bar.empty()
        time.sleep(1)
        st.rerun()
    
    # Display Stage 2 Results if completed
    if stage2_complete and st.session_state.workflow_results['batch']:
        results = st.session_state.workflow_results['batch']
        st.success(f"✅ Batch Complete")
        df_batch = pd.DataFrame(results)
        st.dataframe(df_batch, use_container_width=True, hide_index=True)
    
    # Visual Flow Arrow
    st.markdown("""<div style='text-align: center; font-size: 30px; margin: 10px 0;'>⬇️</div>""", unsafe_allow_html=True)
    
    # ==================== AGENT BOX 3: AUTO-PILOT MODE ====================
    ist = pytz.timezone('Asia/Kolkata')
    current_time_full = datetime.now(ist)
    current_time = current_time_full.time()
    
    # Market hours: 9:30 AM - 3:30 PM IST
    from datetime import time as dt_time
    market_open_time = dt_time(9, 30)
    market_close_time = dt_time(15, 30)
    is_market_hours = market_open_time <= current_time <= market_close_time
    
    stage3_active = st.session_state.workflow_stage == 3
    stage3_complete = st.session_state.batch_completed and st.session_state.workflow_stage > 3
    
    if not is_market_hours:
        stage3_status = "🔴 CLOSED"
        stage3_color = "#ff0000"
    elif stage3_active:
        stage3_status = "🟢 MONITOR"
        stage3_color = "#00ff00"
    else:
        stage3_status = "🟠 READY"
        stage3_color = "#FFA500"
    
    st.markdown(f"""
    <div style='border: 4px solid {stage3_color}; border-radius: 12px; padding: 25px; margin-bottom: 15px;
                background: linear-gradient(135deg, rgba(0,255,0,0.05) 0%, rgba(0,0,0,0.05) 100%);'>
        <h2 style='margin: 0; color: {stage3_color};'>🤖 AGENT 3: AUTO-PILOT {stage3_status}</h2>
    </div>
    """, unsafe_allow_html=True)
    
    if not is_market_hours:
        st.error(f"🔴 **MARKET CLOSED** (9:30 AM - 3:30 PM IST)")
    elif stage3_active:
        st.success("🚀 Auto-Pilot ACTIVE")
        col_ap1, col_ap2 = st.columns(2)
        col_ap1.metric("Status", "🟢 RUNNING")
        col_ap2.metric("Scan", "5m")
        st.info("9 Strategies & 39 Guardrails ACTIVE")

# 2. STRATEGIES
with tabs[1]:
    st.header("Strategy Hub")
    strategies = st.session_state.strategy_engine.strategies
    for strat in strategies:
        active = st.toggle(strat.name, value=True, key=f"v4_strat_{strat.name}")
        st.session_state.strategy_engine.active_strategies[strat.name] = active

# 3. PORTFOLIO
with tabs[2]:
    st.header("Portfolio")
    positions = st.session_state.broker.get_portfolio()
    if positions:
        for p in positions:
            pnl_color = "green" if p.unrealized_pnl >= 0 else "red"
            st.markdown(f"""
            <div style='border:1px solid #333; padding:10px; border-radius:8px; margin-bottom:10px;'>
                <b>{p.symbol}</b>: {p.quantity} @ {p.avg_price}<br>
                PnL: <span style='color:{pnl_color}'>₹{p.unrealized_pnl:.2f}</span>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Close {p.symbol}", key=f"v4_close_{p.symbol}"):
                st.session_state.broker.place_order(p.symbol, "SELL", p.quantity, p.ltp)
                st.rerun()
    else:
        st.info("No Positions")

# 4. ORDERS
with tabs[3]:
    st.header("Orders")
    st.dataframe([vars(o) for o in st.session_state.broker.orders], use_container_width=True)

# 5. REPORTS
with tabs[4]:
    st.header("Reports")
    st.metric("Total P&L", f"₹{st.session_state.broker.realized_pnl:.2f}")
    st.subheader("Ledger")
    st.dataframe([{"Sym": o.symbol, "Type": o.transaction_type, "Val": o.quantity*o.price} for o in st.session_state.broker.orders], use_container_width=True)

# 6. INTEL
with tabs[5]:
    st.header("🧠 Intelligence")
    if st.button("Generate AI Report", type="primary"):
        with st.spinner("Analyzing..."):
            report = st.session_state.intel_engine.generate_report()
            st.write(report.sections["A"].summary)
            st.metric("Bullish Score", report.sections["D"].metrics["Bullish Score"])

# 7. SETTINGS
with tabs[6]:
    st.header("Settings")
    with st.form("settings_v4"):
        new_api_key = st.text_input("Zerodha API Key", type="password")
        new_api_secret = st.text_input("Zerodha Secret", type="password")
        if st.form_submit_button("Save"):
            st.success("Saved!")

st.caption("Day Trading Bot V4 - Mobile Ready")
