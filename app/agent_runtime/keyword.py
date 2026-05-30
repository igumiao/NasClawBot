"""Function-calling keyword extractor for the search path.

Replaces the text-based JSON parsing in app/llm/find_keyword_llm.py with a
structured tool call. Uses tool_choice="auto" because DeepSeek V4 thinking mode rejects
"required" and specific-name formats.
"""

from __future__ import annotations

import json
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


_EXTRACT_KEYWORD_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_keyword",
        "description": "从用户的媒体请求中提取一个精确的搜索关键词，包含标题和可选年份。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，格式: '标题 年份' 或仅 '标题'",
                }
            },
            "required": ["keyword"],
        },
    },
}


def _build_extraction_messages(user_message: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是媒体搜索助手。从用户的媒体请求中提取一个精确的搜索关键词。\n"
                "规则：\n"
                "1. 识别媒体实体和具体属性（演员、导演、年份）\n"
                "2. 如果用户提到特定演员的版本（如'托比·马奎尔的蜘蛛侠'），定位到对应年份\n"
                "3. 关键词格式: '标题 年份' 或仅 '标题'\n"
                "4. 去掉质量描述（4K、1080p）、字幕要求等非标题信息"
            ),
        },
        {"role": "user", "content": user_message},
    ]


class KeywordExtractor:
    """Extract a search keyword via function calling, with the original
    FindKeywordLLM interface for drop-in compatibility.
    """

    def invoke(self, message: str) -> dict[str, str]:
        settings = get_settings()
        from hello_agents.core.llm import HelloAgentsLLM

        llm = HelloAgentsLLM(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        response = llm.invoke_with_tools(
            messages=_build_extraction_messages(message),
            tools=[_EXTRACT_KEYWORD_TOOL],
            tool_choice="auto",
        )
        if not response.tool_calls:
            raise ValueError("LLM did not return a tool call for keyword extraction.")

        tool_call = response.tool_calls[0]
        try:
            arguments = json.loads(tool_call.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse keyword extraction arguments: {exc}") from exc

        keyword = arguments.get("keyword") if isinstance(arguments, dict) else None
        if not isinstance(keyword, str) or not keyword.strip():
            raise ValueError("LLM keyword extraction must return a non-empty keyword.")

        normalized = keyword.strip()
        logger.info("Function-calling keyword extraction succeeded keyword=%s", normalized)
        return {"keyword": normalized}
