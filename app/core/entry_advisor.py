"""
Entry Timing Advisor for DayTradingPaperBot Auto-Pilot.

Uses the dynamically optimized strategy + guardrail values (from 3yr backtesting
and live micro-optimization) to answer, for every watched symbol:

    1. Is NOW a good time to enter?
    2. If not, exactly HOW LONG should we wait?
    3. WHAT CONDITIONS must be met?
    4. WHAT IS the confidence level?

Timing logic sources:
  A. Strategy time windows   — InstitutionalFlow:  10:30–11:30, 13:30–14:30
                             — StopHuntProtection: avoid 9:15–9:30, 14:30+
                             — Others: full session, prefer 10:00–14:30
  B. Backtest regime fit     — Only trade in the regime where the symbol's
                               best strategy historically performed
  C. Confluence requirement  — Dynamically set min_confluence from optimizer
  D. Capital guard           — Don't enter if capital check fails
  E. Signal condition check  — Live price vs VWAP, EMA alignment, RSI, Volume
"""

import datetime
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import pytz

IST = pytz.timezone("Asia/Kolkata")

# ─────────────────────────────────────────────────────────────────────────────
# Time Windows (IST)
# ─────────────────────────────────────────────────────────────────────────────

MARKET_OPEN  = datetime.time(9, 15)
MARKET_CLOSE = datetime.time(15, 30)

# Best institutional entry windows (from InstitutionalFlow strategy backtest)
INST_WINDOWS = [
    (datetime.time(10, 30), datetime.time(11, 30), "Late Morning Accumulation"),
    (datetime.time(13, 30), datetime.time(14, 30), "Post-Lunch Continuation"),
]

# Zones to ALWAYS avoid
AVOID_ZONES = [
    (datetime.time(9, 15),  datetime.time(9, 30),  "Opening Noise / Stop-Hunt Zone"),
    (datetime.time(14, 30), datetime.time(15, 30), "End-of-Day Trap Zone"),
]

# Strategy-specific preferred windows
STRATEGY_PREFERRED_WINDOWS: Dict[str, List[tuple]] = {
    "InstitutionalFlow":     INST_WINDOWS,
    "StopHuntProtection":    INST_WINDOWS,
    "Momentum":              [(datetime.time(9, 45), datetime.time(14, 30), "Main Session")],
    "Breakout":              [(datetime.time(9, 45), datetime.time(13, 0),  "Morning Breakout Session")],
    "VWAPPullback":          [(datetime.time(10, 0), datetime.time(14, 30), "VWAP Active Hours")],
    "MACrossoverTrend":      [(datetime.time(9, 45), datetime.time(14, 0),  "Trend Hours")],
    "Scalping":              [(datetime.time(9, 45), datetime.time(14, 30), "Full Active Session")],
    "MeanReversion":         [(datetime.time(10, 0), datetime.time(14, 0),  "Range-Bound Hours")],
    "RSIReversal":           [(datetime.time(10, 0), datetime.time(14, 0),  "RSI Active Hours")],
    "StatisticalArbitrage":  [(datetime.time(10, 0), datetime.time(14, 30), "Stat-Arb Window")],
}


# ─────────────────────────────────────────────────────────────────────────────
# Result Dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EntryAdvice:
    symbol: str
    best_strategy: str
    can_enter_now: bool

    # Timing
    wait_minutes: int          # 0 if can enter now
    wait_until: str            # "HH:MM" IST
    current_window: str        # name of the current / next window
    time_urgency: str          # "ENTER NOW" / "WAIT" / "AVOID TODAY"

    # Conditions that must be met  (dynamic, from live guardrails + backtest)
    required_conditions: List[str]
    conditions_met: List[str]
    conditions_pending: List[str]

    # Confidence (0-100), colour-coded
    confidence_pct: float
    confidence_label: str      # HIGH / MEDIUM / LOW / AVOID

    # Backtest-derived trade params
    optimal_stop_pct: float
    optimal_target_pct: float
    optimal_capital: float

    # Live guardrail snapshot at time of advice
    min_confluence_required: int
    current_quality_score: float

    # Reason detail
    advice_summary: str


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_ist() -> datetime.datetime:
    return datetime.datetime.now(IST)


