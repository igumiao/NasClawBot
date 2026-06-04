"""Production-oriented tool-calling Agent preset."""

from typing import Optional, TYPE_CHECKING, Any

from ..core.agent import Agent
from ..core.config import Config
from ..core.llm import HelloAgentsLLM
from ..loop import ToolCallingLoop, ToolCallingLoopResult

if TYPE_CHECKING:
    from ..tools.registry import ToolRegistry
    from ..tools.filter import Filter
    from ..tools.gate import Gate


DEFAULT_TOOL_CALLING_SYSTEM_PROMPT = """你是一个可以使用工具完成任务的 AI 助手。

根据用户请求选择必要工具。工具结果返回后，基于结果给出简洁、准确的最终回答。
如果不需要工具，直接回答。
"""


class ToolCallingAgent(Agent):
    """General tool-calling assistant without teaching ReAct conventions."""

    def __init__(
        self,
        name: str,
        llm: HelloAgentsLLM,
        tool_registry: Optional["ToolRegistry"] = None,
        system_prompt: Optional[str] = None,
        config: Optional[Config] = None,
        max_steps: int = 5,
        tool_filter: Optional["Filter"] = None,
        tool_gate: Optional["Gate"] = None,
    ):
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt or DEFAULT_TOOL_CALLING_SYSTEM_PROMPT,
            config=config,
            tool_registry=tool_registry,
        )
        self.max_steps = max_steps
        self.tool_filter = tool_filter
        self.tool_gate = tool_gate
        self.last_result: Optional[ToolCallingLoopResult] = None

    def run(
        self,
        input_text: str,
        session_name: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        loop = ToolCallingLoop(
            agent=self,
            max_steps=self.max_steps,
            session_name=session_name,
        )
        result = loop.run(input_text, **kwargs)
        self.last_result = result
        self._session_metadata["total_steps"] = result.steps
        return result.final_answer

    def resume_tool_call(
        self,
        paused_loop: dict[str, Any],
        tool_response: Any,
        session_name: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        loop = ToolCallingLoop(
            agent=self,
            max_steps=self.max_steps,
            session_name=session_name,
        )
        result = loop.resume(paused_loop, tool_response, **kwargs)
        self.last_result = result
        self._session_metadata["total_steps"] = result.steps
        return result.final_answer
