"""Agent 8 — Execution Agent.

Reads bus["approved_decision"] and places bracket orders via LiveBroker.
Idempotent: tracks placed symbols in bus["executed_today"] so re-ticks
of the same approval don't double-fire. Honors a hard auto_execute flag
on the bus (default False) so the agent loop alone never sends orders.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.live_broker import LiveBroker


class ExecutionAgent(BaseAgent):
    name = "agent08_execution"
    description = "Places bracket orders via Kite for approved decisions; idempotent; gated by bus['auto_execute']."
    interval_seconds = 15.0
    inputs = ["approved_decision", "auto_execute"]
    outputs = ["executed_today"]
    skills = [
        {"id": "place_bracket_order", "description": "Entry + SL + target on one call."},
        {"id": "idempotent_dispatch", "description": "Tracks placed symbols so re-ticks don't double-fire."},
    ]
    uses_llm = False

    def __init__(self, bus) -> None:
        super().__init__(bus)
        self._broker: LiveBroker | None = None

    def _get_broker(self) -> LiveBroker | None:
        if self._broker is not None:
            return self._broker
        try:
            self._broker = LiveBroker()
            return self._broker
        except Exception:
            return None  # awaiting kite login

    def run_once(self) -> AgentResult:
        approved = self.bus.get("approved_decision", max_age_s=30.0) or {}
        if not approved:
            return AgentResult(self.name, True, payload={"placed": 0})
        if not bool(self.bus.get("auto_execute") or False):
            return AgentResult(self.name, True, payload={"placed": 0, "skipped": "auto_execute_off"})
        broker = self._get_broker()
        if broker is None:
            return AgentResult(self.name, False, error="awaiting kite login")
        done: set[str] = set(self.bus.get("executed_today") or set())
        placed = 0
        for sym, dec in approved.items():
            if sym in done:
                continue
            entry, stop, tgt = dec.get("entry"), dec.get("stop"), dec.get("target")
            notional = dec.get("notional") or 0
            qty = max(1, int(notional / entry)) if entry else 0
            if not (entry and stop and tgt and qty):
                continue
            broker.place_bracket_buy(
                symbol=sym,
                quantity=qty,
                limit_price=float(entry),
                stop_loss_price=float(stop),
                target_price=float(tgt),
            )
            done.add(sym)
            placed += 1
        self.bus.set("executed_today", done)
        return AgentResult(self.name, True, payload={"placed": placed})
