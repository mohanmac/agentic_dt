"""Orchestrator for the 12-agent NIFTY 500 trading system.

Builds the bus, instantiates all 12 agents, starts them in dependency order,
and exposes a single Orchestrator.shutdown() for graceful stop. Import this
module and call run() from a script or from the Streamlit dashboard.

  from app.agents.orchestrator import Orchestrator
  orch = Orchestrator(); orch.start_all()
  ...
  orch.shutdown()
"""
from __future__ import annotations

import logging
import signal
import time

from app.agents._bus import AgentBus
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

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self) -> None:
        self.bus = AgentBus()
        self.agents = [
            DataAgent(self.bus),
            FeatureAgent(self.bus),
            TrendAgent(self.bus),
            BreakoutAgent(self.bus),
            PullbackAgent(self.bus),
            DecisionAgent(self.bus),
            RiskAgent(self.bus),
            ExecutionAgent(self.bus),
            SentimentAgent(self.bus),
            MLPredictionAgent(self.bus),
            MonitoringAgent(self.bus),
            PortfolioAgent(self.bus),
        ]

    def start_all(self) -> None:
        # agent08 stays disarmed: the TradingEngine is the sole order executor, so
        # leaving bus["auto_execute"] False prevents the agent pipeline from placing
        # a DUPLICATE bracket order for the same setup. The 12 agents run for
        # monitoring/signals/risk-alerts only.
        self.bus.set("auto_execute", False)
        for agent in self.agents:
            agent.start()
        log.info("orchestrator_started agents=%d", len(self.agents))

    def shutdown(self) -> None:
        for agent in self.agents:
            agent.stop()
        log.info("orchestrator_stopped")

    def set_auto_execute(self, enabled: bool) -> None:
        self.bus.set("auto_execute", bool(enabled))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    orch = Orchestrator()

    def _handle_sig(*_):
        orch.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    orch.start_all()
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()
