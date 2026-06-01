# Memory、Context 与 Prompt 构造分析

> 分析日期：2026-05-22
> 分支：v2
> 分析目标：理解 Agent 如何具备上下文连续性

---

## 一、Memory / Context 相关源码定位

| 文件 | 相关概念 | 重要类 / 函数 | 作用 | 是否核心 |
| ---- | -------- | ------------- | ---- | -------- |
| `app/agent/middleware/memory.py` | 长期记忆、文件记忆、用户偏好 | `MemoryMiddleware`, `MEMORY_SYSTEM_PROMPT`, `MEMORY_ONBOARDING_PROMPT` | 扫描 `.md` 文件注入长期记忆到 System Prompt | ★★★★★ |
| `app/agent/memory/__init__.py` | 对话记忆、会话缓存、TTL | `MemoryManager`, `ConversationMemory` | 内存缓存对话历史（`List[BaseMessage]`），每小时清理过期记忆 | ★★★★★ |
| `app/agent/prompt/__init__.py` | System Prompt 构造、模板、渠道适配 | `PromptManager`, `get_agent_prompt()` | 组装最终 System Prompt：核心提示词 + 渠道能力 + 系统信息 | ★★★★★ |
| `app/agent/prompt/System Core Prompt.txt` | Agent 身份、行为模型、核心工作流 | 纯文本（含 `{placeholder}` 占位符） | 定义 Agent 的 8 大核心能力、5 步工作流、工具调用策略 | ★★★★★ |
| `app/agent/prompt/System Tasks.yaml` | 后台任务定义、模板上下文 | `SystemTaskTypeDefinition`, heartbeat/health_check/transfer_failed_retry 等 | 定义 8 种后台系统任务的 Prompt 模板 | ★★★★ |
| `app/agent/middleware/runtime_config.py` | Persona、运行时配置、动态注入 | `RuntimeConfigMiddleware` | 每次模型调用前动态注入当前激活的 Persona 和 extra_context | ★★★★ |
| `app/agent/runtime.py` | Persona 管理、配置布局、迁移 | `AgentRuntimeManager`, `AgentRuntimeConfig`, `PersonaDefinition` | 管理 Persona 的 CRUD 和切换，渲染 `<agent_persona>` 标签 | ★★★★ |
| `app/agent/middleware/activity_log.py` | 活动日志、历史摘要、自动记录 | `ActivityLogMiddleware`, `_summarize_with_llm()` | 自动记录每次 Agent 交互摘要，注入近 3 天活动日志到 Prompt | ★★★★ |
| `app/agent/middleware/skills.py` | Skills、渐进式披露 | `SkillsMiddleware` | 扫描 `SKILL.md` 文件，按需注入技能说明到 System Prompt | ★★★ |
| `app/agent/middleware/jobs.py` | 定时任务、YAML frontmatter | `JobsMiddleware`, `JobMetadata` | 扫描 `JOB.md` 文件，注入活跃任务元数据 | ★★★ |
| `app/schemas/agent.py` | 数据模型 | `ConversationMemory`, `AgentState`, `UserMessage`, `ToolResult` | 定义 Agent 相关的 Pydantic 数据模型 | ★★★ |
| `app/chain/message.py` | 会话管理、Session ID | `_user_sessions`, `_get_or_create_session_id()`, `_bind_session_id()` | 用户级的 session 创建/复用（24h TTL） | ★★★★ |
| `app/agent/middleware/utils.py` | Prompt 拼接工具 | `append_to_system_message()` | 将文本追加到 SystemMessage 的 content_blocks | ★★ |
| `app/agent/__init__.py` | Agent 执行、状态保存 | `MoviePilotAgent._execute_agent()` → `memory_manager.save_agent_messages()` | 每次 Agent 执行后将完整 messages 保存到 MemoryManager | ★★★★★ |
| `app/agent/middleware/tool_selection.py` | 工具筛选、上下文 | `ToolSelectorMiddleware` | 基于用户消息筛选相关工具子集，使用独立 LLM 调用 | ★★★ |
| `app/agent/llm/helper.py` | LLM 模型创建、max_tokens | `LLMHelper.get_llm()` | 创建 LLM 实例，读取 `LLM_MAX_CONTEXT_TOKENS` 配置 | ★★★ |

---

## 二、Memory 分层分析

### 2.1 五层记忆全景

| Memory 类型 | 是否存在 | 存储位置 | 注入方式 | 源码证据 | 评价 |
| ----------- | -------- | -------- | -------- | -------- | ---- |
| **1. 短期记忆（对话消息）** | **存在** | `MemoryManager.memory_cache` 内存字典 + 可选 Redis（TTL 自动过期） | `memory_manager.get_agent_messages()` → `messages` 列表直接传给 `agent.ainvoke(messages)` | `app/agent/memory/__init__.py:66-79`; `app/agent/__init__.py:642-644` | 完整保存 `List[BaseMessage]`，包含 tool_call/tool_result，是标准的 LangChain 对话记忆模式 |
| **2. 长期记忆（用户偏好）** | **存在** | 文件系统 `config/agent/memory/*.md` | `MemoryMiddleware.abefore_agent()` 扫描 → `modify_request()` 拼接到 System Prompt 的 `<agent_memory>` 标签中 | `app/agent/middleware/memory.py:296-396` | 创新的文件记忆方案，Agent 通过 `write_file`/`edit_file` 工具自行管理记忆 |
| **3. 任务记忆（Agent run 中间状态）** | **存在** | LangGraph `InMemorySaver` checkpoint + middleware state | LangGraph 自动在每个 node 执行后保存 checkpoint；中间件通过 `PrivateStateAttr` 管理自己的状态 | `app/agent/__init__.py:614` — `checkpointer=InMemorySaver()`; 各 middleware 的 state_schema | 框架级状态管理，但中间状态不跨 run 持久化（InMemorySaver 进程内有效） |
| **4. 工具结果记忆** | **存在** | LangGraph messages 列表（tool_call + ToolMessage） | LangChain Agent Loop 自动将 tool_result 作为 ToolMessage 追加到 messages 列表 | `app/agent/tools/base.py:222-224` — `format_tool_result_for_agent()` 格式化后返回 | 工具结果直接进入对话上下文，64KB 截断限制 |
| **5. 压缩记忆** | **存在** | LangChain `SummarizationMiddleware` + `ActivityLogMiddleware` | `SummarizationMiddleware` 在上下文达到 85% 时自动压缩历史消息；`ActivityLogMiddleware` 每次交互后调用 LLM 生成一句话摘要 | `app/agent/__init__.py:581-583` — `SummarizationMiddleware(model=non_streaming_model, trigger=("fraction", 0.85))`; `app/agent/middleware/activity_log.py:377-403` | 双重压缩机制：实时的 context window 管理 + 长期的 activity log |

