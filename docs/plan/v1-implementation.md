# V1 Implementation Plan

> Legacy LangGraph-era implementation plan. The active migration plan is [HelloAgents Migration Plan](helloagents-migration-plan.md). Keep this document as historical context for ADR 001.

## Overview

将当前单一直线 workflow 演进为意图路由 + 多子图的 Agent 系统。

**核心原则**:
- 每个 Phase 独立可验证、可发货
- 增量迁移，不破坏现有功能
- 每个 Phase 不超过 2-3 个子图
- Phase 之间按顺序依赖，Phase 内任务可部分并行

---

## Phase 1: Agent Foundation（前期：基础设施）

**目标**: 建立 Agent 架构骨架，当前功能正常运行。

### 1.1 State Schema & Base Types

- [ ] 实现 `AgentState` TypedDict 及各子状态类型
- [ ] 实现 `MemoryContext` 及相关类型
- [ ] 实现 `PendingUserInput`、`ConfirmationState`、`ErrorState`
- [ ] 实现 `MediaCandidate`、`MediaRequest` 类型
- [ ] 现有 workflow 适配新 State Schema

### 1.2 Tool Registry

- [ ] 实现 `ToolRegistry` 类（注册/查询/白名单）
- [ ] 迁移现有 M-Team search、qBittorrent 操作为 `@tool` 格式
- [ ] 为 `search_download` 子图配置工具白名单
- [ ] 单元测试：Registry 正确返回白名单工具

### 1.3 Main Graph Skeleton

- [ ] 实现 `has_pending_input?` 条件边
- [ ] 实现 `classify_intent` 节点（初始版本：所有请求路由到 search_download）
- [ ] 实现 `route_to_subgraph` 条件边
- [ ] 实现 `final_response` 节点
- [ ] 实现 `handle_pending_input` 节点（骨架，暂无中断类型）

### 1.4 search_download Subgraph

- [ ] 将当前 workflow 封装为独立编译的 `search_download` 子图
- [ ] 子图内部保持现有流程：keyword_finder → search_mteam → build_confirmation → execute_download
- [ ] 适配统一 AgentState
- [ ] 集成测试：现有 /chat + /confirm 流程不受影响

### 1.5 Memory Router (Basic)

- [ ] 创建/迁移 SQLite 表：`user_preferences`, `behavior_events`, `subscriptions`
- [ ] 实现 `load_context` 节点
- [ ] 根据 intent 加载对应 MemoryContext（初始只加载结构化偏好）
- [ ] 阶段结束时手动写入几条测试偏好数据验证

**Phase 1 验证标准**:
- 当前 chat→confirm→download 流程完整可用
- 主图入口跑通，intent classifier 工作
- Tool Registry 正确注入子图
- MemoryContext 正确加载到 State

---

## Phase 2: Agent Core Capabilities（中期：核心 Agent 能力）

**目标**: 实现意图路由、本地库查询、推荐、消歧。

### 2.1 Emby Integration (独立分支验证)

- [ ] 独立分支上验证 Emby API 可用性
- [ ] 验证 Emby 是否能搜到飞牛刮削的内容
- [ ] 如不可用，降级为文件系统扫描方案
- [ ] 合并到主分支后实现 `emby_adapter.py`

### 2.2 query_library Subgraph

- [ ] 实现 Emby 查询工具：`search_emby_library`, `get_emby_item_detail`, `get_emby_library_stats`
- [ ] 实现 `query_library` 子图（Type A 固定流程）
- [ ] 支持查询："家里有没有《XXX》""《XXX》什么版本"
- [ ] 集成测试

### 2.3 TMDB Adapter

- [ ] 实现 `tmdb_adapter.py`：search, detail, recommendations, similar
- [ ] 实现 TMDB 查询工具：`search_tmdb`, `get_media_detail`, `find_similar_media`
- [ ] 单元测试 + API key 配置

### 2.4 Intent Classifier (Enhanced)

- [ ] `classify_intent` 支持所有 V1 意图类型：search_download, query_library, recommend, subscribe, organize
- [ ] LLM prompt 设计：从用户消息中提取意图 + 媒体请求信息
- [ ] 输出 intent + 初步 MediaRequest 抽取

### 2.5 Candidate Resolver

- [ ] 实现 `candidate_resolver` 独立节点
- [ ] 第一层规则判断（分数差距、标题相似、媒体类型冲突）
- [ ] 第二层 LLM Judge（是否安全选择唯一候选、生成澄清问题）
- [ ] 单元测试：各规则触发场景

### 2.6 Disambiguation & Interruption Recovery

- [ ] 实现完整的 `handle_pending_input` 节点（支持 disambiguation 类型）
- [ ] 实现 `resume_workflow` 逻辑
- [ ] 消歧对话：用户回答 → 映射到候选 → 继续执行
- [ ] 集成测试：完整消歧→确认→下载链路

