"""Thread-safe in-memory bus shared by all 12 agents.

Producers call set(key, value); consumers call get(key, max_age_s=...).
Stale values older than max_age_s return None so downstream agents don't
act on data the upstream pipeline stopped refreshing.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any


class AgentBus:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, datetime]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (value, datetime.now())

    def get(self, key: str, max_age_s: float | None = None) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
        if entry is None:
            return None
        value, ts = entry
        if max_age_s is not None and (datetime.now() - ts).total_seconds() > max_age_s:
            return None
        return value

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())

    def snapshot(self) -> dict[str, tuple[Any, datetime]]:
        with self._lock:
            return dict(self._store)
