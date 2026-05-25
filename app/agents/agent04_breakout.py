"""Agent 4 — Breakout Signal Agent.

Opening-range breakout: votes BUY when price closes above the first-15min
high on above-average volume. Delegates to the existing ORB rule in
intraday_agent so signal semantics stay identical to the live engine.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import _try_opening_range_breakout, session_capital


class BreakoutAgent(BaseAgent):
    name = "agent04_breakout"
    description = "Signal: BUY on opening-range breakout above first-15min high on above-average volume."
    interval_seconds = 10.0
    inputs = ["features"]
    outputs = ["signal_breakout"]
    skills = [
        {"id": "orb_detect", "description": "Detect first-15min range break."},
        {"id": "volume_confirm", "description": "Require vol > avg before voting BUY."},
    ]
    uses_llm = False

    def run_once(self) -> AgentResult:
        features = self.bus.get("features", max_age_s=30.0) or {}
        if not features:
            return AgentResult(self.name, False, error="no features")
        capital = session_capital()
        votes: dict[str, dict] = {}
        for sym, ctx in features.items():
            decision = _try_opening_range_breakout(sym, ctx, capital)
            if decision is not None:
                votes[sym] = {
                    "vote": "BUY",
                    "confidence": decision.confidence,
                    "entry": decision.entry_price,
                    "stop": decision.stop_loss,
                    "target": decision.target,
                }
        self.bus.set("signal_breakout", votes)
        return AgentResult(self.name, True, payload={"buys": len(votes)})
