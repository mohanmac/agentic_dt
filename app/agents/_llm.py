"""Single shared LLM accessor for the 12-agent system.

Only agents whose work is genuinely LLM-shaped (free-text reasoning,
sentiment, summarisation) should import this. Everything else — features,
signals, voting, risk, execution — must stay in pure Python. The guard
below raises if an agent name not in ALLOWED tries to use the LLM, so
accidental LLM use in a deterministic agent fails loud at runtime.

One API key, one provider, set once in app/core/config.py via .env.
"""
from __future__ import annotations

import logging

from app.core.llm import llm_client

log = logging.getLogger(__name__)

ALLOWED = frozenset({"agent09_sentiment"})


def llm_generate(agent_name: str, prompt: str, system_prompt: str | None = None) -> str:
    if agent_name not in ALLOWED:
        raise RuntimeError(
            f"LLM use not permitted from {agent_name}. "
            f"Only {sorted(ALLOWED)} may call the LLM."
        )
    return llm_client.generate(prompt, system_prompt=system_prompt)


def llm_health() -> bool:
    try:
        return bool(llm_client.check_health())
    except Exception as exc:
        log.warning("llm_health_failed err=%s", exc)
        return False