### 2.2 逐类详细分析

#### 2.2.1 短期记忆：对话消息

```
存储: MemoryManager.memory_cache (Dict[str, ConversationMemory])
Key:  "{user_id}:{session_id}"
Model: ConversationMemory (Pydantic, app/schemas/agent.py:10)
  - session_id: str
  - user_id: Optional[str]
  - messages: List[BaseMessage]  ← LangChain 原生消息列表
  - updated_at: datetime

读取: memory_manager.get_agent_messages(session_id, user_id)
       → 返回 List[BaseMessage]，直接传给 agent.ainvoke()

写入: memory_manager.save_agent_messages(session_id, user_id, messages)
       → 覆盖写入（每次 Agent 执行后保存完整 messages）
       → 注意：是 OVERWRITE 而非 APPEND，因为 LangGraph Agent 已更新了整个 messages 列表

过期: 每小时清理 > LLM_MEMORY_RETENTION_DAYS 的缓存
```

**关键设计点**：不是追加新消息，而是每次执行后**整体覆盖**。因为 LangChain 的 Agent Loop 已经在 messages 列表中追加了 tool_call 和 tool_result，返回的 `agent.get_state()` 包含完整的更新后消息列表。

#### 2.2.2 长期记忆：文件系统 Memory

```
存储: config/agent/memory/*.md 文件
格式: Markdown 自由格式，支持多文件分主题组织
      - MEMORY.md (主文件，用户偏好/沟通风格)
      - DOWNLOAD_PREFERENCES.md (下载偏好)
      - MEDIA_RULES.md (媒体规则)
      - ... (任意 Agent 创建的主题文件)

扫描: MemoryMiddleware.abefore_agent()
      → 扫描 memory_dir 下所有 .md 文件（不递归子目录）
      → 文件大小限制: 100KB (MAX_MEMORY_FILE_SIZE)
      → 按文件名排序，MEMORY.md 优先

注入: MemoryMiddleware.modify_request()
      → 格式化为 <agent_memory>...</agent_memory> XML 块
      → append_to_system_message() 追加到 System Prompt

空记忆引导: 首次用户（无 .md 文件）时注入 MEMORY_ONBOARDING_PROMPT
              → 引导 Agent 在必要时主动收集用户偏好
              → 要求使用 write_file 工具保存
```

**关键设计点**：这是一个"**Agent 自管理记忆**"方案。不是传统的"系统收集用户偏好→存入数据库→注入 Prompt"，而是**让 Agent 自己通过文件工具管理记忆**。优点是完全解耦、无需额外数据库 schema；缺点是依赖 LLM 的判断力，可能在关键偏好上遗漏。

#### 2.2.3 任务记忆：中间状态

**LangGraph Checkpoint（进程内）**：
```
InMemorySaver() 在每个 LangGraph node 执行后保存 state
Key: thread_id = session_id
State: {"messages": [...], ...各中间件 state}
生命周期: 进程生命周期（重启丢失）
```

**中间件私有状态**（单次 Agent run 有效）：
| 中间件 | 状态字段 | 用途 |
|--------|---------|------|
| MemoryMiddleware | `memory_contents`, `memory_empty` | 缓存已扫描的记忆文件 |
| ActivityLogMiddleware | `activity_log_contents` | 缓存已加载的活动日志 |
| JobsMiddleware | `jobs_metadata` | 缓存已扫描的 Job 列表 |
| SkillsMiddleware | `skills_state` | 缓存已加载的技能 |
| ToolSelectorMiddleware | `selected_tool_names` | 本次 run 筛选出的工具列表 |

这些状态都标记为 `PrivateStateAttr`，不会进入最终的 Agent 状态，不会跨 run 持久化。

#### 2.2.4 工具结果记忆

```
存储: LangGraph messages 列表中的 ToolMessage
内容: format_tool_result_for_agent() 格式化后的字符串
截断: 默认 64KB (DEFAULT_TOOL_RESULT_MAX_CHARS)
      超长时返回结构化预览: {"tool_result_truncated": true, "content_preview": "...", ...}
```

工具结果直接进入对话上下文，可以被后续 LLM 调用引用。这是标准的 Function Calling 模式，不需要额外的检索步骤。

#### 2.2.5 压缩记忆

**双重压缩机制**：

