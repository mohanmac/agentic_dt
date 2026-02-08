"""
Streamlit dashboard for DayTradingPaperBot.
Real-time monitoring, HITL approvals, and system status.
"""
import streamlit as st
import pandas as pd
from datetime import datetime
import time
import sys
import requests
import webbrowser
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.storage import storage
from app.core.zerodha_auth import zerodha_auth
from app.core.config import settings
from app.core.utils import format_price, format_pnl
from app.core.schemas import OrderStatus


# Page config
st.set_page_config(
    page_title="DayTradingPaperBot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .big-metric {
        font-size: 2rem;
        font-weight: bold;
    }
    .safe-mode-alert {
        background-color: #ff4444;
        color: white;
        padding: 1rem;
        border-radius: 0.5rem;
        font-weight: bold;
        text-align: center;
        margin-bottom: 1rem;
    }
    .success-box {
        background-color: #00cc66;
        color: white;
        padding: 0.5rem;
        border-radius: 0.3rem;
        margin: 0.5rem 0;
    }
    .warning-box {
        background-color: #ff9900;
        color: white;
        padding: 0.5rem;
        border-radius: 0.3rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main dashboard function."""
    
    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.title("📈 DayTradingPaperBot")
    
    with col2:
        st.metric("Mode", "PAPER" if not settings.ENABLE_LIVE_TRADING else "LIVE ⚠️")
    
    with col3:
        current_time = datetime.now().strftime("%H:%M:%S")
        st.metric("Time", current_time)
    
    # Auth status
    auth_status = zerodha_auth.get_auth_status()
    
    # Initialize session state for login flow
    if 'login_step' not in st.session_state:
        st.session_state.login_step = 1
        
    # --- Sidebar - Authentication ---
    with st.sidebar:
        st.header("🔐 Authentication")
        
        if not auth_status.get("authenticated"):
            st.warning("❌ Not Authenticated")
            
            # Step 1: Login Credentials
            st.markdown("### Step 1: Login")
            st.info("Enter details to open Zerodha login.")
            
            user_id = st.text_input("User ID", value="RVQ434")
            password = st.text_input("Password", type="password")
                
            if st.button("🚀 Login & Get Token"):
                if user_id and password:
                    st.session_state.temp_user_id = user_id
                    
                    # Fetch login URL
                    try:
                        response = requests.get("http://127.0.0.1:8000/auth/login_url", timeout=2)
                        if response.status_code == 200:
                            login_url = response.json().get("login_url")
                            st.session_state.auth_url = login_url
                            st.session_state.login_step = 2
                            
                            # Auto-open in new tab
                            webbrowser.open_new_tab(login_url)
                            st.success("Opening Zerodha login page...")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Could not fetch URL")
                    except Exception:
                        st.error("Auth server unreachable")
                else:
                    st.warning("Enter User ID & Password")
            
            # Step 2: Login Link & Token Entry
            if st.session_state.get('login_step', 1) >= 2:
                # Login Link
                if st.session_state.get('auth_url'):
                    st.markdown("---")
                    st.markdown(
                        f'''
                        <a href="{st.session_state.auth_url}" target="_blank" style="
                            display: inline-block;
                            width: 100%;
                            background-color: #ff5722;
                            color: white;
                            text-align: center;
                            text-decoration: none;
                            padding: 10px;
                            border-radius: 5px;
                            font-weight: bold;
                            margin-bottom: 10px;">
                            🔑 Open Zerodha Login (New Tab)
                        </a>
                        ''', 
                        unsafe_allow_html=True
                    )
                    st.info("1. Click above to log in.\n2. Copy the 'request_token' from the URL.\n3. Paste it below.")
                
                st.markdown("---")
                st.markdown("### Step 2: Enter Token")
                
                manual_token = st.text_input("Access Token / Request Token", type="password", help="Paste from Zerodha redirect")
                
                if st.button("✅ Sync & Verify"):
                    if manual_token:
                        uid = st.session_state.get('temp_user_id', 'Unknown')
                        # Try to handle both access token (direct) or request token (needs exchange)
                        
                        try:
                            # Attempt 1: Try exchanging as Request Token
                            with st.spinner("Exchanging token..."):
                                zerodha_auth.exchange_request_token(manual_token)
                                st.success("✅ Token Exchanged & Authenticated!")
                                time.sleep(1)
                                st.rerun()
                                
                        except Exception as e:
                            # Attempt 2: Treat as direct Access Token
                            st.warning(f"Exchange failed. Trying as Access Token... ({str(e)})")
                            time.sleep(0.5)
                            
                            try:
                                # Set it
                                zerodha_auth.set_manual_token(manual_token, user_id=uid, user_name=uid)
                                
                                # VALIDATE IMMEDIATELY
                                is_valid, profile = zerodha_auth.validate_token()
                                
                                if is_valid:
                                    st.success(f"✅ Access Token Verified! Welcome {profile.get('user_name')}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    # If validation fails, it's neither a valid Request Token nor a valid Access Token
                                    st.error("❌ Authentication Failed!")
                                    st.error("The token provided is invalid or expired.")
                                    st.markdown("""
                                    **Possible causes:**
                                    1. **Token Expired:** Request tokens expire in minutes. Generate a new one.
                                    2. **API Secret Mismatch:** Check `KITE_API_SECRET` in your `.env` file.
                                    3. **Already Used:** Tokens are one-time use.
                                    """)
                                    # We do NOT rerun here, so user sees the error
                                    
                            except Exception as inner_e:
                                st.error(f"Critical Auth Error: {str(inner_e)}")
                    else:
                        st.error("Paste token first")
            
            # Debug info at bottom of sidebar
            with st.expander("🛠️ Debug Config"):
                st.write(f"**API Key:** `{settings.KITE_API_KEY[:4]}...{settings.KITE_API_KEY[-4:]}`")
                st.write(f"**Secret:** `{settings.KITE_API_SECRET[:4]}...{settings.KITE_API_SECRET[-4:]}`")
                st.info("Restart app if these are wrong.")
                    
        else:
            # Authenticated State in Sidebar
            st.success("✅ Connected")
            st.info("Ready for Trading")
            st.write(f"**User:** {auth_status.get('user_name', 'Unknown')}")
            
            if st.button("Logout"):
                zerodha_auth.logout()
                st.rerun()
                
            st.markdown("---")
            # Emerging Button also goes here if authenticated
            if st.button("Emerging 🚀", help="Show trends of emerging players"):
                show_emerging_trends()

    # --- Main Content ---
    if not auth_status.get("authenticated"):
        st.info("👈 Please authenticate in the Left Sidebar to access the dashboard.")
        return

    # Reset login step if authenticated
    if auth_status.get("authenticated"):
        st.session_state.login_step = 1
    
    # Get daily state
    daily_state = storage.get_or_create_daily_state()
    
    # SAFE_MODE alert
    if daily_state.safe_mode:
        st.markdown(
            '<div class="safe-mode-alert">🚨 SAFE MODE ACTIVE - MAX DAILY LOSS REACHED 🚨</div>',
            unsafe_allow_html=True
        )
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Overview",
        "💼 Positions",
        "📋 Trade History",
        "✅ HITL Approvals",
        "⚙️ Settings",
        "📝 Manual Order"
    ])
    
    with tab1:
        show_overview(daily_state)
    
    with tab2:
        show_positions()
    
    with tab3:
        show_trade_history()
    
    with tab4:
        show_hitl_approvals()
    
    with tab5:
        show_settings()

    with tab6:
        show_manual_order()
    
    # Auto-refresh
    time.sleep(10)
    st.rerun()


def show_overview(daily_state):
    """Show overview metrics."""
    st.header("Daily Overview")
    
    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        pnl_color = "normal" if daily_state.total_pnl >= 0 else "inverse"
        st.metric(
            "Total P&L",
            format_pnl(daily_state.total_pnl),
            delta=f"{daily_state.total_pnl:+.2f}",
            delta_color=pnl_color
        )
    
    with col2:
        st.metric(
            "Realized P&L",
            format_pnl(daily_state.realized_pnl)
        )
    
    with col3:
        st.metric(
            "Unrealized P&L",
            format_pnl(daily_state.unrealized_pnl)
        )
    
    with col4:
        st.metric(
            "Trades Today",
            f"{daily_state.trades_count} / {daily_state.max_trades}"
        )
    
    # Loss budget
    st.subheader("Loss Budget")
    
    budget_pct = (daily_state.loss_budget_remaining / daily_state.max_daily_loss) * 100
    
    st.progress(budget_pct / 100)
    st.write(f"Remaining: {format_price(daily_state.loss_budget_remaining)} / {format_price(daily_state.max_daily_loss)}")
    
    # Active strategy
    st.subheader("Active Strategy")
    
    if daily_state.active_strategy:
        st.info(f"📊 {daily_state.active_strategy.value.replace('_', ' ').title()}")
        
        if daily_state.strategy_switched_at:
            st.caption(f"Last switched: {daily_state.strategy_switched_at.strftime('%H:%M:%S')}")
    else:
        st.warning("No active strategy yet")


def show_emerging_trends():
    """Show trends for emerging players."""
    st.markdown("## 🚀 Emerging 7 (Low Cost & Rising)")
    st.info("Tracking specific low-cost, high-potential emerging stocks.")
    
    symbols = settings.get_trading_symbols()
    
    # Try to fetch live data
    from app.core.market_data import market_data
    
    with st.spinner("Fetching live prices..."):
        try:
            ltp_data = market_data.get_ltp(symbols)
        except Exception:
            ltp_data = {}
            st.warning("⚠️ Live market data unavailable. Showing symbol list.")
    
    # Display in grid
    st.markdown("### Market Watch")
    cols = st.columns(3)
    for i, symbol in enumerate(symbols):
        with cols[i % 3]:
            price = ltp_data.get(symbol, 0.0)
            
            # Simulated trend color (green if price > 0)
            delta_color = "normal"
            
            st.metric(
                label=symbol,
                value=f"₹{price:.2f}" if price else "N/A",
                delta=None
            )
            
            # Add a mini chart or extra info if available (placeholder for now)
            if price > 0 and price < 100:
                st.caption("🔥 Low Cost GEM")
    
    st.markdown("---")


def show_manual_order():
    """Show manual order form."""
    st.header("Manual Order (Paper)")
    
    with st.form("manual_order_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            symbol = st.selectbox("Symbol", settings.get_trading_symbols())
            side = st.selectbox("Side", ["BUY", "SELL"])
        
        with col2:
            order_type = st.selectbox("Type", ["MARKET", "LIMIT"])
            quantity = st.number_input("Quantity", min_value=1, value=1)
        
        price = st.number_input("Price (Limit)", min_value=0.0, value=0.0, step=0.05)
        
        submitted = st.form_submit_button("Place Order")
        
        if submitted:
            place_manual_order(symbol, side, order_type, quantity, price)


def place_manual_order(symbol, side, order_type, quantity, price):
    """Execute manual order."""
    from app.core.schemas import TradeIntent, TradeSide, OrderType, StrategyType, RiskApproval
    from app.agents.execution_paper import execution_paper
    from app.core.storage import storage
    import uuid
    
    try:
        side_enum = TradeSide.BUY if side == "BUY" else TradeSide.SELL
        type_enum = OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT
        
        # Create intent
        intent = TradeIntent(
            strategy_id=StrategyType.MOMENTUM_BREAKOUT,  # Default for manual
            symbol=symbol,
            side=side_enum,
            quantity=quantity,
            entry_type=type_enum,
            entry_price=price if type_enum == OrderType.LIMIT else 0.0,
            stop_loss_price=0.0,  # Manual orders might not have SL
            target_price=0.0,
            confidence_score=1.0,
            rationale="Manual Order from Dashboard",
            expected_risk_rupees=0.0,
            status="approved"
        )
        
        # Save intent to get ID
        intent_id = storage.save_trade_intent(intent)
        
        # Create approval
        approval = RiskApproval(
            intent_id=intent_id,
            approved=True,
            adjusted_quantity=quantity,
            remaining_loss_budget=1000.0, # Placeholder
            trades_today=0,
            current_strategy=StrategyType.MOMENTUM_BREAKOUT
        )
        
        # Save approval
        storage.save_approval(approval)
        
        # Execute
        order = execution_paper.execute(intent, approval)
        
        if order:
            st.success(f"✅ Order placed: {order.symbol} {order.side.value} {order.quantity} @ {order.fill_price}")
            time.sleep(1)
            st.rerun()
        else:
            st.error("❌ Order execution failed (check logs)")
            
    except Exception as e:
        st.error(f"Error placing order: {str(e)}")


def show_positions():
    """Show open positions."""
    st.header("Open Positions")
    
    positions = storage.get_all_positions()
    
    if not positions:
        st.info("No open positions")
        return
    
    # Convert to DataFrame
    pos_data = []
    for pos in positions:
        pos_data.append({
            "Symbol": pos.symbol,
            "Quantity": pos.quantity,
            "Avg Price": f"₹{pos.avg_price:.2f}",
            "Current Price": f"₹{pos.current_price:.2f}" if pos.current_price else "N/A",
            "Unrealized P&L": format_pnl(pos.unrealized_pnl),
            "Stop Loss": f"₹{pos.stop_loss_price:.2f}" if pos.stop_loss_price else "N/A",
            "Target": f"₹{pos.target_price:.2f}" if pos.target_price else "N/A",
            "Strategy": pos.strategy.value if pos.strategy else "N/A"
        })
    
    df = pd.DataFrame(pos_data)
    st.dataframe(df, use_container_width=True)


def show_trade_history():
    """Show trade history."""
    st.header("Trade History")
    
    # Get recent orders from database
    with storage.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                timestamp, symbol, side, quantity, order_type,
                fill_price, slippage, brokerage, status
            FROM paper_orders
            WHERE status = 'filled'
            ORDER BY timestamp DESC
            LIMIT 50
        """)
        
        orders = cursor.fetchall()
    
    if not orders:
        st.info("No trade history yet")
        return
    
    # Convert to DataFrame
    trade_data = []
    for order in orders:
        trade_data.append({
            "Time": order['timestamp'],
            "Symbol": order['symbol'],
            "Side": order['side'].upper(),
            "Quantity": order['quantity'],
            "Type": order['order_type'],
            "Fill Price": f"₹{order['fill_price']:.2f}",
            "Slippage": f"₹{order['slippage']:.2f}",
            "Brokerage": f"₹{order['brokerage']:.2f}"
        })
    
    df = pd.DataFrame(trade_data)
    st.dataframe(df, use_container_width=True)


