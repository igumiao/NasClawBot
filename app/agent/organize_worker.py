"""OrganizeWorkerAgent — a single-use ToolCallingAgent for post-download file organization.

Builds a fresh tool registry per run containing only the tools needed for
media organization (skill_load, TMDB lookup, MCP filesystem read-only and
mutation tools).  A dynamic Gate denies mutating operations (create_directory,
move_file) until the renaming-rules skill has been loaded via ``skill_load``.

After the agent loop completes, the structured ``OrganizeWorkerResult`` is
extracted from the conversation observations — the agent self-verifies by
checking how many ``move_file`` calls succeeded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.adapters.tmdb import TMDBAdapter
from app.config import get_settings
from app.mcp_pool import get_mcp_pool
from hello_agents.agents import ToolCallingAgent
from hello_agents.core.config import Config
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.skills.loader import SkillLoader
from hello_agents.tools import (
    Filter,
    Gate,
    Tool,
    ToolParameter,
    ToolRegistry,
    ToolResponse,
    ToolStatus,
)
from hello_agents.tools.builtin.skill_tool import SkillTool
from hello_agents.tools.mcp.bridge import register_mcp_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORGANIZE_MCP_TOOLS: list[str] = [
    "list_directory",
    "directory_tree",
    "read_text_file",
    "get_file_info",
    "search_files",
    "create_directory",
    "move_file",
]

_ORGANIZE_TOOL_NAMES: list[str] = [
    "skill_load",
    "tmdb_search",
    "tmdb_details",
    "mcp_filesystem_list_directory",
    "mcp_filesystem_directory_tree",
    "mcp_filesystem_read_text_file",
    "mcp_filesystem_get_file_info",
    "mcp_filesystem_search_files",
    "mcp_filesystem_create_directory",
    "mcp_filesystem_move_file",
]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _PROJECT_ROOT / "skills"

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class OrganizeWorkerResult:
    """Structured result returned by :meth:`OrganizeWorkerAgent.run`.

    Attributes:
        status: ``"success"``, ``"failed"``, or ``"error"``.
        summary: Human-readable summary of what was done.
        moved_count: Number of files successfully moved.
        destination: The destination directory for the organized files.
        issues: List of warning or error messages encountered.
        raw_answer: The full text answer from the agent.
        tool_calls: Total number of tool calls made during the run.
    """

    status: str = "error"
    summary: str = ""
    moved_count: int = 0
    destination: str = ""
    issues: list[str] = field(default_factory=list)
    raw_answer: str = ""
    tool_calls: int = 0


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_ORGANIZE_SYSTEM_PROMPT = """你是 NasClawBot 的下载整理助手。

你的任务是将已下载的影视文件按照规范整理到媒体库目录中。

## 必须按以下顺序执行

1. **加载技能** — 第一步必须调用 `skill_load("renaming-rules")` 加载重命名规范。
   技能文档包含完整的目录结构、命名规则和整理流程。
   在加载 renaming-rules 技能之前，文件系统写入工具（create_directory, move_file）不可用。

2. **扫描** — 使用 `list_directory` 或 `directory_tree` 查看源目录的内容。

3. **识别** — 从文件名提取信息。必要时使用 `tmdb_search` / `tmdb_details` 获取准确名称。

4. **创建目录** — 根据技能规范在目标根目录下创建对应的分类目录和 Season 目录。

5. **移动文件** — 使用 `move_file` 将文件移动到目标位置并重命名。

6. **验证** — 用 `get_file_info` 确认文件已到达目标位置。

## 重要原则