| 机制 | 触发条件 | 压缩方式 | 用途 |
|------|---------|---------|------|
| `SummarizationMiddleware` | 上下文达到模型 max_input_tokens 的 85% | LLM 自动摘要较早的消息 | 实时 context window 管理，防止 token 溢出 |
| `ActivityLogMiddleware` | 每次 Agent 执行完毕（`aafter_agent`） | 调用 LLM 对本轮对话生成一句话摘要（≤80 字） | 长期活动记录，注入近 3 天日志到下次 System Prompt |

**SummarizationMiddleware 配置**：
```python
# app/agent/__init__.py:581-583
SummarizationMiddleware(
    model=non_streaming_model,
    trigger=("fraction", 0.85),  # 上下文达到 85% 时触发
)
```

这是一个 LangChain 内置中间件，使用一个独立的非流式 LLM 调用来摘要化较早的消息，保持上下文窗口不溢出。

**ActivityLog 的工作流**：
```
Agent 执行完毕
  → _extract_last_round(messages)           # 提取最后一轮 HumanMessage 开始的对话
  → _format_conversation_for_summary()      # 格式化为文本（截断 4000 字）
  → _summarize_with_llm(conversation_text)  # 调用 LLM 生成一句话摘要
  → _append_activity(summary)               # 追加到 activity/YYYY-MM-DD.md
  → _cleanup_old_logs()                     # 清理 7 天前的日志
```

---

## 三、Memory 存储位置全景

| 记忆数据 | 存储介质 | Schema / Model | 读写位置 | 生命周期 |
| -------- | -------- | -------------- | -------- | -------- |
| 对话消息 (`List[BaseMessage]`) | 内存 `dict`（可选 Redis） | `ConversationMemory` (Pydantic) | 读: `get_agent_messages()` → `app/agent/memory/__init__.py:66`; 写: `save_agent_messages()` → `app/agent/memory/__init__.py:81` | 内存: 按 `LLM_MEMORY_RETENTION_DAYS` 过期; Redis: TTL 自动过期 |
| 长期记忆文件 | 文件系统 `config/agent/memory/*.md` | Markdown 自由格式 | 读: `MemoryMiddleware._scan_memory_files()` → `app/agent/middleware/memory.py:276`; 写: Agent 通过 `write_file`/`edit_file` 工具 | 持久化，用户/Agent 手动管理 |
| Persona 定义 | 文件系统 `config/agent/runtime/personas/*/PERSONA.md` | YAML frontmatter + Markdown body (`PersonaDefinition`) | 读: `AgentRuntimeManager.load_runtime_config()` → `app/agent/runtime.py:224` | 持久化，用户手动创建或 Agent 通过工具管理 |
| 当前激活 Persona | 文件系统 `config/agent/runtime/CURRENT_PERSONA.md` | YAML frontmatter (`version`, `active_persona`, `extra_context_files`) | 读: `_load_from_root()` → `app/agent/runtime.py:437`; 写: `set_active_persona()` | 持久化 |
| 活动日志 | 文件系统 `config/agent/activity/YYYY-MM-DD.md` | Markdown 条目（`- **HH:MM** 摘要`） | 写: `_append_activity()` → `app/agent/middleware/activity_log.py:280`; 读: `_load_recent_logs()` → 同文件:260 | 7 天保留，自动清理 |
| Jobs 元数据 | 文件系统 `config/agent/jobs/*/JOB.md` | YAML frontmatter (`JobMetadata`) | 读: `load_jobs_metadata()` → `app/agent/middleware/jobs.py`; 写: Agent 通过文件工具 | 持久化 |
| Skills 定义 | 文件系统 `config/agent/skills/*/SKILL.md` | YAML frontmatter + Markdown body | 读: `SkillsMiddleware` 扫描 | 持久化 |
| LangGraph Checkpoint | 内存 `InMemorySaver` | LangGraph 内部序列化格式 | 读/写: LangGraph 自动管理 | 进程生命周期 |
| 用户 Session 映射 | 类变量 `MessageChain._user_sessions` | `{userid: (session_id, last_time)}` | 读/写: `_get_or_create_session_id()` → `app/chain/message.py:887` | 24h TTL |
| Token 用量快照 | Agent 实例变量 `_SessionUsageSnapshot` | dataclass (model, input_tokens, output_tokens, total_tokens, ...) | 读: `get_session_status()` → `app/agent/__init__.py:317`; 写: `_record_usage()` → 同文件:286 | Agent 实例生命周期 |
| Tool 共享上下文 | Agent 实例变量 `_tool_context` | `dict` (user_reply_sent, reply_mode, should_dispatch_reply) | 读/写: Tool 和 Agent 共享 → `app/agent/tools/base.py:278-284` | 单次 Agent run |

---

## 四、Memory 注入到 LLM 的方式

### 4.1 一次 LLM 调用前的完整 Prompt 组装过程

