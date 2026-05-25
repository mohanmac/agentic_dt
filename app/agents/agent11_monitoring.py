"""Agent 11 — Monitoring Agent.

Heartbeats every other agent: reads last_result:<name> entries from the bus,
computes staleness, and publishes a single bus["health"] dict for the UI
and external dashboards. Stale > 3x the agent's interval is flagged DEGRADED.
"""
from __future__ import annotations

from datetime import datetime

from app.agents._base import AgentResult, BaseAgent

WATCHED = [
    ("agent01_data", 5.0),
    ("agent02_feature", 5.0),
    ("agent03_trend", 10.0),
    ("agent04_breakout", 10.0),
    ("agent05_pullback", 10.0),
    ("agent06_decision", 15.0),
    ("agent07_risk", 15.0),
    ("agent08_execution", 15.0),
    ("agent09_sentiment", 300.0),
    ("agent10_ml_prediction", 30.0),
    ("agent12_portfolio", 30.0),
]


class MonitoringAgent(BaseAgent):
    name = "agent11_monitoring"
    description = "Heartbeats all other agents; flags DEGRADED when stale > 3x their interval."
    interval_seconds = 10.0
    inputs = ["last_result:*"]
    outputs = ["health"]
    skills = [
        {"id": "heartbeat", "description": "Per-agent status snapshot."},
        {"id": "stale_detection", "description": "DEGRADED if last tick > 3x interval old."},
    ]
    uses_llm = False

    def run_once(self) -> AgentResult:
        now = datetime.now()
        health: dict[str, dict] = {}
        degraded = 0
        for agent_name, interval in WATCHED:
            entry = self.bus.get(f"last_result:{agent_name}")
            if entry is None:
                health[agent_name] = {"status": "NEVER_RAN"}
                degraded += 1
                continue
            stale_s = (now - entry.ts).total_seconds()
            status = "OK" if entry.ok and stale_s < 3 * interval else "DEGRADED"
            if status == "DEGRADED":
                degraded += 1
            health[agent_name] = {
                "status": status,
                "stale_s": round(stale_s, 1),
                "ok": entry.ok,
                "error": entry.error,
            }
        self.bus.set("health", health)
        return AgentResult(self.name, True, payload={"degraded": degraded, "total": len(WATCHED)})
