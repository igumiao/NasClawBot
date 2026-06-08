# TMDB MCP 集成设计

日期: 2026-06-08

## 概述

为 NasClawBot 引入 MCP (Model Context Protocol) 客户端能力，通过通用 MCP 桥接层连接 TMDB MCP server (`Laksh-star/mcp-server-tmdb`)，让 Agent 能够查询电影、剧集、演员等外部数据。

核心目标：
1. NasClawBot 获得 MCP 客户端能力，连接任意 MCP server
2. 首个接入的 MCP server 是 TMDB（电影/剧集查询）
3. MCP 工具与现有内置工具在同一 ToolRegistry/Filter/Gate 下运行
4. 作为学习 MCP 协议的实践项目

## 整体架构

```
┌──────────────────────────────────────────────────┐
│                  app/                            │
│  app/mcp_config.py  ← settings → .env            │
│  app/agent/runner.py  ← ToolRegistry 注册        │
│  app/main.py  ← 启动时连接 MCP servers            │
└──────────────┬───────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────┐
│           hello_agents/tools/mcp/                │
│                                                  │
│  client.py          bridge.py                    │
│  ┌──────────────┐   ┌──────────────────────┐     │
│  │ McpConnection │──▶│ McpBridgeTool(Tool)  │     │
│  │ - connect()  │   │ - wraps one MCP tool │     │
│  │ - list_tools │   │ - params from schema │     │
│  │ - call_tool  │   │ - run() → call_tool  │     │
│  │ - health     │   └──────────────────────┘     │
│  └──────────────┘                                │
│  ┌──────────────┐   ┌──────────────────────┐     │
│  │ McpPool      │──▶│ register_all(pool,   │     │
│  │ - servers[]  │   │   registry, filter,  │     │
│  │ - start_all  │   │   gate)              │     │
│  │ - stop_all   │   └──────────────────────┘     │
│  └──────────────┘                                │
└──────────┬───────────────────────────────────────┘
           │ mcp Python SDK
           │ ClientSession + stdio_client
           ▼
    ┌─────────────────┐  ┌──────────────┐
    │ TMDB MCP Server │  │ future:      │
    │ Laksh-star/     │  │ Radarr MCP   │
    │ mcp-server-tmdb │  │ ...          │
    └─────────────────┘  └──────────────┘
```

### 三层职责

| 层 | 文件 | 职责 |
|----|------|------|
| MCP 协议客户端 | `hello_agents/tools/mcp/client.py` | 封装 `mcp` SDK，管理子进程生命周期，提供工具发现和调用 |
| HelloAgents 桥接 | `hello_agents/tools/mcp/bridge.py` | MCP tool schema → HelloAgents `Tool` 实例的转换 |
| 应用配置 | `app/mcp_config.py` | 从 settings 读取 server 列表，生成 `McpServerConfig` |

### 数据流（一次 Agent 工具调用）

```text
LLM tool_call → ToolRegistry → McpBridgeTool.run(params)
  → McpPool connection → ClientSession.call_tool(name, params)
  → MCP JSON-RPC (STDIO) → MCP server 执行 → result
  → McpBridgeTool 转换为 ToolResponse → Agent loop
```

## 一、`hello_agents/tools/mcp/client.py`

### 数据结构

```python
@dataclass
class McpServerConfig:
    name: str              # "tmdb"
    command: str           # "npx"
    args: list[str]        # ["-y", "mcp-server-tmdb"]
    env: dict[str, str]    # {"TMDB_API_KEY": "..."}
    timeout: float = 30.0

@dataclass
class McpToolInfo:
    name: str
    description: str
    input_schema: dict     # JSON Schema，含 properties + required
```

### McpConnection — 单 MCP server 连接

封装一个 MCP server 子进程的完整生命周期：

```python
class McpConnection:
    """一个 MCP server 进程的生命周期管理"""

    async def connect(self) -> None:
        """启动子进程 → stdio_client → ClientSession → initialize → list_tools → 缓存 McpToolInfo[]"""

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        """直接委托给 ClientSession.call_tool()"""

    async def health(self) -> bool:
        """检查连接是否存活"""

    async def disconnect(self) -> None:
        """关闭 ClientSession，终止子进程"""
```