```text
┌─────────────────────────────────────────────────────────────────┐
│              System Prompt 组装（create_agent 传入）              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [1] System Core Prompt.txt (基础模板)                            │
│      来源: app/agent/prompt/System Core Prompt.txt               │
│      组装: PromptManager.get_agent_prompt()                      │
│      占位符替换:                                                  │
│        {markdown_spec}      → 渠道 Markdown 能力说明              │
│        {verbose_spec}       → 啰嗦/简洁模式约束                   │
│        {button_choice_spec} → 按钮交互能力说明                    │
│        {voice_reply_spec}   → 语音回复能力说明                    │
│        {moviepilot_info}    → 主机名/IP/API端口/数据库/可用命令    │
│      ↓                                                           │
│  [2] 中间件链注入 (每次 awrap_model_call 时动态追加)               │
│      ├─ SkillsMiddleware       → <skills_instructions>           │
│      ├─ JobsMiddleware         → <active_jobs>                   │
│      ├─ RuntimeConfigMiddleware → <agent_runtime_config>         │
│      │                           + <agent_persona>               │
│      │                           + <agent_extra_context>          │
│      ├─ MemoryMiddleware       → <agent_memory>                  │
│      │  (或 ActivityLogMiddleware → <activity_log>)              │
│      └─ (SummarizationMiddleware 触发时自动压缩历史消息)           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   Messages 列表（历史对话）                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [3] 历史消息                                                    │
│      memory_manager.get_agent_messages(session_id, user_id)      │
│      → List[BaseMessage] (含历史 HumanMessage/AIMessage/         │
│        ToolMessage/ToolCall)                                     │
│                                                                  │
│  [4] 当前用户消息                                                │
│      结构化 JSON:                                                 │
│      HumanMessage(content=[                                      │
│        {"type": "text", "text": "{'message': '...', ...}"},     │
│        {"type": "image_url", "image_url": {"url": "data:..."}},  │
│      ])                                                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 10 项 Prompt 组成分析

| Prompt / Context 组成 | 数据来源 | 构造位置 | 是否动态 | 注入到哪里 | 作用 |
| --------------------- | -------- | -------- | -------- | ---------- | ---- |
| **1. System Core Prompt** | `app/agent/prompt/System Core Prompt.txt` 静态文件 | `PromptManager.get_agent_prompt()` (line 118) | 半动态（占位符按渠道/配置替换） | System Prompt 最外层 | 定义 Agent 身份、行为模型、8 大能力、5 步工作流 |
| **2. 渠道能力约束** | `ChannelCapabilityManager.get_capabilities()` 运行时查询 | `PromptManager._generate_formatting_instructions()` (line 373) | **是**（按渠道动态） | 注入到 System Prompt 的 `{markdown_spec}` | 告知 Agent 当前渠道是否支持 Markdown/按钮/图片 |
| **3. 啰嗦模式约束** | `settings.AI_AGENT_VERBOSE` 配置项 | `PromptManager.get_agent_prompt()` (line 147) | **是**（按配置动态） | 注入到 System Prompt 的 `{verbose_spec}` | 控制 Agent 工具调用时是否输出中间文本 |
| **4. 系统信息** | 运行时探测（hostname/IP/PATH/配置路径） | `PromptManager._get_moviepilot_info()` (line 282) | **是**（运行时动态） | 注入到 System Prompt 的 `{moviepilot_info}` | 告知 Agent 系统运行环境，含可用 shell 命令 |
| **5. Persona 配置** | 文件系统 `personas/*/PERSONA.md` | `RuntimeConfigMiddleware.modify_request()` → `AgentRuntimeConfig.render_prompt_sections()` (line 128) | **是**（每次模型调用动态加载，不缓存） | 追加到 System Prompt（`<agent_runtime_config>`, `<agent_persona>`, `<agent_extra_context>`） | 注入当前激活的人格定义和额外上下文 |
| **6. 文件长期记忆** | 文件系统 `memory/*.md` | `MemoryMiddleware.abefore_agent()` → `modify_request()` (line 360) | **是**（每次 Agent run 前扫描） | 追加到 System Prompt（`<agent_memory>`） | 注入用户偏好、历史规则等长期知识 |
| **7. 活动日志** | 文件系统 `activity/YYYY-MM-DD.md` | `ActivityLogMiddleware.abefore_agent()` → `modify_request()` (line 356) | **是**（每次 run 加载近 3 天） | 追加到 System Prompt（`<activity_log>`） | 让 Agent 了解近期做了什么，提供连续性 |
| **8. 历史对话消息** | `MemoryManager.memory_cache` | `MemoryManager.get_agent_messages()` (line 66) | **是**（跨 run 持久化） | 作为 `messages` 列表传给 `agent.ainvoke()` | 提供多轮对话上下文 |
| **9. 特定工具上下文** | Agent 处理时动态构建 | `MoviePilotAgent.process()` (line 647-663) | **是** | 当前 `HumanMessage` content（结构化 JSON + 图片 blocks） | 将图片、文件等复杂输入结构化传给 LLM |
| **10. Tool 执行结果** | Tool 子类 `run()` 返回值 | `MoviePilotTool._arun()` → `format_tool_result_for_agent()` (line 222) | **是** | 作为 `ToolMessage` 追加到 messages | 让 LLM 看到工具执行结果，决定下一步行动 |

### 4.3 关键注入机制：`append_to_system_message()`

```python
# app/agent/middleware/utils.py
def append_to_system_message(
    system_message: SystemMessage | None,
    text: str,
) -> SystemMessage:
    """将文本追加到系统消息的 content_blocks 末尾。"""
```

所有的中间件（Memory、ActivityLog、RuntimeConfig、Skills、Jobs）都使用这个方法**追加**内容到 System Prompt，而不是替换。这意味着 System Prompt 是**累积式构建**的：

```
System Core Prompt (固定)
  + Skills 说明 (动态)
  + Jobs 元数据 (动态)
  + Runtime Config + Persona (动态，不缓存)
  + Memory / ActivityLog (动态)
  + SummarizationMiddleware 压缩标记 (触发时)
```

---

## 五、Prompt 工程质量评价

| 评价项 | 当前实现 | 优点 | 问题 | 改进建议 |
| ------ | -------- | ---- | ---- | -------- |
| **1. 是否清晰分层？** | **是**。五层清晰分离：Core Prompt（身份/行为）→ 中间件注入（Memory/Persona/Skills）→ Channel Spec（渠道能力）→ System Info（环境信息）→ Messages（历史对话） | 职责分明，每层由独立模块管理 | 中间件注入顺序依赖隐式约定（代码中的列表顺序），文档中未显式说明 | 在配置文件中显式声明中间件顺序和职责 |
| **2. Prompt 是否集中管理？** | **部分集中**。Core Prompt 和 System Tasks 集中在 `app/agent/prompt/` 目录；Persona/Memory/Skills/Jobs 分散在 `config/agent/` 各子目录 | 核心 Prompt 由 `PromptManager` 统一加载和缓存 | 分散的文件系统记忆可能被用户或 Agent 随意修改 | 提供 Memory 文件的校验和版本管理 |
| **3. 是否容易维护？** | **中等**。Core Prompt 是纯文本文件，直观易读。但 prompt 和中间件注入逻辑分散在多处 | 核心 Prompt 用 `.txt` 文件，非开发人员也能阅读修改 | YAML/占位符/Python 代码多处管理，修改时需要跨文件追踪 | 统一为 Prompt Registry，提供可视化编辑界面 |
| **4. 是否支持多场景扩展？** | **是**。System Tasks 用 YAML 定义 8 种后台任务类型，每种有独立的 header/objective/steps/task_rules | 声明式定义，新增任务类型只需加 YAML | YAML 和 Python dataclass 耦合，新增字段需改代码 | 使用 JSON Schema 校验 YAML，减少隐式契约 |
| **5. 是否容易上下文污染？** | **中等风险**。MemoryMiddleware 将所有 `.md` 文件全量注入，ActivityLog 注入近 3 天日志 | 信息全面 | 如果用户创建大量 memory 文件或有大量 activity，可能塞入无关信息 | 增加语义相关性过滤（但需要 Embedding） |
| **6. 是否容易塞入无关信息？** | **是，存在风险**。`SummarizationMiddleware` 只在 85% 阈值才触发压缩，此前的冗余信息缺乏主动清理 | 自动化程度高 | 缺少主动的上下文去噪机制 | 增加基于 relevance score 的上下文裁剪 |
| **7. 是否有 token 超限风险？** | **有保护但不完善**。`SummarizationMiddleware(trigger=("fraction", 0.85))` 自动压缩；Memory 文件有 100KB 限制；Tool 结果有 64KB 截断 | 多层截断保护 | 依赖单一阈值，可能在某些边缘情况下（超长 System Prompt + 大量工具调用）溢出 | 增加 pre-flight token counting，超限时主动裁剪 |
| **8. 是否把业务规则和语言风格混在一起？** | **否，设计良好**。Core Prompt 的 `<agent_core>` 定义业务规则，`<communication_runtime>` 定义沟通风格，Persona 单独注入 | 关注点分离 | Persona 文本可能包含业务指令，理论上可能和 Core Prompt 冲突 | Core Prompt 中已有 "memory/persona must NOT override core identity" 的约束 |
| **9. 是否有 prompt version 管理？** | **部分有**。`CURRENT_PERSONA_SCHEMA_VERSION=3`, `PERSONA_SCHEMA_VERSION=1`, `SYSTEM_TASKS_SCHEMA_VERSION=2` | YAML frontmatter 中有 version 字段 | Core Prompt 无版本号；中间件注入的 prompt 模板无版本管理 | 对所有 prompt 模板增加 version 字段和迁移脚本 |
| **10. 是否方便测试？** | **较难**。Prompt 由多层动态拼接，需要完整运行 Agent 才能看到最终 prompt | — | 没有 prompt 预览/dry-run 工具；没有 prompt 单元测试 | 增加 `/debug prompt` 命令输出完整 System Prompt；编写 prompt 快照测试 |

---

## 六、Memory Schema 提炼

基于源码提炼的设计思想，抽象为伪代码：

```python
# ============================================================
# 短期记忆：当前对话的完整消息历史（LangChain 原生格式）
# 存储: MemoryManager.memory_cache (内存)
# 生命周期: 按 LLM_MEMORY_RETENTION_DAYS 过期
# ============================================================
class ConversationMemory:
    session_id: str              # 会话唯一标识
    user_id: Optional[str]       # 用户标识
    messages: List[BaseMessage]  # LangChain 消息列表
                                 # 包含: HumanMessage, AIMessage,
                                 #       ToolMessage, ToolCall
    updated_at: datetime         # 最后更新时间（用于 TTL 判断）

# ============================================================
# 长期记忆：文件系统持久化的用户知识和偏好
# 存储: config/agent/memory/*.md
# 管理: Agent 自管理（通过 write_file/edit_file 工具）
# 注入: MemoryMiddleware → System Prompt 的 <agent_memory>
# ============================================================
class FileMemory:
    """单个人类可读的记忆文件"""
    path: str              # 文件路径
    filename: str          # 文件名（如 MEMORY.md, DOWNLOAD_PREFERENCES.md）
    content: str           # Markdown 自由格式内容
    size: int              # 文件大小（限制 100KB）

class MemoryContext:
    """注入到 System Prompt 的记忆快照"""
    files: List[FileMemory]           # 所有 .md 文件内容
    is_empty: bool                    # 是否为新用户（触发 onboarding）
    primary_file: str                 # 主记忆文件路径（MEMORY.md）
    memory_dir: str                   # 记忆目录路径

# ============================================================
# Persona：当前激活的 Agent 人格定义
# 存储: config/agent/runtime/personas/{id}/PERSONA.md
# 注入: RuntimeConfigMiddleware → System Prompt 的 <agent_persona>
# ============================================================
class PersonaDefinition:
    persona_id: str          # 人格唯一标识
    label: str               # 显示名称
    description: str         # 简短描述
    aliases: List[str]       # 别名（用于切换匹配）
    text: str                # 人格正文（注入到 System Prompt）
    path: Path               # 文件路径

class AgentRuntimeConfig:
    active_persona: str                       # 当前激活的人格 ID
    persona: PersonaDefinition                # 当前人格定义
    available_personas: List[PersonaDefinition]  # 所有可用人格
    extra_context_paths: List[Path]           # 额外上下文文件
    extra_contexts: List[Tuple[Path, str]]     # 额外上下文内容

# ============================================================
# 活动日志：自动记录的历史交互摘要
# 存储: config/agent/activity/YYYY-MM-DD.md
# 注入: ActivityLogMiddleware → System Prompt 的 <activity_log>
# ============================================================
class ActivityLog:
    date: str                    # 日期 (YYYY-MM-DD)
    entries: List[str]           # 条目列表（- **HH:MM** 摘要）
    total_chars: int             # 总字符数（限制 256KB/天）

class ActivityLogContext:
    recent_logs: Dict[str, str]  # 近 3 天的日志内容
    retention_days: int          # 保留天数（默认 7 天）

# ============================================================
# 后台任务：Agent 需要感知的待处理任务
# 存储: config/agent/jobs/{id}/JOB.md
# 注入: JobsMiddleware → System Prompt
# ============================================================
class JobMetadata:
    id: str              # Job 标识符
    name: str            # Job 名称
    description: str     # Job 描述
    schedule: str        # "once" | "recurring"
    status: str          # "pending" | "in_progress" | "completed" | "cancelled"
    last_run: Optional[str]  # 上次执行时间
    path: str            # JOB.md 文件路径

# ============================================================
# Skills：Agent 可用的领域技能
# 存储: config/agent/skills/{name}/SKILL.md
# 注入: SkillsMiddleware → System Prompt（渐进式披露）
# ============================================================
class SkillDefinition:
    name: str             # 技能名称
    description: str      # 简短描述（首先注入）
    full_instructions: str  # 完整指令（Agent 请求时才注入）

# ============================================================
# Session：用户会话绑定
# 存储: MessageChain._user_sessions (类变量)
# ============================================================
class UserSession:
    user_id: str          # 用户标识
    session_id: str       # 当前会话 ID
    last_active: datetime # 最后活跃时间
    timeout: timedelta    # 超时时间（24h）

# ============================================================
# 完整 Memory 注入快照（一次 LLM 调用时的上下文）
# ============================================================
class InjectedMemoryContext:
    """一次 LLM 调用时注入到 System Prompt 的完整上下文"""
    # 固定层
    core_prompt: str                     # 系统核心提示词
    channel_constraints: str             # 渠道能力约束
    system_info: str                     # 系统环境信息

    # 动态层（每次模型调用重新计算）
    persona: AgentRuntimeConfig          # 当前人格配置
    file_memories: MemoryContext         # 长期文件记忆
    activity_log: ActivityLogContext     # 近期活动日志
    active_jobs: List[JobMetadata]       # 活跃后台任务
    available_skills: List[str]          # 可用技能列表
    selected_tools: List[str]            # 工具筛选结果
```

---

## 七、NAS 项目的 MemoryContext 推荐设计

基于 MoviePilot 的设计优缺点，为「NAS 私有媒体库智能管理系统」设计推荐结构：

```typescript
// ============================================================
// 一次 Agent Run 临时存在的上下文（不持久化）
// ============================================================
interface RunTemporaryContext {
  // 当前工具调用链的中间状态
  pendingToolCalls: {
    toolName: string;
    params: Record<string, any>;
    status: 'pending' | 'running' | 'done' | 'failed';
    result?: string;
  }[];

  // 本轮搜索结果（避免重复搜索）
  searchCache: {
    query: string;
    timestamp: number;
    results: MediaCandidate[];
  } | null;

  // 用户确认等待状态
  userConfirmation: {
    awaiting: boolean;
    promptMessage: string;
    options: { label: string; value: string }[];
  } | null;

  // 本轮已使用的 token 估算
  tokenUsage: {
    promptTokens: number;
    completionTokens: number;
    estimatedTotal: number;
  };
}

// ============================================================
// 当前 Conversation 内保存的上下文（跨多轮有效，24h TTL）
// ============================================================
interface ConversationContext {
  conversationId: string;
  userId: string;
  startedAt: Date;
  lastActiveAt: Date;

  // LangChain 标准消息列表（包含 tool_call + tool_result）
  messages: BaseMessage[];

  // 当前会话的意图链（用于追踪用户的多步操作）
  intentChain: {
    primaryIntent: string;          // "search_and_download" | "subscribe" | "library_scan" | ...
    subIntent?: string;             // "quality_selection" | "season_selection" | ...
    resolvedParams: Record<string, any>;  // 已确认的参数
    pendingParams: string[];        // 待确认的参数名
  };

  // 当前会话中已提及的媒体引用
  mentionedMedia: {
    tmdbId: number;
    title: string;
    type: 'movie' | 'tv';
    year?: number;
    mentionedAt: number;  // timestamp
  }[];

  // 当前会话中的任务追踪
  activeTask?: {
    taskId: string;
    taskType: 'download' | 'subscribe' | 'transfer' | 'scan';
    status: 'initiating' | 'searching' | 'confirming' | 'executing' | 'completed' | 'failed';
    candidates?: MediaCandidate[];
    selectedCandidate?: MediaCandidate;
    selectedQuality?: string;
    downloadProgress?: number;
    errorMessage?: string;
  };

  // 不应塞进 Prompt 的冗余信息
  _internal: {
    toolCallHistory: { tool: string; timestamp: number; duration: number }[];
    rawSearchResponses: any[];  // 仅用于调试
  };
}

// ============================================================
// 长期保存的用户偏好（持久化到数据库 + 可选文件备份）
// ============================================================
interface UserProfile {
  userId: string;
  createdAt: Date;
  updatedAt: Date;

  // 媒体偏好
  mediaPreferences: {
    preferredLanguages: string[];       // ["zh", "en", "ja"]
    preferredResolution: string;        // "1080p" | "4K" | "auto"
    preferredQualitySources: string[];  // ["BluRay", "WEB-DL", "HDRip"]
    dislikedGenres: string[];           // ["horror", "reality-tv"]
    favoriteGenres: string[];           // ["sci-fi", "animation"]
    subtitlePreference: string;         // "embedded" | "external" | "none"
    codecPreference?: string;           // "H.264" | "H.265" | "AV1"
  };

  // 下载偏好
  downloadPreferences: {
    defaultDownloadClient: string;      // "qBittorrent" | "Aria2" | "Transmission"
    maxConcurrentDownloads: number;     // 3
    seedRatioLimit: number;             // 2.0
    preferredReleaseGroups: string[];   // ["FRDS", "CMCT", "MTeam"]
    avoidedReleaseGroups: string[];     // []
    autoDownloadNewEpisodes: boolean;   // 订阅的剧集出新集时自动下载
  };

  // 通知偏好
  notificationPreferences: {
    notifyOnDownloadComplete: boolean;
    notifyOnNewEpisode: boolean;
    notifyOnTransferComplete: boolean;
    preferredChannel: string;           // "telegram" | "wechat" | "web"
    quietHours?: { start: string; end: string };  // "23:00"-"07:00"
  };

  // 交互偏好
  interactionPreferences: {
    autoConfirmWhenConfident: boolean;  // 高置信度时跳过确认
    maxCandidatesToShow: number;        // 每次展示候选数（默认 3）
    verboseMode: boolean;               // 是否输出中间步骤
    responseStyle?: string;             // "concise" | "detailed" | "fun"
  };

  // 媒体库信息（缓存，定期刷新）
  mediaLibrarySummary: {
    totalMovies: number;
    totalTvShows: number;
    totalEpisodes: number;
    lastScanAt: Date;
  };
}

// ============================================================
// 需要从数据库查询的业务上下文（每次 run 动态加载）
// ============================================================
interface BusinessContext {
  // 活跃订阅（Agent 需要知道用户已订阅了什么，避免重复）
  activeSubscriptions: {
    subscriptionId: number;
    tmdbId: number;
    title: string;
    type: 'movie' | 'tv';
    seasons?: string;       // "1,2,3" or "all"
    quality: string;
    status: 'active' | 'paused';
    lastDownloadAt?: Date;
  }[];

  // 最近下载（Agent 需要知道最近下载了什么，用于推荐和去重）
  recentDownloads: {
    downloadId: number;
    tmdbId: number;
    title: string;
    quality: string;
    downloadedAt: Date;
    status: 'completed' | 'failed' | 'transferring';
  }[];

  // 最近传输/整理记录
  recentTransfers: {
    transferId: number;
    sourcePath: string;
    destPath: string;
    status: 'success' | 'failed';
    transferredAt: Date;
  }[];

  // 媒体服务器状态
  mediaServerStatus: {
    type: 'Plex' | 'Jellyfin' | 'Emby';
    isOnline: boolean;
    recentlyAdded: { title: string; addedAt: Date }[];
  };

  // 站点状态摘要（如果集成了 PT 站点）
  siteStatus?: {
    totalSites: number;
    onlineSites: number;
    problematicSites: string[];
  };

  // 存储状态
  storageStatus: {
    totalSpace: string;     // "10TB"
    usedSpace: string;      // "7.2TB"
    usagePercent: number;   // 72
  };
}

// ============================================================
// 完整的、注入到 Agent 的 Memory Context
// ============================================================
interface NasMemoryContext {
  // === 注入到 System Prompt（每轮模型调用动态注入） ===

  // 用户画像摘要（精简版，约 200 tokens）
  userProfileSummary: {
    languages: string;
    resolution: string;
    genres_liked: string;
    genres_disliked: string;
    interaction_style: string;
  };

  // 当前人格（类似 MoviePilot 的 Persona 机制，可选）
  activePersona?: {
    id: string;
    instructions: string;
  };

  // 业务上下文摘要（精简版，约 300 tokens）
  businessSummary: {
    active_subs_count: number;
    active_subs_sample: string;     // 前 5 个订阅标题
    recent_downloads_sample: string; // 最近 5 个下载
    library_stats: string;           // "电影 1200 部, 剧集 300 部"
    storage_usage: string;           // "7.2TB / 10TB (72%)"
  };

  // 当前任务状态（来自 ConversationContext.activeTask）
  taskContext?: {
    type: string;
    step: string;
    candidate_count?: number;
    selected_title?: string;
  };

  // === 注入到 Messages 列表 ===

  // 历史对话消息（LangChain 标准格式，自动截断/压缩）
  conversationMessages: BaseMessage[];

  // 当前用户请求（结构化 JSON + 附件引用）
  currentRequest: {
    message: string;
    images: { index: number; type: string }[];
    files: { name: string; path?: string; type?: string }[];
  };

  // === 不注入 Prompt，仅用于内部逻辑 ===

  _runState: RunTemporaryContext;
  _rawBusinessContext: BusinessContext;
}
```

### 设计关键原则

1. **分层注入**：`userProfileSummary` 和 `businessSummary` 是精简版摘要，**不是**完整的 UserProfile 和 BusinessContext。完整数据通过 Tool 按需查询，避免 Prompt 臃肿。

2. **信息密度控制**：每个注入到 System Prompt 的摘要都控制在 ~200-500 tokens，类似 MoviePilot 的 `<agent_memory>` 和 `<activity_log>` 设计。

3. **任务状态外置**：`activeTask` 存在 `ConversationContext` 中，通过 LangGraph State 管理。Agent 不需要在 Prompt 中看到完整任务状态，只需要一个 `taskContext` 摘要。

4. **不该塞进 Prompt 的信息**：
   - 完整的历史 download/transfer 列表（通过 Tool 按需查询）
   - 完整的媒体库索引（通过 `query_library_exists` Tool 检查）
   - 原始 API 响应缓存（存在 `_internal` 中）
   - Token 计数字段（仅运行时使用）
   - 站点的完整配置信息（通过 Tool 查询）

---

## 八、多轮对话案例分析

案例：用户逐步完成一次下载任务

```text
用户：帮我找一下最近上映的科幻片
Agent：找到 3 部，你想下载哪一部？
用户：第二部下载 1080p 就行
用户：算了，换成 4K
用户：下载完通知我
```

| 轮次 | 用户输入 | Intent | 读取的上下文 | 更新的状态 | 说明 |
| ---- | -------- | ------ | ------------ | ---------- | ---- |
| **1** | "帮我找一下最近上映的科幻片" | `search_media` | `userProfile.mediaPreferences`（喜欢的类型/语言）; `businessContext.activeSubscriptions`（排除已订阅）; `businessContext.mediaLibrarySummary`（排除已有） | `conversationContext.intentChain = { primaryIntent: "search_and_download", resolvedParams: {genre: "sci-fi"}, pendingParams: ["title_selection", "quality"] }`; `conversationContext.activeTask = { status: "searching" }` | 第一次请求：创建 intent chain 和 active task，保存搜索参数。长期偏好用于过滤/排序结果 |
| **2** | "第二部下载 1080p 就行" | `select_media` + `set_quality` | `conversationContext.activeTask.candidates`（上一轮的搜索结果）; `conversationContext.intentChain.resolvedParams`（已知 genre） | `activeTask.selectedCandidate = candidates[1]`; `activeTask.selectedQuality = "1080p"`; `intentChain.resolvedParams.quality = "1080p"`; `intentChain.pendingParams = []` | 关键：从上一轮的 candidates 中解析"第二部"。更新 quality 参数。此时可以触发下载确认 |
| **3** | "算了，换成 4K" | `modify_quality` | `conversationContext.activeTask.selectedQuality`（当前选中的 1080p）; `conversationContext.intentChain.resolvedParams.quality` | `activeTask.selectedQuality = "4K"`; `intentChain.resolvedParams.quality = "4K"` | 修改已设置的参数。需要理解"换成"= 替换之前的 quality。不需要重新搜索 |
| **4** | "下载完通知我" | `set_notification` | `conversationContext.activeTask`（确认任务已创建）; `userProfile.notificationPreferences`（默认通知方式） | `userProfile.notificationPreferences.notifyOnDownloadComplete = true`（如果之前是 false）; `activeTask.status = "executing"` | 注意：这个"通知我"不仅是当前任务设置，**应该长期保存**到 UserProfile 中。会话结束后，下一次用户说"下载 xxx"，Agent 应该记得完成后要通知 |

### 上下文生命周期决策

| 信息 | 属于 | 生命周期 | 下次对话是否可用 |
| ---- | ---- | -------- | ---------------- |
| 搜索了"科幻片" | `ConversationContext.intentChain` | 当前会话 | 否（24h 后过期） |
| 搜索结果列表 | `ConversationContext.activeTask.candidates` | 当前会话 | 否 |
| 选择了"第二部" → TMDB ID xxx | `ConversationContext.activeTask.selectedCandidate` | 当前会话 | 否 |
| 选择了"4K" | `ConversationContext.activeTask.selectedQuality` | 当前会话 | 否 |
| 下载任务 ID | `ConversationContext.activeTask.taskId` | 当前会话（但任务本身持久化） | 可通过 Tool 查询 |
| "下载完通知我" | **`UserProfile.notificationPreferences`** | 持久化 | **是** |
| 用户喜欢科幻片 | **`UserProfile.mediaPreferences.favoriteGenres`** | 持久化 | **是**（如果 Agent 从行为中推断并保存） |

---

## 九、总结

1. **MoviePilot 的 Memory 架构是五层金字塔**：
   - 顶层：SummarizationMiddleware 实时压缩（context window 管理）
   - 上层：Conversation Messages 短期对话记忆（内存 + 可选 Redis）
   - 中层：Activity Log 中期活动记录（文件系统，LLM 自动摘要）
   - 下层：File Memory 长期用户知识（文件系统，Agent 自管理）
   - 底层：Persona/Skills/Jobs 持久化配置（文件系统，YAML 定义）

2. **核心创新是 "Agent 自管理文件记忆"**：Agent 通过文件工具自行读写 `.md` 文件管理长期记忆，完全解耦数据库 schema，但依赖 LLM 的记忆判断力。

3. **Prompt 构造是累积式追加**：Core Prompt → 中间件链依次注入 → Messages 列表。每次 LLM 调用都重新经过完整的中间件链（Persona 不缓存，确保人格切换即时生效）。

4. **对 NAS 项目的关键建议**：
   - 借鉴 MoviePilot 的五层记忆分层
   - 文件记忆方案用于用户偏好是好的，但**核心业务数据（订阅列表、下载历史）应通过 Tool 查询数据库**，而非全量注入 Prompt
   - 用户画像应做**摘要化**注入，控制在 200-500 tokens
   - 每个注入到 System Prompt 的内容都需要问："这个信息是不是每一轮 LLM 调用都需要的？"
