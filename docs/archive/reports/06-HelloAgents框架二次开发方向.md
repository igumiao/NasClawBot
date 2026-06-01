# 06-HelloAgents 框架二次开发方向

> 基于 HelloAgents v1.0.0 框架搬移后的扩展规划，面向 NasClawBot 的实际使用场景。

## 1. Memory 多层记忆

### 框架现状

`HistoryManager` 是追加式消息列表 + 简单压缩，`TokenCounter` 做 token 估算。没有真正的记忆分层，跨 session 记忆只能靠 `SessionStore` 的 JSON 文件序列化。

### 扩展设计

**Working Memory（工作记忆）**
- 复用 `HistoryManager`，增加 scoping 机制
- 每个子任务持有独立上下文，主 Agent 只拿到结构化摘要
- 子代理结束后 working memory 自动回收，防止 token 膨胀

**Episodic Memory（情景记忆）**
- 跨 session 的记忆检索层
- `SessionStore` 从 JSON 文件升级为 SQLite + 向量检索
- 复用 NasClawBot 现有的 `app/storage/db.py` SQLite 基础设施
- 关键对话片段自动摘要并入库，支持相似度检索

**Semantic Memory（语义记忆）**
- 新建 `MemoryStore` 抽象层
- 存储长期知识：用户偏好（"喜欢 4K HDR"）、历史决策（"上次下过的系列跳过"）、环境知识（"磁盘空间不足时的策略"）
- 以声明式 key-value + 向量嵌入双模式存储

**File-based Memory（文件记忆）**
- 框架的 `SkillLoader` 已经加载 `SKILL.md`，可扩展为也加载项目级/用户级记忆文件
- 类似 Claude Code 的 `CLAUDE.md` / `MEMORY.md` 模式
- Agent 启动时自动加载，作为 system prompt 的一部分注入

```
hello_agents/memory/
├── working.py      # WorkingMemory（scoped HistoryManager）
├── episodic.py     # EpisodicMemory（SQLite + 向量检索）
├── semantic.py     # SemanticMemory（key-value + embedding）
└── file_memory.py  # FileMemory（CLAUDE.md / MEMORY.md 加载器）
```

---

## 2. HITL 人工审核

### 框架现状

有生命周期 hooks（`on_start` / `on_step` / `on_finish` / `on_error`）和 `ToolFilter` 做工具访问控制，但**没有中断-等待-恢复的审批流**。

### 扩展设计

**ToolResponse 新增 PENDING_APPROVAL 状态**

```python
class ToolStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"
    PENDING_APPROVAL = "pending_approval"  # 新增
```

**新增 `on_approval_required` 生命周期事件**

```python
class EventType(Enum):
    # ... 现有事件
    APPROVAL_REQUIRED = "approval_required"  # 新增
    APPROVAL_RESOLVED = "approval_resolved"  # 新增
```

**审批流程**

1. Agent 执行到需要审批的工具 → 工具返回 `ToolResponse(status=PENDING_APPROVAL)`
2. 框架触发 `EventType.APPROVAL_REQUIRED` 事件，Agent 暂停
3. 外部系统（React 前端）展示审批卡片，用户确认/拒绝
4. 回调 `agent.resume(approval_result)` → 触发 `EventType.APPROVAL_RESOLVED`
5. Agent 从中断点继续执行

**与 NasClawBot 现有模式的映射**

NasClawBot 已有的 `awaiting_confirmation` 状态 + `/confirm` 路由，可以直接抽象为通用的 HITL 中间件，从 LangGraph workflow 层提升到框架层。

---

## 3. Multi-Agent 编排

### 框架现状

`TaskTool` 支持子代理调用（树状委托），`PlanSolveAgent` 有规划-执行模式。但没有 DAG/图编排能力，不支持并行节点和条件分支。

### 扩展设计

**核心抽象**

```
AgentNode（执行单元）+ ConditionalEdge（条件分支）+ SharedState（共享上下文）
```

- **AgentNode**: 包装一个 Agent 实例 + 输入/输出 schema
- **ConditionalEdge**: 基于 State 字段的路由逻辑
- **SharedState**: 框架的 `ExecutionContext` 已经是简化版，扩展为支持 schema 定义和类型校验

**编排模式**

- **Sequential**: A → B → C（已有 PlanSolveAgent 模式）
- **Parallel**: A1 ∥ A2 ∥ A3 → B（框架 `max_concurrent_tools` 已支持工具并行，扩展为 Agent 并行）
- **Conditional**: A → (if x then B else C) → D
- **Loop**: A → B → (condition) → A（类似 ReActAgent loop，但跨 Agent）

**与 LangGraph 的关系**

LangGraph 已经验证了 workflow pattern 在 NasClawBot 的可行性。框架层的编排可以做更轻量的版本：
- 用 `ToolResponse` 作为节点间通信协议（比 LangGraph 的纯文本 state 更结构化）
- 编排层只关心 routing，不关心 LLM 调用细节

