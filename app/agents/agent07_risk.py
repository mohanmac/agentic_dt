"""Agent 7 — Risk Agent.

Applies essential guardrails only:
    - valid entry/stop/target
    - stop-loss strictly below 10%
    - target at least 10%
    - open-position and max-trade caps
Publishes approvals + actionable PREF feedback to the bus.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import session_capital
from app.core.risk_engine import RiskEngine


class RiskAgent(BaseAgent):
    name = "agent07_risk"
    description = "Applies essential intraday guardrails (SL <10%, target >=10%, trade caps) and emits PREF feedback."
    interval_seconds = 15.0
    inputs = ["decision", "features", "executed_today"]
    outputs = ["approved_decision", "risk_alerts", "pref_feedback"]
    skills = [
        {"id": "essential_guardrails", "description": "SL <10% and target >=10% with valid entry/stop/target."},
        {"id": "capacity_limits", "description": "Enforces max open positions and max trades/day."},
        {"id": "publish_risk_alerts", "description": "List of {symbol, reason, severity} for every rejected trade."},
    ]
    uses_llm = False

    def __init__(self, bus, risk_engine: RiskEngine | None = None) -> None:
        super().__init__(bus)
        self.risk = risk_engine or RiskEngine()

    def _open_symbols(self) -> set[str]:
        """Symbols we currently hold or have a pending entry for.

        Combines two sources so the open-position cap holds even before the
        30s portfolio poll catches up to a freshly fired order:
          • BracketManager.snapshot() — brackets this bot opened that are
            ENTRY_PENDING or IN_POSITION (updated synchronously on placement,
            and dropped once an exit fills, so closed trades free a slot).
          • bus['portfolio'] — broker net positions with non-zero qty, which
            also covers positions opened outside the bracket flow.
        """
        syms: set[str] = set()
        try:
            from app.core.bracket_manager import (
                ENTRY_PENDING,
                IN_POSITION,
                get_bracket_manager,
            )

            for b in get_bracket_manager().snapshot():
                if b.get("state") in (ENTRY_PENDING, IN_POSITION):
                    syms.add(b.get("symbol"))
        except Exception:
            pass  # bracket manager unavailable (e.g. awaiting login) — fall back to portfolio
        portfolio = self.bus.get("portfolio", max_age_s=120.0) or {}
        for p in portfolio.get("positions") or []:
            if int(p.get("qty") or 0) != 0:
                syms.add(p.get("symbol"))
        return {s for s in syms if s}

    def run_once(self) -> AgentResult:
        decisions = self.bus.get("decision", max_age_s=30.0) or {}
        approved: dict[str, dict] = {}
        alerts: list[dict] = []
        feedback: dict[str, dict] = {}
        if not decisions:
            self.bus.set("approved_decision", approved)
            self.bus.set("risk_alerts", alerts)
            self.bus.set("pref_feedback", feedback)
            return AgentResult(self.name, True, payload={"approved": 0, "alerts": 0, "task": "awaiting_decision"})
        capital = session_capital()
        open_syms = self._open_symbols()
        max_open = self.risk.config.max_open_positions
        slots = max_open - len(open_syms)
        executed_today = set(self.bus.get("executed_today") or set())
        trades_used = len(executed_today)
        trades_left = max(0, self.risk.config.max_trades_per_day - trades_used)
        for sym, dec in decisions.items():
            if trades_left <= 0:
                alerts.append({
                    "symbol": sym,
                    "severity": "medium",
                    "reason": f"max trades/day reached ({self.risk.config.max_trades_per_day})",
                })
                feedback[sym] = {"status": "rejected", "reason": "daily_trade_cap"}
                continue
            if sym in open_syms:
                continue  # already holding / pending this name — entry is idempotent
            entry, stop = dec.get("entry"), dec.get("stop")
            target = dec.get("target")
            if not entry or not stop or entry <= stop:
                alerts.append({"symbol": sym, "severity": "high", "reason": "invalid entry/stop", "decision": dec})
                feedback[sym] = {"status": "rejected", "reason": "invalid_entry_stop"}
                continue
            if not target or target <= entry:
                alerts.append({"symbol": sym, "severity": "high", "reason": "invalid target", "decision": dec})
                feedback[sym] = {"status": "rejected", "reason": "invalid_target"}
                continue
            sl_frac = (entry - stop) / entry
            tp_frac = (target - entry) / entry
            if sl_frac >= 0.10:
                alerts.append({"symbol": sym, "severity": "high", "reason": "stop loss must be <10%"})
                feedback[sym] = {"status": "rejected", "reason": "sl_ge_10pct", "sl_pct": round(sl_frac * 100, 2)}
                continue
            if tp_frac < 0.10:
                alerts.append({"symbol": sym, "severity": "high", "reason": "target must be >=10%"})
                feedback[sym] = {"status": "rejected", "reason": "tp_lt_10pct", "tp_pct": round(tp_frac * 100, 2)}
                continue
            notional = entry * max(1, int(capital * 0.35 / entry))
            if slots <= 0:
                alerts.append({
                    "symbol": sym,
                    "severity": "medium",
                    "reason": f"Max open positions ({max_open}) reached — {len(open_syms)} already open/pending",
                    "notional": notional,
                })
                feedback[sym] = {"status": "rejected", "reason": "max_open_positions"}
                continue
            approved[sym] = {
                **dec,
                "notional": notional,
                "risk_msg": "essential_guardrails_passed",
                "sl_pct": round(sl_frac * 100, 2),
                "tp_pct": round(tp_frac * 100, 2),
            }
            feedback[sym] = {
                "status": "approved",
                "planning": "Proceed to execution agent for one-shot bracket order.",
                "reasoning": f"SL={sl_frac*100:.2f}% (<10), TP={tp_frac*100:.2f}% (>=10)",
                "feedback": "Track order placement/fill; re-evaluate next cycle.",
            }
            slots -= 1
            trades_left -= 1
        self.bus.set("approved_decision", approved)
        self.bus.set("risk_alerts", alerts)
        self.bus.set("pref_feedback", feedback)
        return AgentResult(
            self.name,
            True,
            payload={
                "approved": len(approved),
                "alerts": len(alerts),
                "open": len(open_syms),
                "max_open": max_open,
                "task": "risk_gated",
            },
        )
