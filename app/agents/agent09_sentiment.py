"""Agent 9 — News / Sentiment Agent.

The ONLY agent permitted to call the LLM (see app/agents/_llm.py). Periodically
scores recent headlines for each symbol; output range is [-1, +1] where +1 is
strongly bullish. The Decision Agent uses this as a soft multiplier. Returns
0.0 if no headlines are buffered or the LLM is unavailable so the pipeline
never blocks on this advanced agent.
"""
from __future__ import annotations

import logging

from app.agents._base import AgentResult, BaseAgent
from app.agents._llm import llm_generate, llm_health

log = logging.getLogger(__name__)

PROMPT = (
    "Score the following Indian-market news for {symbol} on a scale from -1 "
    "(strongly bearish) to +1 (strongly bullish). Reply with just the number.\n\n"
    "Headlines:\n{headlines}"
)


class SentimentAgent(BaseAgent):
    name = "agent09_sentiment"
    description = "ONLY agent that calls the LLM. Scores recent headlines per symbol in [-1, +1]."
    interval_seconds = 300.0  # 5 min — news doesn't move every tick
    inputs = ["features", "news:*"]
    outputs = ["sentiment"]
    skills = [
        {"id": "headline_sentiment", "description": "LLM scores recent headlines; range [-1, +1]."},
    ]
    uses_llm = True

    def _fetch_headlines(self, symbol: str) -> list[str]:
        feed = self.bus.get(f"news:{symbol}") or []
        return list(feed)[:5]

    def _score(self, symbol: str, headlines: list[str]) -> float:
        if not headlines:
            return 0.0
        try:
            reply = llm_generate(self.name, PROMPT.format(symbol=symbol, headlines="\n".join(headlines)))
            return max(-1.0, min(1.0, float(str(reply).strip().split()[0])))
        except Exception as exc:
            log.debug("sentiment_llm_failed sym=%s err=%s", symbol, exc)
            return 0.0

    def run_once(self) -> AgentResult:
        if not llm_health():
            self.bus.set("sentiment", {})
            return AgentResult(self.name, True, payload={"scored": 0, "skipped": "llm_unhealthy"})
        features = self.bus.get("features", max_age_s=60.0) or {}
        scored: dict[str, dict] = {}
        for sym in features.keys():
            heads = self._fetch_headlines(sym)
            scored[sym] = {"score": self._score(sym, heads), "n_headlines": len(heads)}
        self.bus.set("sentiment", scored)
        return AgentResult(self.name, True, payload={"scored": len(scored)})
