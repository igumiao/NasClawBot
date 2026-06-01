# 07-HelloAgents 框架能力审计

> 第一阶段产物：评估当前 HelloAgents 能力、NasClawBot 需求差距，以及替代 LangGraph 的最小可行迁移路径。

## 结论摘要

HelloAgents 适合作为 NasClawBot 的二次开发起点，但当前不能直接替代 LangGraph。

它已经具备 Agent/Tool 层的可用底座：统一 LLM adapter、Function Calling、`ToolResponse` 结构化协议、`ToolRegistry`、生命周期事件、trace、history 压缩、session 文件存储、skills 加载和 circuit breaker。

它缺少的是 NasClawBot 真正需要的 Runtime 层：通用暂停/恢复、HITL 审批、权限分级、typed workflow state、可测试的固定 workflow 编排、session/task 管理、SQLite 记忆存储。

因此迁移策略不是“把 LangGraph 换成 ReActAgent”，而是：

1. 先保持 FastAPI 与前端契约不变。
2. 新增 `HelloAgentWorkflowRunner` 并行替代 `LangGraphWorkflowRunner`。
3. 用当前 search-confirm-download 链路验证框架二开。
4. 成功后再将默认入口切到 HelloAgents，并移除 LangGraph 依赖。

## 当前 NasClawBot Workflow 基线

当前生产链路很小，主要文件：

- `app/workflow/graph.py`: LangGraph wiring 与 `LangGraphWorkflowRunner`
- `app/workflow/nodes.py`: keyword、search、confirmation、download execution 节点
- `app/workflow/state.py`: 最小 `AgentState`
- `app/api/chat_routes.py`: `/chat`、`/confirm` 路由与 adapter 注入
- `tests/test_workflow.py`: workflow 行为测试
- `tests/test_chat_api.py`: API 契约测试

实际流程：

```text
/chat
  user_message
    -> keyword_finder
    -> search_mteam
    -> build_confirmation_payload
    -> status=awaiting_confirmation

/confirm approve
  confirmation_payload
    -> execute_download
    -> receipt
    -> status=completed
```

当前 LangGraph 提供的价值很有限：节点顺序、条件入口、状态合并。真正重要的业务能力在节点函数、domain model、adapter、route protocol 和测试里。

## HelloAgents 能力矩阵

| 能力 | 当前状态 | 可复用程度 | 证据 | 迁移判断 |
|---|---:|---:|---|---|
| 统一 LLM adapter | 已有 | 高 | `hello_agents/core/llm.py`, `hello_agents/core/llm_adapters.py` | 可替代 `app/llm/client.py` 的一部分，但要先做配置适配 |
| Function Calling | 已有 | 高 | `HelloAgentsLLM.invoke_with_tools`, `ReActAgent` | 优先用于 keyword/media request 结构化抽取 |
| Tool 基类 | 已有 | 高 | `hello_agents/tools/base.py` | 可包装 M-Team search、qB submit、未来 TMDB/Emby |
| ToolResponse | 已有 | 高 | `hello_agents/tools/response.py` | 适合作为节点间结构化通信协议 |
| ToolRegistry | 已有 | 中 | `hello_agents/tools/registry.py` | 可用，但需要加入权限、approval、async timeout |
| CircuitBreaker | 已有 | 中 | `hello_agents/tools/circuit_breaker.py` | 可作为工具失败保护，不等同于安全审批 |
| ToolFilter | 已有 | 低到中 | `hello_agents/tools/tool_filter.py` | 目前是 allow/deny，不足以表达 READONLY/SIDE_EFFECT/DESTRUCTIVE |
| HistoryManager | 已有 | 中 | `hello_agents/context/history.py` | 可作为 Working Memory 底座，但缺 scoped memory |
| ContextBuilder | 半成品 | 低 | `hello_agents/context/builder.py` 注明 MemoryTool/RAGTool 已移除 | 不能直接承载 Memory Router，需要重写或收敛 |
| SessionStore | 已有 | 低到中 | `hello_agents/core/session_store.py` | JSON 文件存储可用于 demo，生产应接入 `app/storage/db.py` |
| TraceLogger | 已有 | 中 | `hello_agents/observability/trace_logger.py` | 可保留，但需与业务 request_id/session_id 对齐 |
| Lifecycle event | 已有 | 中 | `hello_agents/core/lifecycle.py` | 可扩展 APPROVAL_REQUIRED/RESOLVED |
| Streaming | 已有 | 中 | `arun_stream`, `StreamEvent` | 后续可接前端事件流，不是第一迁移关键 |
| ReActAgent | 已有 | 中 | `hello_agents/agents/react_agent.py` | 适合受控工具循环，不适合直接承载固定下载确认链路 |
| PlanSolveAgent | 已有 | 低 | `hello_agents/agents/plan_solve_agent.py` | 更像通用 demo，不作为 P0 基础 |
| Multi-agent/task tool | 部分存在 | 低 | `subagent_enabled` 配置与 task tool 注册点 | 还不是 NasClawBot 需要的 graph orchestration |

