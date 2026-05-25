"""Agent 1 — Data Agent.

Polls the broker for current quotes on the watchlist (NIFTY 100/200 subset
of the configured universe) and publishes a {symbol: quote} dict to the bus
key "market_data". All downstream signal agents read from this single source.
"""
from __future__ import annotations

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import load_nifty500_symbols
from app.core.zerodha_auth import zerodha_auth


class DataAgent(BaseAgent):
    name = "agent01_data"
    description = "Polls Kite for quotes on the NIFTY 100/200 watchlist and publishes to the bus."
    interval_seconds = 5.0
    inputs: list[str] = []
    outputs = ["market_data"]
    skills = [
        {"id": "fetch_quotes", "description": "Pull bid/ask/LTP for up to 40 symbols per tick."},
        {"id": "rotate_watchlist", "description": "Load and cache the NIFTY 500 symbol universe."},
    ]
    uses_llm = False

    def __init__(self, bus, max_symbols: int = 40) -> None:
        super().__init__(bus)
        self.max_symbols = max_symbols
        self._watchlist: list[str] = []

    def _watch(self) -> list[str]:
        if not self._watchlist:
            self._watchlist = load_nifty500_symbols()[: self.max_symbols]
        return self._watchlist

    def run_once(self) -> AgentResult:
        symbols = self._watch()
        if not symbols:
            return AgentResult(self.name, False, error="empty watchlist")
        kite = zerodha_auth.get_kite_instance()
        keys = [f"NSE:{s}" for s in symbols]
        quotes = kite.quote(keys) or {}
        cleaned = {k.split(":", 1)[1]: v for k, v in quotes.items()}
        self.bus.set("market_data", cleaned)
        return AgentResult(self.name, True, payload={"symbols": len(cleaned)})
