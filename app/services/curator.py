"""Curator service: classify inbox entries and suggest destinations."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from app.config import get_settings
from app.domain.memory import MemoryKind
from app.services.markdown_memory_store import MarkdownMemoryStore
from hello_agents.core.llm import HelloAgentsLLM


class CuratorSuggestion(BaseModel):
    inbox_index: int
    preview: str
    action: Literal["keep", "discard"]
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None


class CuratorResult(BaseModel):
    suggestions: list[CuratorSuggestion]
    inbox_entry_count: int


def _build_curator_llm():
    settings = get_settings()
    return HelloAgentsLLM(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.1,
    )


def _build_prompt(entries: list[dict], user_profile: str, knowledge: str, sections: dict) -> str:
    entries_text = "\n\n---\n\n".join(
        f"[索引 {e['index']}] {e['timestamp']}\n{e['text']}" for e in entries
    )
    user_sections = "\n".join(f"- {s}" for s in sections.get("user_profile", []))
    knowledge_sections = "\n".join(f"- {s}" for s in sections.get("knowledge", []))

    return f"""你是 NasClawBot 的记忆整理助手。分析以下收件箱条目，判断每条应该保留还是丢弃。

## 收件箱条目

{entries_text}

## 现有用户画像 (user_profile.md)

{user_profile if user_profile.strip() else "（空）"}

## 现有知识库 (knowledge.md)

{knowledge if knowledge.strip() else "（空）"}

## 可用的章节

user_profile 可用章节：
{user_sections}

knowledge 可用章节：
{knowledge_sections}

## 判定规则

- **user_profile** 适合：个人偏好、沟通风格、身份、操作习惯、禁止事项。这类信息影响 Agent 的行为方式。
- **knowledge** 适合：领域技巧、操作经验、事实性环境信息。这类信息在特定场景下按需搜索。
- 如果条目和已有内容高度重复，标记为 discard。
- 如果条目没有长期保留价值（如单次搜索结果），标记为 discard。
- 润色文本：修正错别字、精简表达、补充必要上下文，但保持原意不变。

## 输出要求

严格输出 JSON，不要加任何其他文本：

{{"suggestions": [...], "inbox_entry_count": {len(entries)}}}

每条 suggestion：
- inbox_index: 整数
- preview: 原文前30字
- action: "keep" 或 "discard"
- destination: "user_profile" 或 "knowledge"（discard 时为 null）
- section: 章节名（discard 时为 null）
- edited_text: 润色后文本（discard 时为 null）"""


def run_curation(store: MarkdownMemoryStore) -> CuratorResult:
    """Analyze inbox entries and return structured suggestions.  Does not modify files."""

    entries = store.parse_inbox()
    if not entries:
        return CuratorResult(suggestions=[], inbox_entry_count=0)

    user_profile = store.load(MemoryKind.USER_PROFILE).text
    knowledge = store.load(MemoryKind.KNOWLEDGE).text
    sections = {
        "user_profile": store.get_sections(MemoryKind.USER_PROFILE),
        "knowledge": store.get_sections(MemoryKind.KNOWLEDGE),
    }

    prompt = _build_prompt(entries, user_profile, knowledge, sections)
    llm = _build_curator_llm()
    messages = [{"role": "user", "content": prompt}]
    response = llm.invoke(messages)
    raw = response.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]

    return CuratorResult.model_validate_json(raw)