- 只处理源目录中的文件，不碰已整理好的目录。
- 移动前用 `get_file_info` 确认源文件存在。
- TMDB 和网络搜索都查不到的资源 = 存疑，放入 `其他/` 目录。
- 执行完成后，总结你做了哪些操作：移动了多少文件，目标位置在哪里。
"""


# ---------------------------------------------------------------------------
# Dynamic gate state
# ---------------------------------------------------------------------------


class _SkillGateState:
    """Mutable flag holder referenced by the Gate lambda and the skill wrapper.

    Updated by :class:`_OrganizeSkillTool` when ``skill_load("renaming-rules")``
    returns successfully.  The Gate checks this flag before allowing mutating
    file operations.
    """

    def __init__(self) -> None:
        self.skill_loaded = False


# ---------------------------------------------------------------------------
# Skill tool wrapper
# ---------------------------------------------------------------------------


class _OrganizeSkillTool(Tool):
    """Wraps ``SkillTool`` to update ``_SkillGateState`` on successful load.

    When the agent calls ``skill_load("renaming-rules")`` and the wrapped
    tool succeeds, the gate state flag is flipped so that subsequent
    ``create_directory`` / ``move_file`` calls are allowed through the Gate.
    """

    def __init__(self, skill_tool: SkillTool, gate_state: _SkillGateState) -> None:
        self._wrapped = skill_tool
        self._gate_state = gate_state
        super().__init__(
            name=skill_tool.name,
            description=skill_tool.description,
        )

    def get_parameters(self) -> list[ToolParameter]:
        return self._wrapped.get_parameters()

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        response = self._wrapped.run(parameters)
        if (
            response.status == ToolStatus.SUCCESS
            and parameters.get("name") == "renaming-rules"
        ):
            self._gate_state.skill_loaded = True
            logger.info(
                "renaming-rules skill loaded — Gate now allows mutating operations"
            )
        return response


# ---------------------------------------------------------------------------
# Worker agent
# ---------------------------------------------------------------------------


class OrganizeWorkerAgent:
    """Single-use agent for post-download file organization.

    Each call to :meth:`run` builds a fresh ``ToolCallingAgent`` with a
    purpose-built tool registry and a dynamic Gate.  The agent runs
    synchronously in the calling thread.  Use ``run_in_executor`` to avoid
    blocking the async event loop.

    Typical usage::

        worker = OrganizeWorkerAgent(max_steps=15)
        result = worker.run(source_path="/downloads/未整理/xxx", destination_root="/影视")
        print(result.status, result.moved_count)
    """

    def __init__(self, max_steps: int = 15) -> None:
        """Initialize the organizer.

        Args:
            max_steps: Maximum tool-calling steps for the agent loop.
                Default 15 accommodates the full scan/identify/mkdir/move/verify
                workflow.
        """
        self._max_steps = max_steps

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        source_path: str,
        destination_root: str,
    ) -> OrganizeWorkerResult:
        """Run the organization agent for a single download.

        Args:
            source_path: Path to the downloaded file or directory to organize.
            destination_root: Root directory for organized media (e.g.
                ``/影视``).  The agent will create category subdirectories
                under this root per the renaming rules.

        Returns:
            An ``OrganizeWorkerResult`` with the outcome of the operation.
        """
        agent = self._build_agent()

        task_prompt = (
            f"请整理以下已下载的影视文件：\n\n"
            f"源路径: {source_path}\n"
            f"目标根目录: {destination_root}\n\n"
            f"请按照整理规范执行操作。"
        )

        try:
            answer = agent.run(task_prompt)
        except Exception as exc:
            logger.exception("OrganizeWorkerAgent loop failed")
            return OrganizeWorkerResult(
                status="error",
                summary=f"Agent loop raised an exception: {exc}",
                issues=[str(exc)],
            )

        return self._extract_result(agent, answer)

    # ------------------------------------------------------------------
    # Agent builder (public for testability)
    # ------------------------------------------------------------------

    def _build_agent(self) -> ToolCallingAgent:
        """Build a fresh ``ToolCallingAgent`` for one organization run.

        The registry contains only the subset of tools required for media
        organization.  The Gate denies ``create_directory`` and ``move_file``
        until the renaming-rules skill has been loaded.
        """
        settings = get_settings()
        gate_state = _SkillGateState()

        llm = HelloAgentsLLM(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.1,
        )

        registry = ToolRegistry()

        # -- Skill loader + tool -----------------------------------------
        skill_loader = SkillLoader(skills_dir=_SKILLS_DIR)
        wrapped_skill = SkillTool(skill_loader)
        registry.register_tool(_OrganizeSkillTool(wrapped_skill, gate_state))

        # -- TMDB tools --------------------------------------------------
        tmdb_adapter = TMDBAdapter(api_key=settings.tmdb_api_key)
        from app.tools.tmdb_search import TMDBSearchTool
        from app.tools.tmdb_details import TMDBDetailsTool

        registry.register_tool(TMDBSearchTool(tmdb_adapter))
        registry.register_tool(TMDBDetailsTool(tmdb_adapter))

        # -- MCP filesystem tools (subset) --------------------------------
        mcp_pool = get_mcp_pool()
        if mcp_pool is not None:
            register_mcp_tools(mcp_pool, registry, allow=_ORGANIZE_MCP_TOOLS)

        # -- Filter: restrict to the tool set we built --------------------
        tool_filter = Filter(allow=_ORGANIZE_TOOL_NAMES)

        # -- Gate: deny mutating tools until skill loaded -----------------
        tool_gate = Gate(
            deny=[
                lambda call, st=gate_state: (
                    call.tool_name
                    in (
                        "mcp_filesystem_create_directory",
                        "mcp_filesystem_move_file",
                    )
                    and not st.skill_loaded
                ),
            ],
        )

        config_values = {
            "trace_enabled": False,
            "session_enabled": False,
            "skills_enabled": True,
            "skills_auto_register": False,  # We register _OrganizeSkillTool manually.
            "subagent_enabled": False,
            "todowrite_enabled": False,
            "devlog_enabled": False,
            "preflight_compression_enabled": False,
            "write_time_compression_enabled": False,
            "context_window": min(settings.context_window, 64000),
            "compression_threshold": 0.8,
            "min_retain_rounds": 2,
            "skills_dir": str(_SKILLS_DIR),
        }

        agent = ToolCallingAgent(
            name="organize-worker",
            llm=llm,
            tool_registry=registry,
            system_prompt=_ORGANIZE_SYSTEM_PROMPT,
            config=Config(**config_values),
            max_steps=self._max_steps,
            tool_filter=tool_filter,
            tool_gate=tool_gate,
        )

        # Append L1 skill descriptions to the system prompt.
        if agent.skill_loader is not None:
            descriptions = agent.skill_loader.get_descriptions()
            if descriptions.strip():
                skill_block = (
                    "\n\n## 可用技能 (Skills)\n\n"
                    "你可以使用 `skill_load` 工具加载任意技能的完整指导文档。"
                    "在执行整理任务前，必须先加载 renaming-rules 技能。\n\n"
                    f"{descriptions}"
                )
                agent.system_prompt = (agent.system_prompt or "") + skill_block

        return agent

    # ------------------------------------------------------------------
    # Result extraction
    # ------------------------------------------------------------------

    def _extract_result(
        self,
        agent: ToolCallingAgent,
        answer: str,
    ) -> OrganizeWorkerResult:
        """Parse the agent's observations into a structured ``OrganizeWorkerResult``.

        Iterates over tool observations to count successful ``move_file``
        calls, detect the destination, and collect issues.

        Args:
            agent: The agent after :meth:`~ToolCallingAgent.run` completed.
            answer: The agent's final text answer.

        Returns:
            A populated ``OrganizeWorkerResult``.
        """
        if not hasattr(agent, "last_result") or agent.last_result is None:
            return OrganizeWorkerResult(
                status="error",
                summary="Agent produced no result.  The loop may have been interrupted.",
                issues=["No last_result available on agent"],
            )

        observations = agent.last_result.tool_observations
        if not observations:
            return OrganizeWorkerResult(
                status="error",
                summary="No tool calls were made during the agent run.",
                issues=["No tool observations in last_result"],
            )

        moved_count = 0
        issues: list[str] = []
        destination = ""
        skill_loaded = False

        for obs in observations:
            tool_name = obs.tool_name or "unknown"
            resp_status = obs.response.status if obs.response else "none"
            resp_text = (obs.response.text or "")[:200] if obs.response else ""

            # Log every tool observation for debugging.
            logger.info(
                "organize tool: %s status=%s gate=%s text=%s",
                tool_name,
                resp_status,
                obs.gate_result or "PASS",
                resp_text,
            )

            # Count successful move_file calls.
            if (
                obs.tool_name == "mcp_filesystem_move_file"
                and obs.response is not None
                and obs.response.status == ToolStatus.SUCCESS
            ):
                moved_count += 1
                dest = (obs.arguments or {}).get("destination", "")
                if dest and not destination:
                    destination = dest

            # Detect skill load.
            if obs.tool_name == "skill_load":
                args = obs.arguments or {}
                if (
                    args.get("name") == "renaming-rules"
                    and obs.response is not None
                    and obs.response.status == ToolStatus.SUCCESS
                ):
                    skill_loaded = True

            # Collect error observations.
            if obs.response is not None and obs.response.status == ToolStatus.ERROR:
                issues.append(f"[{obs.tool_name}] {obs.response.text}")

            if obs.gate_result == "DENY":
                issues.append(
                    f"[{obs.tool_name}] DENIED by Gate — {obs.gate_reason or 'no reason'}"
                )

        # Determine overall status.
        if not skill_loaded:
            issues.append(
                "renaming-rules skill was never loaded. "
                "The agent may not have followed the required workflow."
            )
            status = "failed"
        elif moved_count > 0:
            status = "success"
        else:
            status = "failed"
            if not issues:
                issues.append("No files were moved by the agent.")

        return OrganizeWorkerResult(
            status=status,
            summary=(answer or "")[:500],
            moved_count=moved_count,
            destination=destination,
            issues=issues,
            raw_answer=answer or "",
            tool_calls=len(observations),
        )
