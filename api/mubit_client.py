"""Thin wrapper around the MuBit SDK for OpenSCAD generation memory.

All functions are no-ops when MUBIT_API_KEY is not set, so the rest of the
codebase never needs to check for its presence.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None
_disabled = False


def _get_client() -> Any:
    """Lazily initialise the MuBit client.  Returns None if unavailable."""
    global _client, _disabled
    if _disabled:
        return None
    if _client is not None:
        return _client

    api_key = os.getenv("MUBIT_API_KEY", "")
    if not api_key:
        logger.info("MUBIT_API_KEY not set — MuBit integration disabled")
        _disabled = True
        return None

    try:
        from mubit import Client

        _client = Client()
        logger.info("MuBit client initialised")
        return _client
    except Exception as e:
        logger.warning("Failed to initialise MuBit client: %s", e)
        _disabled = True
        return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def get_generation_context(
    agent_id: str,
    session_id: str,
    max_tokens: int = 500,
) -> str:
    """Retrieve past lessons/context for this agent before an LLM call.

    Returns a string to prepend to the user prompt, or "" if unavailable.
    """
    client = _get_client()
    if client is None:
        return ""

    try:
        context = client.get_context(
            run_id=session_id,
            lane=agent_id,
            max_tokens=max_tokens,
        )
        # context may be a dict with a "text" or "context" key, or a string
        if isinstance(context, dict):
            text = context.get("context") or context.get("text") or ""
        else:
            text = str(context) if context else ""

        if text and text.strip():
            return text.strip()
    except Exception as e:
        logger.warning("MuBit get_context failed: %s", e)

    return ""


async def remember_generation(
    agent_id: str,
    session_id: str,
    prompt: str,
    code: str,
    model_used: str,
) -> None:
    """Store a generation interaction as a fact in MuBit memory."""
    client = _get_client()
    if client is None:
        return

    try:
        content = (
            f"Prompt: {prompt[:500]}\n"
            f"Model: {model_used}\n"
            f"Generated OpenSCAD code ({len(code)} chars):\n{code[:1000]}"
        )
        client.remember(
            session_id=session_id,
            agent_id=agent_id,
            content=content,
            intent="fact",
            metadata={"model": model_used, "code_length": len(code)},
        )
    except Exception as e:
        logger.warning("MuBit remember failed: %s", e)


async def record_generation_outcome(
    session_id: str,
    success: bool,
    error_msg: str | None = None,
) -> None:
    """Record whether the generated OpenSCAD code compiled successfully."""
    client = _get_client()
    if client is None:
        return

    try:
        outcome = "success" if success else "failure"
        signal = 1.0 if success else 0.0
        rationale = "OpenSCAD compilation succeeded" if success else f"Compilation failed: {error_msg or 'unknown error'}"

        client.record_outcome(
            run_id=session_id,
            outcome=outcome,
            signal=signal,
            rationale=rationale,
        )
    except Exception as e:
        logger.warning("MuBit record_outcome failed: %s", e)


async def reflect_on_session(session_id: str) -> None:
    """Extract lessons from this generation session."""
    client = _get_client()
    if client is None:
        return

    try:
        client.reflect(run_id=session_id)
    except Exception as e:
        logger.warning("MuBit reflect failed: %s", e)
