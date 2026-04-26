"""Shared OpenAI-compatible helper for LLM-backed workflow modules."""

import httpx

from app.config import get_settings


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

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved_api_key.strip()}",
    }

    payload: dict[str, object] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    # MiniMax supports separating reasoning into `reasoning_details` so final
    # message content stays clean for downstream JSON parsers.
    if resolved_reasoning_split:
        payload["reasoning_split"] = True

    response = httpx.post(
        f"{resolved_base_url}/chat/completions",
        headers=headers,
        json=payload,
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
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str):
                text_parts.append(text_value)
        if text_parts:
            return "".join(text_parts)

    raise ValueError("OpenAI-compatible response message content must be a string.")
