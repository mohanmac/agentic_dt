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
        for sym, dec in decisions.items():
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
            if ok:
                approved[sym] = {**dec, "notional": notional, "risk_msg": msg}
            else:
                alerts.append({"symbol": sym, "severity": "medium", "reason": msg, "notional": notional})
        self.bus.set("approved_decision", approved)
        self.bus.set("risk_alerts", alerts)
        return AgentResult(self.name, True, payload={"approved": len(approved), "alerts": len(alerts)})
