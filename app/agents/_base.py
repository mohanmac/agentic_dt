"""Base class + result type for the 12 proactive agents.

Every agent extends BaseAgent and implements run_once(). Calling start()
launches a daemon thread that ticks run_once() on a fixed interval; stop()
joins the thread cleanly. Exceptions in a tick are logged and stored on
last_result so the loop never dies silently.
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class AgentResult:
    agent: str
    ok: bool
    payload: Any = None
    error: str | None = None
    ts: datetime = field(default_factory=datetime.now)


class BaseAgent(ABC):
    name: str = "base"
    description: str = ""
    interval_seconds: float = 5.0
    inputs: list[str] = []
    outputs: list[str] = []
    skills: list[dict] = []
    uses_llm: bool = False
    version: str = "1.0.0"

    @classmethod
    def card(cls) -> dict:
        """A2A-style agent card — pure static metadata, no live state.

        Live state (heartbeat, last_result) is owned by the running thread
        and surfaced separately via the Monitoring Agent / dashboard.
        """
        return {
            "name": cls.name,
            "version": cls.version,
            "description": cls.description,
            "mode": "proactive",
            "schedule": {"interval_seconds": cls.interval_seconds, "loop": "daemon-thread"},
            "inputs": {"bus_keys": cls.inputs},
            "outputs": {"bus_keys": cls.outputs},
            "skills": cls.skills,
            "llm": {"uses_llm": cls.uses_llm, "shared_key": True, "provider": "configured-in-.env"},
            "card_url": f"/agents/{cls.name}/card.json",
        }

    def __init__(self, bus: "AgentBus") -> None:  # noqa: F821
        self.bus = bus
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last: AgentResult | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()
        log.info("agent_started name=%s interval=%ss", self.name, self.interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info("agent_stopped name=%s", self.name)

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.perf_counter()
            try:
                res = self.run_once()
            except Exception as exc:
                log.exception("agent_tick_failed name=%s", self.name)
                res = AgentResult(agent=self.name, ok=False, error=str(exc))
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            self._last = res
            self.bus.set(f"last_result:{self.name}", res)
            log.info(
                "agent_tick name=%s ok=%s elapsed_ms=%s payload=%s error=%s",
                self.name,
                res.ok,
                elapsed_ms,
                res.payload,
                res.error,
            )
            if self._stop.wait(self.interval_seconds):
                return

    @abstractmethod
    def run_once(self) -> AgentResult: ...

    @property
    def last_result(self) -> AgentResult | None:
        return self._last
