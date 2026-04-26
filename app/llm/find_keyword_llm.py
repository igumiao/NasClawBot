"""LLM-based keyword extraction for the search path."""

import json
from json import JSONDecodeError
from typing import Callable

from app.llm.client import call_openai_compatible_chat


class FindKeywordLLM:
    """Extract a single search keyword phrase from user input."""

    _SYSTEM_PROMPT = (
        "Extract one search keyword phrase from the user message. "
        'Return strict JSON only in the form {"keyword":"..."} with no extra text.'
    )

    def __init__(
        self,
        chat_caller: Callable[..., str] = call_openai_compatible_chat,
    ) -> None:
        self._chat_caller = chat_caller

    def invoke(self, message: str) -> dict[str, str]:
        raw_output = self._chat_caller(
            system_prompt=self._SYSTEM_PROMPT,
            user_prompt=message,
        )
        payload = _parse_json_payload(raw_output)

        keyword = payload.get("keyword") if isinstance(payload, dict) else None
        if not isinstance(keyword, str) or not keyword.strip():
            raise ValueError("LLM output must include a non-empty keyword.")

        return {"keyword": keyword.strip()}


def _parse_json_payload(raw_output: str) -> dict:
    if not isinstance(raw_output, str):
        raise ValueError("LLM output must be valid JSON.")

    candidates = [raw_output.strip()]
    stripped = raw_output.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            candidates.append("\n".join(lines[1:-1]).strip())
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        candidates.append(stripped[first_brace : last_brace + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("LLM output must be valid JSON.")