### 2.7 recommend Subgraph

- [ ] 实现推荐工具：`get_user_watch_profile`, `rank_media_candidates`, `check_library_availability`
- [ ] 实现 `recommend` 子图（Type B Agent Loop，最多 5 轮）
- [ ] 支持："像《降临》的科幻片""周末轻松电影"
- [ ] 推荐结果结合本地库已有内容标注
- [ ] 集成测试

**Phase 2 验证标准**:
- "家里有没有《沙丘2》"→ 查询本地库回答
- "推荐点像《降临》的电影"→ 推荐列表 + 标注本地已有的
- "我想看老男孩"→ 多个候选时触发消歧
- 消歧回答后正确继续执行

---

## Phase 3: Advanced Agent Capabilities（后期：进阶能力）

**目标**: 订阅、整理检测、前端 Agent 面板。

### 3.1 subscribe Subgraph

- [ ] 实现订阅工具：`create_subscription`, `list_subscriptions`, `cancel_subscription`, `check_subscription_status`
- [ ] 实现轮询检查机制（cron 触发检查订阅的媒体是否有更新）
- [ ] 实现 `subscribe` 子图（Type A 固定流程）
- [ ] Web UI 展示订阅列表和状态
- [ ] 集成测试

### 3.2 organize Subgraph (Detect & Report Only)

- [ ] 实现文件扫描工具：`scan_unorganized_files`, `identify_media_files`
- [ ] 实现 `generate_organize_plan` 工具（生成整理计划，不执行）
- [ ] 实现 `organize` 子图（Type A 固定流程）
- [ ] Web UI 展示整理计划 + 确认按钮
- [ ] `apply_organize_plan` 工具（确认后执行，飞牛负责后续刮削）
- [ ] 集成测试

### 3.3 Web Notification

- [ ] 后端通知事件模型（任务完成、订阅更新、整理完成、错误）
- [ ] Web UI 通知展示（通知图标 + 未读计数 + 通知列表）
- [ ] 关键节点完成后触发通知

### 3.4 Memory Context Enhancement

- [ ] Memory Router 根据 intent 差异化加载（推荐加载偏好，整理加载 workflow_preferences 等）
- [ ] 行为事件自动记录（每次搜索/下载/推荐交互写入 behavior_events）
- [ ] `relevant_history` 按语义相关性过滤（初始用关键词匹配，Phase 3 不做 embedding）

### 3.5 Frontend: Agent Dashboard

- [ ] 工具调用可视化面板（展示 tool_trace）
- [ ] 当前 workflow 状态展示（用户在等待什么、Agent 在做什么）
- [ ] 记忆/偏好管理界面（查看和编辑偏好规则）

**Phase 3 验证标准**:
- "以后《海贼王》更新提醒我"→ 创建订阅，后续更新触发通知
- "检查最近下载的文件"→ 生成整理计划，确认后可执行
- Web UI 能看到 Agent 的思考链和工具调用
- 通知系统端到端通

---

## Dependency Graph

```
Phase 1 (Foundation)
  ├── 1.1 State Schema
  ├── 1.2 Tool Registry
  ├── 1.3 Main Graph Skeleton
  ├── 1.4 search_download Subgraph (depends on 1.1, 1.2)
  └── 1.5 Memory Router Basic (depends on 1.1)
       │
       ▼
Phase 2 (Core Capabilities)
  ├── 2.1 Emby Integration (独立，可并行)
  ├── 2.2 query_library Subgraph (depends on 2.1, Phase 1)
  ├── 2.3 TMDB Adapter (独立，可并行)
  ├── 2.4 Intent Classifier Enhanced (depends on Phase 1)
  ├── 2.5 Candidate Resolver (depends on 2.3, Phase 1)
  ├── 2.6 Disambiguation & Recovery (depends on 2.5)
  └── 2.7 recommend Subgraph (depends on 2.3, 2.5, 2.6)
       │
       ▼
Phase 3 (Advanced)
  ├── 3.1 subscribe Subgraph (depends on Phase 2)
  ├── 3.2 organize Subgraph (depends on Phase 2)
  ├── 3.3 Web Notification (depends on 3.1, 3.2)
  ├── 3.4 Memory Enhancement (depends on Phase 2)
  └── 3.5 Agent Dashboard (depends on Phase 2)
```

## Out of Scope (This V1)

- 多 Agent 协作（V5 远期探索）
- 向量记忆 / embedding 检索（Phase 3 只做关键词，embedding 留给后续）
- Telegram/微信/邮件通知
- 自动偏好归纳（从行为更新 confidence）
- 家庭多成员画像
- 自动文件重命名/移动（只做检测 + 计划，不自动执行）
