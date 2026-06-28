"""Agent 6 — Decision Agent.

Confluence-of-2 voting across Trend / Breakout / Pullback signal agents,
weighted by an optional ML score (agent10) and an optional sentiment score
(agent09). Emits one decision per symbol with combined confidence to
bus["decision"]; only symbols clearing min_confidence are published.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent


class DecisionAgent(BaseAgent):
    name = "agent06_decision"
    description = "Confluence-of-2 voting across trend/breakout/pullback with ML+sentiment weighting and PREF planning metadata."
    interval_seconds = 15.0
    inputs = ["signal_trend", "signal_breakout", "signal_pullback", "ml_prediction", "sentiment"]
    outputs = ["decision", "pref_plan"]
    skills = [
        {"id": "weighted_voting", "description": "Confluence ≥2 BUYs + score ≥75 confidence."},
        {"id": "soft_weight_ml", "description": "Add 15% ML score, 10% sentiment score."},
    ]
    uses_llm = False
    min_confidence = 68

    def _vote(self, store: dict | None, sym: str) -> tuple[bool, int]:
        if not store:
            return False, 0
        v = store.get(sym) or {}
        return v.get("vote") == "BUY", int(v.get("confidence") or 0)

    def run_once(self) -> AgentResult:
        trend = self.bus.get("signal_trend", max_age_s=30.0) or {}
        breakout = self.bus.get("signal_breakout", max_age_s=30.0) or {}
        pullback = self.bus.get("signal_pullback", max_age_s=30.0) or {}
        ml = self.bus.get("ml_prediction", max_age_s=60.0) or {}
        sentiment = self.bus.get("sentiment", max_age_s=600.0) or {}

        symbols = set(trend) | set(breakout) | set(pullback)
        decisions: dict[str, dict] = {}
        pref_plan: dict[str, dict] = {}
        for sym in symbols:
            votes = [self._vote(trend, sym), self._vote(breakout, sym), self._vote(pullback, sym)]
            buys = [(ok, conf) for ok, conf in votes if ok]
            if len(buys) < 2:
                continue
            base = sum(c for _, c in buys) / len(buys)
            ml_adj = float((ml.get(sym) or {}).get("score") or 0.0)
            sent_adj = float((sentiment.get(sym) or {}).get("score") or 0.0)
            score = base + 0.15 * ml_adj + 0.10 * sent_adj
            if score >= self.min_confidence:
                src_name = "breakout" if breakout.get(sym) else ("pullback" if pullback.get(sym) else "trend")
                src = breakout.get(sym) or pullback.get(sym) or trend.get(sym) or {}
                reasoning = [
                    f"confluence={len(buys)}/3",
                    f"base_conf={base:.1f}",
                    f"ml_adj={0.15 * ml_adj:.1f}",
                    f"sent_adj={0.10 * sent_adj:.1f}",
                    f"selected_strategy={src_name}",
                ]
                decisions[sym] = {
                    "vote": "BUY",
                    "confidence": round(score, 1),
                    "agree_count": len(buys),
                    "entry": src.get("entry"),
                    "stop": src.get("stop"),
                    "target": src.get("target"),
                    "pref": {
                        "planning": f"Plan BUY {sym} using {src_name} setup with confluence >=2.",
                        "reasoning": reasoning,
                        "feedback": "Wait for risk gate; if approved, execute once and monitor fill/SL/TGT.",
                    },
                }
                pref_plan[sym] = {
                    "planning": f"{sym}: execute {src_name} if risk passes",
                    "reasoning": reasoning,
                    "feedback": "Re-score next cycle if rejected.",
                }
        self.bus.set("decision", decisions)
        self.bus.set("pref_plan", pref_plan)
        return AgentResult(self.name, True, payload={"approved": len(decisions), "task": "planned_pref"})
