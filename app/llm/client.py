"""LLM client interfaces and shared OpenAI-compatible helper.

The workflow depends on an `invoke(message)` contract and Task 1 introduces
an API-call helper that can be shared by LLM modules.
"""

from typing import Protocol

import httpx

from app.config import get_settings


class ConstraintExtractor(Protocol):
    """Interface for extracting structured constraints from user language."""

    def invoke(self, message: str) -> dict:
        ...


class LocalConstraintExtractor:
    """Heuristic extractor used as a safe default during early development."""

    def invoke(self, message: str) -> dict:
        lowered = message.lower()
        optimization_goal = "speed" if any(
            token in lowered for token in ("tonight", "quick", "fast", "马上", "今晚")
        ) else "balanced"
        urgency = "high" if optimization_goal == "speed" else "normal"

        media_type = "unknown"
        if any(token in lowered for token in ("movie", "film", "电影")):
            media_type = "movie"
        elif any(token in lowered for token in ("series", "show", "tv", "剧")):
            media_type = "tv"

        return {
            "query_text": message,
            "title": None,
            "year": None,
            "media_type": media_type,
            "preferred_resolution": None,
            "allow_season_pack": True,
            "urgency": urgency,
            "optimization_goal": optimization_goal,
        }


def call_openai_compatible_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 30.0,
) -> str:
    """Call an OpenAI-compatible `/chat/completions` endpoint and return text."""

    settings = get_settings()
    resolved_model = model or settings.llm_model
    resolved_api_key = api_key or settings.llm_api_key
    resolved_base_url = (base_url or settings.llm_base_url).rstrip("/")
    if not isinstance(resolved_api_key, str) or not resolved_api_key.strip():
        raise ValueError("LLM_API_KEY is required for chat completions.")

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved_api_key.strip()}",
    }

    response = httpx.post(
        f"{resolved_base_url}/chat/completions",
        headers=headers,
        json={
            "model": resolved_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        },
        timeout=timeout,
    )
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("OpenAI-compatible response body must be a JSON object.")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI-compatible response must include a non-empty choices list.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("OpenAI-compatible response choices entries must be JSON objects.")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("OpenAI-compatible response choice is missing message object.")

    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("OpenAI-compatible response message content must be a string.")
    return content
