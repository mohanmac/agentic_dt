"""Agent 3 — Trend Signal Agent.

Uses 1-hour bias on NIFTY as a higher-timeframe filter, then publishes
per-symbol BUY/HOLD votes when the symbol's last close is above its 20-bar
EMA AND the index bias is bullish. Survives single-print spoofing because
the 1H bias is computed across many bars.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import _nifty_trend_bullish


class TrendAgent(BaseAgent):
    name = "agent03_trend"
    description = "Signal: BUY if 1H NIFTY bias bullish AND last close > EMA20. Reflex rule."
    interval_seconds = 10.0
    inputs = ["features"]
    outputs = ["signal_trend"]
    skills = [
        {"id": "trend_vote", "description": "Per-symbol BUY/HOLD vote with confidence."},
        {"id": "regime_filter", "description": "Uses 1H index bias as macro gate."},
    ]
    uses_llm = False

    def run_once(self) -> AgentResult:
        features = self.bus.get("features", max_age_s=30.0) or {}
        if not features:
            return AgentResult(self.name, False, error="no features")
        bias_ok, reason = _nifty_trend_bullish()
        votes: dict[str, dict] = {}
        for sym, ctx in features.items():
            close = ctx.get("close")
            ema20 = ctx.get("ema20")
            if close is None or ema20 is None:
                continue
            vote = "BUY" if bias_ok and close > ema20 else "HOLD"
            votes[sym] = {"vote": vote, "confidence": 65 if vote == "BUY" else 0, "reason": reason}
        self.bus.set("signal_trend", votes)
        buys = sum(1 for v in votes.values() if v["vote"] == "BUY")
        return AgentResult(self.name, True, payload={"buys": buys, "total": len(votes)})
