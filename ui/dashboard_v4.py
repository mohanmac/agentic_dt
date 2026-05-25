import streamlit as st
import sys
import pandas as pd
import os
from datetime import datetime, timedelta
import pytz
from datetime import date

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
from app.core.market_data import market_data
import time
import random

# Import Intelligence Engine
from app.core.intelligence_engine import IntelligenceEngine
from app.core.intraday_agent import (
    scan_intraday_universe,
    decision_to_dict,
    session_capital,
    MIN_CONFIDENCE_TRADE,
    MAX_TRADES_PER_DAY,
    load_nifty500_symbols,
    session_planning_brief,
    MIN_TARGET_PCT,
    MAX_STOP_LOSS_PCT,
)
import app.core.market_calendar as mcal

# Support older copies of market_calendar.py missing session-phase helpers.
equity_cash_session_phase = getattr(mcal, "equity_cash_session_phase", None)
if equity_cash_session_phase is None:

    def equity_cash_session_phase(now=None):
        now = now or mcal.ist_now()
        t = now.time()
        if mcal.REGULAR_START <= t < mcal.REGULAR_END:
            return "regular"
        return "closed"


can_place_nse_bse_equity_trade = mcal.can_place_nse_bse_equity_trade
market_status_line = mcal.market_status_line
ist_now = mcal.ist_now
is_nse_bse_trading_day = mcal.is_nse_bse_trading_day
REGULAR_START = mcal.REGULAR_START
IST = mcal.IST

# --- Page Config ---
st.set_page_config(
    page_title="Momentum/Trend Bot V4 (Mobile)",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="favicon_512.png",
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


def _env_file_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def save_kite_env(new_api_key: str, new_api_secret: str) -> tuple[bool, str]:
    env_path = _env_file_path()
    try:
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
        key_found = secret_found = False
        new_lines = []
        for line in lines:
            if line.startswith("KITE_API_KEY="):
                new_lines.append(f"KITE_API_KEY={new_api_key}\n")
                key_found = True
            elif line.startswith("KITE_API_SECRET="):
                new_lines.append(f"KITE_API_SECRET={new_api_secret}\n")
                secret_found = True
            else:
                new_lines.append(line)
        if not key_found:
            new_lines.append(f"\nKITE_API_KEY={new_api_key}\n")
        if not secret_found:
            new_lines.append(f"KITE_API_SECRET={new_api_secret}\n")
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        return True, "Saved to .env — restart this app if keys still show as missing."
    except Exception as e:
        return False, str(e)


def render_sidebar_kite_api_setup(expanded: bool) -> None:
    with st.sidebar.expander("⚙️ Step 0: Kite API Key & Secret", expanded=expanded):
        st.caption("Create an app at developers.kite.trade — redirect URL must match settings.")
        with st.form("sidebar_kite_api_form"):
            ak = st.text_input("API Key", type="password", placeholder="kite_api_key")
            sk = st.text_input("API Secret", type="password", placeholder="secret")
            save = st.form_submit_button("Save API configuration")
        if save:
            if ak and sk:
                ok, msg = save_kite_env(ak.strip(), sk.strip())
                (st.success if ok else st.error)(msg)
            else:
                st.error("Enter both Key and Secret.")


def render_settings_tab():
    """Kite API config — full Settings tab (after login)."""
    st.header("⚙️ System Settings")
    st.info("Credentials are saved to `.env` under the app folder. **Restart** the app if values do not refresh.")
    
    with st.form("settings_form_v4"):
        new_api_key = st.text_input("Zerodha API Key", type="password", placeholder="Enter your Kite Connect API Key")
        new_api_secret = st.text_input("Zerodha Secret", type="password", placeholder="Enter your Kite Connect Secret")
        
        submitted = st.form_submit_button("Save Configuration")
        
        if submitted:
            if new_api_key and new_api_secret:
                ok, msg = save_kite_env(new_api_key.strip(), new_api_secret.strip())
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"Failed: {msg}")
            else:
                st.error("Please enter both API Key and Secret.")
    
    with st.expander("🔍 Credential Diagnosis", expanded=False):
        c1, c2 = st.columns(2)
        c1.write("**API Key**")
        if settings.KITE_API_KEY and settings.KITE_API_KEY != "your_api_key_here":
            c1.success(f"...{settings.KITE_API_KEY[-4:]}")
        else:
            c1.error("Not Set")
            
        c2.write("**API Secret**")
        if settings.KITE_API_SECRET and settings.KITE_API_SECRET != "your_api_secret_here":
            c2.success("Configured ✅")
        else:
            c2.error("Not Set")
            
        st.write(f"**Redirect URL**: `{settings.KITE_REDIRECT_URL}`")
        if "127.0.0.1" in settings.KITE_REDIRECT_URL or "localhost" in settings.KITE_REDIRECT_URL:
            st.warning("⚠️ Local redirect URL. On deployed apps, use your Streamlit Cloud URL.")
        
        st.info("💡 Ensure your Zerodha Developer Console URL matches exactly.")