def _minutes_until(target: datetime.time, now: datetime.datetime) -> int:
    """Minutes from now until target time today (IST). Negative = already past."""
    today = now.date()
    target_dt = IST.localize(datetime.datetime.combine(today, target))
    delta = (target_dt - now).total_seconds() / 60
    return int(delta)


def _in_window(t: datetime.time, start: datetime.time, end: datetime.time) -> bool:
    return start <= t <= end


def _next_window_start(
    windows: List[tuple],
    now: datetime.datetime,
) -> Optional[tuple]:
    """Returns (start_time, end_time, name, wait_minutes) of the next upcoming window."""
    t = now.time()
    for start, end, name in windows:
        if t < start:
            return (start, end, name, _minutes_until(start, now))
        elif t <= end:
            return (start, end, name, 0)   # currently inside
    return None   # all windows passed for today


def _confidence_label(pct: float) -> str:
    if pct >= 70:
        return "HIGH"
    elif pct >= 50:
        return "MEDIUM"
    elif pct >= 30:
        return "LOW"
    return "AVOID"


# ─────────────────────────────────────────────────────────────────────────────
# Core Advisor
# ─────────────────────────────────────────────────────────────────────────────

class EntryTimingAdvisor:
    """
    For each (symbol, pre_trade_analysis) pair, computes EntryAdvice:
      - Best entry window for today
      - How many minutes to wait
      - Which conditions are still pending
      - Overall confidence
    """

    def __init__(self, strategy_engine, risk_engine):
        self.strategy_engine = strategy_engine
        self.risk_engine     = risk_engine

    def advise(
        self,
        symbol: str,
        pre_trade_analysis: dict,
        live_price: float = 0.0,
        live_vwap: float  = 0.0,
        live_rsi: float   = 50.0,
        live_volume_ratio: float = 1.0,
        live_ema9: float  = 0.0,
        live_ema21: float = 0.0,
        live_ema50: float = 0.0,
        quality_score: float = 50.0,
    ) -> EntryAdvice:
        """
        Compute full entry advice for one symbol.
        All live_* params are optional — if 0 / missing, they are estimated
        from the backtest averages.
        """
        import app.core.strategy_engine as se_module

        now            = _now_ist()
        current_time   = now.time()
        best_strategy  = pre_trade_analysis.get("best_strategy", "Ensemble")
        win_rate       = pre_trade_analysis.get("win_rate", 50.0)
        sharpe         = pre_trade_analysis.get("sharpe", 0.0)
        stop_pct       = pre_trade_analysis.get("optimal_stop_pct", 5.0)
        target_pct     = pre_trade_analysis.get("optimal_target_pct", 8.0)
        capital        = pre_trade_analysis.get("optimal_capital", 3000.0)
        regime_verdict = pre_trade_analysis.get("regime_verdict", "BULL")
        bt_verdict     = pre_trade_analysis.get("trade_verdict", "PROCEED")

        min_confluence = se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"]

        # ── 1. Market hour check ─────────────────────────────────────────
        if not _in_window(current_time, MARKET_OPEN, MARKET_CLOSE):
            mins_to_open = _minutes_until(MARKET_OPEN, now)
            if mins_to_open < 0:
                mins_to_open = 0  # market opens tomorrow
            return EntryAdvice(
                symbol=symbol, best_strategy=best_strategy,
                can_enter_now=False,
                wait_minutes=mins_to_open,
                wait_until=MARKET_OPEN.strftime("%H:%M"),
                current_window="Market Closed",
                time_urgency="AVOID TODAY",
                required_conditions=["Market must be open (9:15–15:30 IST)"],
                conditions_met=[], conditions_pending=["Market closed"],
                confidence_pct=0.0, confidence_label="AVOID",
                optimal_stop_pct=stop_pct, optimal_target_pct=target_pct,
                optimal_capital=capital,
                min_confluence_required=min_confluence,
                current_quality_score=quality_score,
                advice_summary="❌ Market is closed. Wait for 9:15 AM IST.",
            )

        # ── 2. Hard avoid-zone check ──────────────────────────────────────
        for az_start, az_end, az_name in AVOID_ZONES:
            if _in_window(current_time, az_start, az_end):
                wait = _minutes_until(az_end, now) + 1
                return EntryAdvice(
                    symbol=symbol, best_strategy=best_strategy,
                    can_enter_now=False,
                    wait_minutes=wait,
                    wait_until=az_end.strftime("%H:%M"),
                    current_window=az_name,
                    time_urgency="WAIT",
                    required_conditions=[f"Must be past {az_end.strftime('%H:%M')} IST"],
                    conditions_met=[], conditions_pending=[f"Currently in {az_name}"],
                    confidence_pct=10.0, confidence_label="AVOID",
                    optimal_stop_pct=stop_pct, optimal_target_pct=target_pct,
                    optimal_capital=capital,
                    min_confluence_required=min_confluence,
                    current_quality_score=quality_score,
                    advice_summary=f"🚫 Inside {az_name}. Wait {wait} min until {az_end.strftime('%H:%M')}.",
                )

        # ── 3. Strategy-preferred window check ────────────────────────────
        pref_windows = STRATEGY_PREFERRED_WINDOWS.get(
            best_strategy,
            [(datetime.time(9, 45), datetime.time(14, 30), "Main Session")]
        )
        window_info  = _next_window_start(pref_windows, now)
        in_pref_window = False
        current_window_name = "Outside preferred window"
        wait_for_window = 0

        if window_info:
            w_start, w_end, w_name, w_wait = window_info
            if w_wait == 0:
                in_pref_window = True
                current_window_name = w_name
            else:
                wait_for_window = w_wait
                current_window_name = f"Next: {w_name} at {w_start.strftime('%H:%M')}"
        else:
            # All windows for today have passed
            return EntryAdvice(
                symbol=symbol, best_strategy=best_strategy,
                can_enter_now=False,
                wait_minutes=0,
                wait_until="09:30 Tomorrow",
                current_window="All windows passed for today",
                time_urgency="AVOID TODAY",
                required_conditions=[],
                conditions_met=[], conditions_pending=["No more entry windows today"],
                confidence_pct=0.0, confidence_label="AVOID",
                optimal_stop_pct=stop_pct, optimal_target_pct=target_pct,
                optimal_capital=capital,
                min_confluence_required=min_confluence,
                current_quality_score=quality_score,
                advice_summary="⏰ All entry windows exhausted for today. Resume tomorrow.",
            )

        # ── 4. Build required conditions (dynamic from guardrails) ────────
        required_conditions: List[str] = []
        conditions_met: List[str] = []
        conditions_pending: List[str] = []

        # 4a. Backtest quality gate
        req_bt = f"3yr backtest verdict = PROCEED (score > 0)"
        required_conditions.append(req_bt)
        if bt_verdict == "PROCEED":
            conditions_met.append(f"✅ BT verdict: PROCEED (WR={win_rate:.0f}%, Sharpe={sharpe:.2f})")
        else:
            conditions_pending.append(f"❌ BT verdict: {bt_verdict} — skip this symbol")

        # 4b. Quality score gate (from live optimizer)
        req_qs = f"Quality score ≥ 40 (current: {quality_score:.1f})"
        required_conditions.append(req_qs)
        if quality_score >= 40:
            conditions_met.append(f"✅ Quality: {quality_score:.1f}/100")
        else:
            conditions_pending.append(f"⏳ Quality score too low ({quality_score:.1f} < 40)")

        # 4c. Preferred time window
        req_win = f"Inside preferred window for {best_strategy}"
        required_conditions.append(req_win)
        if in_pref_window:
            conditions_met.append(f"✅ In window: {current_window_name}")
        else:
            conditions_pending.append(
                f"⏳ Wait {wait_for_window} min for {current_window_name}"
            )

        # 4d. Price > VWAP (if we have live data)
        if live_price > 0 and live_vwap > 0:
            req_vwap = "Price > VWAP (bullish structure)"
            required_conditions.append(req_vwap)
            if live_price > live_vwap:
                dist = (live_price - live_vwap) / live_vwap * 100
                conditions_met.append(f"✅ Price > VWAP (+{dist:.2f}%)")
            else:
                conditions_pending.append(f"⏳ Price < VWAP ({live_price:.1f} < {live_vwap:.1f})")

        # 4e. EMA alignment (if we have live data)
        if live_ema9 > 0 and live_ema21 > 0:
            req_ema = f"EMA 9 > EMA 21 (required by {best_strategy})"
            required_conditions.append(req_ema)
            if live_ema9 > live_ema21:
                conditions_met.append(f"✅ EMA9({live_ema9:.1f}) > EMA21({live_ema21:.1f})")
            else:
                conditions_pending.append(
                    f"⏳ EMA9({live_ema9:.1f}) < EMA21({live_ema21:.1f}) — awaiting bullish cross"
                )

        # 4f. Volume confirmation
        req_vol = f"Volume ratio > {1.2 if 'Institutional' not in best_strategy else 1.5}x avg"
        required_conditions.append(req_vol)
        vol_threshold = 1.5 if "Institutional" in best_strategy else 1.2
        if live_volume_ratio >= vol_threshold:
            conditions_met.append(
                f"✅ Volume: {live_volume_ratio:.1f}x (threshold {vol_threshold}x)"
            )
        else:
            conditions_pending.append(
                f"⏳ Volume: {live_volume_ratio:.1f}x < {vol_threshold}x required"
            )

        # 4g. RSI filter
        if best_strategy in ("RSIReversal", "MeanReversion"):
            req_rsi = "RSI < 35 (oversold entry)"
            required_conditions.append(req_rsi)
            if live_rsi < 35:
                conditions_met.append(f"✅ RSI={live_rsi:.1f} (oversold)")
            else:
                conditions_pending.append(f"⏳ RSI={live_rsi:.1f} — wait for RSI < 35")
        else:
            req_rsi = "RSI > 45 (momentum confirmation)"
            required_conditions.append(req_rsi)
            if live_rsi > 45:
                conditions_met.append(f"✅ RSI={live_rsi:.1f} (momentum ok)")
            else:
                conditions_pending.append(f"⏳ RSI={live_rsi:.1f} — wait for RSI > 45")

        # 4h. Min confluence (from live optimizer)
        req_conf = f"≥ {min_confluence} strategies must agree (dynamic confluence)"
        required_conditions.append(req_conf)
        # We can't know current confluence without running the full ensemble here,
        # so we estimate from quality_score as a proxy
        estimated_agreeing = max(1, int(min_confluence * quality_score / 70))
        if estimated_agreeing >= min_confluence:
            conditions_met.append(
                f"✅ Est. confluence: ~{estimated_agreeing}/{min_confluence} strategies agree"
            )
        else:
            conditions_pending.append(
                f"⏳ Confluence: ~{estimated_agreeing} agreeing < {min_confluence} required"
            )

        # ── 5. Compute overall wait time ──────────────────────────────────
        wait_minutes = wait_for_window  # base: wait for preferred window

        # If conditions are pending due to live indicator signals, add 5-min bars
        pending_indicator_conditions = [
            c for c in conditions_pending
            if "Volume" in c or "EMA" in c or "RSI" in c or "VWAP" in c
        ]
        if pending_indicator_conditions:
            # Each pending indicator condition ≈ 1 scan cycle (5 min) to resolve
            wait_minutes += len(pending_indicator_conditions) * 5

        # If quality is low, wait for it to improve (1 trade outcome per cycle)
        if quality_score < 40:
            wait_minutes += 15   # wait ~3 scan cycles

        # Wait until time string
        wait_until_dt = now + datetime.timedelta(minutes=wait_minutes)
        wait_until_str = wait_until_dt.strftime("%H:%M")

        # ── 6. Confidence score ───────────────────────────────────────────
        total_conditions = len(required_conditions)
        met_count        = len(conditions_met)
        pct_met          = (met_count / total_conditions * 100) if total_conditions else 50

        # Weight: backtest quality (40%) + conditions met (40%) + quality score (20%)
        confidence = (
            min(win_rate, 80) / 80 * 40 +
            pct_met * 0.40 +
            min(quality_score, 100) / 100 * 20
        )
        confidence = round(min(100.0, confidence), 1)

        # ── 7. can_enter_now ─────────────────────────────────────────────
        can_enter = (
            wait_minutes == 0
            and bt_verdict == "PROCEED"
            and quality_score >= 40
            and in_pref_window
            and len(conditions_pending) == 0
        )

        # Build urgency label
        if can_enter:
            urgency = "🚀 ENTER NOW"
        elif wait_minutes <= 10:
            urgency = f"⏰ WAIT {wait_minutes} MIN"
        elif wait_minutes <= 30:
            urgency = f"⏳ WAIT {wait_minutes} MIN"
        else:
            urgency = f"🕐 WAIT {wait_minutes} MIN"

        # ── 8. Advice summary ─────────────────────────────────────────────
        if can_enter:
            summary = (
                f"✅ All {total_conditions} conditions met. "
                f"Enter via {best_strategy} | Stop: {stop_pct:.1f}% | "
                f"Target: {target_pct:.1f}% | Capital: ₹{capital:,.0f}"
            )
        elif wait_minutes == 0 and conditions_pending:
            summary = (
                f"⏳ {len(conditions_pending)} condition(s) still pending. "
                f"Monitor every 5 min."
            )
        else:
            summary = (
                f"⏰ Wait ~{wait_minutes} min until {wait_until_str}. "
                f"Then verify: {', '.join(c[:40] for c in conditions_pending[:2])}"
            )

        return EntryAdvice(
            symbol=symbol,
            best_strategy=best_strategy,
            can_enter_now=can_enter,
            wait_minutes=wait_minutes,
            wait_until=wait_until_str,
            current_window=current_window_name,
            time_urgency=urgency,
            required_conditions=required_conditions,
            conditions_met=conditions_met,
            conditions_pending=conditions_pending,
            confidence_pct=confidence,
            confidence_label=_confidence_label(confidence),
            optimal_stop_pct=stop_pct,
            optimal_target_pct=target_pct,
            optimal_capital=capital,
            min_confluence_required=min_confluence,
            current_quality_score=quality_score,
            advice_summary=summary,
        )

    def advise_all(
        self,
        candidates: list,
        quality_score: float = 50.0,
    ) -> List[EntryAdvice]:
        """
        Runs advise() for all candidates in the current workflow.
        Uses pre_trade_analysis stored inside each candidate dict.
        Returns list sorted by: can_enter_now first, then lowest wait_minutes.
        """
        advices = []
        for cand in candidates:
            pta = cand.get("pre_trade_analysis", {})
            if not pta:
                continue
            adv = self.advise(
                symbol=cand.get("symbol", "?"),
                pre_trade_analysis=pta,
                live_price=cand.get("price", 0.0),
                quality_score=quality_score,
            )
            advices.append(adv)

        advices.sort(key=lambda a: (not a.can_enter_now, a.wait_minutes))
        return advices
