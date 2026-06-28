"""Intraday bracket lifecycle on Kite using SUPPORTED order types.

Zerodha discontinued native Bracket Orders (``VARIETY_BO``) in 2020 — the
constant no longer even exists in the kiteconnect library, so the old
``place_order(variety=VARIETY_BO, squareoff=…, stoploss=…)`` call raised
AttributeError before any order was sent. This manager reproduces a bracket
with currently-supported orders and manages the exit lifecycle itself:

  1. ENTRY : regular MIS LIMIT buy.
  2. once the entry fills →
        TARGET : regular MIS LIMIT sell @ target
        STOP   : regular MIS SL-M  sell @ trigger = stop
  3. OCO   : when one exit fills, the sibling is cancelled.
  4. EOD   : the bot force-exits tracked brackets at 15:15 IST; broker
             auto-square-off remains the last backstop.

Two modes, chosen by ``settings.ENABLE_LIVE_TRADING``:
  • live=True  → real ``kite.place_order`` / ``orders`` / ``cancel_order``.
  • live=False → DRY-RUN: no real orders. Fills are simulated against a quote
    function so the whole buy→sell cycle can be validated with zero risk.

The manager is a process-wide singleton (``get_bracket_manager()``) so the
TradingEngine thread, the agents, and the dashboard all share one tracker and
any of them can advance it via ``poll()``.
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

log = logging.getLogger("bracket")

# Bracket lifecycle states
ENTRY_PENDING = "ENTRY_PENDING"   # entry order placed, awaiting fill
IN_POSITION = "IN_POSITION"       # entry filled, target + stop working
DONE = "DONE"                     # one exit filled, sibling cancelled
FAILED = "FAILED"                 # entry rejected/cancelled, never in position

# Kite string values (identical to KiteConnect.VARIETY_* / ORDER_TYPE_* etc.).
# Used literally so neither this module nor the test needs the kite constants.
_VARIETY = "regular"
_EXCHANGE = "NSE"
_PRODUCT_MIS = "MIS"
_VALIDITY_DAY = "DAY"
_BUY, _SELL = "BUY", "SELL"
_LIMIT, _SLM, _MARKET = "LIMIT", "SL-M", "MARKET"
_COMPLETE = "COMPLETE"
_DEAD = ("REJECTED", "CANCELLED")


@dataclass
class Bracket:
    symbol: str
    quantity: int
    entry_price: float
    stop_price: float
    target_price: float
    entry_id: str = ""
    target_id: str = ""
    stop_id: str = ""
    state: str = ENTRY_PENDING
    opened_at: datetime = field(default_factory=datetime.now)
    note: str = ""


class BracketManager:
    def __init__(
        self,
        kite=None,
        live: bool = False,
        quote_fn: Optional[Callable[[str], float]] = None,
    ) -> None:
        self._kite_obj = kite
        self.live = bool(live)
        self.quote_fn = quote_fn
        self._brackets: Dict[str, Bracket] = {}   # one active bracket per symbol/day
        self._lock = threading.Lock()
        self._sim_orders: Dict[str, dict] = {}     # dry-run order book

    # ── kite access ─────────────────────────────────────────────────────────
    def _kite(self):
        if self._kite_obj is not None:
            return self._kite_obj
        from app.core.zerodha_auth import zerodha_auth
        return zerodha_auth.get_kite_instance()

    # ── order primitives ──────────────────────────────────────────────────────
    def _place(self, *, symbol: str, txn: str, qty: int, order_type: str,
               price: Optional[float] = None, trigger: Optional[float] = None) -> str:
        """Place one leg. Returns an order id. Real in live mode, simulated in dry-run."""
        if self.live:
            oid = self._kite().place_order(
                variety=_VARIETY,
                exchange=_EXCHANGE,
                tradingsymbol=symbol,
                transaction_type=txn,
                quantity=int(qty),
                product=_PRODUCT_MIS,
                order_type=order_type,
                price=price,
                trigger_price=trigger,
                validity=_VALIDITY_DAY,
            )
            log.info("LIVE %s %s qty=%s type=%s price=%s trig=%s -> %s",
                     txn, symbol, qty, order_type, price, trigger, oid)
            return str(oid)
        oid = "SIM-" + uuid.uuid4().hex[:8]
        self._sim_orders[oid] = {
            "order_id": oid, "tradingsymbol": symbol, "transaction_type": txn,
            "status": "OPEN", "order_type": order_type, "price": price, "trigger_price": trigger,
        }
        log.info("[DRY-RUN] %s %s qty=%s type=%s price=%s trig=%s -> %s",
                 txn, symbol, qty, order_type, price, trigger, oid)
        return oid

    def _cancel(self, order_id: str) -> None:
        if not order_id:
            return
        if self.live:
            try:
                self._kite().cancel_order(variety=_VARIETY, order_id=order_id)
                log.info("LIVE cancel %s", order_id)
            except Exception:
                log.exception("cancel failed %s", order_id)
            return
        o = self._sim_orders.get(order_id)
        if o and o["status"] == "OPEN":
            o["status"] = "CANCELLED"
            log.info("[DRY-RUN] cancel %s", order_id)

    def _statuses(self) -> Dict[str, str]:
        if self.live:
            try:
                return {o["order_id"]: o.get("status", "") for o in (self._kite().orders() or [])}
            except Exception:
                log.exception("kite.orders() failed")
                return {}
        # dry-run: simulate fills from the latest quote before reporting status
        if self.quote_fn:
            for b in list(self._brackets.values()):
                self._sim_fill(b)
        return {oid: o["status"] for oid, o in self._sim_orders.items()}

    def _sim_fill(self, b: Bracket) -> None:
        """DRY-RUN only: mark sim orders filled when the simulated price crosses them."""
        try:
            px = float(self.quote_fn(b.symbol))  # type: ignore[misc]
        except Exception:
            return
        if px <= 0:
            return
        e = self._sim_orders.get(b.entry_id)
        if e and e["status"] == "OPEN" and px <= b.entry_price:   # limit BUY fills at/below entry
            e["status"] = _COMPLETE
        t = self._sim_orders.get(b.target_id)
        if t and t["status"] == "OPEN" and px >= b.target_price:  # target LIMIT sell
            t["status"] = _COMPLETE
        s = self._sim_orders.get(b.stop_id)
        if s and s["status"] == "OPEN" and px <= b.stop_price:    # SL-M trigger
            s["status"] = _COMPLETE

    # ── public API ──────────────────────────────────────────────────────────
    def open_bracket(self, symbol: str, quantity: int, entry_price: float,
                     stop_price: float, target_price: float) -> Optional[Bracket]:
        """Place the entry leg and start tracking. Returns None if a bracket for
        this symbol is already active (idempotent against re-ticks)."""
        with self._lock:
            existing = self._brackets.get(symbol)
            if existing and existing.state in (ENTRY_PENDING, IN_POSITION):
                return None
            b = Bracket(
                symbol=symbol, quantity=int(quantity),
                entry_price=round(float(entry_price), 2),
                stop_price=round(float(stop_price), 2),
                target_price=round(float(target_price), 2),
            )
            b.entry_id = self._place(symbol=symbol, txn=_BUY, qty=b.quantity,
                                     order_type=_LIMIT, price=b.entry_price)
            self._brackets[symbol] = b
            self._persist_snapshot_locked()
            log.info("bracket opened %s qty=%s entry=%s sl=%s tgt=%s live=%s",
                     symbol, b.quantity, b.entry_price, b.stop_price, b.target_price, self.live)
            return b

    def poll(self) -> None:
        """Advance every active bracket: place exits once entry fills, run OCO."""
        with self._lock:
            active = [b for b in self._brackets.values() if b.state in (ENTRY_PENDING, IN_POSITION)]
            if not active:
                return
            statuses = self._statuses()
            for b in active:
                try:
                    self._advance(b, statuses)
                except Exception:
                    log.exception("bracket advance failed %s", b.symbol)
            self._persist_snapshot_locked()

    def _advance(self, b: Bracket, statuses: Dict[str, str]) -> None:
        if b.state == ENTRY_PENDING:
            st = statuses.get(b.entry_id, "")
            if st == _COMPLETE:
                b.target_id = self._place(symbol=b.symbol, txn=_SELL, qty=b.quantity,
                                          order_type=_LIMIT, price=b.target_price)
                b.stop_id = self._place(symbol=b.symbol, txn=_SELL, qty=b.quantity,
                                        order_type=_SLM, trigger=b.stop_price)
                b.state = IN_POSITION
                log.info("ENTRY filled %s — exits placed target=%s stop=%s",
                         b.symbol, b.target_id, b.stop_id)
            elif st in _DEAD:
                b.state = FAILED
                b.note = f"entry {st}"
                log.warning("entry %s for %s", st, b.symbol)
        elif b.state == IN_POSITION:
            t_st = statuses.get(b.target_id, "")
            s_st = statuses.get(b.stop_id, "")
            if t_st == _COMPLETE:
                self._cancel(b.stop_id)
                b.state = DONE
                b.note = "target hit (+profit)"
                log.info("TARGET hit %s — stop cancelled", b.symbol)
            elif s_st == _COMPLETE:
                self._cancel(b.target_id)
                b.state = DONE
                b.note = "stop hit (loss capped)"
                log.info("STOP hit %s — target cancelled", b.symbol)

    def force_square_off(self) -> dict:
        """Cancel outstanding bracket legs and flatten tracked MIS positions.

        Called once near the end of the intraday session (default 15:15 IST).
        In live mode it sends MARKET SELL MIS orders for tracked symbols with
        positive net quantity. In dry-run it marks active brackets as DONE so the
        UI and open-position cap free up cleanly.
        """
        result = {"closed": 0, "cancelled": 0, "failures": []}
        with self._lock:
            active = [b for b in self._brackets.values() if b.state in (ENTRY_PENDING, IN_POSITION)]
            if not active:
                return result

            if not self.live:
                for b in active:
                    for oid in (b.entry_id, b.target_id, b.stop_id):
                        o = self._sim_orders.get(oid)
                        if o and o.get("status") == "OPEN":
                            o["status"] = "CANCELLED"
                            result["cancelled"] += 1
                    b.state = DONE
                    b.note = "force square-off simulated"
                    result["closed"] += 1
                self._persist_snapshot_locked()
                return result

            kite = self._kite()
            positions: dict[str, int] = {}
            try:
                for p in (kite.positions().get("net") or []):
                    sym = p.get("tradingsymbol")
                    qty = int(p.get("quantity") or 0)
                    if sym and qty > 0:
                        positions[sym] = qty
            except Exception as exc:
                result["failures"].append(f"positions: {exc}")
                log.exception("force square-off: positions failed")

            for b in active:
                for oid in (b.entry_id, b.target_id, b.stop_id):
                    try:
                        self._cancel(oid)
                        if oid:
                            result["cancelled"] += 1
                    except Exception as exc:
                        result["failures"].append(f"{b.symbol} cancel {oid}: {exc}")
                qty = positions.get(b.symbol, 0)
                if qty <= 0:
                    b.state = DONE
                    b.note = "force square-off: no live qty"
                    continue
                try:
                    oid = self._place(symbol=b.symbol, txn=_SELL, qty=qty, order_type=_MARKET)
                    b.state = DONE
                    b.note = f"force square-off market sell {oid}"
                    result["closed"] += 1
                except Exception as exc:
                    result["failures"].append(f"{b.symbol} square-off: {exc}")
                    log.exception("force square-off failed %s", b.symbol)
            self._persist_snapshot_locked()
        return result

    def snapshot(self) -> List[dict]:
        with self._lock:
            rows = [
                {
                    "symbol": b.symbol, "qty": b.quantity, "state": b.state,
                    "entry": b.entry_price, "stop": b.stop_price, "target": b.target_price,
                    "note": b.note,
                }
                for b in self._brackets.values()
            ]
        if rows:
            return rows
        try:
            from app.core.storage import storage

            return storage.get_runtime_state("brackets:snapshot", []) or []
        except Exception:
            return []

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for b in self._brackets.values() if b.state in (ENTRY_PENDING, IN_POSITION))

    def _persist_snapshot_locked(self) -> None:
        try:
            from app.core.storage import storage

            storage.set_runtime_state(
                "brackets:snapshot",
                [
                    {
                        "symbol": b.symbol,
                        "qty": b.quantity,
                        "state": b.state,
                        "entry": b.entry_price,
                        "stop": b.stop_price,
                        "target": b.target_price,
                        "note": b.note,
                    }
                    for b in self._brackets.values()
                ],
            )
        except Exception:
            return


# ── process-wide singleton ────────────────────────────────────────────────────
_MGR_LOCK = threading.Lock()
_MGR: Optional[BracketManager] = None


def _default_quote_fn(symbol: str) -> float:
    from app.core.market_data import market_data
    qm = market_data.get_quote_full([symbol]) or {}
    q = qm.get(symbol) or {}
    return float(q.get("ltp") or 0.0)


def get_bracket_manager() -> BracketManager:
    """Singleton bracket manager. Mode follows settings.ENABLE_LIVE_TRADING."""
    global _MGR
    with _MGR_LOCK:
        if _MGR is None:
            from app.core.config import settings
            live = bool(settings.ENABLE_LIVE_TRADING)
            _MGR = BracketManager(kite=None, live=live, quote_fn=_default_quote_fn)
            log.info("BracketManager created live=%s", live)
        return _MGR
