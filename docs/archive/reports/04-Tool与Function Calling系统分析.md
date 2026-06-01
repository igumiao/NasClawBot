# 04 — Tool / Function Calling 系统分析

> MoviePilot v2 Agent 源码阅读 Round 4  
> 目标：理解 Agent 如何从"会说话"变成"会做事"

---

## 目录

1. [Tool 源码定位总表](#1-tool-源码定位总表)
2. [Tool 定义方式分析](#2-tool-定义方式分析)
3. [Tool 注册机制分析](#3-tool-注册机制分析)
4. [Tool 调用链路追踪](#4-tool-调用链路追踪)
5. [Tool 错误处理分析](#5-tool-错误处理分析)
6. [Tool 安全与权限控制](#6-tool-安全与权限控制)
7. [Tool 工程化评价](#7-tool-工程化评价)
8. [NAS 项目 Tool Registry 草案](#8-nas-项目-tool-registry-草案)
9. [示例 Tool 定义（伪代码）](#9-示例-tool-定义伪代码)

---

## 1. Tool 源码定位总表

### 1.1 基础设施层（4 个文件）

| 文件 | 行数 | 角色 | 核心内容 |
|------|------|------|----------|
| `app/agent/tools/__init__.py` | — | 包入口 | 空模块 |
| `app/agent/tools/base.py` | 418 | 基类 | `MoviePilotTool(BaseTool)` — 所有工具的抽象基类 |
| `app/agent/tools/factory.py` | 284 | 工厂 | `MoviePilotToolFactory` — 70+ 内置工具的注册与装配 |
| `app/agent/tools/manager.py` | 332 | HTTP/MCP 桥接 | `MoviePilotToolsManager` — **无 Agent 时的工具调用入口** |

### 1.2 中间件层（1 个关键文件）

| 文件 | 行数 | 角色 | 核心内容 |
|------|------|------|----------|
| `app/agent/middleware/tool_selection.py` | 550 | 预筛选 | `ToolSelectorMiddleware` — 独立 LLM 调用预筛工具列表 |

### 1.3 工具实现层（70+ 个文件）

按功能域分类：

| 分类 | 文件数 | 代表工具 |
|------|--------|----------|
| 媒体搜索 | 6 | `search_media`, `search_torrents`, `search_person`, `search_person_credits`, `recognize_media`, `scrape_metadata` |
| 订阅管理 | 5 | `add_subscribe`, `delete_subscribe`, `update_subscribe`, `query_subscribes`, `search_subscribe` |
| 下载管理 | 5 | `add_download`, `delete_download`, `modify_download`, `delete_download_history`, `query_download_tasks` |
| 站点管理 | 4 | `query_sites`, `query_site_userdata`, `update_site`, `update_site_cookie`, `test_site` |
| 文件操作 | 4 | `read_file`, `write_file`, `edit_file`, `list_directory` |
| 系统命令 | 2 | `execute_command`, `terminal_session` |
| 插件管理 | 7 | `install_plugin`, `uninstall_plugin`, `reload_plugin`, `query_installed_plugins`, `query_market_plugins`, `query_plugin_config`, `update_plugin_config` |
| 系统配置 | 5 | `query_system_settings`, `update_system_settings`, `query_directory_settings`, `query_schedulers`, `run_scheduler` |
| 规则/过滤器 | 8 | `add_custom_filter_rule`, `delete_custom_filter_rule`, `update_custom_filter_rule`, `query_custom_filter_rules`, `query_builtin_filter_rules` 等 |
| 通信/交互 | 4 | `send_message`, `send_voice_message`, `send_local_file`, `ask_user_choice` |
| 媒体库 | 2 | `query_library_exists`, `query_library_latest` |
| 工作流 | 2 | `query_workflows`, `run_workflow` |
| 其他 | 8+ | `search_web`, `browse_webpage`, `query_transfer_history`, `delete_transfer_history`, `query_downloaders` 等 |

### 1.4 工具定义中调用的 Chain 层（业务逻辑桥接）

| Chain | 文件 | 用途 |
|-------|------|------|
| `DownloadChain` | `app/chain/download.py` | 下载任务创建/查询/删除 |
| `SubscribeChain` | `app/chain/subscribe.py` | 订阅的增删改查 |
| `SearchChain` | `app/chain/search.py` | 媒体搜索 |
| `TransferChain` | `app/chain/transfer.py` | 文件整理 |
| `SiteChain` | `app/chain/site.py` | 站点管理 |
| `MessageChain` | `app/chain/message.py` | 消息发送 |
| `ToolChain` | `app/agent/tools/base.py` (第 97 行) | 工具专用的轻量 Chain，支持异步消息发送 |

### 1.5 辅助工具文件

| 文件 | 用途 |
|------|------|
| `app/agent/tools/impl/_plugin_tool_utils.py` | 插件工具共享辅助：预览截断、插件摘要、候选搜索、安装/卸载 |
| `app/agent/tools/impl/_torrent_search_utils.py` | 种子搜索共享：缓存管理、种子整理、匹配验证 |
| `app/agent/tools/impl/_filter_rule_utils.py` | 过滤规则辅助 |
| `app/agent/tools/impl/_system_setting_utils.py` | 系统设置辅助 |

---

## 2. Tool 定义方式分析

### 2.1 核心基类：`MoviePilotTool`

```python
# app/agent/tools/base.py:114
class MoviePilotTool(BaseTool, metaclass=ABCMeta):
```

继承自 LangChain 的 `BaseTool`，这让工具原生兼容 LangChain `create_agent()` 的 tool calling 体系。所有 MoviePilot 工具都需要覆写 `run()` 方法。

**基类提供的标准能力：**

| 属性/方法 | 行号 | 作用 |
|-----------|------|------|
| `name: str` | 119 | 工具名，对应 LLM 返回的 `function.name` |
| `description: str` | 120 | 工具描述，注入 `tools` 定义中 |
| `args_schema: Type[BaseModel]` | 121 | Pydantic 输入模型，自动生成 JSON Schema |
| `require_admin: bool` | 126 | 管理员权限标记 |
| `result_max_chars: int` | 129 | 结果最大字符数（64KB 默认） |
| `_check_permission()` | 286 | 9 渠道管理员校验 |
| `_arun()` | 139 | **异步入口**：权限→消息→流式→执行→格式化 |
| `run_blocking()` | 248 | 将同步操作卸载到线程池 |
| `format_tool_result_for_agent()` | 50 | 强制 JSON 序列化 + 截断 |
| `set_agent_context()` | 278 | 注入共享字典（session_id, channel, user_id 等） |
| `get_tool_message()` | — | 生成友好的进度提示文本 |
| `set_message_attr()` | — | 设置消息属性（userid, username, channel 等） |

### 2.2 三种 Tool 定义模式

#### 模式 A：Pydantic args_schema（70+ 内置工具的标准方式）

```python
# 示例：app/agent/tools/impl/search_media.py
class SearchMediaInput(BaseModel):
    explanation: str = Field(..., description="Clear explanation of why...")
    title: str = Field(..., description="The media title to search for (required)")
    year: Optional[int] = Field(None, description="Release year to filter...")
    media_type: Optional[str] = Field(None, description="Media category...")
    season: Optional[int] = Field(None, description="Season number for TV series...")

class SearchMediaTool(MoviePilotTool):
    name: str = "search_media"
    description: str = "Search for movies/TV shows..."
    args_schema: Type[BaseModel] = SearchMediaInput

    async def run(self, title: str, explanation: str, **kwargs) -> str:
        ...
```

**关键特征：**
- `args_schema` 将 Pydantic 模型自动转为 JSON Schema 供 LLM 使用
- 所有工具输入都包含 `explanation` 字段（强制 LLM 解释调用意图）
- 返回类型统一为 `str`（纯文本），供 LLM 阅读

#### 模式 B：`@tool` 装饰器（未使用）

MoviePilot **没有**使用 LangChain 的 `@tool` 装饰器方式。全部采用类继承。

#### 模式 C：插件动态注册（see 3.2 节）

```python
# app/agent/tools/factory.py:244
plugin_tools = PluginManager().get_plugin_agent_tools()
```

### 2.3 `explanation` 字段的设计意图

这是一个值得注意的工程实践——**每个工具输入都要求 LLM 提供 `explanation`**：

```python
explanation: str = Field(
    ...,
    description="Clear explanation of why the agent needs to call this tool"
)
```

**作用：**
1. **审计可追溯**：每条 tool call 都记录了 LLM 的"思考动机"
2. **调试友好**：日志中可以按 `explanation` 快速定位问题调用
3. **Chain-of-Thought 前置**：强制 LLM 在调用前进行一次推理

### 2.4 返回结果的格式化链

工具返回值经过严格的格式化流水线：

```
LLM tool_call
  → MoviePilotTool._arun()
    → 权限检查 _check_permission()
    → 发送 tool_message（"正在搜索..."进度提示）
    → 流式显示处理 _stream_handler
    → 实际执行 run()
    → format_tool_result_for_agent()  ← 关键
      → serialize_tool_result_for_agent()  # JSON 序列化
      → truncation (默认 64KB)            # 截断
      → str()                             # 确保返回字符串
    → 返回给 LLM（作为 ToolMessage.content）
```

**`format_tool_result_for_agent()` 核心逻辑**（`app/agent/tools/base.py:45-71`）：

```python
DEFAULT_TOOL_RESULT_MAX_CHARS = 64 * 1024  # 64KB

def format_tool_result_for_agent(self, result: Any) -> str:
    max_chars = getattr(self, "result_max_chars", DEFAULT_TOOL_RESULT_MAX_CHARS)
    serialized = serialize_tool_result_for_agent(result)  # JSON dump
    if len(serialized) > max_chars:
        serialized = serialized[:max_chars] + f"\n...(内容过长，已截断 {max_chars} 字符)"
    return str(serialized)
```

---

## 3. Tool 注册机制分析

### 3.1 注册流程全景

```
AgentInitializer.initialize()
  → agent_manager.initialize()                   # app/agent/__init__.py:943
    → MoviePilotToolFactory.create_tools()       # app/agent/tools/factory.py:137
      ├── 1. 初始化 ToolChain，设置消息属性
      ├── 2. 获取 settings.AI_AGENT_PLAYWRIGHT_RELAY_URL
      ├── 3. 实例化 70+ 内置工具类
      ├── 4. 为每个工具注入消息属性 + 流式处理器 + agent_context
      ├── 5. 获取 PluginManager().get_plugin_agent_tools()
      ├── 6. 返回 tools 列表
      └── 7. 传递给 create_agent(tools=tools, ...)
```

### 3.2 注册地址：`MoviePilotToolFactory`

```python
# app/agent/tools/factory.py:137
@staticmethod
def create_tools(...) -> List[MoviePilotTool]:
```

**内置工具注册列表**（第 151-226 行）：

```python
tool_definitions = [
    SearchMediaTool,
    SearchTorrentsTool,
    AddSubscribeTool,
    AddDownloadTool,
    # ... 70+ 个工具类
]
```

**注册时的装配流程**（第 228-242 行）：

```python
for tool_cls in tool_definitions:
    tool = tool_cls()              # 1. 实例化
    tool.set_message_attr(...)     # 2. 注入消息属性
    tool.set_stream_handler(...)   # 3. 注入流式处理器
    tool.set_agent_context(...)    # 4. 注入共享上下文
    tools.append(tool)
```

### 3.3 插件工具的扩展点

```python
# app/agent/tools/factory.py:244-271
plugin_tools = PluginManager().get_plugin_agent_tools()

for tool in plugin_tools:
    if not tool.name or not tool.run:
        continue
    if tool.name in existing_tool_names:
        continue  # 同名工具不覆盖
    tool.set_message_attr(...)
    tool.set_stream_handler(...)
    tool.set_agent_context(...)
    tools.append(tool)
```

这意味着任何插件都可以通过 `get_plugin_agent_tools()` 贡献新工具。

### 3.4 Agent 初始化时如何使用这些工具

```python
# app/agent/__init__.py:609-615
agent = create_agent(
    model=model,
    tools=tools,                              # ← 完整的工具列表
    system_prompt=system_prompt,
    middleware=middleware_list,
    checkpointer=InMemorySaver(),
    ...
)
```

LangChain `create_agent()` 接收工具列表后，自动完成：
1. 将 `args_schema` 转为 OpenAI function schema
2. 将所有函数的 name + description + parameters 注入 model 的 `tools` 参数
3. 在 LangGraph StateGraph 中创建 `call_tools` 节点

### 3.5 工具选择中间件：运行时预筛选

70+ 个工具全部传给 LLM，会严重消耗 context window。`ToolSelectorMiddleware` 做了预筛选：

```python
# app/agent/middleware/tool_selection.py:494
async def abefore_agent(self, state, runtime, config):
    # 每个 Agent 运行一次，调用独立的小 LLM 调用来筛选相关工具
    # 支持的模型：DeepSeek (json_object mode) 或标准 (tool_calling mode)
    # 返回: {selected_tools: [...], always_include_tools: [...]}
```

**永远包含的工具**（`TOOL_SELECTOR_ALWAYS_INCLUDE_NAMES`，factory.py 第 96 行）：

```python
TOOL_SELECTOR_ALWAYS_INCLUDE_NAMES = [
    "list_directory",
    "write_file",
    "read_file",
    "edit_file",
    "execute_command",
    "ask_user_choice",
]
```

这 6 个基础工具不会被筛掉——它们是 Agent 自主操作文件系统和与用户交互的最低能力保障。

---

## 4. Tool 调用链路追踪

### 4.1 完整链路（端到端）

```
用户发送消息 "/ai 帮我搜索盗梦空间"
  │
  ├─ [1] MessageChain._handle_ai_message()
  │     → asyncio.run_coroutine_threadsafe(agent_manager.process_message(...))
  │
  ├─ [2] AgentManager._session_worker()           # app/agent/__init__.py:1082
  │     → 从 asyncio.Queue 中取出消息
  │     → _process_message_internal()
  │
  ├─ [3] MoviePilotAgent.process()                # app/agent/__init__.py:620
  │     → 构建结构化 UserMessage（包含用户信息、系统信息、媒体上下文）
  │     → _execute_agent()
  │
  ├─ [4] _execute_agent()                         # app/agent/__init__.py:720
  │     ┌─ abefore_agent 钩子链 ─────────────────┐
  │     │ SkillsMiddleware   → 扫描 SKILL.md     │
  │     │ JobsMiddleware     → 扫描 JOB.md       │
  │     │ RuntimeConfigMiddleware → 加载 Persona │
  │     │ MemoryMiddleware   → 加载文件记忆      │
  │     │ ActivityLogMiddleware → 加载活动日志   │
  │     │ SummarizationMiddleware → 检查是否需要摘要 │
  │     │ PatchToolCallsMiddleware → 修复悬空调用 │
  │     │ UsageMiddleware    → 等待模型响应时记录 │
  │     └─── ToolSelectorMiddleware → **预筛工具**┘
  │
  ├─ [5] LangChain create_agent() 内部
  │     → 将筛选后的 tools 列表 + system_prompt + messages 发给 LLM
  │     → LLM 返回 response: AIMessage(tool_calls=[...])
  │
  ├─ [6] LangGraph StateGraph 路由
  │     → 检测到 AIMessage.tool_calls 不为空
  │     → 路由到 call_tools 节点
  │
  ├─ [7] LangChain 调用 tool._arun(tool_call_id=..., args={...})
  │     │
  │     ├─ MoviePilotTool._arun()                    # base.py:139
  │     │   ├─ _check_permission(channel, userid)    # 权限检查
  │     │   │   └─ require_admin=True → 校验管理员
  │     │   │
  │     │   ├─ get_tool_message(**tool_args)         # 生成进度文本
  │     │   │   └─ "正在搜索 盗梦空间 的媒体信息..."
  │     │   │
  │     │   ├─ ToolChain().async_post_message(...)   # 发送进度到聊天
  │     │   │
  │     │   ├─ _stream_handler.on_tool_start(...)    # 流式处理器记录
  │     │   │
  │     │   ├─ run(**tool_args)                      # ★ 执行业务逻辑
  │     │   │   ├─ [可能] run_blocking(bucket, func) # 同步阻塞→线程池
  │     │   │   ├─ 调用 Chain 层（SearchChain, DownloadChain...）
  │     │   │   └─ 返回结果 dict / str
  │     │   │
  │     │   ├─ format_tool_result_for_agent(result)  # JSON + 截断
  │     │   │
  │     │   └─ return str(serialized)                # 返回给 LangChain
  │     │
  │     └─ LangChain 将返回值包装为 ToolMessage
  │         → 追加到 messages 列表
  │
  ├─ [8] Agent Loop 下一轮推理
  │     → LLM 读取 ToolMessage
  │     → 决定：是继续调用更多工具，还是生成最终回复
  │     → 如果继续调用工具 → 回到步骤 [6]
  │     → 如果生成最终回复 → 进入步骤 [9]
  │
  └─ [9] 流式输出给用户
        → _ThinkTagStripper → StreamingHandler._flush()
        → 每 0.3s 批处理 token → 编辑消息 or 发送新消息
```

### 4.2 核心调用链的精确代码路径

| 步骤 | 文件:行号 | 方法 | 关键参数 |
|------|-----------|------|----------|
| Tool Call 检测 | LangChain 内部 | `should_continue` | 检查 `AIMessage.tool_calls` |
| 异步入口 | `base.py:139` | `MoviePilotTool._arun()` | `tool_call_id`, `**kwargs` |
| 权限检查 | `base.py:286` | `_check_permission()` | `channel`, `userid` |
| 进度提示 | 各工具覆写 | `get_tool_message()` | 按工具参数生成 |
| 阻塞卸载 | `base.py:248` | `run_blocking()` | `bucket_name`, `func` |
| 结果格式化 | `base.py:45` | `format_tool_result_for_agent()` | `result: Any` |
| 返回给 LLM | LangChain 内部 | — | `ToolMessage(content=...)` |

### 4.3 `run_blocking()` 的线程池设计

```python
# app/agent/tools/base.py:77-90
_BLOCKING_BUCKET_LIMITS = {
    "default": 4,
    "config": 2,
    "db": 4,
    "downloader": 4,
    "site": 4,
    "storage": 4,
    "media_server": 2,
    "subscriber": 2,
    "transfer": 2,
}

_blocking_semaphores: Dict[str, asyncio.Semaphore] = {}

@staticmethod
async def run_blocking(bucket: str, func: Callable, *args, **kwargs):
    sem = _blocking_semaphores[bucket]
    async with sem:
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: func(*args, **kwargs)
        )
```

**设计要点：**
- **9 个分类桶**，按操作类型隔离，避免下载操作耗尽所有线程
- **每个桶有独立的并发上限**（Semaphore），站群操作最多 4 并发
- 使用默认的 `ThreadPoolExecutor`（`None` 参数），Python 自动管理

### 4.4 Agent Loop 和 Tool Calling 的关系

重申 Round 2 的核心发现：**Agent Loop 存在于 LangChain `create_agent()` 内部**。

```
MoviePilot 层面：
  process_message() → 一次性的 Agent 执行

LangChain create_agent() 内部：
  LLM推理 → tool_calls? → 执行工具 → ToolMessage → LLM推理 → ... → 最终回复
  ↑                                                                    │
  └──────────────── Agent Loop（LangGraph StateGraph 自动管理）──────────┘
```

每次 LangChain 内部的 Agent Loop 可能经历 **LLM ↔ Tool 交替 0~N 次**，直到 LLM 决定不再调用工具。

---

## 5. Tool 错误处理分析

### 5.1 错误处理的四层防线

```
第一层：Pydantic 输入校验
  └─ args_schema 自动校验类型、必填项
     └─ 校验失败 → 不会进入 run()，LangChain 返回 schema error 给 LLM

第二层：_arun() 的通用异常捕获
  └─ base.py:200-203
     except Exception as e:
         return format_tool_result_for_agent({
             "success": False,
             "error": str(e),
             "error_type": type(e).__name__
         })

第三层：结果截断保护
  └─ base.py:53-62
     结果超过 64KB → 截断 + 附加截断提示

第四层：PatchToolCallsMiddleware 悬空调用修复
  └─ middleware/patch_tool_calls.py:12
     检测 AIMessage.tool_calls 无对应 ToolMessage → 插入取消说明
```

### 5.2 错误信息格式

所有工具异常都通过统一的错误格式返回给 LLM：

```json
{
  "success": false,
  "error": "具体错误信息",
  "error_type": "ValueError"
}
```

LLM 能读懂这个格式，并根据错误信息调整策略（如换关键词重试、提醒用户等）。

### 5.3 关键设计：异常返回而非抛出

```python
# base.py:139-203 (_arun 简化逻辑)
async def _arun(self, tool_call_id=None, **kwargs):
    try:
        # 权限检查失败 → 返回错误字符串（不抛异常）
        if not self._check_permission(...):
            return "Permission denied: this tool requires admin access"

        # 执行工具
        result = await self.run(**kwargs)

        # 格式化结果
        return self.format_tool_result_for_agent(result)

    except Exception as e:
        # 任何异常都捕获，返回给 LLM 而不是向上传播
        return self.format_tool_result_for_agent({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        })
```

**为什么这样设计？** 如果抛出异常，LangGraph StateGraph 的 `call_tools` 节点会中断整个 Agent Loop，导致对话失败。而返回错误字符串让 LLM 有机会"看到错误"并尝试修复。

### 5.4 并发控制与超时

**execute_command 的专用并发限制：**（`execute_command.py:31`）
```python
COMMAND_CONCURRENCY_LIMIT = 2
```

**命令执行超时：**（`execute_command.py:27`）
```python
MAX_TIMEOUT_SECONDS = 300  # 5 分钟硬上限
```

**超时处理流程**（`execute_command.py:396-440`）：
```
超时 → SIGTERM (graceful)
  → 等待 3 秒
  → SIGKILL (force)
  → 返回已捕获的输出 + "terminated (timeout)" 提示
```

---

## 6. Tool 安全与权限控制

### 6.1 `require_admin` 权限体系

```python
# base.py:126, 286-308
class MoviePilotTool(BaseTool):
    require_admin: bool = False

    def _check_permission(self, channel, userid):
        if not self.require_admin:
            return True

        # 检查当前渠道类型和用户是否具有管理员权限
        channel_type = MessageChannel(channel) if channel else None
        user_admins = settings.ADMIN_LIST or []

        # 9 种消息渠道的独立管理员检查
        ...
```

**需要管理员权限的工具**（部分）：
| 工具名 | 风险等级 | 原因 |
|--------|----------|------|
| `execute_command` | 高危 | 任意命令执行 |
| `add_download` | 中危 | 消耗存储/带宽 |
| `delete_subscribe` | 中危 | 数据破坏 |
| `delete_download` | 中危 | 数据破坏 |
| `update_system_settings` | 中危 | 系统配置修改 |
| `install_plugin` | 中危 | 代码加载 |
| `restart` (slash command) | 高危 | 系统重启 |

### 6.2 `execute_command` 的多层防护

这是 MoviePilot 工具系统中最危险的工具，因此有最严格的安全控制：

```
第 1 层：require_admin = True
  └─ 只有管理员能调用

第 2 层：COMMAND_FORBIDDEN_KEYWORDS 黑名单
  └─ execute_command.py:32-43
     "rm -rf /", fork bomb, dd, mkfs, reboot, shutdown...

第 3 层：COMMAND_CONCURRENCY_LIMIT = 2
  └─ 全局最多同时跑 2 个命令

第 4 层：MAX_TIMEOUT_SECONDS = 300
  └─ 超时强制 kill

第 5 层：MAX_OUTPUT_PREVIEW_BYTES = 10KB
  └─ 防止 stdout flood 炸 context window
```

### 6.3 MCP 协议层的工具隐藏

```python
# app/api/endpoints/mcp.py:22
MCP_HIDDEN_TOOLS = [
    "execute_command",
    "search_web",
    "edit_file",
    "write_file",
    "read_file",
]
```

通过 MCP 协议调用的客户端**看不到**这 5 个工具。这防止了：
- 外部 MCP 客户端执行任意命令
- 非受控的文件读写
- 通过 `search_web` 发起 SSRF 攻击

### 6.4 命令黑名单审查

```python
# execute_command.py:32-43
COMMAND_FORBIDDEN_KEYWORDS = [
    "rm -rf /",           # 毁灭性删除
    "fork bomb",          # 资源耗尽
    ":(){ :|:& };:",      # fork bomb 语法
    "dd if=",             # 磁盘覆写
    "mkfs",               # 文件系统格式化
    "mkswap",             # 格式化 swap
    "reboot",             # 重启
    "shutdown",           # 关机
    "halt",               # 关机
    "poweroff",           # 关机
]
```

**评价：** 黑名单有覆盖，但对 NAS 场景来说偏粗粒度。缺少对以下场景的防护：
- `rm -rf ~/` / `rm -rf /*` 变体
- `curl ... | sh` 管道下载执行
- `chmod 777` 权限放大
- `iptables` 防火墙修改

### 6.5 AgentContext 的数据隔离

```python
# base.py:278-283
def set_agent_context(self, context: dict):
    self._agent_context = context
```

每个工具实例共享一个 `agent_context` 字典，包含：
- `session_id` — 当前会话 ID
- `channel` — 消息渠道
- `user_id` — 用户 ID
- `username` — 用户名
- `source` — 消息来源

这确保了工具执行时有完整的用户上下文用于权限校验和审计日志。

---

## 7. Tool 工程化评价

### 7.1 优点

| 维度 | 评价 | 依据 |
|------|------|------|
| **统一基类** | 优秀 | 所有工具继承 `MoviePilotTool`，统一的 `_arun()` 流水线 |
| **类型安全** | 优秀 | Pydantic `args_schema` 提供编译时 + 运行时输入校验 |
| **错误隔离** | 优秀 | 工具异常不传播，统一格式返回给 LLM，允许自我修复 |
| **线程池隔离** | 良好 | 9 个分类桶按操作类型隔离并发，避免相互阻塞 |
| **结果截断** | 良好 | 64KB 默认截断保护 context window |
| **审计追溯** | 良好 | `explanation` 字段强制记录调用动机 |
| **权限控制** | 良好 | `require_admin` + 9 渠道独立校验 |
| **工具预筛选** | 良好 | `ToolSelectorMiddleware` 减少 context window 消耗 |
| **扩展性** | 良好 | 插件可通过 `get_plugin_agent_tools()` 动态注册工具 |
| **安全防护** | 合格 | 命令黑名单 + 超时 + 并发限制 + MCP 隐藏 |

### 7.2 可改进点

| 维度 | 问题 | 改进建议 |
|------|------|----------|
| **Tool 单元测试** | 70+ 工具几乎没有 unit test | 每个工具至少 2 个 test case（正常输入 + 异常输入） |
| **Tool Metrics** | 无调用频率/成功率统计 | 添加 middleware 记录 tool_call 的 latency、error_rate |
| **超时机制** | 只有 `execute_command` 有超时 | 为所有阻塞工具添加全局超时（如 60s） |
| **结果截断** | 64KB 一刀切 | 不同类型工具应有不同截断策略（文件列表 16KB，文件内容 128KB） |
| **Tool Redundancy** | `query_*` 类工具有 20+ 个 | 考虑合并为通用的 `query(type, filters)` |
| **命令黑名单** | 基于关键字匹配，易绕过 | 使用白名单 + sandbox 执行 |
| **Tool Versioning** | 无版本管理 | 工具 schema 变更时应支持版本兼容 |
| **Rate Limiting** | 无调用频率限制 | LLM 可能在一轮中疯狂调用工具，需要限流 |

### 7.3 与主流 Agent 框架的对比

| 特性 | MoviePilot | LangChain 标准 | OpenAI Assistants | Anthropic Tool Use |
|------|-----------|----------------|-------------------|-------------------|
| 工具定义 | Pydantic BaseModel | Pydantic / Zod | JSON Schema | JSON Schema |
| 并发执行 | 不支持 | 不支持 | 不支持 | 不支持 |
| 错误反馈给 LLM | 支持 | 需手动实现 | 支持 | 支持 |
| 工具预筛选 | 独立 LLM 调用 | 无 | 无 | 无 |
| 执行进度提示 | 支持 | 无 | 无 | 无 |
| 插件扩展 | 支持 | 支持 | 不支持 | 不支持 |

---

## 8. NAS 项目 Tool Registry 草案

基于 MoviePilot 的工具设计模式，为你的 NAS 私有媒体库智能管理系统设计以下 Tool Registry。

### 8.1 设计原则

1. **从少开始**：首批 12 个核心工具，后续按需扩充
2. **功能域隔离**：5 个功能域，清晰的职责边界
3. **安全第一**：写操作必须 `require_admin`，危险操作有二次确认
4. **类型安全**：所有 Input 用 Pydantic/TypeScript interface 定义
5. **错误反馈**：统一 `{success, error, data}` 返回格式

### 8.2 工具分类总表

#### 类别 A：媒体搜索与识别（3 个）

| 工具名 | 触发时机 | 输入 | 输出 |
|--------|----------|------|------|
| `media.search` | 用户要求搜索影片 | `query: str`, `type?: movie\|tv`, `year?: int` | `[{tmdb_id, title, year, poster}]` |
| `media.detail` | 用户选中某个媒体 | `tmdb_id: int`, `type: movie\|tv` | `{title, overview, cast, seasons, rating...}` |
| `media.recommend` | 用户要求推荐 | `tmdb_id?: int`, `genre?: str`, `count: int=5` | `[{tmdb_id, title, year, reason}]` |

#### 类别 B：下载管理（3 个）

| 工具名 | 触发时机 | 输入 | 输出 | require_admin |
|--------|----------|------|------|---------------|
| `download.create_task` | 用户要求下载 | `tmdb_id: int`, `quality?: str`, `season?: int` | `{task_id, status}` | true |
| `download.query` | 用户询问下载状态 | `status?: active\|completed\|failed` | `[{task_id, title, progress, eta, speed}]` | false |
| `download.cancel` | 用户要求取消下载 | `task_id: str` | `{success, message}` | true |

#### 类别 C：文件管理（3 个）

| 工具名 | 触发时机 | 输入 | 输出 | require_admin |
|--------|----------|------|------|---------------|
| `file.browse` | 浏览媒体库目录 | `path?: str`, `pattern?: str` | `[{name, size, type, mtime}]` | false |
| `file.rename` | 手动整理重命名 | `path: str`, `new_name: str` | `{old_path, new_path}` | true |
| `file.delete` | 删除媒体文件 | `path: str`, `confirm: bool` | `{success, message}` | true |

#### 类别 D：系统监控（2 个）

| 工具名 | 触发时机 | 输入 | 输出 |
|--------|----------|------|------|
| `system.status` | 用户询问 NAS 状态 | — | `{cpu, mem, disk, uptime, temp}` |
| `system.service` | 管理后台服务 | `service: str`, `action: start\|stop\|restart` | `{success, status}` |

#### 类别 E：订阅/自动追更（1 个）

| 工具名 | 触发时机 | 输入 | 输出 |
|--------|----------|------|------|
| `subscribe.manage` | 管理追更订阅 | `tmdb_id: int`, `action: add\|remove\|list` | `{status, subscriptions}` |

### 8.3 工具扩展预留

随着项目发展，建议按以下阶段扩展：

**Phase 2（6 个月后）:**
- `media.transcode` — 视频转码
- `media.analyze` — 媒体信息分析（编解码、HDR、音轨）
- `backup.create` — 备份配置/数据库
- `notify.test` — 测试通知渠道
- `log.query` — 查询系统日志

**Phase 3（12 个月后）:**
- `ai.subtitle` — AI 字幕生成
- `ai.recognition` — AI 内容识别（成人内容过滤）
- `user.manage` — NAS 多用户权限管理
- `storage.expand` — 存储扩容引导

### 8.4 Tool Registry 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Tool Registry                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │              Tool 抽象基类                        │  │
│  │  name, description, args_schema, require_admin    │  │
│  │  _arun() → check_permission → run → format_result │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                               │
│    ┌─────────┬──────────┬──────────┬──────────┐         │
│    │ Media   │ Download │  File    │ System   │         │
│    │ Toolkit │  Toolkit │ Toolkit  │ Toolkit  │         │
│    │         │          │          │          │         │
│    │ search  │ create   │ browse   │ status   │         │
│    │ detail  │ query    │ rename   │ service  │         │
│    │ recmd   │ cancel   │ delete   │          │         │
│    └─────────┴──────────┴──────────┴──────────┘         │
│                          │                               │
│                    ┌─────┴─────┐                         │
│                    │  Plugin   │  ← 插件扩展入口          │
│                    │  Adapter  │                         │
│                    └───────────┘                         │
└─────────────────────────────────────────────────────────┘
```

---

## 9. 示例 Tool 定义（伪代码）

### 9.1 `media.search` — 读工具

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

# ---------- Input Schema ----------
class MediaSearchInput(BaseModel):
    explanation: str = Field(
        ...,
        description="Why the agent needs to search for this media"
    )
    query: str = Field(
        ...,
        description="Search keyword: title, actor, director, or keyword"
    )
    media_type: Optional[Literal["movie", "tv"]] = Field(
        None,
        description="Filter by media type. Leave empty to search both."
    )
    year: Optional[int] = Field(
        None,
        description="Release year to narrow down results"
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of results to return"
    )

# ---------- Tool Definition ----------
class MediaSearchTool(NasBaseTool):
    """NAS 媒体库搜索工具 — 只读操作，无需管理员权限。"""

    name: str = "media.search"
    require_admin: bool = False
    args_schema = MediaSearchInput

    description: str = (
        "Search the NAS media library for movies or TV shows. "
        "Returns matching titles with TMDB IDs, years, and poster URLs. "
        "Use this when the user asks to find a specific movie/show, "
        "or browse what's available in the library."
    )

    def get_tool_message(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        return f"🔍 正在搜索「{query}」..."

    async def run(self, query: str, explanation: str, **kwargs) -> str:
        media_type = kwargs.get("media_type")
        year = kwargs.get("year")
        limit = min(kwargs.get("limit", 10), 50)

        # 调用 TMDb API
        results = await self.tmdb.search(
            query=query,
            media_type=media_type,
            year=year,
        )

        # 精简返回 —— 只给 Agent 需要的信息
        simplified = []
        for item in results[:limit]:
            simplified.append({
                "tmdb_id": item["id"],
                "title": item.get("title") or item.get("name"),
                "year": (item.get("release_date") or item.get("first_air_date") or "")[:4],
                "overview": (item.get("overview") or "")[:150],
                "poster": f"https://image.tmdb.org/t/p/w200{item['poster_path']}"
                    if item.get("poster_path") else None,
                "rating": item.get("vote_average"),
            })

        return json.dumps({
            "success": True,
            "count": len(simplified),
            "results": simplified,
        }, ensure_ascii=False)
```

### 9.2 `download.create_task` — 写工具

```python
class DownloadCreateInput(BaseModel):
    explanation: str = Field(
        ...,
        description="Why the agent is initiating this download"
    )
    tmdb_id: int = Field(
        ...,
        description="TMDb ID of the media to download"
    )
    media_type: Literal["movie", "tv"] = Field(
        ...,
        description="Whether this is a movie or TV show"
    )
    quality: Optional[str] = Field(
        None,
        description="Preferred quality: 4K, 1080p, 720p, or 'any'"
    )
    season: Optional[int] = Field(
        None,
        description="Season number (required if media_type is 'tv')"
    )


class DownloadCreateTool(NasBaseTool):
    """下载任务创建工具 — 写操作，需要管理员权限。"""

    name: str = "download.create_task"
    require_admin: bool = True
    args_schema = DownloadCreateInput

    description: str = (
        "Create a new download task in the NAS downloader. "
        "This searches for available torrents/usenet releases and "
        "adds the best match to the download queue. "
        "Requires admin access."
    )

    def get_tool_message(self, **kwargs) -> str:
        return f"⬇️ 正在搜索 {kwargs.get('tmdb_id')} 的下载资源..."

    async def run(
        self,
        tmdb_id: int,
        media_type: str,
        explanation: str,
        **kwargs,
    ) -> str:
        quality = kwargs.get("quality", "any")
        season = kwargs.get("season")

        # 1. 用 TMDB ID 获取元数据
        metadata = await self.tmdb.get_detail(tmdb_id, media_type)
        if not metadata:
            return json.dumps({
                "success": False,
                "error": f"No metadata found for TMDB ID {tmdb_id}",
            })

        # 2. 搜索种子
        search_results = await self.downloader.search(
            title=metadata["title"],
            year=metadata["year"],
            quality=quality,
            season=season,
        )

        if not search_results:
            return json.dumps({
                "success": False,
                "error": "No download resources found for this media",
            })

        # 3. 选择最优资源并创建任务（阻塞操作 → 线程池）
        best = search_results[0]  # 按种子数/做种者排序

        download_result = await self.run_blocking(
            "downloader",
            self.downloader.add_task,
            torrent_url=best["download_url"],
            save_path=f"/Media/{media_type}/{metadata['title']}",
            category=media_type,
        )

        return json.dumps({
            "success": True,
            "task_id": download_result["task_id"],
            "title": metadata["title"],
            "quality": best["quality"],
            "size": best["size"],
            "status": "downloading",
        }, ensure_ascii=False)
```

### 9.3 基类设计（TypeScript 版本，适用于 Node.js 后端）

```typescript
// ---------- Tool 基类 ----------
interface ToolInput {
  explanation: string;  // ← MoviePilot 的核心设计：强制 LLM 解释意图
}

interface ToolResult {
  success: boolean;
  error?: string;
  error_type?: string;
  data?: unknown;
}

interface ToolDefinition {
  name: string;
  description: string;
  parameters: JsonSchema;          // 供 LLM 使用
  requireAdmin: boolean;
  handler: (input: ToolInput, ctx: AgentContext) => Promise<ToolResult>;
  getProgressMessage?: (input: ToolInput) => string;  // 进度提示
  maxResultChars?: number;          // 结果截断长度
}

// ---------- Agent 上下文 ----------
interface AgentContext {
  sessionId: string;
  userId: string;
  channel: "telegram" | "wechat" | "web";
  isAdmin: boolean;
}

// ---------- Tool Registry ----------
class ToolRegistry {
  private tools: Map<string, ToolDefinition> = new Map();

  register(tool: ToolDefinition): void {
    this.tools.set(tool.name, tool);
  }

  getToolsForAgent(availableNames?: string[]): ToolDefinition[] {
    return Array.from(this.tools.values())
      .filter(t => !availableNames || availableNames.includes(t.name));
  }

  async executeTool(
    name: string,
    input: ToolInput,
    ctx: AgentContext,
  ): Promise<ToolResult> {
    const tool = this.tools.get(name);
    if (!tool) {
      return { success: false, error: `Unknown tool: ${name}` };
    }
    if (tool.requireAdmin && !ctx.isAdmin) {
      return { success: false, error: "Admin access required" };
    }
    try {
      const result = await tool.handler(input, ctx);
      // 截断过长结果
      const maxChars = tool.maxResultChars ?? 64 * 1024;
      const serialized = JSON.stringify(result);
      if (serialized.length > maxChars) {
        return {
          success: true,
          data: serialized.slice(0, maxChars) + `...(truncated at ${maxChars} chars)`,
        };
      }
      return result;
    } catch (e) {
      return {
        success: false,
        error: e.message,
        error_type: e.constructor.name,
      };
    }
  }
}
```

### 9.4 最小可用工具集启动清单

| 优先级 | 工具 | 理由 |
|--------|------|------|
| P0 | `media.search` | Agent 最核心能力：帮用户找片子 |
| P0 | `media.detail` | 搜索结果需要展开详情 |
| P0 | `system.status` | 用户查看 NAS 状态的最常见请求 |
| P1 | `download.create_task` | 从"说"到"做"的关键一步 |
| P1 | `download.query` | 下载后需要追踪进度 |
| P1 | `file.browse` | 浏览文件是最常见的 NAS 操作 |
| P2 | `file.rename` | 手动整理场景 |
| P2 | `subscribe.manage` | 追更场景（差异化卖点） |
| P2 | `media.recommend` | 提升用户体验 |

**建议先实现 P0 的 3 个工具，构成最小闭环。** 这足以覆盖"搜索→查看→询问状态"的核心流程。P1 加入后，Agent 从"会说话"到"会做事"。P2 提供差异化竞争力。

---

## 总结

MoviePilot 的 Tool 系统是一个**工业级的 Agent 工具基础设施**，主要亮点：

1. **统一的 `MoviePilotTool` 基类**封装了权限、错误处理、结果格式化、流式消息的全套流水线
2. **Pydantic `args_schema`** 确保类型安全，`explanation` 字段强制 LLM 审计追溯
3. **70+ 工具通过 Factory 模式注册**，支持插件动态扩展
4. **`ToolSelectorMiddleware`** 用独立 LLM 调用预筛工具，节省 context window
5. **多层安全防护**：permission gate → forbidden keywords → concurrency limit → timeout → output truncation
6. **异常不传播**：所有工具错误以结构化数据返回给 LLM，允许 Agent 自我纠正
7. **9 桶线程池隔离**：按操作类型分类，防止不同类型操作相互阻塞

对于你的 NAS 项目，建议从 **P0 的 3 个工具起步**（`media.search` + `media.detail` + `system.status`），先搭建好 Tool Registry 基础设施，再逐步扩展到 P1/P2，避免过早陷入大规模工具开发的维护负担。