### McpPool — 多 server 连接池

```python
class McpPool:
    """管理多个 McpConnection，提供统一查询接口"""

    async def start_all(self) -> dict[str, bool]:
        """并发连接所有 server，返回每 server 成功/失败"""

    async def stop_all(self) -> None:
        """关闭所有连接"""

    def get_tools(self, server_name: str | None = None) -> list[tuple[str, McpToolInfo]]:
        """返回 (server_name, tool_info) 对，可按 server 过滤"""

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> CallToolResult:
        """找到对应 connection → call_tool"""
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 连接时机 | 启动时全连 | Agent 对话时不需要等待连接；失败 server 只记日志不阻断启动 |
| 工具缓存 | connect 时一次性拉取 | MCP 工具集在进程生命周期内不变 |
| 断连处理 | 调用时检测 → 抛 `McpConnectionError` | 不自动重连，避免半初始化的复杂状态 |
| transport | 仅 STDIO（本期） | TMDB MCP 等主流 server 都用 STDIO；SSE 后续再加 |
| 依赖 | `mcp>=1.0.0` (modelcontextprotocol/python-sdk) | 官方 SDK |

### 启动/关闭流程

```text
FastAPI lifespan startup
  → McpPool.start_all()
    → for each server: McpConnection.connect()
      → stdio_client(command, args, env)
        → ClientSession(read, write)
          → session.initialize()
          → session.list_tools() → 缓存 McpToolInfo[]
    → 失败的 server 记日志，标记 unhealthy
    → 成功的工具通过 bridge.register_mcp_tools() 注册到 ToolRegistry

FastAPI lifespan shutdown
  → McpPool.stop_all()
    → for each: McpConnection.disconnect()
```

## 二、`hello_agents/tools/mcp/bridge.py`

### McpBridgeTool

把单个 MCP 工具包装成 HelloAgents `Tool` 实例：

```python
class McpBridgeTool(Tool):
    """把单个 MCP 工具包装成 HelloAgents Tool"""

    def __init__(self, pool: McpPool, server_name: str, tool_info: McpToolInfo):
        # name 格式: mcp_{server_name}_{tool_name}
        # 如: mcp_tmdb_search_movies

    def get_parameters(self) -> list[ToolParameter]:
        """从 MCP input_schema (JSON Schema) 转换为 ToolParameter 列表"""

    def run(self, parameters: dict) -> ToolResponse:
        """通过 pool.call_tool() 调用 MCP server，提取 text content 返回"""
```

### Schema 转换规则

```
MCP input_schema (JSON Schema)        →  HelloAgents ToolParameter[]
─────────────────────────────────────────────────────────────────
{                                      [
  "type": "object",                      ToolParameter(
  "properties": {                          name="query",
    "query": {                             type="string",
      "type": "string",                    description="搜索关键词",
      "description": "搜索关键词"            required=True,
    },                                   ),
  },                                     ToolParameter(
  "required": ["query"]                    name="year",
}                                          type="integer",
                                           description="发行年份",
                                           required=False,
                                         ),
                                       ]
```

- `required` 为 true 的字段 → `ToolParameter(required=True)`
- `properties` 中不在 `required` 数组的字段 → `ToolParameter(required=False)`
- 不支持 `enum` 的自动转换（本期不做，MCP server 的 enum 会由 LLM 自然遵守）

### 工厂函数

```python
def register_mcp_tools(
    pool: McpPool,
    registry: ToolRegistry,
    tool_filter: Filter | None = None,
    tool_gate: Gate | None = None,
    allow: list[str] | None = None,      # 按 tool name 筛选，None = 全部注册
) -> int:
    """从 pool 所有健康连接中收集工具，包装为 McpBridgeTool 并注册。返回注册数量。"""
