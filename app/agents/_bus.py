"""Thread-safe in-memory bus shared by all 12 agents.

Producers call set(key, value); consumers call get(key, max_age_s=...).
Stale values older than max_age_s return None so downstream agents don't
act on data the upstream pipeline stopped refreshing.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any


PERSISTED_KEYS = {
    "auto_execute",
    "executed_today",
    "pref_feedback",
    "approved_decision",
    "risk_alerts",
    "decision",
    "health",
    "market_data_error",
}


def _json_safe(value: Any) -> Any:
    """Convert common runtime objects into JSON-safe structures."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, set):
        return {"__set__": [_json_safe(v) for v in value]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if all(hasattr(value, attr) for attr in ("agent", "ok", "ts")):
        return {
            "__agent_result__": True,
            "agent": getattr(value, "agent", ""),
            "ok": bool(getattr(value, "ok", False)),
            "payload": _json_safe(getattr(value, "payload", None)),
            "error": getattr(value, "error", None),
            "ts": getattr(value, "ts", datetime.now()).isoformat(),
        }
    return str(value)


def _from_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        if "__set__" in value:
            return set(_from_json_safe(v) for v in value["__set__"])
        if "__datetime__" in value:
            try:
                return datetime.fromisoformat(value["__datetime__"])
            except Exception:
                return datetime.now()
        return {k: _from_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_json_safe(v) for v in value]
    return value


class AgentBus:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, datetime]] = {}
        self._lock = threading.Lock()
        self._hydrate_runtime_state()

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (value, datetime.now())
        self._persist_if_needed(key, value)

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

    def _persist_if_needed(self, key: str, value: Any) -> None:
        if key not in PERSISTED_KEYS and not key.startswith("last_result:"):
            return
        try:
            from app.core.storage import storage

            storage.set_runtime_state(f"bus:{key}", _json_safe(value))
        except Exception:
            # Persistence must never break the agent loop.
            return

    def _hydrate_runtime_state(self) -> None:
        try:
            from app.core.storage import storage

            rows = storage.list_runtime_state()
        except Exception:
            return
        now = datetime.now()
        restored: dict[str, tuple[Any, datetime]] = {}
        for key, value in rows.items():
            if not key.startswith("bus:"):
                continue
            bus_key = key.split("bus:", 1)[1]
            if bus_key not in PERSISTED_KEYS and not bus_key.startswith("last_result:"):
                continue
            restored[bus_key] = (_from_json_safe(value), now)
        with self._lock:
            self._store.update(restored)
