"""Agent 1 — Data Agent.

Polls the broker for current quotes on the watchlist (NIFTY 100/200 subset
of the configured universe) and publishes a {symbol: quote} dict to the bus
key "market_data". All downstream signal agents read from this single source.
"""
from __future__ import annotations

import logging

from app.agents._base import AgentResult, BaseAgent
from app.core.intraday_agent import load_nifty500_symbols
from app.core.zerodha_auth import zerodha_auth

log = logging.getLogger(__name__)


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
        try:
            kite = zerodha_auth.get_kite_instance()
            keys = [f"NSE:{s}" for s in symbols]
            log.info("agent01_data_quote_request symbols=%s sample=%s", len(keys), keys[:3])
            quotes = kite.quote(keys) or {}
        except Exception as exc:
            msg = str(exc)
            log.error("agent01_data_quote_failed symbols=%s error=%s", len(symbols), msg)
            self.bus.set(
                "market_data_error",
                {
                    "agent": self.name,
                    "error": msg,
                    "hint": (
                        "Kite rejected the quote request. Re-login after redeploy; "
                        "if it persists during market hours, check Kite Connect app permissions/subscription."
                    ),
                },
            )
            return AgentResult(self.name, False, error=f"Kite market-data blocked: {msg}")
        cleaned = {k.split(":", 1)[1]: v for k, v in quotes.items()}
        log.info("agent01_data_quote_success requested=%s received=%s", len(symbols), len(cleaned))
        self.bus.set("market_data_error", {})
        self.bus.set("market_data", cleaned)
        return AgentResult(self.name, True, payload={"symbols": len(cleaned)})
