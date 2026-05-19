"""LLM-based keyword extraction for the search path."""

import json
from json import JSONDecodeError
import logging
import re
from typing import Callable

from app.llm.client import call_openai_compatible_chat

logger = logging.getLogger(__name__)


class FindKeywordLLM:
    """Extract a single search keyword phrase from user input."""

    _SYSTEM_PROMPT = """
# Role
You are a Media Librarian. Your goal is to convert vague user requests into precise "Title + Year" search queries.

# Logic
1. Identify the media entity and any specific attributes (actors, directors, release periods).
2. Use your internal knowledge to map these attributes to the exact movie/TV show.
3. If the user mentions an actor (e.g., "Toby Maguire's Spider-Man"), identify all movies in that series.
4. If multiple movies fit (like a trilogy), return the main series keyword or the first entry, but append the YEAR for precision.

# Output Format
Return JSON: {"keyword": "Title(must have exact title) Year(optional)"}

# Examples
User: "我想看托比·马奎尔的蜘蛛侠"
Response: {
  "keyword": "蜘蛛侠 2002", 
}
"reasoning": "User specified Tobey Maguire, referring to the original Sam Raimi trilogy starting in 2002."

User: "诺兰的蝙蝠侠"
Response: {
  "keyword": "蝙蝠侠 开战时刻 2005",
  
}
"reasoning": "Christopher Nolan's Dark Knight trilogy began with Batman Begins in 2005."

# Other Examples
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

        normalized_keyword = keyword.strip()
        logger.info("LLM keyword extraction succeeded keyword=%s", normalized_keyword)
        return {"keyword": normalized_keyword}


def _parse_json_payload(raw_output: str) -> dict:
    if not isinstance(raw_output, str):
        raise ValueError("LLM output must be valid JSON.")

    stripped = raw_output.strip()
    # Some providers still prepend think blocks even with reasoning split.
    stripped = re.sub(r"^\s*<think>[\s\S]*?</think>\s*", "", stripped, flags=re.IGNORECASE)

    candidates = [stripped]
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
