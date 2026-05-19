"""Shared OpenAI-compatible helper for LLM-backed workflow modules."""

import logging
from typing import Any

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - dependency checked at install/runtime
    OpenAI = None

from app.config import get_settings

logger = logging.getLogger(__name__)


def call_openai_compatible_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    reasoning_split: bool | None = None,
    timeout: float = 30.0,
) -> str:
    """Call an OpenAI-compatible `/chat/completions` endpoint and return text."""

    settings = get_settings()
    resolved_model = model or settings.llm_model
    resolved_api_key = api_key or settings.llm_api_key
    resolved_base_url = (base_url or settings.llm_base_url).rstrip("/")
    resolved_reasoning_split = settings.llm_reasoning_split if reasoning_split is None else reasoning_split
    if not isinstance(resolved_api_key, str) or not resolved_api_key.strip():
        raise ValueError("LLM_API_KEY is required for chat completions.")
    if OpenAI is None:
        raise RuntimeError("openai is not installed")

    logger.info(
        "LLM chat completion started model=%s base_url=%s reasoning_split=%s system_chars=%s user_chars=%s",
        resolved_model,
        resolved_base_url,
        resolved_reasoning_split,
        len(system_prompt),
        len(user_prompt),
    )

    client = OpenAI(
        api_key=resolved_api_key.strip(),
        base_url=resolved_base_url,
        timeout=timeout,
    )
    create_kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    # MiniMax supports separating reasoning into `reasoning_details` so final
    # message content stays clean for downstream JSON parsers.
    if resolved_reasoning_split:
        create_kwargs["extra_body"] = {"reasoning_split": True}

    try:
        response = client.chat.completions.create(**create_kwargs)
    except Exception:
        logger.exception(
            "LLM chat completion failed model=%s base_url=%s",
            resolved_model,
            resolved_base_url,
        )
        raise

    choices = _read_response_value(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI-compatible response must include a non-empty choices list.")

    first_choice = choices[0]
    if first_choice is None:
        raise ValueError("OpenAI-compatible response choices entries must be JSON objects.")

    message = _read_response_value(first_choice, "message")
    if message is None:
        raise ValueError("OpenAI-compatible response choice is missing message object.")

    content = _read_response_value(message, "content")
    if isinstance(content, str):
        logger.info(
            "LLM chat completion succeeded model=%s response_chars=%s",
            resolved_model,
            len(content),
        )
        if settings.llm_log_raw_output:
            logger.debug(
                "LLM raw output preview raw_chars=%s raw_preview=%s",
                len(content),
                _preview_text(content),
            )
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            text_value = _read_response_value(item, "text")
            if isinstance(text_value, str):
                text_parts.append(text_value)
        if text_parts:
            joined = "".join(text_parts)
            logger.info(
                "LLM chat completion succeeded model=%s response_chars=%s",
                resolved_model,
                len(joined),
            )
            if settings.llm_log_raw_output:
                logger.debug(
                    "LLM raw output preview raw_chars=%s raw_preview=%s",
                    len(joined),
                    _preview_text(joined),
                )
            return joined

    raise ValueError("OpenAI-compatible response message content must be a string.")


def _read_response_value(payload: Any, key: str) -> Any:
    """Read SDK response objects or dict-like test doubles uniformly."""
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _preview_text(value: str, limit: int = 1000) -> str:
    """Return a one-line preview suitable for debug logs."""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."
