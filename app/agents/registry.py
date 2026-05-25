"""Static registry of the 12 agent classes for card discovery.

Importing this module is side-effect free — no threads are started. The
FastAPI server uses it to serve /agents and /agents/{name}/card.json
without instantiating the running orchestrator.
"""
from __future__ import annotations

from app.agents._base import BaseAgent
from app.agents.agent01_data import DataAgent
from app.agents.agent02_feature import FeatureAgent
from app.agents.agent03_trend import TrendAgent
from app.agents.agent04_breakout import BreakoutAgent
from app.agents.agent05_pullback import PullbackAgent
from app.agents.agent06_decision import DecisionAgent
from app.agents.agent07_risk import RiskAgent
from app.agents.agent08_execution import ExecutionAgent
from app.agents.agent09_sentiment import SentimentAgent
from app.agents.agent10_ml_prediction import MLPredictionAgent
from app.agents.agent11_monitoring import MonitoringAgent
from app.agents.agent12_portfolio import PortfolioAgent

AGENT_CLASSES: list[type[BaseAgent]] = [
    DataAgent,
    FeatureAgent,
    TrendAgent,
    BreakoutAgent,
    PullbackAgent,
    DecisionAgent,
    RiskAgent,
    ExecutionAgent,
    SentimentAgent,
    MLPredictionAgent,
    MonitoringAgent,
    PortfolioAgent,
]

AGENT_BY_NAME: dict[str, type[BaseAgent]] = {cls.name: cls for cls in AGENT_CLASSES}


def system_card() -> dict:
    """Top-level card describing the whole 12-agent system."""
    return {
        "name": "nifty500_intraday_agent_system",
        "version": "1.0.0",
        "description": (
            "12 proactive agents for NIFTY 500 intraday trading. Reflex/utility "
            "patterns; LLM used only by agent09_sentiment via a single shared key."
        ),
        "mode": "proactive",
        "trade_mandate": {
            "min_profit_target_pct": 10.0,
            "max_stop_loss_pct": 9.5,
            "min_signal_confidence": 75,
            "confluence_required": 2,
        },
        "llm": {"single_key": True, "callers_allowed": ["agent09_sentiment"]},
        "agents": [
            {"name": cls.name, "description": cls.description, "card_url": f"/agents/{cls.name}/card.json"}
            for cls in AGENT_CLASSES
        ],
    }
