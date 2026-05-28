"""Load Streamlit Cloud secrets into os.environ and fix cloud-only settings.

Must run before ``Settings()`` is constructed (imported from config.py).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

CLOUD_APP_URL = "https://proactive-agentic-dt.streamlit.app"

# Keys Streamlit Cloud secrets should provide (also read from .env locally).
_ENV_KEYS = (
    "KITE_API_KEY",
    "KITE_API_SECRET",
    "KITE_REDIRECT_URL",
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "GOOGLE_API_KEY",
    "GOOGLE_MODEL",
    "DAILY_CAPITAL",
    "MAX_DAILY_LOSS",
    "MAX_TRADES_PER_DAY",
    "ENABLE_LIVE_TRADING",
)


def is_streamlit_cloud() -> bool:
    """True when running on Streamlit Community Cloud (/mount/src/...)."""
    cwd = str(Path.cwd())
    if "/mount/src/" in cwd:
        return True
    host = (
        os.environ.get("HOSTNAME", "")
        + os.environ.get("STREAMLIT_SERVER_ADDRESS", "")
        + os.environ.get("STREAMLIT_RUNTIME_ENV", "")
    ).lower()
    return "streamlit" in host


def _flatten_secret_value(key: str, value: Any, into: dict[str, str]) -> None:
    if isinstance(value, dict):
        for sub_k, sub_v in value.items():
            _flatten_secret_value(str(sub_k), sub_v, into)
        return
    if value is None:
        return
    into[str(key).upper()] = str(value).strip()


def _load_streamlit_secrets() -> None:
    try:
        import streamlit as st
    except ImportError:
        return
    try:
        raw = st.secrets
    except Exception:
        return
    flat: dict[str, str] = {}
    try:
        for key, value in raw.items():
            _flatten_secret_value(str(key), value, flat)
    except Exception:
        return
    for k, v in flat.items():
        if v:
            os.environ[k] = v


def normalize_kite_redirect(url: str) -> str:
    """On Cloud, never use localhost callback URLs from old .env / secrets templates."""
    u = (url or "").strip().rstrip("/")
    if not is_streamlit_cloud():
        return u or "http://127.0.0.1:8000/callback"
    bad = (
        not u
        or "127.0.0.1" in u
        or "localhost" in u.lower()
        or "your-new-app" in u
        or "your-app" in u
        or u.endswith("/callback")  # FastAPI local callback path
    )
    if bad or "streamlit.app" not in u:
        return CLOUD_APP_URL
    return u


def apply_env_bootstrap() -> None:
    """Inject secrets and apply cloud-safe defaults."""
    _load_streamlit_secrets()

    redirect = normalize_kite_redirect(os.environ.get("KITE_REDIRECT_URL", ""))
    os.environ["KITE_REDIRECT_URL"] = redirect

    if is_streamlit_cloud():
        if not os.environ.get("LLM_PROVIDER"):
            os.environ["LLM_PROVIDER"] = "openai"
