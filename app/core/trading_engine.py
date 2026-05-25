"""
Background trading engine — daemon thread, phase-aware, auto-arms at 9:15 IST.

Daily phases (IST):
  • pre_market  (<09:15)       : engine idle even if enabled
  • setup       (09:15–09:30)  : auto-armed, no trades — watchlist warm-up
  • noisy_open  (09:30–10:15)  : auto-armed, observation only (skip trades)
  • active      (10:15–14:45)  : full scan + (optionally) auto-execute
  • closing     (14:45–15:25)  : no new entries; let broker MIS handle exits
  • after_15_25 (15:25–15:30)  : final close grace; nothing new
  • closed      (else / holiday): disarmed

Singleton: TradingEngine() — first call constructs + spawns the thread.
Safety: auto_execute defaults to False; orders are placed only when explicitly
enabled by the user.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any, List, Optional

from app.core.market_calendar import is_nse_bse_trading_day, IST
from app.core.risk_engine import RiskEngine
from app.core.zerodha_auth import zerodha_auth

log = logging.getLogger("engine")

# Phase constants
PHASE_PRE_MARKET = "pre_market"
PHASE_SETUP = "setup"
PHASE_NOISY_OPEN = "noisy_open"
PHASE_ACTIVE = "active"
PHASE_CLOSING = "closing"
PHASE_AFTER_15_25 = "final_close"
PHASE_CLOSED = "closed"

PHASE_LABEL = {
    PHASE_PRE_MARKET: "Pre-market (idle)",
    PHASE_SETUP: "Setup (9:15–9:30)",
    PHASE_NOISY_OPEN: "Noisy open (9:30–10:15)",
    PHASE_ACTIVE: "Active trading (10:15–14:45)",
    PHASE_CLOSING: "Closing (14:45–15:25)",
    PHASE_AFTER_15_25: "Final close (15:25–15:30)",
    PHASE_CLOSED: "Market closed",
}


@dataclass
class EngineSnapshot:
    enabled: bool = False
    armed: bool = False
    auto_execute: bool = False
    phase: str = PHASE_CLOSED
    phase_label: str = ""
    last_tick: str = ""
    last_scan_at: str = ""
    last_scan_count: int = 0
    trades_today: int = 0
    halted: bool = False
    halt_reason: str = ""
    candidates: List[Any] = field(default_factory=list)
    activity: List[dict] = field(default_factory=list)


class TradingEngine:
    _instance: Optional["TradingEngine"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._enabled = False
        self._auto_execute = False
        self._armed = False
        self._phase = PHASE_CLOSED
        self._last_tick = ""
        self._last_scan_at = ""
        self._candidates: List[Any] = []
        self._activity: deque = deque(maxlen=200)
        self._trades_today = 0
        self.risk_engine = RiskEngine()
        self._thread: Optional[threading.Thread] = None
        # Thread is started lazily on the first .enable() call so module import is cheap.

    # ── Public controls ─────────────────────────────────────────────────────
    def enable(self) -> None:
        with self._lock:
            self._enabled = True
        self._start_thread()
        self._log("Bot ENABLED — auto-arms at 9:15 IST on trading days")

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._armed = False
        self._log("Bot DISABLED — armed = False", "warn")

    def set_auto_execute(self, value: bool) -> None:
        with self._lock:
            self._auto_execute = bool(value)
        self._log(f"Auto-execute = {'ON' if value else 'OFF'}", "warn" if value else "info")

    def kill_all(self) -> dict:
        """Disarm + cancel every open order. Returns counts."""
        with self._lock:
            self._enabled = False
            self._armed = False
        cancelled = 0
        failures: List[str] = []
        try:
            from app.core.live_broker import LiveBroker
            kite = LiveBroker().kite
            for o in kite.orders():
                if o.get("status") in ("OPEN", "TRIGGER PENDING", "AMO REQ RECEIVED"):
                    try:
                        kite.cancel_order(variety=o.get("variety", "regular"), order_id=o["order_id"])
                        cancelled += 1
                    except Exception as e:
                        failures.append(f"{o.get('order_id')}: {e}")
        except Exception as e:
            failures.append(str(e))
        self._log(f"KILL ALL — cancelled {cancelled}, failures {len(failures)}", "error")
        return {"cancelled": cancelled, "failures": failures}

    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            return EngineSnapshot(
                enabled=self._enabled,
                armed=self._armed,
                auto_execute=self._auto_execute,
                phase=self._phase,
                phase_label=PHASE_LABEL.get(self._phase, self._phase),
                last_tick=self._last_tick,
                last_scan_at=self._last_scan_at,
                last_scan_count=len(self._candidates),
                trades_today=self.risk_engine.daily_stats.total_trades,
                halted=self.risk_engine.daily_stats.is_trading_halted,
                halt_reason="",
                candidates=list(self._candidates),
                activity=list(self._activity)[-50:],
            )

    # ── Internals ───────────────────────────────────────────────────────────
    def _log(self, msg: str, level: str = "info") -> None:
        ts = datetime.now(IST).strftime("%H:%M:%S")
        self._activity.append({"ts": ts, "level": level, "msg": msg})
        getattr(log, level, log.info)(msg)

    def _compute_phase(self) -> str:
        now = datetime.now(IST)
        if not is_nse_bse_trading_day(now.date()):
            return PHASE_CLOSED
        t = now.time()
        if t < dtime(9, 15):
            return PHASE_PRE_MARKET
        if t < dtime(9, 30):
            return PHASE_SETUP
        if t < dtime(10, 15):
            return PHASE_NOISY_OPEN
        if t < dtime(14, 45):
            return PHASE_ACTIVE
        if t < dtime(15, 25):
            return PHASE_CLOSING
        if t < dtime(15, 30):
            return PHASE_AFTER_15_25
        return PHASE_CLOSED

    def _start_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="trading_engine")
        self._thread.start()
        log.info("trading_engine thread started")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log.exception("engine tick failed")
                self._log(f"Tick error: {e}", "error")
            interval = 5 if self._phase == PHASE_ACTIVE else 30
            self._stop_event.wait(interval)

    def _tick(self) -> None:
        with self._lock:
            phase = self._compute_phase()
            now_str = datetime.now(IST).strftime("%H:%M:%S")
            phase_changed = phase != self._phase
            self._phase = phase
            self._last_tick = now_str

            if not self._enabled:
                self._armed = False
                if phase_changed:
                    self._log(f"Phase → {PHASE_LABEL[phase]} (bot disabled, idle)")
                return

            if phase == PHASE_CLOSED:
                if self._armed:
                    self._armed = False
                    self._log("Market closed — disarmed", "warn")
                return

            if phase == PHASE_PRE_MARKET:
                self._armed = False
                if phase_changed:
                    self._log("Phase → Pre-market (waiting for 9:15)")
                return

            # Phases >= SETUP: auto-arm
            if not self._armed:
                self._armed = True
                self._log(f"AUTO-ARMED at {now_str} (phase: {PHASE_LABEL[phase]})")

            if phase_changed:
                self._log(f"Phase → {PHASE_LABEL[phase]}")

            if phase in (PHASE_SETUP, PHASE_NOISY_OPEN):
                # Watchlist warm-up + observation; no trades yet.
                return

            if phase in (PHASE_CLOSING, PHASE_AFTER_15_25):
                # No new entries — broker MIS auto-square-off at 15:30 handles exits.
                return

        # Outside the lock: PHASE_ACTIVE work (scan + optional execute)
        try:
            from app.core.intraday_agent import scan_intraday_universe, session_capital
            capital = session_capital()
            cands = scan_intraday_universe(capital, max_symbols=40)
            with self._lock:
                self._candidates = cands
                self._last_scan_at = datetime.now(IST).strftime("%H:%M:%S")
            self._log(f"Scan: {len(cands)} candidates")

            if self._auto_execute and not self.risk_engine.daily_stats.is_trading_halted:
                self._auto_place_top_candidates(cands, capital)
        except Exception as e:
            self._log(f"Scan failed: {e}", "error")

    def _auto_place_top_candidates(self, cands: List[Any], capital: float) -> None:
        """Place bracket BUY for top candidates that pass risk checks."""
        from app.core.live_broker import LiveBroker
        from app.core.market_calendar import can_place_nse_bse_equity_trade

        slots_left = self.risk_engine.config.max_trades_per_day - self.risk_engine.daily_stats.total_trades
        if slots_left <= 0:
            self._log("Trade slots exhausted for today", "warn")
            return

        # Re-check market window — should be open in PHASE_ACTIVE, but verify
        ok_mkt, msg_mkt = can_place_nse_bse_equity_trade()
        if not ok_mkt:
            self._log(f"Market gate failed pre-order: {msg_mkt}", "warn")
            return

        broker = LiveBroker()
        for d in cands[: min(3, slots_left)]:
            if self.risk_engine.daily_stats.is_trading_halted:
                self._log("Halted mid-batch — stopping execution", "warn")
                break
            notional = d.entry_price * d.quantity
            sl_pct = d.risk_pct / 100.0
            ok_risk, msg_risk = self.risk_engine.can_place_trade(notional, assumed_sl_pct=sl_pct)
            if not ok_risk:
                self._log(f"Skip {d.stock}: {msg_risk}", "warn")
                continue
            try:
                order = broker.place_bracket_buy(
                    symbol=d.stock,
                    quantity=int(d.quantity),
                    limit_price=float(d.entry_price),
                    stop_loss_price=float(d.stop_loss),
                    target_price=float(d.target),
                )
                self.risk_engine.daily_stats.total_trades += 1
                oid = getattr(order, "order_id", order)
                self._log(f"AUTO BUY {d.stock} qty={d.quantity} oid={oid}")
            except Exception as e:
                self._log(f"AUTO order failed {d.stock}: {e}", "error")