def show_hitl_approvals():
    """Show HITL approval panel."""
    st.header("Human-in-the-Loop Approvals")
    
    # Get pending approvals
    with storage.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                a.id as approval_id,
                a.intent_id,
                a.hitl_reason,
                a.hitl_status,
                t.timestamp,
                t.strategy_id,
                t.symbol,
                t.side,
                t.quantity,
                t.entry_price,
                t.stop_loss_price,
                t.target_price,
                t.confidence_score,
                t.rationale,
                t.expected_risk_rupees
            FROM approvals a
            JOIN trade_intents t ON a.intent_id = t.id
            WHERE a.hitl_required = 1 AND a.hitl_status = 'pending'
            ORDER BY a.timestamp DESC
        """)
        
        pending = cursor.fetchall()
    
    if not pending:
        st.success("✅ No pending approvals")
        return
    
    st.warning(f"⏳ {len(pending)} trade(s) awaiting approval")
    
    for approval in pending:
        with st.expander(f"📋 {approval['symbol']} - {approval['strategy_id']} ({approval['side'].upper()})"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Trade Details:**")
                st.write(f"- Symbol: {approval['symbol']}")
                st.write(f"- Strategy: {approval['strategy_id']}")
                st.write(f"- Side: {approval['side'].upper()}")
                st.write(f"- Quantity: {approval['quantity']}")
                st.write(f"- Entry: ₹{approval['entry_price']:.2f}" if approval['entry_price'] else "MARKET")
                st.write(f"- Stop Loss: ₹{approval['stop_loss_price']:.2f}")
                st.write(f"- Target: ₹{approval['target_price']:.2f}" if approval['target_price'] else "N/A")
            
            with col2:
                st.write("**Risk & Confidence:**")
                st.write(f"- Confidence: {approval['confidence_score']:.1%}")
                st.write(f"- Expected Risk: ₹{approval['expected_risk_rupees']:.2f}")
                st.write(f"- HITL Reason: {approval['hitl_reason']}")
            
            st.write("**Rationale:**")
            st.info(approval['rationale'])
            
            # Approval buttons
            col_approve, col_reject = st.columns(2)
            
            with col_approve:
                if st.button(f"✅ Approve", key=f"approve_{approval['approval_id']}"):
                    # Update approval status
                    with storage.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE approvals SET hitl_status = 'approved' WHERE id = ?",
                            (approval['approval_id'],)
                        )
                        cursor.execute(
                            "UPDATE trade_intents SET status = 'approved' WHERE id = ?",
                            (approval['intent_id'],)
                        )
                    
                    st.success("Trade approved!")
                    time.sleep(1)
                    st.rerun()
            
            with col_reject:
                if st.button(f"❌ Reject", key=f"reject_{approval['approval_id']}"):
                    # Update approval status
                    with storage.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE approvals SET hitl_status = 'rejected' WHERE id = ?",
                            (approval['approval_id'],)
                        )
                        cursor.execute(
                            "UPDATE trade_intents SET status = 'rejected' WHERE id = ?",
                            (approval['intent_id'],)
                        )
                    
                    st.success("Trade rejected")
                    time.sleep(1)
                    st.rerun()


def show_settings():
    """Show settings and configuration."""
    st.header("Settings & Configuration")
    
    st.subheader("Trading Parameters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"**Daily Capital:** {format_price(settings.DAILY_CAPITAL)}")
        st.write(f"**Max Daily Loss:** {format_price(settings.MAX_DAILY_LOSS)}")
        st.write(f"**Max Trades/Day:** {settings.MAX_TRADES_PER_DAY}")
        st.write(f"**Per-Trade Max Loss %:** {settings.PER_TRADE_MAX_LOSS_PERCENT}%")
    
    with col2:
        st.write(f"**Trading Mode:** {'PAPER' if not settings.ENABLE_LIVE_TRADING else 'LIVE ⚠️'}")
        st.write(f"**HITL First N Trades:** {settings.REQUIRE_HITL_FIRST_N_TRADES}")
        st.write(f"**HITL Confidence Threshold:** {settings.HITL_CONFIDENCE_THRESHOLD}")
        st.write(f"**Strategy Switch Cooldown:** {settings.STRATEGY_SWITCH_COOLDOWN_MINUTES} min")
    
    st.subheader("LLM Configuration")
    st.write(f"**Provider:** {settings.LLM_PROVIDER.upper()}")
    
    if settings.LLM_PROVIDER == "google":
        st.write(f"**Model:** {settings.GOOGLE_MODEL}")
        masked_key = f"{settings.GOOGLE_API_KEY[:4]}...{settings.GOOGLE_API_KEY[-4:]}" if settings.GOOGLE_API_KEY else "Not Set"
        st.write(f"**API Key:** {masked_key}")
    else:
        st.write(f"**Base URL:** {settings.OLLAMA_BASE_URL}")
        st.write(f"**Model:** {settings.OLLAMA_MODEL}")
    
    st.subheader("Trading Symbols")
    # Show symbols from settings which we updated
    st.write(", ".join(settings.get_trading_symbols()))
    
    # Actions
    st.subheader("Actions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Reset Daily State"):
            from app.agents.risk_policy import risk_policy
            risk_policy.reset_daily_state()
            st.success("Daily state reset!")
            time.sleep(1)
            st.rerun()
    
    with col2:
        if st.button("🚨 Trigger SAFE_MODE"):
            from app.agents.risk_policy import risk_policy
            risk_policy.trigger_safe_mode("Manual trigger from dashboard")
            st.warning("SAFE_MODE activated!")
            time.sleep(1)
            st.rerun()
    
    with col3:
        if st.button("📊 Flatten All Positions"):
            from app.agents.execution_paper import execution_paper
            execution_paper.flatten_all_positions("Manual flatten from dashboard")
            st.info("All positions flattened")
            time.sleep(1)
            st.rerun()


if __name__ == "__main__":
    main()
