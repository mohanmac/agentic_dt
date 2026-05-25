"""Agent 12 — Portfolio Agent.

Polls open positions + margins from the broker and publishes a single
bus["portfolio"] snapshot: net exposure, sector weights (where derivable),
unrealised PnL, and remaining buying power. Independent of the trade
pipeline so the UI's funds tile keeps refreshing even when scanning is paused.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.live_broker import LiveBroker
from app.core.zerodha_auth import zerodha_auth


class PortfolioAgent(BaseAgent):
    name = "agent12_portfolio"
    description = "Polls open positions + funds + unrealised PnL from Kite; refreshes the sidebar funds tile."
    interval_seconds = 30.0
    inputs: list[str] = []
    outputs = ["portfolio"]
    skills = [
        {"id": "fetch_positions", "description": "Live positions list."},
        {"id": "fetch_margins", "description": "Available cash, net, used."},
    ]
    uses_llm = False

    def __init__(self, bus) -> None:
        super().__init__(bus)
        self.broker = LiveBroker()

    def run_once(self) -> AgentResult:
        positions = self.broker.get_portfolio() or []
        kite = zerodha_auth.get_kite_instance()
        margins = kite.margins(segment="equity") or {}
        avail = (margins.get("available") or {})
        used = (margins.get("utilised") or {})
        unreal = sum(
            (getattr(p, "ltp", 0.0) - getattr(p, "avg_price", 0.0)) * getattr(p, "quantity", 0)
            for p in positions
        )
        snapshot = {
            "positions": [
                {
                    "symbol": getattr(p, "symbol", ""),
                    "qty": getattr(p, "quantity", 0),
                    "avg": getattr(p, "avg_price", 0.0),
                    "ltp": getattr(p, "ltp", 0.0),
                }
                for p in positions
            ],
            "open_count": len(positions),
            "unrealised_pnl": round(unreal, 2),
            "available_cash": float(avail.get("live_balance") or avail.get("cash") or 0.0),
            "net": float(margins.get("net") or 0.0),
            "used": float(used.get("debits") or 0.0),
        }
        self.bus.set("portfolio", snapshot)
        return AgentResult(self.name, True, payload={"open": snapshot["open_count"]})
