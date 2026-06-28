"""
Background trading engine — daemon thread, phase-aware, auto-arms at 9:15 IST.

Daily phases (IST):
  • pre_market  (<09:15)       : engine idle even if enabled
  • setup       (09:15–09:30)  : auto-armed, no trades — watchlist warm-up
  • noisy_open  (09:30–10:15)  : auto-armed, observation only (skip trades)
  • active      (10:15–14:45)  : full scan + (optionally) auto-execute
  • closing     (14:45–15:25)  : no new entries; force-exit tracked brackets at 15:15
  • after_15_25 (15:25–15:30)  : final close grace; nothing new
  • closed      (else / holiday): disarmed

Singleton: TradingEngine() — first call constructs + spawns the thread.
Safety: auto_execute defaults to False; orders are placed only when explicitly
confirmed in the dashboard.
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
ENTRY_LIMIT_BUFFER_PCT = 0.12

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
        restored = self._load_persisted_control_state()
        self._enabled = bool(restored.get("enabled", False))
        self._auto_execute = bool(restored.get("auto_execute", False))
        self._armed = False
        self._phase = PHASE_CLOSED
        self._last_tick = ""
        self._last_scan_at = ""
        self._candidates: List[Any] = []
        self._activity: deque = deque(self._load_persisted_activity(), maxlen=200)
        self._trades_today = 0
        self.risk_engine = RiskEngine()
        self._thread: Optional[threading.Thread] = None
        self._force_square_off_date: str | None = None
        self._scan_offset = 0
        # Thread is started lazily on the first .enable() call, or restored if the
        # previous Cloud process had an enabled bot for the current trading day.
        if self._enabled:
            self._start_thread()

    # ── Public controls ─────────────────────────────────────────────────────
    def enable(self) -> None:
        with self._lock:
            self._enabled = True
            self._auto_execute = True
            self._persist_control_state_locked()
        self._start_thread()
        self._log("Bot ENABLED — auto-execute ON; will place orders during the active phase")

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._armed = False
            self._auto_execute = False
            self._persist_control_state_locked()
        self._log("Bot DISABLED — armed = False", "warn")

    def set_auto_execute(self, value: bool) -> None:
        with self._lock:
            self._auto_execute = bool(value)
            self._persist_control_state_locked()
        self._log(f"Auto-execute = {'ON' if value else 'OFF'}", "warn" if value else "info")

    def kill_all(self) -> dict:
        """Disarm + cancel every open order. Returns counts."""
        with self._lock:
            self._enabled = False
            self._armed = False
            self._auto_execute = False
            self._persist_control_state_locked()
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
        self._persist_activity()

    def _load_persisted_control_state(self) -> dict:
        try:
            from app.core.storage import storage

            return storage.get_runtime_state("engine:control", {}) or {}
        except Exception:
            return {}

    def _load_persisted_activity(self) -> list[dict]:
        try:
            from app.core.storage import storage

            rows = storage.get_runtime_state("engine:activity", []) or []
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _persist_control_state_locked(self) -> None:
        try:
            from app.core.storage import storage

            storage.set_runtime_state(
                "engine:control",
                {
                    "enabled": bool(self._enabled),
                    "auto_execute": bool(self._auto_execute),
                    "armed": bool(self._armed),
                    "updated_at": datetime.now(IST).isoformat(),
                },
            )
        except Exception:
            return

    def _persist_activity(self) -> None:
        try:
            from app.core.storage import storage

            storage.set_runtime_state("engine:activity", list(self._activity)[-50:])
        except Exception:
            return

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
            try:
                self._force_square_off_if_due()
            except Exception as e:
                log.exception("force square-off check failed")
                self._log(f"Force square-off check failed: {e}", "error")
            # Advance open brackets every iteration (place exits once entries fill,
            # run OCO) regardless of phase, so exits are managed right up to close.
            try:
                from app.core.bracket_manager import get_bracket_manager
                get_bracket_manager().poll()
            except Exception:
                log.exception("bracket poll failed")
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
                # No new entries. _force_square_off_if_due() exits tracked
                # brackets at/after the configured 15:15 IST safety cutoff.
                return

        # Outside the lock: PHASE_ACTIVE work (scan + optional execute)
        try:
            from app.core import intraday_agent
            capital = intraday_agent.session_capital()
            cands = intraday_agent.scan_intraday_universe(capital, max_symbols=40, offset=self._scan_offset)
            self._scan_offset = (self._scan_offset + 40) % 500
            with self._lock:
                self._candidates = cands
                self._last_scan_at = datetime.now(IST).strftime("%H:%M:%S")
            if cands:
                self._log(f"Scan: {len(cands)} candidates")
            else:
                diag = intraday_agent.LAST_SCAN_DIAGNOSTICS or {}
                reasons = diag.get("reasons") or {}
                behavior = diag.get("behavior") or {}
                top = sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)[:4]
                detail = ", ".join(f"{k}={v}" for k, v in top) or "no diagnostics"
                label = behavior.get("label")
                summary = behavior.get("summary")
                if label:
                    self._log(f"Scan: 0 candidates · {label} ({detail}) — {summary}", "warn")
                else:
                    self._log(f"Scan: 0 candidates ({detail})", "warn")

            if self._auto_execute and not self.risk_engine.daily_stats.is_trading_halted:
                self._auto_place_top_candidates(cands, capital)
        except Exception as e:
            self._log(f"Scan failed: {e}", "error")

    def _auto_place_top_candidates(self, cands: List[Any], capital: float) -> None:
        """Open a managed intraday bracket for top candidates that pass risk checks.

        Uses BracketManager (supported MIS entry + target/stop exits), which also
        gives us a DRY-RUN mode when ENABLE_LIVE_TRADING is off — no real orders.
        """
        from app.core.bracket_manager import get_bracket_manager
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

        mgr = get_bracket_manager()
        mode = "LIVE" if mgr.live else "DRY-RUN"
        for d in cands[: min(3, slots_left)]:
            if self.risk_engine.daily_stats.is_trading_halted:
                self._log("Halted mid-batch — stopping execution", "warn")
                break
            if mgr.active_count() >= self.risk_engine.config.max_open_positions:
                self._log(
                    f"Max open positions ({self.risk_engine.config.max_open_positions}) reached — no new entries",
                    "warn",
                )
                break
            entry_limit = round(float(d.entry_price) * (1 + ENTRY_LIMIT_BUFFER_PCT / 100.0), 2)
            notional = entry_limit * d.quantity
            sl_pct = d.risk_pct / 100.0
            ok_risk, msg_risk = self.risk_engine.can_place_trade(notional, assumed_sl_pct=sl_pct)
            if not ok_risk:
                self._log(f"Skip {d.stock}: {msg_risk}", "warn")
                continue
            try:
                b = mgr.open_bracket(
                    symbol=d.stock,
                    quantity=int(d.quantity),
                    entry_price=entry_limit,
                    stop_price=float(d.stop_loss),
                    target_price=float(d.target),
                )
                if b is None:
                    self._log(f"Skip {d.stock}: bracket already active", "warn")
                    continue
                self.risk_engine.daily_stats.total_trades += 1
                self._log(
                    f"{mode} BUY {d.stock} qty={d.quantity} limit=₹{entry_limit:.2f} "
                    f"signal=₹{d.entry_price:.2f} "
                    f"tgt=₹{d.target:.2f} sl=₹{d.stop_loss:.2f} id={b.entry_id}"
                )
            except Exception as e:
                self._log(f"AUTO order failed {d.stock}: {e}", "error")

    def _force_square_off_if_due(self) -> None:
        """Bot-side final exit for tracked brackets before broker MIS square-off.

        Broker square-off remains the last backstop, but waiting for it leaves too
        much uncertainty. This fires once per trading day at settings.FORCE_EXIT_TIME
        (default 15:15 IST), only when the bot has been enabled.
        """
        from app.core.config import settings
        from app.core.market_calendar import is_nse_bse_trading_day

        now = datetime.now(IST)
        if not is_nse_bse_trading_day(now.date()):
            return
        if now.time() < dtime(settings.FORCE_EXIT_TIME_HOUR, settings.FORCE_EXIT_TIME_MINUTE):
            return
        day_key = now.date().isoformat()
        with self._lock:
            if not self._enabled:
                return
            if self._force_square_off_date == day_key:
                return
            self._force_square_off_date = day_key
            self._auto_execute = False

        from app.core.bracket_manager import get_bracket_manager

        result = get_bracket_manager().force_square_off()
        self._log(
            "FORCE SQUARE-OFF 15:15 — "
            f"closed={result.get('closed', 0)} cancelled={result.get('cancelled', 0)} "
            f"failures={len(result.get('failures', []))}",
            "warn",
        )
