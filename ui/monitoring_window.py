"""
Lightweight monitoring window for live trading activity.
Shows real-time status, trade count, and next trade prediction.
Runs as a separate Streamlit app that can be opened in a small window.

Usage:
    streamlit run ui/monitoring_window.py --logger.level=error
"""
import streamlit as st
import sys
import os
from datetime import datetime
import time

# Path setup to include 'app' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.storage import storage
from app.core.config import settings

# --- Page Config ---
st.set_page_config(
    page_title="Trading Monitor",
    layout="wide",
    initial_sidebar_state="collapsed",
    page_icon="📊",
)

# --- Custom Styling for Monitoring Window ---
st.markdown("""
    <style>
    /* Compact layout */
    body { margin: 0; padding: 0; }
    .stContainer { max-width: 100%; }
    
    /* Large readable font for monitoring */
    .monitor-status {
        font-size: 24px;
        font-weight: bold;
        text-align: center;
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 15px;
    }
    
    .monitor-live {
        background-color: #00ff00;
        color: #000;
    }
    
    .monitor-paper {
        background-color: #4da6ff;
        color: #fff;
    }
    
    .monitor-safe {
        background-color: #ff6666;
        color: #fff;
    }
    
    .monitor-metric {
        font-size: 18px;
        margin: 10px 0;
        padding: 10px;
        background-color: #f0f0f0;
        border-radius: 5px;
    }
    
    .metric-label {
        font-weight: bold;
        color: #333;
    }
    
    .metric-value {
        font-size: 20px;
        color: #0066cc;
    }
    
    .metric-green { color: #00cc00; }
    .metric-red { color: #ff3333; }
    
    /* Spinning indicator */
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    .spinner {
        display: inline-block;
        width: 20px;
        height: 20px;
        border: 3px solid #f3f3f3;
        border-top: 3px solid #0066cc;
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin-right: 10px;
    }
    
    .next-trade-box {
        background-color: #fff9e6;
        padding: 15px;
        border-left: 4px solid #ff9900;
        border-radius: 5px;
        margin-top: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# --- Auto-refresh ---
if 'refresh_counter' not in st.session_state:
    st.session_state.refresh_counter = 0

# Refresh every 5 seconds
placeholder = st.empty()
with placeholder.container():
    # Get monitoring data
    monitoring_status = storage.get_monitoring_status()
    next_trade_prediction = storage.get_next_trade_prediction()
    trades_today = storage.get_completed_trades_today()
    
    # --- Main Status ---
    mode = monitoring_status['mode']
    safe_mode = monitoring_status['safe_mode_active']
    
    # Select status color and class
    if safe_mode:
        status_class = "monitor-safe"
        status_text = "🛑 SAFE MODE - NO TRADING"
    elif mode == "LIVE":
        status_class = "monitor-live"
        status_text = "✓ LIVE TRADING ACTIVE"
    else:
        status_class = "monitor-paper"
        status_text = "📄 PAPER TRADING"
    
    st.markdown(f'<div class="monitor-status {status_class}">{status_text}</div>', unsafe_allow_html=True)
    
    # --- Key Metrics ---
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
            <div class="monitor-metric">
                <span class="metric-label">Trades Today</span><br>
                <span class="metric-value">{trades_today} / {monitoring_status['max_trades']}</span>
            </div>
        """, unsafe_allow_html=True)
    
    with col2:
        pnl = monitoring_status['current_pnl']
        pnl_class = "metric-green" if pnl >= 0 else "metric-red"
        pnl_sign = "+" if pnl >= 0 else ""
        st.markdown(f"""
            <div class="monitor-metric">
                <span class="metric-label">Daily P&L</span><br>
                <span class="metric-value {pnl_class}">₹ {pnl_sign}{pnl:.2f}</span>
            </div>
        """, unsafe_allow_html=True)
    
    with col3:
        capital = monitoring_status['loss_budget_remaining']
        capital_pct = (capital / monitoring_status['capital']) * 100 if monitoring_status['capital'] > 0 else 0
        st.markdown(f"""
            <div class="monitor-metric">
                <span class="metric-label">Loss Budget</span><br>
                <span class="metric-value">₹ {capital:.2f}</span><br>
                <small>({capital_pct:.0f}% remaining)</small>
            </div>
        """, unsafe_allow_html=True)
    
    # --- Next Trade Prediction ---
    if not safe_mode:
        next_status = next_trade_prediction['status']
        
        if next_status == "WAITING":
            reason = next_trade_prediction['reason']
            confidence = next_trade_prediction['confidence_pct']
            est_time = next_trade_prediction['estimated_time']
            
            if est_time:
                time_obj = datetime.fromtimestamp(est_time)
                time_str = time_obj.strftime("%H:%M:%S")
                time_from_now = int(est_time - time.time())
                min_sec = f"{time_from_now // 60}m {time_from_now % 60}s"
            else:
                time_str = "N/A"
                min_sec = "N/A"
            
            st.markdown(f"""
                <div class="next-trade-box">
                    <div style="display: flex; align-items: center;">
                        <div class="spinner"></div>
                        <span style="font-size: 16px; font-weight: bold;">Code is monitoring...</span>
                    </div>
                    <div style="margin-top: 10px; font-size: 14px;">
                        <b>Next Trade Predicted:</b> {time_str} ({min_sec} from now)<br>
                        <b>Confidence:</b> {confidence}%<br>
                        <b>Reason:</b> {reason}
                    </div>
                </div>
            """, unsafe_allow_html=True)
        
        elif next_status == "DONE":
            reason = next_trade_prediction['reason']
            st.markdown(f"""
                <div class="next-trade-box" style="background-color: #e6f2ff; border-left-color: #0066cc;">
                    <div style="font-size: 16px; font-weight: bold;">✓ Trading Complete for Today</div>
                    <div style="margin-top: 10px; font-size: 14px;">
                        {reason}
                    </div>
                </div>
            """, unsafe_allow_html=True)
        
        else:
            reason = next_trade_prediction['reason']
            st.markdown(f"""
                <div class="next-trade-box" style="background-color: #fff0e6; border-left-color: #ff6600;">
                    <div style="font-size: 16px; font-weight: bold;">⏳ Waiting to Resume</div>
                    <div style="margin-top: 10px; font-size: 14px;">
                        {reason}
                    </div>
                </div>
            """, unsafe_allow_html=True)
    
    else:
        st.markdown("""
            <div class="next-trade-box" style="background-color: #ffe6e6; border-left-color: #ff3333;">
                <div style="font-size: 16px; font-weight: bold;">🛑 No trading in SAFE MODE</div>
                <div style="margin-top: 10px; font-size: 14px;">
                    Market halted due to risk limits reached. Manual reset required.
                </div>
            </div>
        """, unsafe_allow_html=True)
    
    # --- Current Capital ---
    st.markdown("---")
    
    current_capital = monitoring_status['capital'] + monitoring_status['current_pnl']
    capital_change = monitoring_status['current_pnl']
    capital_change_pct = (capital_change / monitoring_status['capital']) * 100 if monitoring_status['capital'] > 0 else 0
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("Starting Capital", f"₹ {monitoring_status['capital']:.2f}")
    
    with col2:
        change_color = "🟢" if capital_change >= 0 else "🔴"
        st.metric("Current Capital", f"₹ {current_capital:.2f}", delta=f"{change_color} {capital_change_pct:+.1f}%")

# --- Footer ---
st.markdown("---")
st.markdown(f"""
<div style="text-align: center; font-size: 12px; color: #666;">
    <b>{mode} Mode</b> | Last Updated: {datetime.now().strftime('%H:%M:%S')} | Auto-refresh: 5s
</div>
""", unsafe_allow_html=True)

# Trigger refresh after 5 seconds
time.sleep(5)
st.rerun()