```
hello_agents/orchestration/
├── graph.py        # AgentGraph（StateGraph 轻量实现）
├── node.py         # AgentNode
├── edge.py         # ConditionalEdge
└── state.py        # SharedState（扩展 ExecutionContext）
```

---

## 4. Permission / 安全分级

### 框架现状

`ToolFilter` 是二元的 allow/deny（白名单/黑名单），没有风险分级。

### 扩展设计

**三级风险模型**

| 等级 | 类型 | 示例工具 | 策略 |
|------|------|----------|------|
| `READONLY` | 只读 | search, list, read | 自动执行 |
| `SIDE_EFFECT` | 副作用 | download, write, create | HITL 确认 |
| `DESTRUCTIVE` | 破坏性 | delete, format, rm | 双重确认 |

**实现路径**

```python
class ToolPermission(Enum):
    READONLY = "readonly"
    SIDE_EFFECT = "side_effect"
    DESTRUCTIVE = "destructive"

class Tool(ABC):
    permission: ToolPermission = ToolPermission.READONLY  # 默认只读
```

`ToolRegistry.execute_tool()` 在调用前检查权限等级：
- `READONLY` → 直接执行
- `SIDE_EFFECT` → 触发 HITL approval flow
- `DESTRUCTIVE` → 双重确认（HITL + CircuitBreaker 连续拒绝熔断）

与 HITL 体系合并设计，`CircuitBreaker` 作为安全兜底。

---

## 5. 结构化输出与约束

### 框架现状

`ToolResponse` 天生是结构化的（`status` + `data` + `error_info`），但 Agent 之间的信息传递大量依赖自由文本。

### 扩展设计

- LLM 的 tool call arguments 就是 schema-constrained JSON，天然比自由文本解析可靠
- 下游节点直接消费 `ToolResponse.data` 而非解析 `ToolResponse.text`
- 每个 AgentNode 的输入/输出声明为 typed schema，编排层在编译期校验

**与 NasClawBot 现有痛点的对应**

keyword extraction 目前是 LLM 自由输出 JSON + 正则兜底。改用 function calling + `ToolResponse.data`：
- LLM 被强制输出符合 schema 的 JSON（OpenAI/Anthropic/Gemini 均支持）
- 解析成功率从 "靠正则兜底" 提升到接近 100%
- 不需要 LangGraph 的纯文本 state 传递

---

## 6. Persistent Agent Runtime

### 框架现状

Request-response 模式：`agent.run(input)` → 返回结果。Agent 是无状态的，每次调用创建新的执行上下文。

### 扩展设计

**AgentRuntime 抽象层**

```python
class AgentRuntime:
    """长时间运行的 Agent 服务"""
    
    async def start(self): ...
    async def stop(self): ...
    async def submit_task(self, task: Task) -> TaskHandle: ...
    async def cancel_task(self, task_id: str): ...
```

**三种运行模式**

- **后台调度（Cron）**: 定时检查 RSS 更新、磁盘空间、种子健康度 → 触发 Agent 决策
- **事件驱动（Event）**: qB 下载完成事件 → 触发重命名/刮削/通知流程
- **持续 Loop**: Agent 一直在跑，从消息队列消费任务，持续做决策

**与 NasClawBot 的对接**

FastAPI 作为 HTTP 层接收用户请求，`AgentRuntime` 作为后台引擎持续运行：
- `/chat` → `runtime.submit_task(ChatTask(...))`
- qB webhook → `runtime.submit_task(DownloadCompleteTask(...))`
- cron 触发器 → `runtime.submit_task(HealthCheckTask(...))`

---

## 7. 多用户 / 多会话隔离

### 框架现状

单 Agent 实例模式。`SessionStore` 支持单 session 的保存/恢复，但没有并发 session 管理。

### 扩展设计

- **SessionManager**: 管理多个并发 session，每个 session 持有独立的 `HistoryManager` + `ToolRegistry`
- **UserProfile**: 对接 NasClawBot 现有的 `preference_store`，每个用户拥有独立的偏好和权限
- **TaskQueue**: 并发任务队列 + worker pool，限制同时执行的 Agent 数量

```
hello_agents/runtime/
├── session_manager.py   # 多 session 生命周期管理
├── user_profile.py      # 用户偏好 + 权限
└── task_queue.py        # 任务队列 + worker pool
```

---

## 优先级建议

按 NasClawBot 的实际需求排序：

| 优先级 | 方向 | 理由 |
|--------|------|------|
| P0 | HITL + Permission | NasClawBot 最核心的差异化能力，框架 hooks + ToolResponse 可直接扩展 |
| P0 | Memory（Working + Episodic） | 解决 "Agent 不记得上次聊了什么" 的基础体验 |
| P1 | Multi-Agent 编排 | 把固定 LangGraph workflow 升级为动态 planning + 子代理协作 |
| P1 | 结构化输出 | 解决 keyword extraction 脆弱性问题 |
| P2 | Agent Runtime | 把 Agent 从 request-response 升级为常驻服务 |
| P2 | 多用户隔离 | 当前单用户场景够用，多用户时再扩展 |
| P3 | Memory（Semantic + File） | 依赖前两层 Memory 稳定后再做 |