# --- Mobile-Optimized Styling ---
st.markdown("""
    <style>
    /* Mobile-first responsive design */
    .big-font { font-size:18px !important; }
    .risk-alert { color: #ff4b4b; font-weight: bold; }
    .success-text { color: #00fa9a; font-weight: bold; }
    
    /* Bigger touch targets — main content only.
       Do NOT target all `.stButton>button` globally: password fields and other
       widgets embed small buttons; forcing width:100% / height:3.2em breaks them
       and can blank the UI when focusing Password. */
    .main .block-container .stButton > button,
    section[data-testid="stMain"] .block-container .stButton > button {
        width: 100%;
        border-radius: 8px;
        height: 3.2em;
        font-size: 16px;
        font-weight: 600;
    }

    /* Base Web / small control buttons inside sidebar inputs (e.g. password visibility) */
    [data-testid="stSidebar"] [data-baseweb="input"] button {
        width: auto !important;
        min-width: unset !important;
        height: auto !important;
        min-height: unset !important;
    }
    
    /* Mobile-friendly tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        overflow-x: auto;
        flex-wrap: nowrap;
    }
    .stTabs [data-baseweb="tab"] {
        height: 48px;
        white-space: pre-wrap;
        font-size: 13px;
        padding: 8px 12px;
    }
    
    /* Compact metrics for mobile */
    [data-testid="stMetricValue"] {
        font-size: 1.2rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }
    
    /* Compact dataframes */
    .stDataFrame { font-size: 12px !important; }
    
    /* Scrollable containers */
    .scrollable-guardrails {
        max-height: 400px;
        overflow-y: auto;
    }
    
    /* Agent box mobile styling */
    .agent-box {
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- Sidebar Auth & Info ---
st.sidebar.title("🚀 Momentum/Trend Bot V4")
st.sidebar.caption("📱 Mobile Optimized — **left pane** has Zerodha login")

if 'auth_status' not in st.session_state:
    # FORCE LOGIN ON NEW SESSION (Do not auto-load from file)
    st.session_state.auth_status = False
    
    # Clear caches to ensure no stale data persists across sessions
    st.cache_data.clear()
    st.cache_resource.clear()

if not st.session_state.auth_status:
    _api_ok = (
        settings.KITE_API_KEY
        and settings.KITE_API_KEY != "your_api_key_here"
        and settings.KITE_API_SECRET
        and settings.KITE_API_SECRET != "your_api_secret_here"
    )
    render_sidebar_kite_api_setup(expanded=not _api_ok)

    if not _api_ok:
        st.sidebar.warning(
            "Add **API Key** & **Secret** in **Step 0** above, **save**, then **restart** this app."
        )

    st.sidebar.markdown("##### Sign in to Zerodha")
    st.sidebar.caption(
        "**Username** and **password** are not stored and not sent by this app. "
        "After **Login**, use them only on Zerodha’s Kite page."
    )
    st.sidebar.text_input(
        "Username (Kite User ID)",
        placeholder="Your Kite login ID",
        key="pre_kite_username",
    )
    st.sidebar.text_input(
        "Password",
        type="password",
        placeholder="Use on Kite after Login",
        key="pre_kite_password",
    )

    if "request_token" in st.query_params:
        rt = st.query_params.get("request_token")
        st.query_params.clear()
        if rt:
            if _api_ok:
                with st.sidebar:
                    with st.spinner("🔄 Auto-exchanging token from URL..."):
                        try:
                            zerodha_auth.exchange_request_token(rt)
                            st.session_state.auth_status = True
                            st.success("Authenticated Successfully! ✅")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Auto-auth failed: {str(e)}")
            else:
                st.session_state["_pending_request_token"] = rt
                st.sidebar.info(
                    "**Request token** from the URL is saved for this session. Configure **Step 0**, restart, then **Authenticate** below."
                )

    if _api_ok:
        login_url = zerodha_auth.generate_login_url()
        st.sidebar.markdown(
            f'<p style="margin:0.35rem 0 0.5rem 0;">'
            f'<a href="{login_url}" target="_blank" rel="noopener noreferrer">'
            f"<strong>Login</strong> — Kite Connect (new tab)</a></p>",
            unsafe_allow_html=True,
        )
        st.sidebar.caption(
            "After login, your **Redirect URL** loads with **request_token** in the address bar."
        )
    else:
        st.sidebar.caption("Configure **Step 0** before **Login**.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("##### Authorize app")
    _pending = st.session_state.pop("_pending_request_token", None)

    _ta_kwargs = dict(
        label="token",
        height=110,
        key="auth_token_input",
        label_visibility="collapsed",
        placeholder="Paste request_token from the redirect URL here",
    )
    if _pending:
        _ta_kwargs["value"] = _pending

    with st.sidebar.form(key="auth_form"):
        token_input = st.text_area(**_ta_kwargs)
        submit_auth = st.form_submit_button("Authenticate", type="primary", use_container_width=True)

    if submit_auth:
        if not _api_ok:
            st.sidebar.error("Save **API Key** & **Secret** in **Step 0**, **restart** the app, then try **Authenticate** again.")
        elif token_input:
            token_val = token_input.strip()
            try:
                with st.spinner("Verifying token..."):
                    zerodha_auth.exchange_request_token(token_val)
                    st.session_state.auth_status = True
                    st.sidebar.success("Authenticated Successfully! ✅")
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                err_msg = str(e)
                if "checksum" in err_msg.lower():
                    st.sidebar.error(
                        "❌ **Invalid Checksum**: Check **API Key / Secret** in **Step 0** and **Settings**, then restart."
                    )
                elif "request_token" in err_msg.lower():
                    st.sidebar.error(
                        "❌ **Invalid or used request token**. Generate a fresh one with **Login**."
                    )
                else:
                    st.sidebar.warning(f"Exchange failed, trying as access token… ({err_msg})")
                try:
                    zerodha_auth.set_manual_token(token_val)
                    is_valid, _ = zerodha_auth.validate_token()
                    if is_valid:
                        st.session_state.auth_status = True
                        st.sidebar.success("Access Token verified! ✅")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.sidebar.error("Auth failed: token invalid or expired.")
                except Exception:
                    st.sidebar.error(f"Auth failed: {err_msg}")
        else:
            st.sidebar.error("Paste the token first.")

else:
    # AUTHENTICATED STATE
    _prof = zerodha_auth.get_auth_status()
    _disp_name = (_prof.get("user_name") or _prof.get("user_id") or "Trader") if _prof.get("authenticated") else "Trader"
    st.sidebar.success(f"✅ Authenticated ({_disp_name})")
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
        _ok_m, _mmsg = can_place_nse_bse_equity_trade()
        if _ok_m:
            st.sidebar.caption(f"🟢 {_mmsg}")
        else:
            st.sidebar.error(f"🔴 Real orders blocked: {_mmsg}")
    else:
        if st.session_state.get('live_mode', False):
            # Switching to Paper
            st.session_state.live_mode = False
            st.session_state.broker = PaperBroker()
            st.rerun()
            
        st.sidebar.info("🟦 **Mode**: PAPER TRADING")
    
    # NIFTY 500 intraday risk sync (3% daily stop, 5 trades, 1% risk sizing via agent)
    try:
        _cap = session_capital()
    except Exception:
        _cap = float(settings.DAILY_CAPITAL)
    st.session_state.risk_engine.config.max_trades_per_day = MAX_TRADES_PER_DAY
    st.session_state.risk_engine.config.max_loss_per_day = _cap * 0.03
    st.session_state.risk_engine.config.max_capital_per_trade = max(_cap * 0.35, 15000.0)

    # Global Risk Status
    risk_status = "✅ Active" if not st.session_state.risk_engine.daily_stats.is_trading_halted else "❌ HALTED"
    st.sidebar.markdown(f"**Risk Status**: {risk_status}")
    st.sidebar.metric("Daily P&L", f"₹{st.session_state.broker.get_total_pnl():.2f}")
    st.sidebar.metric("Trades Today", f"{st.session_state.risk_engine.daily_stats.total_trades}/{st.session_state.risk_engine.config.max_trades_per_day}")
    st.sidebar.caption(market_status_line())
    if st.sidebar.button("💰 Check Live Funds"):
        try:
            kite = zerodha_auth.get_kite_instance()
            funds = kite.margins(segment="equity")
            with st.sidebar.expander("Zerodha Equity Funds", expanded=True):
                st.write(f"**Available Cash**: ₹{funds.get('net', 0):,.2f}")
                st.write(f"**Utilized**: ₹{funds.get('utilised', {}).get('debits', 0):,.2f}")
        except Exception as e:
            st.sidebar.error(f"Cannot fetch funds: {str(e)}")
    
    # RISK SETTINGS
    with st.sidebar.expander("🛡️ Risk Guardrails", expanded=False):
        cfg = st.session_state.risk_engine.config
        
        st.markdown('<div class="scrollable-guardrails">', unsafe_allow_html=True)
        
        st.markdown("##### 🔒 Intraday Agent (NIFTY 500)")
        st.text("Universe: NIFTY 500, ₹50–₹300, vol ≥5L, spread ≤0.2%")
        st.text(f"Target ≥ {MIN_TARGET_PCT:g}% | Max stop distance <10% (cap {MAX_STOP_LOSS_PCT:g}%)")
        st.text(f"Max trades/day: {MAX_TRADES_PER_DAY} | Confidence ≥ {MIN_CONFIDENCE_TRADE} | HITL before send")
        st.text("Stops: −3% day / 3 losses in a row → halt")
        
        st.markdown("##### 💰 Capital & Loss Limits")
        st.text(f"Max Capital/Trade: ₹{cfg.max_capital_per_trade:,.0f}")
        st.text(f"Max Daily Loss (3%): ₹{cfg.max_loss_per_day:,.0f}")
        st.text("Per-trade risk: ~1% of equity (via bracket SL distance)")
        st.text("Paper Brokerage: ₹20/order (sim)")
        
        st.markdown("##### 📊 Position & Exposure")
        st.text(f"Max Trades/Day: {cfg.max_trades_per_day}")
        st.text(f"10. Max Open Positions: {cfg.max_open_positions}")
        st.text(f"11. Max Position Size: {cfg.max_position_size_percent:.0f}%")
        st.text(f"12. Max Portfolio Exposure: {cfg.max_portfolio_exposure_percent:.0f}%")
        st.text(f"13. Max Sector Exposure: {cfg.max_sector_exposure_percent:.0f}%")
        
        st.markdown("##### ⏰ Time-Based")
        st.text(f"14. Avoid First {cfg.avoid_first_minutes} min")
        st.text(f"15. Avoid Last {cfg.avoid_last_minutes} min")
        st.text(f"16. Min Hold: {cfg.min_hold_time_minutes} min")
        st.text(f"17. Max Age: {cfg.max_position_age_hours} hrs")
        st.text("18. Force Exit By: 3:15 PM IST (MIS — verify broker)")
        
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
        st.text(f"28. Max Deviation: {cfg.max_price_deviation_percent:.1f}%")
        
        st.markdown("##### 🧠 Strategies & PARF")
        st.text("VWAP pullback • ORB (15m) • Momentum (RSI/MA/vol)")
        st.text("Workflow: Plan → Reason → Human approve → Act → Feedback log")
        st.text("Learning: review Feedback log + broker statements after close")
        
        st.markdown("##### 👤 Human in the Loop (required)")
        st.text("All workflow orders: you pick symbols + confirm checkboxes")
        st.text("Below threshold trades are not listed (conf < 75)")
        st.caption("Legacy ensemble tab still toggles 10-strategy paper tests only.")
        
        st.markdown("##### 🛡️ Session safety")
        st.text("Manual risk halt reset clears PnL tally (see button below)")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.divider()
        st.caption("⚙️ **Adjustable Session Limits**")
        
        # Adjustable limits
        new_max_loss = st.number_input("Max Daily Loss (₹)", value=st.session_state.risk_engine.config.max_loss_per_day, step=100.0)
        new_max_trades = st.slider("Max Trades/Day", min_value=1, max_value=5, value=min(5, st.session_state.risk_engine.config.max_trades_per_day), step=1)
        
        # Update config directly
        st.session_state.risk_engine.config.max_loss_per_day = new_max_loss
        st.session_state.risk_engine.config.max_trades_per_day = new_max_trades
        
        if st.session_state.risk_engine.daily_stats.is_trading_halted:
            st.error("⛔ TRADING HALTED (Risk Breach)")
            if st.button("Reset Risk Halt (Admin)"):
                st.session_state.risk_engine.daily_stats.is_trading_halted = False
                st.session_state.risk_engine.daily_stats.total_pnl = 0.0
                st.session_state.risk_engine.daily_stats.consecutive_losses = 0
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
if 'par_feedback_log' not in st.session_state:
    st.session_state.par_feedback_log = []

# --- Main Tabs (same as V3: visible before login — use ⚙️ Settings for API keys) ---
tabs = st.tabs(["🤖 Workflow", "🧠 Strategies", "📂 Portfolio", "📝 Orders", "📊 Reports", "🤖 Intel", "⚙️ Settings"])

with tabs[6]:
    render_settings_tab()

# =====================================================================
# 1. AUTOMATED WORKFLOW - THREE AGENT BOXES
# =====================================================================
with tabs[0]:
    if not st.session_state.auth_status:
        st.info(
            "**Not logged in to Zerodha.** In the **left sidebar**: complete **Step 0** (API keys) if needed, "
            "then **Login** (opens Kite Connect), then paste **request_token** under **Authorize app** and click **Authenticate**. "
            "You can also set keys in **⚙️ Settings** — **restart** after saving."
        )
    st.title("🚀 NIFTY 500 Intraday Agent")
    st.caption(
        "**PARF + HITL:** Plan → Reason → **You approve** → Act → Feedback. "
        f"Targets ≥ **{MIN_TARGET_PCT:g}%**; stops **&lt; 10%** (cap **{MAX_STOP_LOSS_PCT:g}%**). "
        f"Max {MAX_TRADES_PER_DAY} tickets/day, confidence ≥ {MIN_CONFIDENCE_TRADE}, ~1% equity risk vs SL. "
        "Square-off by **3:15 PM IST** (verify with broker for MIS). **Real intraday orders** only in **normal session Mon–Fri 9:15–3:30 PM IST**; pre-open / closing / AMO per exchange rules."
    )
    st.markdown("---")
    
    # START/STOP/RESET Buttons (mobile-friendly)
    col_btn1, col_btn2, col_btn3 = st.columns(3)
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
            if 'intraday_decisions' in st.session_state:
                del st.session_state.intraday_decisions
            st.session_state.par_feedback_log = []
            st.rerun()
    
    st.markdown("---")
    
    if 'batch_tickers' not in st.session_state:
        syms = load_nifty500_symbols()
        st.session_state.batch_tickers = syms[:20] if syms else settings.get_trading_symbols()[:20]
    
    batch_tickers = st.session_state.batch_tickers
    
    # ==================== AGENT BOX 1: INTRADAY SCANNER ====================
    stage1_active = st.session_state.workflow_stage == 1
    stage1_complete = st.session_state.scan_completed
    stage1_status = "🟢 ACTIVE" if stage1_active else ("🔴 DONE" if stage1_complete else "🟠 READY")
    stage1_color = "#00ff00" if stage1_active else ("#ff0000" if stage1_complete else "#FFA500")
    
    st.markdown(f"""
    <div style='border: 3px solid {stage1_color}; border-radius: 10px; padding: 15px; margin-bottom: 10px; 
                background: linear-gradient(135deg, rgba(0,255,0,0.05) 0%, rgba(0,0,0,0.05) 100%);'>
        <h3 style='margin: 0; color: {stage1_color}; font-size: 18px;'>🔍 AGENT 1: INTRADAY SCANNER (NIFTY 500) {stage1_status}</h3>
        <p style='margin: 3px 0 0 0; color: #aaa; font-size: 12px;'>Liquidity + spread + VWAP / ORB / Momentum (Kite OHLCV, RSI, MAs, depth)</p>
    </div>
    """, unsafe_allow_html=True)
    
    if stage1_active and not stage1_complete:
        with st.spinner("🔍 Scanning NIFTY 500 universe (rule filters + strategies)..."):
            try:
                _cap = session_capital()
            except Exception:
                _cap = float(settings.DAILY_CAPITAL)
            decisions = scan_intraday_universe(_cap, max_symbols=40)
            st.session_state.intraday_decisions = decisions
            st.session_state.workflow_results['scanner'] = [decision_to_dict(d) for d in decisions]
            if decisions:
                st.session_state.batch_tickers = [d.stock for d in decisions[:15]]
            st.session_state.scan_completed = True
            st.session_state.workflow_stage = 2
            st.rerun()
    
    if stage1_complete and st.session_state.workflow_results.get('scanner'):
        raw_scan = st.session_state.workflow_results['scanner']
        st.success(f"✅ {len(raw_scan)} actionable setup(s) (all rules + confidence ≥ {MIN_CONFIDENCE_TRADE})")
        scanner_table = []
        for row in raw_scan:
            scanner_table.append({
                "Stock": row["Stock"],
                "Strategy": row["Strategy"],
                "Entry": f"₹{row['Entry Price']:.2f}",
                "SL": f"₹{row['Stop Loss']:.2f}",
                "Target": f"₹{row['Target']:.2f}",
                "Reward %": f"{(row['Target']/row['Entry Price']-1)*100:.1f}%",
                "Risk %": f"{row['Risk %']:.3f}",
                "Conf": row["Confidence Score (0–100)"],
                "Qty": row["Quantity"],
            })
        st.dataframe(pd.DataFrame(scanner_table), use_container_width=True, hide_index=True)
        with st.expander("Decision detail (reasoning)"):
            for row in raw_scan:
                st.markdown(f"**{row['Stock']} — {row['Strategy']}**")
                if row.get("Planning"):
                    st.markdown("**Planning**")
                    st.info(row["Planning"])
                if row.get("HITL checklist"):
                    st.markdown("**Human-in-the-loop checklist**")
                    for pt in row["HITL checklist"]:
                        st.markdown(f"- {pt}")
                st.write(row.get("Reasoning", ""))
                st.caption("Indicators: " + "; ".join(row.get("Indicator signals") or []))
                st.caption("Volume: " + "; ".join(row.get("Volume confirmation") or []))
                st.caption("Market: " + "; ".join(row.get("Market alignment") or []))
                st.divider()
    
    st.markdown("""<div style='text-align: center; font-size: 28px; margin: 8px 0;'>⬇️</div>""", unsafe_allow_html=True)
    
    # ==================== AGENT BOX 2: EXECUTION ====================
    stage2_active = st.session_state.workflow_stage == 2
    stage2_complete = st.session_state.batch_completed
    stage2_status = "🟢 ACTIVE" if stage2_active else ("🔴 DONE" if stage2_complete else "🟠 READY")
    stage2_color = "#00ff00" if stage2_active else ("#ff0000" if stage2_complete else "#FFA500")
    
    _exec_mode = "REAL (bracket MIS)" if st.session_state.get("live_mode") else "PAPER (limit buy — manage SL/target manually)"
    st.markdown(f"""
    <div style='border: 3px solid {stage2_color}; border-radius: 10px; padding: 15px; margin-bottom: 10px;
                background: linear-gradient(135deg, rgba(0,255,0,0.05) 0%, rgba(0,0,0,0.05) 100%);'>
        <h3 style='margin: 0; color: {stage2_color}; font-size: 18px;'>⚡ AGENT 2: ACTING + HITL ({_exec_mode}) {stage2_status}</h3>
        <p style='margin: 3px 0 0 0; color: #aaa; font-size: 12px;'>Planning & reasoning above → your approval → bracket / paper limit</p>
    </div>
    """, unsafe_allow_html=True)
    
    if stage2_active and not stage2_complete:
        try:
            _cap_pb = session_capital()
        except Exception:
            _cap_pb = float(settings.DAILY_CAPITAL)
        _slots = max(
            0,
            st.session_state.risk_engine.config.max_trades_per_day
            - st.session_state.risk_engine.daily_stats.total_trades,
        )
        st.markdown("### 🧭 Planning (proactive)")
        st.markdown(session_planning_brief(_cap_pb, _slots, scan_width=40))

        st.markdown("### 🧠 Reasoning (from scan)")
        st.caption("Each row passed liquidity, NIFTY/RS checks where required, confidence ≥ 75, and **≥10% / &lt;10% SL** profile.")

        decisions = st.session_state.get("intraday_decisions") or []
        sym_labels = [f"{d.stock} ({d.strategy}, conf {d.confidence:.0f})" for d in decisions]
        sym_map = {f"{d.stock} ({d.strategy}, conf {d.confidence:.0f})": d for d in decisions}

        st.markdown("### ✋ Acting — Human in the Loop")
        if st.session_state.risk_engine.daily_stats.is_trading_halted:
            st.error("⛔ Risk engine halted — reset in sidebar or wait for next session.")
            one_shot = [{"Symbol": "—", "Action": "⛔ HALT", "Entry Price": "-", "Exit Price": "-", "Quantity": 0, "Investment": "₹0.00", "P&L": "₹0.00", "ROI": "0.0%", "Reason": "Halted"}]
            st.session_state.workflow_results["batch"] = one_shot
            st.session_state.batch_completed = True
            st.session_state.workflow_stage = 3
            st.rerun()
        elif not decisions:
            st.warning("No setups to approve — adjust session or rerun scan.")
            one_shot = [{"Symbol": "—", "Action": "ℹ️ SKIP", "Entry Price": "-", "Exit Price": "-", "Quantity": 0, "Investment": "₹0.00", "P&L": "₹0.00", "ROI": "0.0%", "Reason": "No setups"}]
            st.session_state.workflow_results["batch"] = one_shot
            st.session_state.batch_completed = True
            st.session_state.workflow_stage = 3
            st.rerun()
        else:
            with st.form("hitl_execute_form"):
                default_pick = sym_labels[: min(len(sym_labels), _slots)]
                picked = st.multiselect(
                    "Approve orders (max = slots left today)",
                    options=sym_labels,
                    default=default_pick,
                    help="Agent will only send what you select. Bracket uses your mandate: ≥10% target, <10% stop.",
                )
                conf_news = st.checkbox("I confirm: no blocking news, spreads OK, bracket levels reviewed")
                conf_risk = st.checkbox("I accept capital risk and broker rules for MIS / bracket orders")
                submitted = st.form_submit_button("Execute approved orders")

            if submitted:
                if not (conf_news and conf_risk):
                    st.error("Confirm both HITL checkboxes to proceed.")
                else:
                    approved = [sym_map[s] for s in picked if s in sym_map]
                    approved = [d for d in approved if d.confidence >= MIN_CONFIDENCE_TRADE][: max(0, _slots)]
                    results = []

                    if st.session_state.get("live_mode"):
                        mk_ok, mk_msg = can_place_nse_bse_equity_trade()
                        if not mk_ok:
                            st.session_state.workflow_results["batch"] = [
                                {
                                    "Symbol": "—",
                                    "Action": "🔴 BLOCKED",
                                    "Entry Price": "-",
                                    "Exit Price": "-",
                                    "Quantity": 0,
                                    "Investment": "₹0.00",
                                    "P&L": "₹0.00",
                                    "ROI": "0.0%",
                                    "Reason": f"NSE/BSE session: {mk_msg}",
                                }
                            ]
                            st.session_state.par_feedback_log.append(
                                {
                                    "ts": datetime.now().isoformat(),
                                    "results": st.session_state.workflow_results["batch"],
                                    "live": True,
                                    "approved": [],
                                }
                            )
                            st.session_state.batch_completed = True
                            st.session_state.workflow_stage = 3
                            st.error(mk_msg)
                            st.rerun()

                    progress_bar = st.progress(0)
                    status_line = st.empty()
                    for i, d in enumerate(approved):
                        status_line.text(f"Executing {d.stock} ({i+1}/{len(approved)})...")
                        est = d.entry_price * d.quantity
                        sl_frac = (d.entry_price - d.stop_loss) / d.entry_price if d.entry_price > 0 else 0.01
                        allowed, rreason = st.session_state.risk_engine.can_place_trade(
                            est, assumed_sl_pct=max(sl_frac, 0.005)
                        )
                        if not allowed:
                            results.append(
                                {
                                    "Symbol": d.stock,
                                    "Action": "🔴 SKIP",
                                    "Entry Price": "-",
                                    "Exit Price": "-",
                                    "Quantity": 0,
                                    "Investment": "₹0.00",
                                    "P&L": "₹0.00",
                                    "ROI": "0.0%",
                                    "Reason": rreason,
                                }
                            )
                            progress_bar.progress((i + 1) / max(1, len(approved)))
                            continue
                        try:
                            if st.session_state.get("live_mode"):
                                if hasattr(st.session_state.broker, "place_bracket_buy"):
                                    st.session_state.broker.place_bracket_buy(
                                        d.stock, d.quantity, d.entry_price, d.stop_loss, d.target
                                    )
                                else:
                                    raise RuntimeError("Live broker missing bracket helper")
                            else:
                                st.session_state.broker.place_order(d.stock, "BUY", d.quantity, d.entry_price)
                            st.session_state.risk_engine.record_trade_entry()
                            results.append(
                                {
                                    "Symbol": d.stock,
                                    "Action": "✅ SENT",
                                    "Entry Price": f"₹{d.entry_price:.2f}",
                                    "Exit Price": f"₹{d.target:.2f}"
                                    if st.session_state.get("live_mode")
                                    else "manual",
                                    "Quantity": d.quantity,
                                    "Investment": f"₹{est:.2f}",
                                    "P&L": "₹0.00",
                                    "ROI": "0.0%",
                                    "Reason": f"{d.strategy} | HITL OK | bracket"
                                    if st.session_state.get("live_mode")
                                    else f"{d.strategy} | HITL | paper limit — SL ₹{d.stop_loss:.2f} TGT ₹{d.target:.2f}",
                                }
                            )
                        except Exception as ex:
                            results.append(
                                {
                                    "Symbol": d.stock,
                                    "Action": "🔴 FAIL",
                                    "Entry Price": "-",
                                    "Exit Price": "-",
                                    "Quantity": 0,
                                    "Investment": "₹0.00",
                                    "P&L": "₹0.00",
                                    "ROI": "0.0%",
                                    "Reason": str(ex)[:120],
                                }
                            )
                        progress_bar.progress((i + 1) / max(1, len(approved)))
                    if not results:
                        results.append(
                            {
                                "Symbol": "—",
                                "Action": "ℹ️ SKIP",
                                "Entry Price": "-",
                                "Exit Price": "-",
                                "Quantity": 0,
                                "Investment": "₹0.00",
                                "P&L": "₹0.00",
                                "ROI": "0.0%",
                                "Reason": "No orders executed (nothing selected or all skipped)",
                            }
                        )
                    status_line.empty()
                    progress_bar.empty()
                    st.session_state.workflow_results["batch"] = results
                    st.session_state.par_feedback_log.append(
                        {
                            "ts": datetime.now().isoformat(),
                            "results": results,
                            "live": bool(st.session_state.get("live_mode")),
                            "approved": [d.stock for d in approved],
                        }
                    )
                    st.session_state.batch_completed = True
                    st.session_state.workflow_stage = 3
                    st.rerun()

    # Display Stage 2 Results if completed
    if stage2_complete and st.session_state.workflow_results['batch']:
        results = st.session_state.workflow_results['batch']
        st.success(f"✅ Batch Complete - {len(results)} trades processed")
        # Calculate summary
        total_pnl = sum([float(r['P&L'].replace('₹','')) for r in results])
        traded_count = len([r for r in results if r['Action'] in ('✅ TRADED', '✅ SENT')])
        
        col_met1, col_met2, col_met3 = st.columns(3)
        col_met1.metric("Total P&L", f"₹{total_pnl:.2f}", delta=f"{total_pnl:.2f}")
        col_met2.metric("Executed", traded_count)
        col_met3.metric("Hit Rate", f"{(traded_count/max(1, len(results))*100):.0f}%")

        with st.expander("📒 Feedback — Planning / Acting log (last cycles)", expanded=False):
            st.caption(
                "**Learning loop:** After close, compare broker fills vs planned entry/SL/TGT; note slippage and news; "
                "adjust your approval checklist if the same failure mode repeats."
            )
            if not st.session_state.par_feedback_log:
                st.caption("No completed HITL cycles yet this session.")
            for entry in reversed(st.session_state.par_feedback_log[-6:]):
                mode = "LIVE" if entry.get("live") else "PAPER"
                ap = ", ".join(entry.get("approved") or []) or "—"
                st.markdown(f"**{entry.get('ts', '')}** · {mode} · Approved: {ap}")
        
        st.markdown("#### 📝 Trade-by-Trade Breakdown")
        
        # Display visual breakdown
        for idx, r in enumerate(results):
            sym = r['Symbol']
            pnl_str = r['P&L']
            invested = r['Investment']
            
            if r['Action'] in ('✅ TRADED', '✅ SENT'):
                pnl_val = float(pnl_str.replace('₹',''))
                if pnl_val > 0:
                    status_emoji = "🟢"
                    status_text = "PROFIT"
                    color = "#00fa9a"
                elif pnl_val < 0:
                    status_emoji = "🔴"
                    status_text = "LOSS"
                    color = "#ff4b4b"
                else:
                    status_emoji = "⚪"
                    status_text = "FLAT"
                    color = "#ffffff"
                
                st.markdown(f"""
                <div style='border-left: 4px solid {color}; padding: 10px; margin-bottom: 8px; background-color: rgba(255,255,255,0.05); border-radius: 4px;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <b>{sym}</b>
                        <span style='color: {color};'><b>{status_emoji} {status_text} • {pnl_str}</b></span>
                    </div>
                    <div style='color: #888; font-size: 13px; margin-top: 4px;'>
                        Invested: <b>{invested}</b> &nbsp;|&nbsp; Entry: {r['Entry Price']} &nbsp;|&nbsp; Exit: {r['Exit Price']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                 st.markdown(f"""
                <div style='border-left: 4px solid #FFA500; padding: 10px; margin-bottom: 8px; background-color: rgba(255,165,0,0.05); border-radius: 4px;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <b style='color: #888;'>{sym}</b>
                        <span style='color: #FFA500;'><b>⚠️ SKIPPED</b></span>
                    </div>
                    <div style='color: #888; font-size: 13px; margin-top: 4px;'>
                        Reason: {r['Reason']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    
    # Visual Flow Arrow
    st.markdown("""<div style='text-align: center; font-size: 28px; margin: 8px 0;'>⬇️</div>""", unsafe_allow_html=True)
    
    # ==================== AGENT BOX 3: AUTO-PILOT MODE ====================
    current_time_full = ist_now()
    current_time = current_time_full.time()
    today_date = current_time_full.date()

    session_name = equity_cash_session_phase(current_time_full)
    is_market_hours = session_name == "regular" and is_nse_bse_trading_day(today_date)
    
    stage3_active = st.session_state.workflow_stage == 3
    stage3_complete = st.session_state.batch_completed and st.session_state.workflow_stage > 3
    
    # Determine status and color based on session
    if not is_market_hours:
        stage3_status = "🔴 CLOSED"
        stage3_color = "#ff0000"
    elif stage3_active:
        stage3_status = "🟢 LIVE"
        stage3_color = "#00ff00"
    elif stage3_complete:
        stage3_status = "🔴 DONE"
        stage3_color = "#ff0000"
    else:
        stage3_status = "🟠 READY"
        stage3_color = "#FFA500"
    
    st.markdown(f"""
    <div style='border: 3px solid {stage3_color}; border-radius: 10px; padding: 15px; margin-bottom: 10px;
                background: linear-gradient(135deg, rgba(0,255,0,0.05) 0%, rgba(0,0,0,0.05) 100%);'>
        <h3 style='margin: 0; color: {stage3_color}; font-size: 18px;'>🤖 AGENT 3: AUTO-PILOT {stage3_status}</h3>
        <p style='margin: 3px 0 0 0; color: #aaa; font-size: 12px;'>Monitor • algo slices | Mandate: ≥{MIN_TARGET_PCT:g}% TGT / &lt;10% SL | Square-off check 3:15 PM IST</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Check if market is closed (normal / continuous session only)
    if not is_market_hours:
        if not is_nse_bse_trading_day(today_date):
            _why = "Not an equity **trading day** (weekend or exchange holiday)."
        elif session_name == "pre_open":
            _why = "**Pre-open** (9:00–9:15 IST). Normal session 9:15–3:30 PM IST."
        elif session_name == "between_regular_and_closing":
            _why = "Between **normal close (3:30 PM)** and **closing call (3:40–4:00 PM IST)**."
        elif session_name == "closing":
            _why = "**Closing price session** (3:40–4:00 PM IST), not continuous trading."
        else:
            _why = "Outside **normal** cash hours. **AMO** may apply until next open (verify broker)."
        st.error(f"""
        🔴 **AUTO-PILOT (normal session) OFF** — {_why}

        **Cash market (typical):** Pre-open 9:00–9:15 · Normal 9:15–3:30 · Closing call 3:40–4:00 — all IST. Mon–Fri only.  
        **Current time:** {current_time_full.strftime('%I:%M:%S %p')} IST  
        """)

        # Show market closed countdown
        col_closed1, col_closed2, col_closed3 = st.columns(3)
        col_closed1.metric("Status", "🔴 CLOSED")
        col_closed2.metric("Time", current_time_full.strftime('%I:%M %p'))

        if current_time < REGULAR_START and is_nse_bse_trading_day(today_date):
            open_at = datetime.combine(current_time_full.date(), REGULAR_START, tzinfo=IST)
            time_to_open = open_at - current_time_full
            hours, remainder = divmod(max(0, int(time_to_open.total_seconds())), 3600)
            minutes, _ = divmod(remainder, 60)
            col_closed3.metric("Normal opens in", f"{hours}h {minutes}m")
        else:
            col_closed3.metric("Next normal", "Mon–Fri 9:15 AM")
    
    # Display Stage 3 if active and market is open
    elif stage3_active:
        st.success("🚀 Auto-Pilot ACTIVE - Monitoring")
        
        col_ap1, col_ap2, col_ap3 = st.columns(3)
        col_ap1.metric("Status", "🟢 RUNNING")
        col_ap2.metric("Time", current_time_full.strftime("%H:%M:%S"))
        col_ap3.metric("Next Scan", "5 min")
        
        # Show Active Strategy Validation
        st.markdown("### 🧠 Intraday strategies (VWAP pullback • ORB • Momentum)")
        st.caption("Live path uses Kite OHLCV + depth; bracket orders handle target/stop when Zerodha allows BO on the symbol.")
        
        # Get active strategies from the engine
        strategies = st.session_state.strategy_engine.strategies

        # --- HFT-LITE EXECUTION LOOP (Every Cycle) ---
        if 'broker' in st.session_state:
             if st.session_state.get('live_mode', False):
                 if hasattr(st.session_state.broker, 'process_algo_orders'):
                     st.session_state.broker.process_algo_orders()
             else:
                 try:
                     market_data_map = market_data.get_quote(batch_tickers)
                     if hasattr(st.session_state.broker, 'process_algo_orders'):
                         st.session_state.broker.process_algo_orders(market_data_map)
                 except Exception as e:
                     pass
        
        # Display strategy status in a grid (2 columns for mobile)
        st.markdown("#### 📊 Active Strategy Matrix")
        
        col_s1, col_s2 = st.columns(2)
        strategy_cols = [col_s1, col_s2]
        
        for idx, strat in enumerate(strategies):
            col = strategy_cols[idx % 2]
            is_active = st.session_state.strategy_engine.active_strategies.get(strat.name, True)
            
            if is_active:
                col.markdown(f"""
                <div style='border: 2px solid #00ff00; border-radius: 8px; padding: 8px; margin-bottom: 6px; background-color: rgba(0,255,0,0.1);'>
                    <b style='color: #00ff00; font-size: 13px;'>✅ {strat.name}</b><br>
                    <span style='color: #888; font-size: 10px;'>{strat.description[:35]}...</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                col.markdown(f"""
                <div style='border: 2px solid #666; border-radius: 8px; padding: 8px; margin-bottom: 6px; background-color: rgba(100,100,100,0.1);'>
                    <b style='color: #666; font-size: 13px;'>⏸️ {strat.name}</b>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Show validation flow (compact for mobile)
        st.markdown("### 🔄 Monitor loop")
        col_f1, col_f2 = st.columns(2)
        
        col_f1.markdown("""
        **Positions & brackets**  
        📊 Live quotes / depth  
        🧠 VWAP • ORB • Momentum context
        """)
        
        col_f2.markdown("""
        **Discipline**  
        ⚖️ ≥10% T / &lt;10% SL profile  
        🛡️ Risk engine + HITL on new sends
        """)
        
        st.markdown("---")
        
        st.info("""
        **🔍 Monitor (Agent 3):**
        - MIS brackets carry **≥10%** target and **&lt;10%** stop as set in Agent 2
        - Algo slices (if any) still respect VWAP for child fills
        - **Re-scan:** run Workflow **RESET** then **START** for a fresh plan (no auto re-HITL)
        - Exit discipline: confirm **3:15 PM IST** square-off with your broker
        """)
        
        # Live Activity Log
        st.markdown("### 📝 Activity")
        with st.container():
            st.text(f"{current_time_full.strftime('%H:%M:%S')} - ✅ Intraday mandate: TGT ≥{MIN_TARGET_PCT:g}% / SL <10%")
            st.text(f"{current_time_full.strftime('%H:%M:%S')} - ✅ Workflow sends only after HITL (Agent 2)")
            st.text(f"{current_time_full.strftime('%H:%M:%S')} - 🔄 Monitor / algo slice tick")
            st.text(f"{current_time_full.strftime('%H:%M:%S')} - 📊 Watchlist: {', '.join(batch_tickers)}")
    else:
        if is_market_hours:
            st.info("⏳ Finish Agent 2 (HITL approval & execution) to enter monitor phase.")
        else:
            st.warning(f"""
            ⏰ **Outside normal session** ({session_name.replace('_', ' ')}) — Auto-Pilot uses **9:15 AM–3:30 PM IST** on trading days.  
            Current: {current_time_full.strftime('%I:%M %p')} IST
            """)

# =====================================================================
# 2. STRATEGIES
# =====================================================================
with tabs[1]:
    st.header("🧠 Strategy Engine")
    st.markdown("Enable/Disable strategies. **Momentum/Trend strategies are prioritized.**")
    
    strategies = st.session_state.strategy_engine.strategies
    for strat in strategies:
        active = st.toggle(strat.name, value=True, key=f"v4_strat_{strat.name}")
        st.session_state.strategy_engine.active_strategies[strat.name] = active
        st.caption(f"Logic: {strat.description}")

# =====================================================================
# 3. PORTFOLIO
# =====================================================================
with tabs[2]:
    st.header("📂 Portfolio")
    positions = st.session_state.broker.get_portfolio()
    if positions:
        for p in positions:
            if not st.session_state.get('live_mode', False) and p.ltp == 0:
                 p.ltp = p.avg_price * 1.01  # Fallback mock
            
            pnl_color = "green" if p.unrealized_pnl >= 0 else "red"
            st.markdown(f"""
            <div style='border:1px solid #333; padding:10px; border-radius:8px; margin-bottom:8px;'>
                <b>{p.symbol}</b>: {p.quantity} Qty @ {p.avg_price}<br>
                P&L: <span style='color:{pnl_color}'>₹{p.unrealized_pnl:.2f}</span>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"Close {p.symbol}", key=f"v4_close_{p.symbol}"):
                if st.session_state.get("live_mode"):
                    mk_ok, mk_msg = can_place_nse_bse_equity_trade()
                    if not mk_ok:
                        st.error(f"Cannot close (live): {mk_msg}")
                    else:
                        st.session_state.broker.place_order(p.symbol, "SELL", p.quantity, p.ltp)
                        st.session_state.risk_engine.update_after_trade((p.ltp - p.avg_price) * p.quantity)
                        st.rerun()
                else:
                    st.session_state.broker.place_order(p.symbol, "SELL", p.quantity, p.ltp)
                    st.session_state.risk_engine.update_after_trade((p.ltp - p.avg_price) * p.quantity)
                    st.rerun()
    else:
        st.info("No Open Positions")

# =====================================================================
# 4. ORDERS & TOOLS
# =====================================================================
with tabs[3]:
    st.header("📝 Order Book & Tools")
    st.dataframe([vars(o) for o in st.session_state.broker.orders], use_container_width=True)
    
    entry_title = "Manual Order Entry (REAL MONEY ⚠️)" if st.session_state.get('live_mode') else "Manual Paper Entry (Test)"
    st.subheader(entry_title)
    with st.form("manual_order_v4"):
        sym = st.text_input("Symbol")
        col_q, col_p = st.columns(2)
        with col_q:
            qty = st.number_input("Qty", min_value=1, value=1)
        with col_p:
            price = st.number_input("Price", min_value=1.0, value=100.0)
        submitted = st.form_submit_button("Test Buy")
        
        if submitted:
             allowed, reason = st.session_state.risk_engine.can_place_trade(price * qty)
             if allowed:
                 if st.session_state.get("live_mode"):
                     mk_ok, mk_msg = can_place_nse_bse_equity_trade()
                     if not mk_ok:
                         st.error(f"Real order blocked: {mk_msg}")
                     else:
                         st.session_state.broker.place_order(sym, "BUY", qty, price)
                         st.session_state.risk_engine.record_trade_entry()
                         st.success("Order Placed")
                         st.rerun()
                 else:
                     st.session_state.broker.place_order(sym, "BUY", qty, price)
                     st.session_state.risk_engine.record_trade_entry()
                     st.success("Test Order Placed")
                     st.rerun()
             else:
                 st.error(f"Risk Block: {reason}")

# =====================================================================
# 5. REPORTS
# =====================================================================
with tabs[4]:
    st.header("📊 Performance Reports")
    
    # Metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Realized P&L", f"₹{st.session_state.broker.realized_pnl:.2f}")
    
    orders = st.session_state.broker.orders
    closed_trades = [o for o in orders if o.transaction_type == "SELL"]
    wins = len([t for t in closed_trades if (t.price * t.quantity) > (t.quantity * 100)]) 
    
    col2.metric("Total Orders", len(orders))
    
    # Detailed Trade Ledger
    st.subheader("📜 Trade History")
    
    if orders:
        ledger_data = []
        for o in orders:
            total_val = o.quantity * o.price
            ledger_data.append({
                "Time": o.timestamp.strftime("%H:%M:%S"),
                "Symbol": o.symbol,
                "Type": o.transaction_type,
                "Qty": o.quantity,
                "Price": f"₹{o.price:.2f}",
                "Value": f"₹{total_val:.2f}",
                "Brokerage": f"₹{o.brokerage_est:.2f}"
            })
        
        st.dataframe(ledger_data, use_container_width=True)
        
        st.markdown("### 📊 Profitability Analysis")
        closed_positions_summary = []
        from collections import defaultdict
        trades_by_sym = defaultdict(list)
        for o in orders:
            trades_by_sym[o.symbol].append(o)
            
        for sym, trade_list in trades_by_sym.items():
            buys = [t for t in trade_list if t.transaction_type == "BUY"]
            sells = [t for t in trade_list if t.transaction_type == "SELL"]
            
            if buys and sells:
                avg_buy = sum(b.price * b.quantity for b in buys) / sum(b.quantity for b in buys)
                total_sold_qty = sum(s.quantity for s in sells)
                avg_sell = sum(s.price * s.quantity for s in sells) / total_sold_qty
                
                invested = avg_buy * total_sold_qty
                sold_val = avg_sell * total_sold_qty
                profit = sold_val - invested
                
                closed_positions_summary.append({
                    "Stock": sym,
                    "Avg Buy": f"₹{avg_buy:.2f}",
                    "Bought": sum(b.quantity for b in buys), 
                    "Sold": total_sold_qty,
                    "Invested": f"₹{invested:.2f}",
                    "Sold Val": f"₹{sold_val:.2f}",
                    "Profit": f"₹{profit:.2f}",
                    "Status": "PROFIT" if profit > 0 else "LOSS"
                })
        
        if closed_positions_summary:
            st.dataframe(closed_positions_summary, use_container_width=True)
        else:
            st.info("No closed positions yet.")
            
    else:
        st.info("No trades executed yet.")

# =====================================================================
# 6. MARKET INTELLIGENCE
# =====================================================================
with tabs[5]:
    st.header("🤖 Market Intelligence")
    st.caption("AI-Driven Deep Dive Report")
    
    if st.button("Generate Intelligence Report 🧠", type="primary"):
        with st.spinner("Analyzing Institutional Data, History, Regimes..."):
            time.sleep(2)
            report = st.session_state.intel_engine.generate_report()
            
            st.success(f"Report @ {report.timestamp.strftime('%H:%M:%S')}")
            
            # SECTION A
            st.subheader("A. Institutional Entry")
            sec_a = report.sections["A"]
            st.info(f"**{sec_a.summary}**")
            c1, c2 = st.columns(2)
            c1.metric("Inst. Prob", sec_a.metrics["Inst. Dominance Prob"])
            c2.metric("Order Flow", sec_a.metrics["Bid-Ask Imbalance"])
            st.metric("Action", sec_a.metrics["Suggested Action"])
            for detail in sec_a.details:
                st.write(f"- {detail}")
            st.divider()

            # SECTION B
            st.subheader("B. Strategy Performance (2Y)")
            sec_b = report.sections["B"]
            st.markdown(f"*{sec_b.summary}*")
            c1, c2 = st.columns(2)
            c1.metric("Best Strategy", sec_b.metrics["Best Strategy"])
            c2.metric("Worst Strategy", sec_b.metrics["Worst Strategy"])
            st.metric("Reliability", sec_b.metrics["Reliability"])
            for detail in sec_b.details:
                st.write(f"- {detail}")
            st.divider()

            # SECTION C
            st.subheader("C. Market Context (5Y)")
            sec_c = report.sections["C"]
            st.markdown(f"*{sec_c.summary}*")
            c1, c2 = st.columns(2)
            c1.metric("Regime", sec_c.metrics["Market Regime"])
            c2.metric("Expansion Prob", sec_c.metrics["Expansion Probability"])
            st.metric("Horizon", sec_c.metrics["Time Horizon"])
            for detail in sec_c.details:
                st.write(f"- {detail}")
            st.divider()

            # SECTION D
            st.subheader("D. Bullish vs Bearish")
            sec_d = report.sections["D"]
            st.warning(f"**{sec_d.summary}**")
            c1, c2 = st.columns(2)
            c1.metric("Bull Score", sec_d.metrics["Bullish Score"])
            c2.metric("Bear Score", sec_d.metrics["Bearish Score"])
            st.metric("Verdict", sec_d.metrics["Control"].replace("**",""))
            for detail in sec_d.details:
                st.write(f"- {detail}")

st.caption("📱 Momentum/Trend Bot V4 — Mobile Ready")
