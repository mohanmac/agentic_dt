"""
Zerodha Intraday Bot — real-money, phase-aware auto loop.

Once you click **Enable bot**, the background TradingEngine takes over:
  • Pre-market (<9:15) — idle
  • 9:15–9:30        — auto-arms, warm-up, no trades
  • 9:30–10:15       — observation only (noisy open)
  • 10:15–14:45      — scans every 5s; trades if Auto-execute is ON
  • 14:45–15:30      — no new entries; broker MIS auto-squares-off

Enabling the bot turns Auto-execute ON automatically (real orders during the
active phase). Untick "Auto-execute orders" in the sidebar to fall back to
scan-only mode, where the UI shows candidates for manual placement.

The dashboard auto-refreshes every 15s and auto-logs-off at 15:40 IST (after
broker MIS square-off) on trading days.
"""
from __future__ import annotations

import sys
import logging
import traceback
from datetime import datetime
from pathlib import Path

# Trust the OS keychain so corporate MITM TLS works. Must run before any HTTPS.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))

st.set_page_config(
    page_title="Zerodha Intraday Bot",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Paint immediately so Streamlit Cloud never shows a blank page while imports/init run.
st.title("Zerodha Intraday Bot")
_boot_status = st.empty()
_boot_status.info("Loading dashboard…")

log = logging.getLogger("app")

try:
    from app.core.config import settings
    from app.core.zerodha_auth import zerodha_auth
    from app.core.env_bootstrap import is_streamlit_cloud, CLOUD_APP_URL
    from app.core.market_calendar import (
        can_place_nse_bse_equity_trade,
        is_nse_bse_trading_day,
        market_status_line,
        ist_now,
        IST,
    )
except Exception as e:
    _boot_status.error(f"Import failed: {e}")
    st.code(traceback.format_exc())
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
ss = st.session_state
ss.setdefault("authed", False)
ss.setdefault("profile", None)
ss.setdefault("strategy_enabled", {
    "Opening Range Breakout": True,
    "VWAP Pullback": True,
    "Momentum": True,
})


# ─────────────────────────────────────────────────────────────────────────────
# Auth bootstrap
# ─────────────────────────────────────────────────────────────────────────────
def bootstrap_auth() -> None:
    """Handle OAuth redirect query params only (fast — no blocking Kite API calls)."""
    if ss.authed:
        return
    qp = st.query_params
    if "auth_error" in qp:
        err = qp.get("auth_error")
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.sidebar.error(f"Login failed: {err}")
        return
    if "request_token" in qp:
        token = str(qp.get("request_token") or "")
        if ss.get("_oauth_token_done") == token:
            try:
                st.query_params.clear()
            except Exception:
                pass
            return
        ss._oauth_token_done = token
        try:
            zerodha_auth.exchange_request_token(token)
            log.info("kite_oauth_exchange_success")
            ok, profile = zerodha_auth.validate_token()
            if ok and profile:
                ss.authed = True
                ss.profile = {
                    "user_id": profile.get("user_id"),
                    "user_name": profile.get("user_name"),
                    "email": profile.get("email"),
                }
        except Exception as exc:
            log.exception("kite_oauth_exchange_failed")
            st.sidebar.error(f"Kite login failed: {exc}")
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.rerun()
    if "auth" in qp:
        try:
            st.query_params.clear()
        except Exception:
            pass


def try_restore_session() -> None:
    """Validate saved token once per session (can be slow — not at module import)."""
    if ss.authed or ss.get("_auth_restore_attempted"):
        return
    ss._auth_restore_attempted = True
    try:
        zerodha_auth._load_token()
        if not zerodha_auth.kite.access_token:
            return
        ok, profile = zerodha_auth.validate_token()
        if ok and profile:
            ss.authed = True
            ss.profile = {
                "user_id": profile.get("user_id"),
                "user_name": profile.get("user_name"),
                "email": profile.get("email"),
            }
    except Exception as e:
        log.exception("try_restore_session failed")
        st.sidebar.warning(f"Auth check failed: {e}")


@st.cache_resource
def get_engine():
    """Singleton engine — created on first use, not at import."""
    from app.core.trading_engine import TradingEngine
    return TradingEngine()


@st.cache_resource
def get_orchestrator():
    """One Orchestrator across Streamlit reruns — threads aren't recreated each tick."""
    from app.agents.orchestrator import Orchestrator
    return Orchestrator()


@st.cache_resource
def _intraday_rules():
    from app.core.intraday_agent import (
        MIN_TARGET_PCT,
        MAX_STOP_LOSS_PCT,
        MAX_TRADES_PER_DAY,
        session_capital,
        scan_intraday_universe,
    )
    return MIN_TARGET_PCT, MAX_STOP_LOSS_PCT, MAX_TRADES_PER_DAY, session_capital, scan_intraday_universe


ss.setdefault("agents_running", False)


def get_orch():
    """Lazy init — avoids Cloud deploy rollback when orchestrator fails at import time."""
    try:
        return get_orchestrator()
    except Exception as e:
        st.error(f"Orchestrator() failed: {e}")
        st.code(traceback.format_exc())
        st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
PULSE_CSS = """
<style>
@keyframes pulseDot {
  0%   { opacity: 1; transform: scale(1); }
  50%  { opacity: 0.35; transform: scale(1.4); }
  100% { opacity: 1; transform: scale(1); }
}
.pulse-dot {
  display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; background: #16a34a; margin-right: 6px;
  vertical-align: middle; animation: pulseDot 1.1s ease-in-out infinite;
}
.idle-dot {
  display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; background: #6b7280; margin-right: 6px;
  vertical-align: middle; opacity: 0.45;
}
.warn-dot {
  display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; background: #f59e0b; margin-right: 6px;
  vertical-align: middle;
}
.agent-line { font-family: ui-monospace, Menlo, monospace; font-size: 0.78rem; line-height: 1.5; }
</style>
"""


def sidebar_llm_meter() -> None:
    """LLM tokens + tokens-per-trade — always visible at the top of the sidebar."""
    try:
        from app.core.llm import llm_client
        total_tokens = int(getattr(llm_client, "total_tokens_used", 0) or 0)
    except Exception:
        total_tokens = 0
    try:
        trades_today = int(get_engine().risk_engine.daily_stats.total_trades or 0)
    except Exception:
        trades_today = 0
    per_trade = (total_tokens / trades_today) if trades_today else None

    c1, c2 = st.sidebar.columns(2)
    c1.metric("LLM tokens", f"{total_tokens:,}")
    c2.metric("Per trade", f"{per_trade:,.0f}" if per_trade is not None else "—",
              help="Total LLM tokens consumed today ÷ trades placed today.")
    st.sidebar.caption("LLM used only by **agent09_sentiment** — every other agent is pure Python.")


def sidebar() -> None:
    st.sidebar.markdown(PULSE_CSS, unsafe_allow_html=True)
    st.sidebar.title("Zerodha Intraday Bot")
    if is_streamlit_cloud():
        st.sidebar.success("Streamlit Cloud")
        if "127.0.0.1" in settings.KITE_REDIRECT_URL or "localhost" in settings.KITE_REDIRECT_URL:
            st.sidebar.error("Fix Secrets: KITE_REDIRECT_URL must be your .streamlit.app URL")
        else:
            st.sidebar.caption(f"OAuth: {settings.KITE_REDIRECT_URL}")
    sidebar_llm_meter()
    st.sidebar.divider()
    min_tgt, _, max_trades, _, _ = _intraday_rules()
    st.sidebar.caption(
        f"Capital ₹{settings.DAILY_CAPITAL:,.0f}  ·  SL <10%  ·  Target ≥{min_tgt:g}%  "
        f"·  Max {max_trades}/day"
    )

    api_ok = (
        settings.KITE_API_KEY and settings.KITE_API_KEY.strip() != "your_api_key_here"
        and settings.KITE_API_SECRET and settings.KITE_API_SECRET.strip() != "your_api_secret_here"
    )
    if not api_ok:
        st.sidebar.error("KITE_API_KEY / KITE_API_SECRET missing in .env")
        return

    if ss.authed and ss.profile:
        st.sidebar.success(f"Logged in: {ss.profile.get('user_name') or ss.profile.get('user_id')}")
        if ss.profile.get("email"):
            st.sidebar.caption(ss.profile["email"])
        if st.sidebar.button("Logout", use_container_width=True, key="logout_btn"):
            try:
                zerodha_auth.logout()
            except Exception:
                pass
            get_engine().disable()
            ss.authed = False
            ss.profile = None
            st.rerun()
        st.sidebar.divider()
        sidebar_funds()
        st.sidebar.divider()
        sidebar_engine_controls()
        st.sidebar.divider()
        sidebar_agents()
        st.sidebar.divider()
        sidebar_strategies()
        return

    # Not logged in
    st.sidebar.subheader("Login")
    st.sidebar.text_input("User ID", placeholder="e.g. RVQ434", key="login_user_id", autocomplete="off")
    st.sidebar.text_input(
        "Password (entered on Kite's page)",
        placeholder="will be filled on Kite",
        key="login_password",
        autocomplete="off",
    )
    st.sidebar.caption(
        "Click **Login to Kite** — Zerodha verifies credentials on their own site, "
        "then redirects back. Your password is never sent through this app."
    )
    login_url = zerodha_auth.generate_login_url()
    st.sidebar.link_button("Login to Kite", login_url, use_container_width=True, type="primary")

    # Manual fallback: if Kite's redirect URL points somewhere this app can't
    # receive (e.g. a dead localhost callback), paste the request_token here.
    with st.sidebar.expander("Trouble logging in? Paste token manually"):
        st.caption(
            "After **Login to Kite**, copy the `request_token=…` value from the "
            "page Kite redirects you to (you can paste the whole URL too), then "
            "authenticate here. Tokens expire in ~2 minutes — be quick."
        )
        raw = st.text_input(
            "request_token (or full redirect URL)",
            key="manual_request_token",
            autocomplete="off",
            placeholder="e.g. 1cYvT5nkL88piDYZdO8xaF2NBcx3TngB",
        )
        if st.button("Authenticate", use_container_width=True, key="manual_auth_btn"):
            from urllib.parse import urlparse, parse_qs

            token = (raw or "").strip()
            if "request_token=" in token:  # user pasted the whole redirect URL
                qs = parse_qs(urlparse(token).query)
                token = (qs.get("request_token") or [""])[0]
            if not token:
                st.error("Paste a request_token (or the full redirect URL) first.")
            else:
                try:
                    zerodha_auth.exchange_request_token(token)
                    ok, profile = zerodha_auth.validate_token()
                    if ok and profile:
                        ss.authed = True
                        ss.profile = {
                            "user_id": profile.get("user_id"),
                            "user_name": profile.get("user_name"),
                            "email": profile.get("email"),
                        }
                        log.info("kite_manual_token_exchange_success")
                        st.rerun()
                    else:
                        st.error("Token accepted but profile validation failed. Try a fresh token.")
                except Exception as exc:
                    log.exception("kite_manual_token_exchange_failed")
                    st.error(f"Login failed: {exc}. Generate a fresh token and retry quickly.")


def sidebar_funds() -> None:
    """Live funds & margins from Zerodha (equity segment)."""
    st.sidebar.subheader("Zerodha funds (equity)")
    try:
        kite = zerodha_auth.get_kite_instance()
        m = kite.margins(segment="equity") or {}
        avail = (m.get("available") or {})
        used = (m.get("utilised") or {})

        cash = float(avail.get("live_balance") or avail.get("cash") or 0.0)
        net = float(m.get("net") or 0.0)
        margin_used = float(used.get("debits") or 0.0)
        m2m = float(used.get("m2m_unrealised") or 0.0) + float(used.get("m2m_realised") or 0.0)

        c1, c2 = st.sidebar.columns(2)
        c1.metric("Available", f"₹{cash:,.0f}")
        c2.metric("Net", f"₹{net:,.0f}")
        c1.metric("Used", f"₹{margin_used:,.0f}")
        c2.metric("M2M", f"₹{m2m:+,.0f}")
        if st.sidebar.button("↻ Refresh funds", use_container_width=True, key="refresh_funds_btn"):
            st.rerun()
    except Exception as e:
        st.sidebar.warning(f"Funds unavailable: {e}")


def sidebar_engine_controls() -> None:
    st.sidebar.subheader("Bot controls")
    snap = get_engine().snapshot()

    try:
        if snap.enabled:
            if st.sidebar.button("⏸ Disable bot", use_container_width=True, key="disable_bot_btn"):
                log.info("UI: Disable bot clicked")
                get_engine().disable()
                get_engine().set_auto_execute(False)
                ss["auto_exec_checkbox"] = False
                if ss.agents_running:
                    get_orch().set_auto_execute(False)
                    get_orch().shutdown()
                    ss.agents_running = False
        else:
            if st.sidebar.button(
                "▶️ Enable bot", type="primary", use_container_width=True, key="enable_bot_btn"
            ):
                log.info("UI: Enable bot clicked")
                get_engine().enable()
                if not ss.agents_running:
                    get_orch().start_all()
                    ss.agents_running = True
                # User mandate: enabling the bot also arms auto-execution so it
                # places trades on its own during the active phase. start_all()
                # resets the bus flag, so set both AFTER it.
                get_engine().set_auto_execute(True)
                get_orch().set_auto_execute(True)
                ss["auto_exec_checkbox"] = True
    except Exception as e:
        log.exception("Bot toggle failed")
        st.sidebar.error(f"Toggle failed: {e}")

    # Auto-execute toggle. The engine is the source of truth; we mirror it into
    # the widget's own session_state key (no `value=`) so a programmatic flip —
    # e.g. auto-ON when the bot is enabled — and a user click never fight and
    # silently revert each other across reruns.
    try:
        ss.setdefault("auto_exec_checkbox", snap.auto_execute)
        new_auto = st.sidebar.checkbox(
            "Auto-execute orders",
            key="auto_exec_checkbox",
            help="When ON, the engine places top candidates automatically during the active phase. "
                 "When OFF, you place each trade manually from Signals.",
        )
        if new_auto != snap.auto_execute:
            get_engine().set_auto_execute(new_auto)
            get_orch().set_auto_execute(new_auto)
        if new_auto:
            st.sidebar.warning("⚠️ Auto-execute is ON — engine will place real orders.")
        else:
            st.sidebar.caption("Auto-execute OFF — engine scans only; you place manually.")
    except Exception as e:
        log.exception("Auto-execute toggle failed")
        st.sidebar.error(f"Auto-exec toggle failed: {e}")


AGENT_NAMES = [
    "agent01_data", "agent02_feature", "agent03_trend", "agent04_breakout",
    "agent05_pullback", "agent06_decision", "agent07_risk", "agent08_execution",
    "agent09_sentiment", "agent10_ml_prediction", "agent11_monitoring", "agent12_portfolio",
]


def _agents_fragment() -> None:
    """Renders the 12-agent panel. Refreshes with the page every 15s (see
    auto_refresh()); a per-fragment run_every broke first-render on Streamlit Cloud."""
    st.subheader("Agent system (12)")
    if not ss.agents_running:
        st.caption("Idle — Enable bot to start the 12-agent loop.")
        return
    health = get_orch().bus.get("health") or {}
    ok = sum(1 for v in health.values() if v.get("status") == "OK")
    st.caption(f"{ok}/{len(AGENT_NAMES)} OK · refreshes every 15s")

    for name in AGENT_NAMES:
        last = get_orch().bus.get(f"last_result:{name}")
        recent = bool(last and (datetime.now() - last.ts).total_seconds() <= 2.0)
        info = health.get(name) or {}
        status = info.get("status")
        if recent:
            dot = '<span class="pulse-dot"></span>'
        elif status == "OK":
            dot = '<span class="pulse-dot" style="animation: none; opacity: 0.7;"></span>'
        elif status == "DEGRADED":
            dot = '<span class="warn-dot"></span>'
        else:
            dot = '<span class="idle-dot"></span>'
        stale = info.get("stale_s")
        suffix = f"<span style='color:#888'> · {stale:.1f}s</span>" if isinstance(stale, (int, float)) else ""
        if is_streamlit_cloud():
            card_link = "<span style='color:#888'>card (local API)</span>"
        else:
            card_link = f"<a href='http://127.0.0.1:8000/agents/{name}/card.json' target='_blank' style='color:#3b82f6; text-decoration:none;'>card</a>"
        st.markdown(
            f"<div class='agent-line'>{dot}{name}{suffix} · {card_link}</div>",
            unsafe_allow_html=True,
        )

    # Risk alerts from agent07
    alerts = get_orch().bus.get("risk_alerts") or []
    if alerts:
        st.markdown("---")
        st.markdown("**⚠️ Risk alerts (agent07)**")
        for a in alerts[:6]:
            sev = a.get("severity", "?")
            colour = "#ef4444" if sev == "high" else "#f59e0b"
            st.markdown(
                f"<div class='agent-line' style='color:{colour}'>"
                f"• {a.get('symbol', '—')}: {a.get('reason', '')}</div>",
                unsafe_allow_html=True,
            )


def sidebar_agents() -> None:
    with st.sidebar:
        _agents_fragment()


def sidebar_strategies() -> None:
    st.sidebar.subheader("Strategies")
    for name in list(ss.strategy_enabled.keys()):
        ss.strategy_enabled[name] = st.sidebar.checkbox(
            name, value=ss.strategy_enabled[name], key=f"strat_{name}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Top status strip
# ─────────────────────────────────────────────────────────────────────────────
def minutes_to_square_off() -> int | None:
    now = ist_now()
    if not is_nse_bse_trading_day(now.date()):
        return None
    from datetime import datetime as _dt, time as _t
    eod = _dt.combine(now.date(), _t(15, 0), tzinfo=IST)
    delta = eod - now
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds() // 60)


def top_status_strip(capital: float, snap) -> None:
    mkt_ok, mkt_msg = can_place_nse_bse_equity_trade()
    re = get_engine().risk_engine

    c = st.columns([1.4, 1.4, 1.0, 1.0, 1.0, 1.2, 1.0])

    # Bot + phase
    if snap.enabled:
        if snap.armed:
            c[0].markdown("🟢 **BOT ENABLED · ARMED**")
        else:
            c[0].markdown("🟡 **BOT ENABLED · IDLE**")
    else:
        c[0].markdown("⚪ **BOT DISABLED**")
    c[0].caption(snap.phase_label or "—")

    # Market + last tick
    if mkt_ok:
        c[1].markdown("🟢 **MARKET OPEN**")
    elif is_nse_bse_trading_day():
        c[1].markdown("🟠 **OFF-HOURS**")
    else:
        c[1].markdown("🔴 **HOLIDAY/WKND**")
    c[1].caption(f"Last tick: {snap.last_tick or '—'}")

    # Equity + PnL
    c[2].metric("Equity", f"₹{capital:,.0f}", delta=f"₹{re.daily_stats.total_pnl:+,.0f}")

    # Trade slots
    used = re.daily_stats.total_trades
    cap_trades = re.config.max_trades_per_day
    c[3].metric("Trades", f"{used}/{cap_trades}")
    c[3].progress(min(1.0, used / cap_trades if cap_trades else 0), text=" ")

    # Risk used
    loss_used = max(0.0, -re.daily_stats.total_pnl)
    loss_cap = re.config.max_loss_per_day
    pct = min(1.0, loss_used / loss_cap if loss_cap else 0)
    c[4].metric("Risk used", f"{pct * 100:.0f}%")
    c[4].progress(pct, text=" ")

    # Square-off countdown
    mins = minutes_to_square_off()
    if mins is None:
        c[5].metric("Square-off", "—")
    elif mins == 0:
        c[5].metric("Square-off", "NOW")
    else:
        c[5].metric("Square-off in", f"{mins} min")

    # KILL ALL
    if c[6].button(
        "🔥 KILL ALL",
        key="kill_all_btn",
        use_container_width=True,
        help="Emergency: disable bot + cancel all open Kite orders",
    ):
        with st.spinner("Cancelling all open orders…"):
            result = get_engine().kill_all()
        st.toast(
            f"KILL ALL — cancelled {result['cancelled']}, failures {len(result['failures'])}",
            icon="🔥",
        )
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Pre-trade validation
# ─────────────────────────────────────────────────────────────────────────────
def validate_trade(entry: float, sl: float, target: float, qty: int, capital: float, strategy: str):
    if not ss.strategy_enabled.get(strategy, False):
        return False, f"Strategy '{strategy}' disabled in sidebar."
    if qty <= 0:
        return False, "Quantity must be > 0."
    if min(entry, sl, target) <= 0:
        return False, "Entry / SL / target must be positive."
    sl_pct = (entry - sl) / entry * 100
    tgt_pct = (target - entry) / entry * 100
    if sl_pct <= 0:
        return False, f"SL must be below entry (SL ₹{sl:.2f}, entry ₹{entry:.2f})."
    if sl_pct >= 10.0:
        return False, f"SL distance {sl_pct:.2f}% violates hard cap (<10%)."
    min_tgt, _, _, _, _ = _intraday_rules()
    if tgt_pct < min_tgt - 1e-6:
        return False, f"Target {tgt_pct:.2f}% below {min_tgt:.1f}% floor."
    re = get_engine().risk_engine
    pos_cap_inr = capital * (re.config.max_position_size_percent / 100.0)
    notional = entry * qty
    if notional > pos_cap_inr:
        return False, (
            f"Position ₹{notional:,.0f} > cap ₹{pos_cap_inr:,.0f} "
            f"({re.config.max_position_size_percent:.0f}% of capital)."
        )
    ok_mkt, msg_mkt = can_place_nse_bse_equity_trade()
    if not ok_mkt:
        return False, msg_mkt
    ok_risk, msg_risk = re.can_place_trade(notional, assumed_sl_pct=sl_pct / 100.0)
    if not ok_risk:
        return False, msg_risk
    return True, "OK"


# ─────────────────────────────────────────────────────────────────────────────
# Strategy cards
# ─────────────────────────────────────────────────────────────────────────────
def strategy_cards(snap) -> None:
    st.subheader("Strategies")
    counts = {k: 0 for k in ss.strategy_enabled.keys()}
    for d in snap.candidates or []:
        if d.strategy in counts:
            counts[d.strategy] += 1
    descriptions = {
        "Opening Range Breakout": "Breakout above first-15m high with volume + NIFTY bias",
        "VWAP Pullback": "Holding/discounting VWAP with bullish candle + volume",
        "Momentum": "RSI > 60, price > 20MA, volume > 2× avg, RS vs NIFTY",
    }
    cols = st.columns(3)
    for i, name in enumerate(["Opening Range Breakout", "VWAP Pullback", "Momentum"]):
        with cols[i].container(border=True):
            enabled = ss.strategy_enabled.get(name, False)
            badge = "🟢 ON" if enabled else "⚪ OFF"
            st.markdown(f"**{name}** &nbsp;&nbsp;{badge}")
            st.caption(descriptions[name])
            st.metric("Signals (latest scan)", counts[name])


# ─────────────────────────────────────────────────────────────────────────────
# Panels
# ─────────────────────────────────────────────────────────────────────────────
def safe(name: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log.exception(f"section '{name}' failed")
        st.error(f"Section **{name}** failed: {e}")
        with st.expander("stack trace", expanded=False):
            st.code(traceback.format_exc())
        return None


def positions_panel() -> None:
    st.subheader("Open positions (live)")
    try:
        from app.core.live_broker import LiveBroker
        b = LiveBroker()
        portfolio = b.get_portfolio()
    except Exception as e:
        st.warning(f"Could not fetch positions: {e}")
        return
    if not portfolio:
        st.caption("No open positions.")
        return
    rows = [
        {
            "Symbol": getattr(p, "symbol", ""),
            "Qty": getattr(p, "quantity", 0),
            "Avg": round(getattr(p, "avg_price", 0.0), 2),
            "LTP": round(getattr(p, "ltp", 0.0), 2),
            "Unrealized PnL": round(
                (getattr(p, "ltp", 0.0) - getattr(p, "avg_price", 0.0))
                * getattr(p, "quantity", 0),
                2,
            ),
        }
        for p in portfolio
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def order_book_panel() -> None:
    st.subheader("Order book (live)")
    try:
        from app.core.live_broker import LiveBroker
        b = LiveBroker()
        orders = b.orders
    except Exception as e:
        st.warning(f"Could not fetch order book: {e}")
        return
    if not orders:
        st.caption("No orders today.")
        return
    rows = [
        {
            "Order ID": o.order_id,
            "Symbol": o.symbol,
            "Side": o.transaction_type,
            "Qty": o.quantity,
            "Price": o.price,
            "Status": o.status,
            "Time": str(o.timestamp),
        }
        for o in orders
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def signals_panel(capital: float, snap) -> None:
    from app.core.trading_engine import PHASE_ACTIVE
    min_tgt, _, _, _, _ = _intraday_rules()
    st.subheader("Signals (engine candidates)")
    re = get_engine().risk_engine
    slots = max(0, re.config.max_trades_per_day - re.daily_stats.total_trades)
    st.caption(
        f"Slots left: **{slots}/{re.config.max_trades_per_day}** · "
        f"SL cap <10% · Target floor ≥{min_tgt:g}% · "
        + (f"Last scan **{snap.last_scan_at}** IST" if snap.last_scan_at else "No scan yet")
    )
    candidates = snap.candidates or []
    if not candidates:
        if not snap.enabled:
            st.info("Bot is disabled. Press **Enable bot** in the sidebar to start the auto loop.")
        elif snap.phase == PHASE_ACTIVE:
            st.info("Active phase — no candidates passed the last scan. Engine will retry on the next tick.")
        else:
            st.info(f"Phase: {snap.phase_label}. Engine scans candidates only during the active phase (10:15–14:45 IST).")
        return

    visible = [d for d in candidates if ss.strategy_enabled.get(d.strategy, False)][:5]
    if not visible:
        st.caption("Engine has candidates, but all matching strategies are disabled in the sidebar.")
        return

    for d in visible:
        with st.container(border=True):
            top = st.columns([2, 1, 1, 1, 1, 1])
            top[0].markdown(f"**{d.stock}** · {d.strategy}")
            top[1].metric("Entry", f"₹{d.entry_price:.2f}")
            top[2].metric(
                "SL", f"₹{d.stop_loss:.2f}",
                delta=f"-{d.risk_pct:.2f}%",
                delta_color="inverse",
            )
            tgt_pct = (d.target / d.entry_price - 1) * 100
            top[3].metric("Target", f"₹{d.target:.2f}", delta=f"+{tgt_pct:.2f}%")
            top[4].metric("Qty", d.quantity)
            top[5].metric("Confidence", f"{d.confidence:.0f}")

            with st.expander("Plan & checks"):
                st.markdown(d.planning or "_no plan_")
                for pt in d.hitl_points:
                    st.markdown(f"- {pt}")

            ok_v, msg_v = validate_trade(
                d.entry_price, d.stop_loss, d.target, d.quantity, capital, d.strategy
            )
            ac = st.columns([2, 1, 1])
            ac[0].caption(("✅ " if ok_v else "⛔ ") + msg_v)
            confirmed = ac[1].checkbox("I checked it", key=f"chk_{d.stock}")
            disabled = (not snap.enabled) or (not ok_v) or (not confirmed)
            help_text = "Enable bot first" if not snap.enabled else None
            if ac[2].button(
                "Place bracket",
                key=f"buy_{d.stock}",
                type="primary",
                disabled=disabled,
                use_container_width=True,
                help=help_text,
            ):
                place_bracket_manually(d)


def place_bracket_manually(d) -> None:
    ok, msg = can_place_nse_bse_equity_trade()
    if not ok:
        st.error(f"Market gate: {msg}")
        return
    try:
        from app.core.live_broker import LiveBroker
        b = LiveBroker()
        order = b.place_bracket_buy(
            symbol=d.stock,
            quantity=int(d.quantity),
            limit_price=float(d.entry_price),
            stop_loss_price=float(d.stop_loss),
            target_price=float(d.target),
        )
        get_engine().risk_engine.daily_stats.total_trades += 1
        oid = getattr(order, "order_id", order)
        st.success(f"✅ Live order sent: {oid}")
    except Exception as e:
        st.error(f"Order failed: {e}")


def activity_feed(snap) -> None:
    st.subheader("Activity (engine)")
    if not snap.activity:
        st.caption("No events yet.")
        return
    icons = {"info": "·", "warn": "⚠️", "error": "🛑"}
    for ev in reversed(snap.activity[-15:]):
        st.markdown(
            f"<span style='color:#888'>{ev['ts']}</span>  "
            f"{icons.get(ev['level'], '·')}  {ev['msg']}",
            unsafe_allow_html=True,
        )


def guardrails_panel() -> None:
    min_tgt, max_sl, _, _, _ = _intraday_rules()
    re = get_engine().risk_engine
    c = re.config
    st.markdown(
        f"""
**Daily flow (auto-managed by the engine)**
- `< 9:15` Pre-market — idle
- `9:15–9:30` Setup — auto-armed, no trades
- `9:30–10:15` Noisy open — observation only
- `10:15–14:45` Active — scans every 5s; auto-executes if toggle is ON
- `14:45–15:30` Closing — no new entries; broker MIS squares off

**Hard rules (every order)**
- SL distance **< 10%** (engine caps at {max_sl:g}%)
- Target **≥ {min_tgt:g}%**
- Position size **≤ {c.max_position_size_percent:.0f}%** of capital
- Max open positions: **{c.max_open_positions}**
- Max trades/day: **{c.max_trades_per_day}**
- Max daily loss: **₹{c.max_loss_per_day:.0f}** (auto-halt)
- Halt on consecutive losses: **{c.max_consecutive_losses}**
- Min capital threshold: **₹{c.min_capital_threshold:.0f}**

**Kill switches**
- **Disable bot** — armed/auto-execute off; open positions untouched
- **🔥 KILL ALL** — disarms + cancels every open Kite order in one click
        """
    )


def dashboard() -> None:
    snap = get_engine().snapshot()
    _, _, _, session_capital, _ = _intraday_rules()
    cap = session_capital()
    safe("top_strip", top_status_strip, cap, snap)
    st.divider()
    safe("strategy_cards", strategy_cards, snap)
    st.divider()
    left, right = st.columns([3, 2])
    with left:
        tabs = st.tabs(["Signals", "Order book", "Guardrails"])
        with tabs[0]:
            safe("signals", signals_panel, cap, snap)
        with tabs[1]:
            safe("order_book", order_book_panel)
        with tabs[2]:
            safe("guardrails", guardrails_panel)
    with right:
        safe("positions", positions_panel)
        safe("activity", activity_feed, snap)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-refresh + auto-logoff
# ─────────────────────────────────────────────────────────────────────────────
def auto_refresh(interval_ms: int = 15_000, key: str = "dash_autorefresh") -> None:
    """Re-run the script every interval_ms so the 12-agent status, candidates and
    countdowns stay live without a manual click.

    Uses streamlit-autorefresh — a websocket-driven rerun, NOT a full browser
    reload — so the Kite session/session_state survive and the KILL ALL button
    stays responsive. Degrades to a hint if the component isn't installed.
    """
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=interval_ms, key=key)
    except Exception:
        st.caption("⏳ Auto-refresh unavailable (install streamlit-autorefresh) — click any control to refresh.")


def auto_logoff_after_close() -> None:
    """At/after 15:40 IST on a trading day, stop the bot + agents and log off Kite.

    15:40 is the post-square-off boundary (REGULAR_END 15:30 → CLOSING_START 15:40),
    so MIS positions are already flat. Guarded to fire once per day, so a manual
    re-login afterwards (to review the order book) won't be kicked out again.
    """
    if not ss.authed:
        return
    from datetime import time as _t
    now = ist_now()
    if not is_nse_bse_trading_day(now.date()):
        return
    if now.time() < _t(15, 40):
        return
    if ss.get("_auto_logged_off_date") == now.date().isoformat():
        return
    ss._auto_logged_off_date = now.date().isoformat()
    try:
        get_engine().disable()
    except Exception:
        log.exception("auto_logoff: engine.disable failed")
    try:
        if ss.agents_running:
            get_orch().shutdown()
            ss.agents_running = False
    except Exception:
        log.exception("auto_logoff: orchestrator shutdown failed")
    try:
        zerodha_auth.logout()
    except Exception:
        log.exception("auto_logoff: kite logout failed")
    ss.authed = False
    ss.profile = None
    log.info("auto_logoff_after_close at %s IST", now.strftime("%H:%M:%S"))
    st.toast("Exchange closed (15:40 IST) — bot stopped and logged out.", icon="🔒")
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Render
# ─────────────────────────────────────────────────────────────────────────────
try:
    auto_refresh()
    bootstrap_auth()
    try_restore_session()
    auto_logoff_after_close()
    _boot_status.empty()
    st.caption(f"Real-money · {datetime.now().strftime('%H:%M:%S')}")
    sidebar()
    if ss.authed:
        dashboard()
    else:
        min_tgt, _, max_trades, _, _ = _intraday_rules()
        st.info(
            f"Log in via the **left pane**. Hard rules: SL <10%, Target ≥{min_tgt:g}%, "
            f"NSE/BSE 9:15–15:30 IST only, max {max_trades} trades/day."
        )
        redirect = settings.KITE_REDIRECT_URL.strip()
        st.caption(f"Kite redirect URL: `{redirect}`")
        if is_streamlit_cloud():
            st.markdown(
                f"**Cloud checklist:** Kite console redirect = `{CLOUD_APP_URL}` · "
                "Secrets must include `KITE_API_KEY`, `KITE_API_SECRET`, same redirect URL, "
                "`LLM_PROVIDER=openai`, and `OPENAI_API_KEY`. Then **Reboot app** after saving Secrets."
            )
            if redirect == CLOUD_APP_URL:
                st.success("Redirect URL is correct for Streamlit Cloud.")
            else:
                st.warning(
                    f"Redirect should be `{CLOUD_APP_URL}` (not localhost). "
                    "Update Streamlit Secrets and reboot."
                )
except Exception as e:
    _boot_status.empty()
    st.error(f"Render failed: {e}")
    st.code(traceback.format_exc())
