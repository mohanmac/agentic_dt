"""Agent 5 — Pullback (VWAP) Signal Agent.

Buys dips holding the VWAP in an established uptrend — i.e. rides
institutional execution flow rather than fighting it. Reuses the live
engine's VWAP-pullback rule for identical semantics.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import _try_vwap_pullback


class PullbackAgent(BaseAgent):
    name = "agent05_pullback"
    description = "Signal: BUY on VWAP pullback in an established uptrend — rides institutional flow."
    interval_seconds = 10.0
    inputs = ["features"]
    outputs = ["signal_pullback"]
    skills = [
        {"id": "vwap_pullback_detect", "description": "Detect price hold/discount to VWAP."},
        {"id": "bullish_bar_confirm", "description": "Confirm with a bullish candle."},
    ]
    uses_llm = False

    def run_once(self) -> AgentResult:
        features = self.bus.get("features", max_age_s=30.0) or {}
        if not features:
            return AgentResult(self.name, False, error="no features")
        votes: dict[str, dict] = {}
        for sym, ctx in features.items():
            decision = _try_vwap_pullback(sym, ctx)
            if decision is not None:
                votes[sym] = {
                    "vote": "BUY",
                    "confidence": decision.confidence,
                    "entry": decision.entry_price,
                    "stop": decision.stop_loss,
                    "target": decision.target,
                }
        self.bus.set("signal_pullback", votes)
        return AgentResult(self.name, True, payload={"buys": len(votes)})