## 必须二开的 Runtime 能力

### 1. HITL 暂停/恢复

当前 HelloAgents 没有“工具需要用户审批 -> Agent 暂停 -> 外部确认 -> 从断点恢复”的通用机制。

需要扩展：

- `ToolStatus.PENDING_APPROVAL`
- `EventType.APPROVAL_REQUIRED`
- `EventType.APPROVAL_RESOLVED`
- `ApprovalRequest` / `ApprovalDecision`
- `AgentRuntime.resume(task_id, decision)`

NasClawBot 现有 `awaiting_confirmation` 可以迁移为第一种 approval 类型：`download_submission`。

### 2. Permission 分级

当前 `ToolFilter` 是白名单/黑名单，不能表达风险等级。

需要扩展：

- `ToolPermission.READONLY`
- `ToolPermission.SIDE_EFFECT`
- `ToolPermission.DESTRUCTIVE`
- `ToolRegistry.execute_tool()` 前置权限检查
- side effect 自动进入 approval flow
- destructive 使用更严格确认策略

映射：

- `mteam.search`: READONLY
- `mteam.get_download_url`: READONLY 或 SIDE_EFFECT，取决于站点是否产生下载行为
- `qb.add_torrent`: SIDE_EFFECT
- 未来文件删除/移动: DESTRUCTIVE

### 3. Workflow Runner

HelloAgents 现在有 Agent loop，但缺少固定 workflow runner。NasClawBot P0 仍需要可靠、可测试、可解释的固定流程。

需要新增：

- `HelloAgentWorkflowRunner`
- `WorkflowState`
- `WorkflowStep` 或轻量 `AgentNode`
- 明确状态返回：`awaiting_confirmation`、`completed`、`error`

第一阶段只实现顺序 workflow，不做 DAG。

### 4. 结构化抽取

当前 `FindKeywordLLM` 靠自由文本 JSON + 正则兜底。HelloAgents 已有 Function Calling，适合替代。

第一步不必抽完整 `MediaRequest`，可以先保持输出：

```json
{"keyword": "沙丘2"}
```

后续再升级为：

```json
{
  "title": "沙丘2",
  "year": 2024,
  "media_type": "movie",
  "quality": "4K",
  "extra_notes": null
}
```

### 5. SQLite Session/Memory

HelloAgents JSON `SessionStore` 不适合长期运行服务。NasClawBot 已有 `app/storage/db.py`，应作为生产存储基础。

P0 只需要：

- 保存 pending approval
- 保存 workflow status
- 保存 confirmation payload

Memory 的 episodic/semantic 可以后置。

## 保留的架构原则

ADR 001 中以下判断仍然正确：

- 单 Agent + 多 Tool 是当前阶段主线。
- 固定主流程 + 局部 LLM 决策点，比全自主 Agent loop 更可靠。
- 读工具细粒度，写工具粗粒度。
- 文件整理先检测报告，后人工确认执行。
- 记忆结构化优先。

需要替换的是实现方式：

- 不再用 LangGraph 的 `StateGraph` 作为主编排实现。
- 用 HelloAgents 二开出的 `WorkflowRunner` + `ToolRegistry` + approval runtime 作为框架层。

## 推荐第一条 Tracer Bullet

目标：不改前端，不改 API 契约，用 HelloAgents 跑通当前最小业务链路。

范围：

```text
ChatRequest
  -> HelloAgentWorkflowRunner.run_chat()
  -> structured keyword extractor
  -> MTeamSearchTool(Tool)
  -> ConfirmationPayload
  -> status=awaiting_confirmation

ConfirmRequest approve
  -> HelloAgentWorkflowRunner.run_confirm()
  -> approval decision
  -> QBAddTorrentTool(Tool)
  -> receipt
  -> status=completed
```

验收标准：

- `tests/test_workflow.py` 有等价 HelloAgents runner 测试。
- `/chat` 仍返回 `ConfirmationPayload`。
- `/confirm approve` 仍返回 receipt。
- `reject_and_refine` 仍保持当前 Phase 2A 行为。
- side-effect 工具不能绕过 approval 执行。

## 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| ReActAgent 过度自由 | 下载流程不稳定 | P0 不用 ReActAgent 承载主流程，只在局部抽取/判断使用 LLM |
| HelloAgents print 较多 | 服务日志噪声 | 二开时统一改为 logger |
| ToolRegistry 参数输入仍偏字符串 | 类型安全不足 | P0 runner 直接传 dict，并为工具加 Pydantic schema |
| SessionStore 文件化 | 多请求恢复不可靠 | 生产 pending 状态写 SQLite |
| 同时重写太多 | 回归风险高 | 并行 runner + 测试先行，LangGraph 暂不删除 |