```

- `allow` 不传时默认注册全部 MCP 工具
- 传了则只注册 `tool_info.name` 在 `allow` 列表中的工具
- 控制上下文窗口开销：20+ 个工具 schema 可能占 ~10000 tokens，精选 6 个只需 ~3000

**本期 `allow` 精选（`app/mcp_config.py`）：**

```python
TMDB_TOOLS_ALLOW = [
    "search_movies",        # 按名称搜索电影
    "get_movie_details",    # 电影详情（含 imdb_id）
    "search_tv_shows",      # 搜索剧集
    "search_person",        # 搜索演员/导演
    "get_recommendations",  # 基于电影的推荐
    "get_trending",         # 热门趋势
]
```

这 6 个覆盖了核心查询场景。`get_movie_details` 返回的 IMDB ID 桥接到 `mteam_search(imdb=...)`，形成完整搜索链。

### 同步/异步桥接

`mcp` SDK 的 `call_tool()` 是 async，但 `Tool.run()` 是同步方法。在 FastAPI 环境（已有 running event loop）直接调 `asyncio.run()` 会抛 RuntimeError。

`McpBridgeTool` 同时重写 `run()` 和 `arun()`：

```python
class McpBridgeTool(Tool):

    async def arun(self, parameters: dict) -> ToolResponse:
        """异步原生路径 — FastAPI 请求处理时走这条"""
        try:
            result = await self._pool.call_tool(
                self._server, self._tool_info.name, parameters
            )
        except McpConnectionError as e:
            return ToolResponse.error(...)
        return self._to_response(result)

    def run(self, parameters: dict) -> ToolResponse:
        """同步回退路径 — 测试或非 async 上下文中走这条"""
        try:
            return asyncio.run(self.arun(parameters))
        except RuntimeError:
            # 已有 running event loop（不应在生产中发生，但做了防御）
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, self.arun(parameters)).result()
```

`Tool.arun()` 的默认实现是在线程池里跑 `run()`。`McpBridgeTool` 反过来 — `arun()` 是主路径（真正 async），`run()` 用 `asyncio.run()` 桥接。这样生产走 async-native，测试走 sync bridge。

### 错误处理

```python
def _to_response(self, result) -> ToolResponse:
    text_parts = [c.text for c in result.content if hasattr(c, "text")]
    return ToolResponse.success(
        text="\n".join(text_parts) if text_parts else json.dumps(result.structuredContent or {}),
        data={"server": self._server, "raw": result.structuredContent},
    )
```

### 命名规则

`mcp_{server_name}_{tool_name}`，如 `mcp_tmdb_search_movies`。mcp_ 前缀避免与内置工具命名冲突，也让 LLM 和用户一眼识别为外部 MCP 工具。

### 只读性质

MCP 工具都是远程查询，天然只读。不需要在 Gate 里加确认规则 — 默认 `ALLOW`。如果未来接入有副作用的 MCP server（如控制智能家居），按需在 app 层加 confirm 规则。

## 三、`app/mcp_config.py`

```python
from hello_agents.tools.mcp.client import McpServerConfig

TMDB_SERVER_CONFIG = McpServerConfig(
    name="tmdb",
    command="npx",
    args=["-y", "mcp-server-tmdb"],
    env={"TMDB_API_KEY": ...},  # 来自 settings.tmdb_api_key
)

TMDB_TOOLS_ALLOW = [
    "search_movies",
    "get_movie_details",
    "search_tv_shows",
    "search_person",
    "get_recommendations",
    "get_trending",
]

def load_mcp_servers() -> list[McpServerConfig]:
    """从 settings 读取 MCP server 配置列表"""
    return [TMDB_SERVER_CONFIG]
```

`.env` 新增：

```bash
TMDB_API_KEY=xxx
```

## 四、Runner 集成

### `app/agent/runner.py`

```python
class NasClawAgentRunner:
    def __init__(self, ..., mcp_pool: McpPool | None = None):
        self.mcp_pool = mcp_pool

    def _build_agent(self) -> ToolCallingAgent:
        # ... 现有工具注册 ...
        
        # MCP 工具注册
        if self.mcp_pool:
            from hello_agents.tools.mcp.bridge import register_mcp_tools
            register_mcp_tools(self.mcp_pool, registry, self.tool_filter, self.tool_gate)
