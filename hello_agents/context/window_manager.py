"""Preflight context-window management for Agent loops."""

from datetime import datetime
import json
from typing import Any, TYPE_CHECKING

from ..core.message import Message

if TYPE_CHECKING:
    from ..core.agent import Agent


SUMMARY_SYSTEM_PROMPT = """你是一个对话压缩助手。

请把下面即将被压缩的旧对话整理成可靠摘要，供后续 Agent 继续完成任务。
要求：
- 保留用户目标、明确偏好、已经确认的事实、工具结果和未完成事项
- 不要添加原文中没有的事实
- 对工具结果要标明来源和不确定性
- 用简洁中文输出
"""


class ContextWindowManager:
    """Check and compress conversation history before model calls."""

    def __init__(self, agent: "Agent"):
        self.agent = agent

    def prepare_for_model_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Compress active history if the full model input is over threshold.

        Returns:
            Whether the agent history was compressed and model messages should
            be rebuilt by the caller.
        """
        if not self.agent.config.preflight_compression_enabled:
            return False

        all_messages = messages + list(extra_messages or [])
        estimated_tokens = self._estimate_model_input_tokens(all_messages, tools or [])
        threshold = int(self.agent.config.context_window * self.agent.config.compression_threshold)
        if estimated_tokens <= threshold:
            return False

        return self._compress_active_history(estimated_tokens=estimated_tokens)

    def _estimate_model_input_tokens(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> int:
        total = 0
        for message in messages:
            total += self._count_api_message(message)
        if tools:
            total += self.agent.token_counter.count_text(json.dumps(tools, ensure_ascii=False))
        return total

    def _count_api_message(self, message: dict[str, Any]) -> int:
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        tokens = self.agent.token_counter.count_text(content) + 4
        if message.get("tool_calls"):
            tokens += self.agent.token_counter.count_text(json.dumps(message["tool_calls"], ensure_ascii=False))
        if message.get("tool_call_id"):
            tokens += self.agent.token_counter.count_text(str(message["tool_call_id"]))
        return tokens

    def _compress_active_history(self, estimated_tokens: int) -> bool:
        history = self.agent.history_manager.get_history()
        boundaries = self.agent.history_manager.find_round_boundaries()
        retain_rounds = self.agent.config.min_retain_rounds
        if len(boundaries) <= retain_rounds:
            return False

        keep_from_index = boundaries[-retain_rounds]
        to_compress = history[:keep_from_index]
        recent_messages = history[keep_from_index:]
        if not to_compress:
            return False

        summary = self._generate_summary(to_compress)
        now = datetime.now().isoformat()
        summary_message = Message(
            content=f"## Conversation Summary\n{summary}",
            role="summary",
            metadata={
                "kind": "preflight_compression",
                "compressed_at": now,
                "source_message_count": len(to_compress),
                "retained_recent_rounds": retain_rounds,
                "estimated_tokens_before": estimated_tokens,
            },
        )

        archive = {
            "id": f"archive-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
            "created_at": now,
            "reason": "preflight_compression",
            "summary": summary,
            "source_message_count": len(to_compress),
            "retained_recent_rounds": retain_rounds,
            "estimated_tokens_before": estimated_tokens,
            "messages": [message.to_dict() for message in to_compress],
        }
        archives = list(getattr(self.agent, "_conversation_archives", []))
        archives.append(archive)
        setattr(self.agent, "_conversation_archives", archives)

        self.agent.history_manager.clear()
        self.agent.history_manager.append(summary_message)
        for message in recent_messages:
            self.agent.history_manager.append(message)

        self.agent._history_token_count = self.agent.token_counter.count_messages(
            self.agent.history_manager.get_history()
        )
        if self.agent.trace_logger:
            self.agent.trace_logger.log_event(
                "preflight_compression",
                {
                    "source_message_count": len(to_compress),
                    "retained_recent_rounds": retain_rounds,
                    "estimated_tokens_before": estimated_tokens,
                    "archive_id": archive["id"],
                },
            )
        return True

    def _generate_summary(self, messages: list[Message]) -> str:
        if not self.agent.config.enable_smart_compression:
            return self._simple_summary(messages)

        prompt = self._summary_prompt(messages)
        try:
            response = self.agent.llm.invoke(
                [
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.agent.config.summary_temperature,
                max_tokens=self.agent.config.summary_max_tokens,
            )
        except Exception as exc:
            if self.agent.config.debug:
                print(f"preflight compression summary failed: {exc}")
            if self.agent.trace_logger:
                self.agent.trace_logger.log_event(
                    "error",
                    {
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "context": "preflight compression summary generation failed — falling back to simple summary",
                        "message_count": len(messages),
                    },
                )
            return self._simple_summary(messages)

        content = response.content if hasattr(response, "content") else str(response)
        return content or self._simple_summary(messages)

    def _summary_prompt(self, messages: list[Message]) -> str:
        return f"""请压缩以下旧对话。它们会从活跃上下文中移入 archive，但摘要会继续提供给 Agent。

## 旧对话
{self._format_messages(messages)}

## 输出格式
- 当前任务/用户目标：
- 已确认事实：
- 工具结果：
- 用户偏好/约束：
- 未完成或不确定事项：
"""

    def _format_messages(self, messages: list[Message]) -> str:
        lines = []
        for message in messages:
            content = message.content
            if len(content) > 800:
                content = f"{content[:800]}\n...[truncated]"
            lines.append(f"[{message.role}] {content}")
        return "\n\n".join(lines)

    def _simple_summary(self, messages: list[Message]) -> str:
        user_count = sum(1 for message in messages if message.role == "user")
        assistant_count = sum(1 for message in messages if message.role == "assistant")
        tool_count = sum(1 for message in messages if message.role == "tool")
        return (
            f"旧对话已压缩：共 {len(messages)} 条消息，其中用户消息 {user_count} 条、"
            f"助手消息 {assistant_count} 条、工具消息 {tool_count} 条。"
        )
