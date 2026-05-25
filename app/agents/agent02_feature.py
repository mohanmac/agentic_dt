"""Agent 2 — Feature Agent.

Reads raw quotes from bus["market_data"] and emits a per-symbol feature
vector to bus["features"]. Uses _build_5m_context() from intraday_agent
which already computes RSI/EMA/VWAP/ATR/volume-ratio from 5m bars.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import _build_5m_context


class FeatureAgent(BaseAgent):
    name = "agent02_feature"
    description = "Computes RSI/EMA20/EMA50/VWAP/ATR/vol_ratio per symbol from 5-minute bars."
    interval_seconds = 5.0
    inputs = ["market_data"]
    outputs = ["features"]
    skills = [
        {"id": "compute_features", "description": "Vectorised technical indicators per symbol."},
    ]
    uses_llm = False

    def run_once(self) -> AgentResult:
        quotes = self.bus.get("market_data", max_age_s=15.0)
        if not quotes:
            return AgentResult(self.name, False, error="no fresh market_data")
        features: dict[str, dict] = {}
        for symbol, quote in quotes.items():
            ctx = _build_5m_context(symbol, quote or {})
            if ctx is not None:
                features[symbol] = ctx
        self.bus.set("features", features)
        return AgentResult(self.name, True, payload={"with_features": len(features)})