```

- MCP 工具不在 Filter 中额外声明 — `register_mcp_tools` 可选接受 `tool_filter`，如果传入则自动将所有注册的 MCP 工具名加入白名单
- MCP 工具不在 Gate 中加 confirm 规则（只读）

### `app/main.py`

```python
# lifespan startup
mcp_pool = McpPool(load_mcp_servers())
await mcp_pool.start_all()
runner = NasClawAgentRunner(..., mcp_pool=mcp_pool)

# lifespan shutdown
await mcp_pool.stop_all()
```

## 五、Prompts 更新

`AGENT_SESSION_PROMPT` 新增：

```
你也可以查询外部影视数据源（通过 MCP 协议连接）:
- 搜索电影: mcp_tmdb_search_movies
- 搜索剧集: mcp_tmdb_search_tv_shows
- 查看电影/剧集详情: mcp_tmdb_get_movie_details
- 查找演员/导演: mcp_tmdb_search_person, mcp_tmdb_get_person_details
- 获取推荐: mcp_tmdb_get_recommendations, mcp_tmdb_get_similar_movies
- 查看热门内容: mcp_tmdb_get_trending
这些工具均为只读，直接执行，不需要用户确认。
```

## 六、涉及文件

| 文件 | 变更 |
|------|------|
| `hello_agents/tools/mcp/__init__.py` | 新建 |
| `hello_agents/tools/mcp/client.py` | 新建：`McpServerConfig`、`McpConnection`、`McpPool` |
| `hello_agents/tools/mcp/bridge.py` | 新建：`McpBridgeTool`、`register_mcp_tools()` |
| `app/mcp_config.py` | 新建：`load_mcp_servers()` |
| `app/main.py` | 修改：lifespan 中启动/关闭 McpPool |
| `app/agent/runner.py` | 修改：接收 `mcp_pool`，注册 MCP 工具，更新 prompt |
| `pyproject.toml` | 修改：新增 `mcp>=1.0.0` 依赖 |

## 七、测试策略

| 层级 | 测试内容 | 方式 |
|------|---------|------|
| `McpConnection` | connect/list_tools/call_tool 生命周期 | mock `ClientSession`，不启动真实子进程 |
| `McpPool` | start_all 部分失败、get_tools 聚合 | 多 connection 的 mock 场景 |
| `McpBridgeTool` | schema 转换、run 正常/异常路径 | 构造 McpToolInfo 验证参数解析；mock pool.call_tool 验证 ToolResponse |
| `register_mcp_tools` | 正常注册、pool 空、connection 全部 unhealthy | 验证 ToolRegistry 中的工具数量和命名 |
| 集成测试 | 完整 startup → Agent turn → MCP 工具调用 | 可选，需要真实 TMDB API key |

## 八、选择的 MCP Server

**Laksh-star/mcp-server-tmdb** (MIT License, 51 stars, 2026-02-19 更新)

安装: `npx -y mcp-server-tmdb`，环境变量 `TMDB_API_KEY=xxx`

选型理由：工具数量多（~20+），支持电影、剧集、演员、推荐、流媒体信息，活跃维护。

**版本说明：** GitHub README 只列了 3 个基础工具（search_movies、get_recommendations、get_trending），但 glama.ai 等 MCP 目录上列了 ~20+ 个扩展工具。`npx -y mcp-server-tmdb` 安装的实际版本需在实现时通过 `list_tools()` 确认。工具数不确定不影响设计 — `McpConnection.connect()` 自动发现并缓存，`allow` 筛选确保只注册需要的工具。如果实际版本缺少 `get_movie_details` 等工具，TMDB 的 resource 端点 (`tmdb:///movie/{id}`) 也可以获取包含 IMDb ID 的详情。
