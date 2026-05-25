"""Agent 10 — ML Prediction Agent.

Lightweight logistic-regression-style scorer over the feature vector. Emits
a [0, 100] probability of upside per symbol. Replace _predict() with a real
trained model later — the weights below are deliberately conservative so
the Decision Agent isn't dominated by an unvetted model.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent


WEIGHTS = {
    "rsi_norm": 0.20,        # (rsi - 50) / 50
    "ema_gap": 0.25,         # (close - ema20) / ema20
    "vwap_gap": 0.20,        # (close - vwap) / vwap
    "vol_ratio": 0.20,       # bounded to [0, 3]
    "rs_vs_nifty": 0.15,     # relative return vs index
}


class MLPredictionAgent(BaseAgent):
    name = "agent10_ml_prediction"
    description = "Sigmoid scorer over RSI/EMA/VWAP/vol/RS features. No LLM. Soft input to Decision Agent."
    interval_seconds = 30.0
    inputs = ["features"]
    outputs = ["ml_prediction"]
    skills = [
        {"id": "predict_upside_prob", "description": "Logistic-style probability of upside, range [0, 100]."},
    ]
    uses_llm = False

    def _predict(self, ctx: dict) -> float:
        try:
            close = float(ctx["close"]); ema20 = float(ctx["ema20"]); vwap = float(ctx["vwap"])
        except (KeyError, TypeError, ValueError):
            return 0.0
        feats = {
            "rsi_norm": (float(ctx.get("rsi") or 50) - 50) / 50.0,
            "ema_gap": (close - ema20) / ema20 if ema20 else 0.0,
            "vwap_gap": (close - vwap) / vwap if vwap else 0.0,
            "vol_ratio": min(3.0, float(ctx.get("vol_ratio") or 1.0)) / 3.0,
            "rs_vs_nifty": float(ctx.get("rs_vs_nifty") or 0.0),
        }
        z = sum(WEIGHTS[k] * v for k, v in feats.items())
        prob = 1.0 / (1.0 + pow(2.71828, -3.0 * z))  # sigmoid
        return round(100.0 * prob, 1)

    def run_once(self) -> AgentResult:
        features = self.bus.get("features", max_age_s=60.0) or {}
        scored = {sym: {"score": self._predict(ctx)} for sym, ctx in features.items()}
        self.bus.set("ml_prediction", scored)
        return AgentResult(self.name, True, payload={"scored": len(scored)})
