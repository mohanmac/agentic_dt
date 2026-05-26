"""
NIFTY 500 intraday agent: rule-based long-only MIS logic with Zerodha-friendly outputs.
Paper mode uses the same math with simulated quotes when Kite fails.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.market_data import market_data
from app.core.utils import logger
from app.core.zerodha_auth import zerodha_auth

IST = ZoneInfo("Asia/Kolkata")

MIN_PRICE = 50.0
MAX_PRICE = 150.0  # Tuned for ₹2,000 session capital — keeps 4-5 shares per ₹700 ticket
                  # for usable position granularity at intraday 10% targets.
MIN_DAILY_VOLUME = 500_000
MAX_SPREAD_PCT = 0.2
MIN_DEPTH_EACH_SIDE = 2_000
MIN_CONFIDENCE_TRADE = 75
MAX_TRADES_PER_DAY = 5
RAMP_EXIT_HOUR = 15
RAMP_EXIT_MINUTE = 15

# User mandate: target not below +10%, stop distance strictly under 10%
MIN_TARGET_PCT = 10.0
MAX_STOP_LOSS_PCT = 9.5

ORB_VOL_MULT = 1.5
MOM_VOL_MULT = 2.0
VWAP_PULLBACK_VOL_MULT = 1.3


@dataclass
class IntradayDecision:
    stock: str
    strategy: str
    entry_price: float
    stop_loss: float
    target: float
    risk_pct: float
    confidence: float
    quantity: int
    reasoning: str = ""
    indicator_notes: List[str] = field(default_factory=list)
    volume_notes: List[str] = field(default_factory=list)
    market_alignment: List[str] = field(default_factory=list)
    planning: str = ""
    hitl_points: List[str] = field(default_factory=list)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def load_nifty500_symbols() -> List[str]:
    path = _project_root() / "data" / "nifty500_tradingsymbols.txt"
    if not path.exists():
        logger.warning("nifty500_tradingsymbols.txt missing; using TRADING_SYMBOLS from settings")
        return settings.get_trading_symbols()
    syms: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        syms.append(line.upper())
    return list(dict.fromkeys(syms))


def _today_mask(idx: pd.DatetimeIndex, tz=IST) -> np.ndarray:
    """Boolean mask for rows belonging to 'today' in IST."""
    if idx.tz is None:
        idx = idx.tz_localize("UTC").tz_convert(tz)
    else:
        idx = idx.tz_convert(tz)
    d0 = datetime.now(tz).date()
    return np.array([ts.date() == d0 for ts in idx], dtype=bool)


def _nifty_trend_bullish() -> Tuple[bool, str]:
    """Use NIFTY 50 spot quote: bullish if LTP > open and above session VWAP."""
    sym = "NIFTY 50"
    try:
        qm = market_data.get_quote_full([sym])
        q = qm.get(sym)
        if not q:
            return True, "NIFTY data unavailable — assumed bullish (verify manually)"
        ltp = float(q["ltp"])
        o = float((q.get("ohlc") or {}).get("open") or ltp)
        vwap = float(q["vwap"] or ltp)
        ok = ltp >= o and ltp >= vwap * 0.999
        note = f"NIFTY LTP {ltp:.2f} vs open {o:.2f}, VWAP {vwap:.2f}"
        return ok, note
    except Exception as e:
        logger.warning(f"NIFTY bias failed: {e}")
        return True, "NIFTY check failed — manual review required"


def _relative_strength_vs_nifty(stock_ret: float) -> Tuple[bool, str]:
    """Sector momentum proxy: stock recent return vs NIFTY."""
    sym = "NIFTY 50"
    try:
        n5 = market_data.get_ohlc(sym, interval="5minute", days=2)
        if n5 is None or len(n5) < 8:
            return True, "NIFTY history short — momentum alignment skipped"
        r_n = (n5["close"].iloc[-1] / n5["close"].iloc[-6] - 1.0) * 100
        ok = stock_ret >= r_n - 0.05
        return ok, f"Stock 5m ret {stock_ret:.3f}% vs NIFTY {r_n:.3f}%"
    except Exception:
        return True, "NIFTY RS unavailable"


def _liquidity_ok(spread_pct: float, bid_q: int, ask_q: int) -> Tuple[bool, str]:
    if spread_pct > MAX_SPREAD_PCT:
        return False, f"Spread {spread_pct:.3f}% > {MAX_SPREAD_PCT}%"
    if bid_q < MIN_DEPTH_EACH_SIDE or ask_q < MIN_DEPTH_EACH_SIDE:
        return False, f"Depth weak bid={bid_q} ask={ask_q} (min {MIN_DEPTH_EACH_SIDE})"
    return True, "Order book depth acceptable"


def _daily_volume_ok(symbol: str) -> Tuple[bool, int]:
    try:
        df = market_data.get_ohlc(symbol, interval="day", days=10)
        if df is None or df.empty:
            return False, 0
        vol = int(df["volume"].iloc[-1])
        return vol >= MIN_DAILY_VOLUME, vol
    except Exception:
        return False, 0


def _build_5m_context(symbol: str, quote: dict) -> Optional[Dict[str, Any]]:
    try:
        df = market_data.get_ohlc(symbol, interval="5minute", days=5)
    except Exception as e:
        logger.warning(f"OHLC fail {symbol}: {e}")
        return None
    if df is None or len(df) < 60:
        return None

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC").tz_convert(IST)
    else:
        df = df.tz_convert(IST)

    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(min(50, len(close) - 1)).mean().iloc[-1]) if len(close) > 50 else sma20
    rsi14 = market_data.rsi_wilder(close, 14)
    avg_vol = float(vol.tail(20).mean() or 1.0)
    last_vol = float(vol.iloc[-1])
    vol_ratio = last_vol / avg_vol if avg_vol else 0.0

    mask_td = _today_mask(df.index)
    if mask_td.any():
        vwap_day = float(market_data.calculate_vwap(df[mask_td]))
    else:
        vwap_day = float(quote.get("vwap") or close.iloc[-1])
    ltp = float(quote.get("ltp") or close.iloc[-1])

    today = df[_today_mask(df.index)]
    or_high = or_low = None
    if len(today) >= 3:
        or_high = float(today.head(3)["high"].max())
        or_low = float(today.head(3)["low"].min())
    elif len(today) >= 1:
        or_high = float(today["high"].max())
        or_low = float(today["low"].min())

    # Last candles for microstructure
    prev_row = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    last_row = df.iloc[-1]
    bullish_candle = float(last_row["close"]) > float(last_row["open"])
    prev_bullish = float(prev_row["close"]) > float(prev_row["open"])

    stock_ret_5m = (close.iloc[-1] / close.iloc[-6] - 1.0) * 100 if len(close) > 6 else 0.0

    return {
        "ltp": ltp,
        "vwap": vwap_day,
        "sma20": sma20,
        "sma50": sma50,
        "rsi14": rsi14,
        "vol_ratio": vol_ratio,
        "or_high": or_high,
        "or_low": or_low,
        "avg_vol_20": avg_vol,
        "last_vol": last_vol,
        "bullish_candle": bullish_candle,
        "prev_bullish": prev_bullish,
        "prev_close": float(prev_row["close"]),
        "prev_open": float(prev_row["open"]),
        "adx_proxy": float((high.tail(14) - low.tail(14)).mean() / close.iloc[-1] * 100) if close.iloc[-1] else 0,
        "stock_ret_5m": stock_ret_5m,
    }


def _score_confidence(base: int, checks: List[Tuple[bool, str]]) -> Tuple[int, List[str]]:
    score = base
    notes = []
    for ok, msg in checks:
        if ok:
            score += 8
        notes.append(f"{'✓' if ok else '✗'} {msg}")
    return min(100, score), notes


def apply_profit_stop_profile(d: IntradayDecision) -> Optional[IntradayDecision]:
    """Min profit +10% from entry; stop distance strictly under 10% (tighten wide structural SL)."""
    e = d.entry_price
    if e <= 0:
        return None
    t_floor = e * (1 + MIN_TARGET_PCT / 100)
    d.target = round(max(d.target, t_floor), 2)
    max_risk_frac = MAX_STOP_LOSS_PCT / 100.0
    stop_floor_price = e * (1 - max_risk_frac)
    d.stop_loss = round(max(d.stop_loss, stop_floor_price), 2)
    risk_pct = (e - d.stop_loss) / e * 100
    if risk_pct >= 10.0 - 1e-9:
        d.stop_loss = round(e * (1 - 9.49 / 100), 2)
        risk_pct = (e - d.stop_loss) / e * 100
    d.risk_pct = round(risk_pct, 3)
    reward_pct = (d.target - e) / e * 100
    if reward_pct + 0.05 < MIN_TARGET_PCT:
        return None
    if d.stop_loss >= e or d.target <= e:
        return None
    if risk_pct >= 10.0:
        return None
    return d


def enrich_par_metadata(d: IntradayDecision, capital: float) -> None:
    """Planning + HITL prompts (PARF: proactive plan before you act)."""
    tp_pct = (d.target / d.entry_price - 1) * 100
    d.planning = (
        f"Plan: {d.strategy} on {d.stock} — entry ~₹{d.entry_price:.2f}, qty {d.quantity} "
        f"(~1% equity risk vs SL on ₹{capital:,.0f}), target **+{tp_pct:.1f}%** (floor {MIN_TARGET_PCT:g}%), "
        f"stop **−{d.risk_pct:.1f}%** (<10%)."
    )
    d.hitl_points = [
        "No fresh stock-specific news / results / circuits",
        "Spread & order book still support exit at send time",
        f"Bracket sanity: SL ₹{d.stop_loss:.2f}, TGT ₹{d.target:.2f}",
        "MIS margin and daily / streak loss headroom OK",
    ]


def _try_opening_range_breakout(
    symbol: str, ctx: Dict[str, Any], nifty_bullish: bool
) -> Optional[IntradayDecision]:
    orh, orl = ctx.get("or_high"), ctx.get("or_low")
    if orh is None or orl is None:
        return None
    ltp = ctx["ltp"]
    if ltp <= orh * 1.0005:
        return None
    if ctx["vol_ratio"] < ORB_VOL_MULT:
        return None
    if not nifty_bullish:
        return None

    entry = ltp
    stop = orl
    target = entry * 1.02
    if stop >= entry * 0.995:
        stop = entry * 0.993

    risk_pct = ((entry - stop) / entry * 100) if entry else 0
    sector_ok, sector_note = _relative_strength_vs_nifty(ctx["stock_ret_5m"])
    conf, ck = _score_confidence(
        55,
        [
            (ctx["vol_ratio"] >= ORB_VOL_MULT, f"Vol {ctx['vol_ratio']:.2f}x vs avg (need ≥{ORB_VOL_MULT})"),
            (nifty_bullish, "NIFTY alignment"),
            (ltp > ctx["vwap"], "Price above VWAP"),
            (sector_ok, sector_note),
        ],
    )
    if conf < MIN_CONFIDENCE_TRADE:
        return None

    return IntradayDecision(
        stock=symbol,
        strategy="Opening Range Breakout",
        entry_price=round(entry, 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        risk_pct=round(risk_pct, 3),
        confidence=float(conf),
        quantity=0,
        reasoning="First 15m high breakout with volume; NIFTY trend supportive.",
        indicator_notes=[f"OR high {orh:.2f}, low {orl:.2f}", f"RSI(14) {ctx['rsi14']:.1f}"],
        volume_notes=[f"Volume {ctx['vol_ratio']:.2f}x average"],
        market_alignment=ck + [sector_note],
    )


def _try_vwap_pullback(symbol: str, ctx: Dict[str, Any]) -> Optional[IntradayDecision]:
    ltp = ctx["ltp"]
    vwap = ctx["vwap"]
    if vwap <= 0:
        return None
    if not (ltp >= vwap * 0.998 and ltp <= vwap * 1.003):
        return None
    if not (ctx["bullish_candle"] or ctx["prev_bullish"]):
        return None
    if ctx["vol_ratio"] < VWAP_PULLBACK_VOL_MULT:
        return None
    if not (ctx["prev_close"] > vwap or ltp > vwap):
        return None

    entry = ltp
    stop = entry * (1 - 0.0085)
    target = entry * (1 + 0.0175)
    risk_pct = ((entry - stop) / entry * 100) if entry else 0

    sector_ok, sector_note = _relative_strength_vs_nifty(ctx["stock_ret_5m"])
    conf, ck = _score_confidence(
        52,
        [
            (ltp > vwap * 0.999, "Holding/discounting VWAP"),
            (ctx["vol_ratio"] >= VWAP_PULLBACK_VOL_MULT, f"Vol spike {ctx['vol_ratio']:.2f}x"),
            (ctx["rsi14"] < 72, f"RSI not extreme ({ctx['rsi14']:.1f})"),
            (sector_ok, "Relative strength"),
        ],
    )
    if conf < MIN_CONFIDENCE_TRADE:
        return None

    return IntradayDecision(
        stock=symbol,
        strategy="VWAP Pullback",
        entry_price=round(entry, 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        risk_pct=round(risk_pct, 3),
        confidence=float(conf),
        quantity=0,
        reasoning="Pullback to VWAP with bullish candle and confirming volume.",
        indicator_notes=[f"VWAP {vwap:.2f}", f"RSI {ctx['rsi14']:.1f}", f"vs SMA20 {ctx['sma20']:.2f}"],
        volume_notes=[f"Vol ratio {ctx['vol_ratio']:.2f}x"],
        market_alignment=ck + [sector_note],
    )


def _try_momentum(symbol: str, ctx: Dict[str, Any]) -> Optional[IntradayDecision]:
    if ctx["rsi14"] <= 60:
        return None
    if not (ctx["ltp"] > ctx["sma20"]):
        return None
    if ctx["vol_ratio"] < MOM_VOL_MULT:
        return None
    sector_ok, sector_note = _relative_strength_vs_nifty(ctx["stock_ret_5m"])
    if not sector_ok:
        return None

    entry = ctx["ltp"]
    stop = entry * (1 - 0.01)
    target = entry * (1 + 0.025)
    trail_note = (
        "Initial MIS bracket: +10% target / capped stop; optionally trail below VWAP or prior low after partial progress."
    )
    risk_pct = ((entry - stop) / entry * 100) if entry else 0

    conf, ck = _score_confidence(
        50,
        [
            (ctx["rsi14"] > 60, f"RSI {ctx['rsi14']:.1f} > 60"),
            (ctx["ltp"] > ctx["sma20"], "Price > 20 MA"),
            (ctx["vol_ratio"] >= MOM_VOL_MULT, f"Vol {ctx['vol_ratio']:.2f}x"),
            (sector_ok, sector_note),
        ],
    )
    if conf < MIN_CONFIDENCE_TRADE:
        return None

    return IntradayDecision(
        stock=symbol,
        strategy="Momentum",
        entry_price=round(entry, 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        risk_pct=round(risk_pct, 3),
        confidence=float(conf),
        quantity=0,
        reasoning="Momentum continuation: RSI, MA alignment, volume spike, positive RS vs NIFTY. " + trail_note,
        indicator_notes=[f"RSI {ctx['rsi14']:.1f}", f"SMA20 {ctx['sma20']:.2f}"],
        volume_notes=[f"Vol {ctx['vol_ratio']:.2f}x"],
        market_alignment=ck,
    )


def _position_size(entry: float, stop: float, capital: float) -> int:
    risk_inr = max(capital, settings.DAILY_CAPITAL) * 0.01
    per_share = entry - stop
    if per_share <= 0:
        return 0
    qty = int(risk_inr // per_share)
    return max(0, qty)


def evaluate_symbol(symbol: str, capital: float) -> Optional[IntradayDecision]:
    """Run full gate + strategy stack for one symbol."""
    quotes = market_data.get_quote_full([symbol])
    quote = quotes.get(symbol)
    if not quote:
        return None

    ltp = float(quote["ltp"])
    if not (MIN_PRICE <= ltp <= MAX_PRICE):
        return None

    spread_pct, bid_q, ask_q = market_data.quote_spread_and_depth(quote)
    liq_ok, liq_msg = _liquidity_ok(spread_pct, bid_q, ask_q)
    if not liq_ok:
        logger.debug(f"{symbol} liquidity: {liq_msg}")
        return None

    dv_ok, dv = _daily_volume_ok(symbol)
    if not dv_ok:
        return None

    ctx = _build_5m_context(symbol, quote)
    if not ctx:
        return None

    if ctx["adx_proxy"] < 0.12 and ctx["vol_ratio"] < 1.1:
        return None

    nifty_bullish, nifty_note = _nifty_trend_bullish()

    candidates: List[IntradayDecision] = []
    orb = _try_opening_range_breakout(symbol, ctx, nifty_bullish)
    if orb:
        candidates.append(orb)
    vwap = _try_vwap_pullback(symbol, ctx)
    if vwap:
        candidates.append(vwap)
    mom = _try_momentum(symbol, ctx)
    if mom:
        candidates.append(mom)

    if not candidates:
        return None

    best = max(candidates, key=lambda d: d.confidence)
    best = apply_profit_stop_profile(best)
    if best is None:
        return None
    best.quantity = _position_size(best.entry_price, best.stop_loss, capital)
    best.market_alignment = [nifty_note, liq_msg, f"Daily vol {dv:,}"] + best.market_alignment
    enrich_par_metadata(best, capital)
    if best.quantity < 1:
        return None
    return best


def scan_intraday_universe(capital: float, max_symbols: int = 35) -> List[IntradayDecision]:
    """Scan a subset of the NIFTY 500 list (deterministic slice per day for speed)."""
    universe = load_nifty500_symbols()
    day_seed = datetime.now(IST).strftime("%Y%m%d")
    # stable rotation
    start = int(day_seed) % max(1, len(universe) - max_symbols)
    batch = universe[start : start + max_symbols]
    if len(batch) < max_symbols:
        batch = batch + universe[: max_symbols - len(batch)]

    out: List[IntradayDecision] = []
    for sym in batch:
        try:
            d = evaluate_symbol(sym, capital)
            if d:
                out.append(d)
        except Exception as e:
            logger.debug(f"scan skip {sym}: {e}")
    out.sort(key=lambda x: x.confidence, reverse=True)
    return out


def decision_to_dict(d: IntradayDecision) -> Dict[str, Any]:
    return {
        "Stock": d.stock,
        "Strategy": d.strategy,
        "Entry Price": d.entry_price,
        "Stop Loss": d.stop_loss,
        "Target": d.target,
        "Risk %": d.risk_pct,
        "Confidence Score (0–100)": d.confidence,
        "Quantity": d.quantity,
        "Planning": d.planning,
        "HITL checklist": d.hitl_points,
        "Reasoning": d.reasoning,
        "Indicator signals": d.indicator_notes,
        "Volume confirmation": d.volume_notes,
        "Market alignment": d.market_alignment,
    }


def session_planning_brief(capital: float, trade_slots_left: int, scan_width: int = 40) -> str:
    """Proactive session plan shown before HITL execution."""
    return (
        f"**Sizing basis:** ₹{capital:,.0f}  \n"
        f"**Scan:** ~{scan_width} NIFTY 500 names / pass  \n"
        f"**Mandate:** profit target ≥ **{MIN_TARGET_PCT:g}%**; stop distance **under 10%** "
        f"(engine caps at **{MAX_STOP_LOSS_PCT:g}%**)  \n"
        f"**Slots left today:** {trade_slots_left} / {MAX_TRADES_PER_DAY}  \n"
        f"**Agent loop:** **Plan** → **Reason** (signals) → **You approve** → **Act** → **Feedback**"
    )


def session_capital() -> float:
    """Best-effort equity net for sizing; falls back to settings."""
    try:
        k = zerodha_auth.get_kite_instance()
        m = k.margins(segment="equity")
        return float(m.get("net") or settings.DAILY_CAPITAL)
    except Exception:
        return float(settings.DAILY_CAPITAL)
