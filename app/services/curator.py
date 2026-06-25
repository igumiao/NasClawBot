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
    inbox_index: int | None = None   # null for modify / delete
    preview: str = ""                # empty for modify/delete
    action: Literal["keep", "discard", "modify", "delete"]

    # keep-specific
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None

    # modify / delete-specific
    existing_text: str | None = None  # exact original line from the file to match
    new_text: str | None = None       # replacement line (modify only)
    reason: str | None = None         # why this change is needed


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
    from app.domain.runtime_tasks import app_now_iso

    now = app_now_iso().split("T")[0]

    entries_text = "\n\n---\n\n".join(
        f"[索引 {e['index']}] {e['timestamp']}\n{e['text']}" for e in entries
    )
    knowledge_sections = "\n".join(f"- {s}" for s in sections.get("knowledge", []))

    return f"""当前日期：{now}。用这个日期判断信息是否过时。

你是 NasClawBot 的记忆整理助手。分析收件箱条目和已有记忆，判断每条应该保留、丢弃、修改还是删除。

## 现有用户画像 (user_profile.md)

{user_profile if user_profile.strip() else "（空）"}

## 现有知识库 (knowledge.md)

{knowledge if knowledge.strip() else "（空）"}

## 收件箱条目

{entries_text if entries_text.strip() else "（空）"}

## 可用的章节

knowledge 可用章节：
{knowledge_sections}

## 判定规则

### inbox 条目（keep / discard）

NasClawBot 是用户的贴身管家，不是只记技术参数的工具。收到关于用户的信息时，从这些维度判断归属：

- **user_profile** 适合：
  - 用户身份、称呼、职业、所在地域
  - 语言偏好、语气、沟通习惯
  - 兴趣爱好、媒体偏好、价值观、生活习惯
  - NAS / 技术约束、明确禁忌
  - 保留为独立条目，写入 `user_profile.md` 时**不要提供 section**
- **knowledge** 适合：领域技巧、操作经验、可复用的方法、生活效率技巧。
- 如果条目和已有内容高度重复，标记为 discard。
- 如果条目没有长期保留价值，标记为 discard。
- **关键规则**：如果一条 inbox 条目触发了对已有条目的 modify（矛盾导致旧信息被新信息替代），
  且 modify 已经充分体现了 inbox 条目的信息，则 inbox 条目应该标记为 **discard**，
  而不是 keep。因为修改已经覆盖了新信息，不需要再 append 一条内容相近的条目。
- 润色文本：修正错别字、精简表达、补充必要上下文，保持原意不变。

### 已有条目（modify / delete）
- **矛盾检测**：如果 inbox 新条目和已有条目矛盾，标记 modify 旧条目（用新信息替代旧信息）。
  如果已有条目之间互相矛盾，modify 过时的、保留最新的。
  **重要**：当你因为 inbox 条目而 modify 旧条目时，同时把该 inbox 条目标记为 discard。
- **过时检测**：如果已有条目明显过时或无效（结合日期判断），标记 delete。
- **重复检测**：如果 inbox 条目和已有条目高度重复，discard inbox 条目即可（不需要 modify 已有条目）。

### modify / delete 输出要求
- `existing_text`：文件中的**精确原文**，一字不差。后端用它定位要修改/删除的行。
- `new_text`（modify）：替换后的完整行内容，保持 markdown 格式。
- `reason`：简要说明为什么要修改或删除这条信息。
- 不要凭空创造 modify/delete——只有当已有内容确实需要变更时才输出。

## 输出要求

严格输出 JSON，不要加任何其他文本：

{{"suggestions": [...], "inbox_entry_count": {len(entries)}}}

每条 suggestion：
- inbox_index: 整数（modify/delete 时为 null）
- preview: 原文前30字（modify/delete 时为空字符串）
- action: "keep" / "discard" / "modify" / "delete"
- destination: "user_profile" 或 "knowledge"（discard 时为 null）
- section: 章节名；`destination="user_profile"` 时必须为 null，`destination="knowledge"` 时必填（discard/modify/delete 按需为 null）
- edited_text: 润色后文本（discard/modify/delete 时为 null）
- existing_text: 文件中的精确原文（仅 modify/delete 需要，必须一字不差）
- new_text: 替换后的行内容（仅 modify 需要）
- reason: 修改/删除的原因（仅 modify/delete 需要）"""


def run_curation(store: MarkdownMemoryStore) -> CuratorResult:
    """Analyze inbox entries and return structured suggestions.  Does not modify files."""

    entries = store.parse_inbox()
    if not entries:
        return CuratorResult(suggestions=[], inbox_entry_count=0)

    user_profile = store.load(MemoryKind.USER_PROFILE).text
    knowledge = store.load(MemoryKind.KNOWLEDGE).text
    sections = {
        "user_profile": [],
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
