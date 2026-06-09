"""Agent 7 — Risk Agent.

Validates each decision against RiskEngine + a combined institutional-spike
filter (vol > 5x avg AND |return| > 1.5*ATR over the last bar). Only
decisions clearing all checks are published to bus["approved_decision"].
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import session_capital
from app.core.risk_engine import RiskEngine


class RiskAgent(BaseAgent):
    name = "agent07_risk"
    description = "Validates each decision via RiskEngine + institutional-spike veto; emits identified risks to bus['risk_alerts']."
    interval_seconds = 15.0
    inputs = ["decision", "features"]
    outputs = ["approved_decision", "risk_alerts"]
    skills = [
        {"id": "risk_engine_validate", "description": "Position cap, daily loss cap, consecutive loss check."},
        {"id": "institutional_spike_filter", "description": "Skip if vol > 5x avg AND |return| > 1.5*ATR."},
        {"id": "publish_risk_alerts", "description": "List of {symbol, reason, severity} for every rejected trade."},
    ]
    uses_llm = False

    def __init__(self, bus, risk_engine: RiskEngine | None = None) -> None:
        super().__init__(bus)
        self.risk = risk_engine or RiskEngine()

    def _institutional_spike(self, ctx: dict | None) -> bool:
        if not ctx:
            return False
        vol_ratio = float(ctx.get("vol_ratio") or 0.0)
        atr = float(ctx.get("atr") or 0.0)
        last_return = abs(float(ctx.get("last_return") or 0.0))
        if atr <= 0:
            return False
        return vol_ratio > 5.0 and last_return > 1.5 * atr

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
        features = self.bus.get("features", max_age_s=30.0) or {}
        approved: dict[str, dict] = {}
        alerts: list[dict] = []
        if not decisions:
            self.bus.set("approved_decision", approved)
            self.bus.set("risk_alerts", alerts)
            return AgentResult(self.name, True, payload={"approved": 0, "alerts": 0})
        capital = session_capital()
        open_syms = self._open_symbols()
        max_open = self.risk.config.max_open_positions
        slots = max_open - len(open_syms)
        for sym, dec in decisions.items():
            if sym in open_syms:
                continue  # already holding / pending this name — entry is idempotent
            entry, stop = dec.get("entry"), dec.get("stop")
            if not entry or not stop or entry <= stop:
                alerts.append({"symbol": sym, "severity": "high", "reason": "invalid entry/stop", "decision": dec})
                continue
            if self._institutional_spike(features.get(sym)):
                alerts.append({"symbol": sym, "severity": "high", "reason": "institutional volume spike — possible fake breakout"})
                continue
            sl_frac = (entry - stop) / entry
            notional = entry * max(1, int(capital * 0.35 / entry))
            ok, msg = self.risk.can_place_trade(notional, assumed_sl_pct=sl_frac)
            if not ok:
                alerts.append({"symbol": sym, "severity": "medium", "reason": msg, "notional": notional})
                continue
            if slots <= 0:
                alerts.append({
                    "symbol": sym,
                    "severity": "medium",
                    "reason": f"Max open positions ({max_open}) reached — {len(open_syms)} already open/pending",
                    "notional": notional,
                })
                continue
            approved[sym] = {**dec, "notional": notional, "risk_msg": msg}
            slots -= 1
        self.bus.set("approved_decision", approved)
        self.bus.set("risk_alerts", alerts)
        return AgentResult(
            self.name,
            True,
            payload={"approved": len(approved), "alerts": len(alerts), "open": len(open_syms), "max_open": max_open},
        )
