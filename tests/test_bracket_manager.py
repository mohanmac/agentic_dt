"""Tests for BracketManager — the supported-order-type replacement for the
discontinued Zerodha Bracket Order (VARIETY_BO).

Exercises the LIVE code path against a FakeKite so we assert the exact order
parameters and the OCO exit lifecycle without touching a real account.
"""
from app.core.bracket_manager import (
    BracketManager,
    ENTRY_PENDING,
    IN_POSITION,
    DONE,
    FAILED,
)


class FakeKite:
    """Records orders and lets a test script their statuses."""

    def __init__(self):
        self.placed = []          # list of kwargs dicts
        self.cancelled = []       # list of order_ids
        self._status = {}         # order_id -> status
        self._seq = 0

    def place_order(self, **kwargs):
        self._seq += 1
        oid = f"OID{self._seq}"
        self.placed.append({"order_id": oid, **kwargs})
        self._status[oid] = "OPEN"
        return oid

    def cancel_order(self, variety, order_id):
        self.cancelled.append(order_id)
        self._status[order_id] = "CANCELLED"

    def orders(self):
        return [{"order_id": oid, "status": st} for oid, st in self._status.items()]

    # test helpers
    def set_status(self, order_id, status):
        self._status[order_id] = status


def _mgr():
    k = FakeKite()
    return BracketManager(kite=k, live=True), k


def test_entry_uses_supported_order_type_not_bo():
    mgr, k = _mgr()
    b = mgr.open_bracket("ACME", quantity=3, entry_price=100.0, stop_price=91.0, target_price=110.0)
    assert b is not None and b.state == ENTRY_PENDING
    assert len(k.placed) == 1
    entry = k.placed[0]
    # Supported regular MIS LIMIT buy — never the dead bracket variety.
    assert entry["variety"] == "regular"
    assert entry["product"] == "MIS"
    assert entry["order_type"] == "LIMIT"
    assert entry["transaction_type"] == "BUY"
    assert entry["quantity"] == 3
    assert entry["price"] == 100.0
    assert "squareoff" not in entry and "stoploss" not in entry  # no BO params


def test_exits_placed_only_after_entry_fills():
    mgr, k = _mgr()
    b = mgr.open_bracket("ACME", 3, 100.0, 91.0, 110.0)
    # Entry still OPEN → no exits yet.
    mgr.poll()
    assert len(k.placed) == 1
    assert b.state == ENTRY_PENDING
    # Fill the entry → poll places target (LIMIT) + stop (SL-M).
    k.set_status(b.entry_id, "COMPLETE")
    mgr.poll()
    assert b.state == IN_POSITION
    assert len(k.placed) == 3
    target = next(o for o in k.placed if o["order_id"] == b.target_id)
    stop = next(o for o in k.placed if o["order_id"] == b.stop_id)
    assert target["transaction_type"] == "SELL" and target["order_type"] == "LIMIT"
    assert target["price"] == 110.0
    assert stop["transaction_type"] == "SELL" and stop["order_type"] == "SL-M"
    assert stop["trigger_price"] == 91.0
    assert stop["product"] == "MIS"


def test_oco_target_hit_cancels_stop():
    mgr, k = _mgr()
    b = mgr.open_bracket("ACME", 3, 100.0, 91.0, 110.0)
    k.set_status(b.entry_id, "COMPLETE")
    mgr.poll()                       # places exits
    k.set_status(b.target_id, "COMPLETE")
    mgr.poll()                       # target hit
    assert b.state == DONE
    assert b.stop_id in k.cancelled  # sibling stop cancelled
    assert b.target_id not in k.cancelled


def test_oco_stop_hit_cancels_target():
    mgr, k = _mgr()
    b = mgr.open_bracket("ACME", 3, 100.0, 91.0, 110.0)
    k.set_status(b.entry_id, "COMPLETE")
    mgr.poll()
    k.set_status(b.stop_id, "COMPLETE")
    mgr.poll()
    assert b.state == DONE
    assert b.target_id in k.cancelled
    assert b.stop_id not in k.cancelled


def test_rejected_entry_marks_failed_no_exits():
    mgr, k = _mgr()
    b = mgr.open_bracket("ACME", 3, 100.0, 91.0, 110.0)
    k.set_status(b.entry_id, "REJECTED")
    mgr.poll()
    assert b.state == FAILED
    assert len(k.placed) == 1        # never placed exits


def test_open_bracket_is_idempotent_per_symbol():
    mgr, k = _mgr()
    first = mgr.open_bracket("ACME", 3, 100.0, 91.0, 110.0)
    dup = mgr.open_bracket("ACME", 3, 100.0, 91.0, 110.0)
    assert first is not None and dup is None
    assert len(k.placed) == 1


def test_dry_run_simulates_full_cycle_without_kite():
    # No kite at all; price function drives simulated fills.
    price = {"ACME": 100.0}
    mgr = BracketManager(kite=None, live=False, quote_fn=lambda s: price[s])
    b = mgr.open_bracket("ACME", 3, 100.0, 91.0, 110.0)
    mgr.poll()                       # px=100 <= entry 100 → entry fills, exits placed
    assert b.state == IN_POSITION
    price["ACME"] = 111.0            # cross the target
    mgr.poll()
    assert b.state == DONE and "target" in b.note
