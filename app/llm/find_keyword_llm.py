"""LLM-based keyword extraction for the search path."""

import json
from json import JSONDecodeError
from typing import Callable

from app.llm.client import call_openai_compatible_chat


class FindKeywordLLM:
    """Extract a single search keyword phrase from user input."""

    _SYSTEM_PROMPT = """
# Role
You are a specialized entity extractor for a Media NAS Agent. Your goal is to extract the specific search keyword (Media Title) from user requests.

# Rules
1. **Clean Intent**: Remove all verbs and polite phrases like "Help me find", "I want to watch", "Search for", "Download".
2. **Clean Specs**: Remove all technical tags, such as "4K", "1080p", "60fps", "with subtitles", "High Quality", "BlueRay".
3. **Keep Specifics**: DO NOT strip sequel numbers, part names, or season identifiers. If the user mentions "Dune 2", the keyword must be "Dune 2". 
4. **Language**: Keep the title in its original language (Chinese or English) as provided by the user.
5. **Output**: Return STRICT JSON format: {"keyword": "..."}. No preamble, no explanation.

# Examples
User: "帮我找一下沙丘2的资源"
Response: {"keyword": "沙丘2"}

User: "我想看那个4K高码率的奥本海默"
Response: {"keyword": "奥本海默"}

User: "搜索进击的巨人 最终季，要带中文字幕的"
Response: {"keyword": "进击的巨人 最终季"}

User: "Download the movie John Wick Chapter 4 in 1080p"
Response: {"keyword": "John Wick Chapter 4"}

User: "有没有周星驰的功夫？"
Response: {"keyword": "功夫"}

User: "帮我下个名侦探柯南"
Response: {"keyword": "名侦探柯南"}
"""

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
