# ADR 001: Agent Architecture

## Status

Superseded in part by [ADR 002: HelloAgents Runtime Migration](002-helloagents-runtime-migration.md) (2026-05-29).

The domain decisions in this ADR still stand unless ADR 002 explicitly changes them. The superseded parts are the framework-specific LangGraph decisions around graph/subgraph implementation.

## Context

NasClawBot 当前是一条直线 workflow（keyword → search → confirm → download），需要演进为一个具备意图识别、工具调用、长期记忆、消歧对话能力的 Agent 系统。项目目标重新定位为"面向 NAS 私有媒体库的智能运营助手"。

本次讨论覆盖了 Agent 架构、工具设计、记忆系统、消歧机制、文件整理策略、通知渠道等核心决策。

## Decisions

### D1: 单 Agent + 多 Tool，暂不多 Agent

**决定**: V1-V4 采用单 Agent + 多 Tool 架构，V5 的多 Agent 化标记为远期探索方向。

**理由**:
- 当前功能（意图路由、消歧、推荐、订阅、整理）本质上是一个 Agent 配多个 Tool 即可覆盖
- 多 Agent 有价值的前提是不同 Agent 有独立且冲突的目标需要协商，或需要隔离记忆/状态空间 —— 当前场景不具备
- 文档 V5 列的 Planner / Library / Recommendation / Subscription Agent 更像是按功能拆分的 Tool 集合
- 等到单 Agent 的 prompt 过长、工具过多导致 LLM 选择困难时再拆分

### D2: 混合架构 —— 固定主流程 + 局部 LLM 决策点

**决定**: 查询/下载/订阅/整理使用固定流程子图（LLM 只负责抽取和排序），推荐/消歧/复杂需求使用受控 Agent Loop 子图（LLM 在限定工具白名单内自主决策）。

**理由**:
- 固定流程可靠、可测试、可预测，适合有明确步骤的任务
- Agent Loop 灵活，适合需要动态组合工具的任务
- 每个子图有独立工具白名单，防止 LLM 越权调用

### D3: 子图隔离 + 统一 State Schema

**决定**: 使用 LangGraph 的编译子图挂载方式（`add_node("subgraph", subgraph.compile())`），所有子图共享统一 `AgentState`，子图只读写自己的 domain state。

**理由**:
- 工具白名单设计天然与子图隔离对应
- 统一 State 使中断恢复简单（pending_input 跨子图共享）
- 子图可独立开发、测试、调试

### D4: 中断恢复入口放在主图最前面

**决定**: 主图入口第一道判断为 `has_pending_input?`，而非直接走 `classify_intent`。

```
START → has_pending_input?
         ├─ yes → handle_pending_input → resume_workflow
         └─ no  → load_context → classify_intent → route_to_subgraph
```

**理由**:
- 用户第二轮回答"韩国那个"不能重新走 intent classifier
- 所有中断类型（消歧、确认、缺字段）共用同一套恢复机制
- `pending_input.type` 决定恢复后进入哪个处理节点

### D5: 工具粒度 —— 读细写粗

**决定**:
- 查询类工具（search_emby, search_tmdb, search_download_source）细粒度，允许 Agent 自主组合
- 写入类工具（create_download_task, apply_organize_plan）粗粒度封装，包含事务边界和确认机制
- 推荐类工具中等抽象，Agent 控制组合但不直接操作文件
- 每个子图有独立工具白名单，Agent 看不到无关工具

**理由**:
- 只读操作低风险，细粒度体现 Agent 工具调用能力
- 写入操作必须有确认、回滚和日志，粗粒度封装保证安全
- 工具白名单限制防止 LLM 幻觉导致危险操作

### D6: 消歧机制 —— candidate_resolver 独立节点

**决定**: 消歧不由 LLM 在规划阶段预判，也不仅靠搜索结果判断。设计独立的 `candidate_resolver` 节点，使用规则 + LLM Judge 混合判断。

- **规则层**: Top 1 和 Top 2 分数差距 < 0.15、多个候选标题近似相同、候选跨媒体类型 → 直接触发消歧
- **LLM Judge 层**: 规则通过后，LLM 判断是否可安全选择唯一候选，否则生成澄清问题

**理由**:
- 先搜索再判断，不凭感觉猜测歧义
- 规则处理明确场景（快速、可靠），LLM 处理模糊场景（灵活）
- 独立节点便于复用，所有子图共用同一套消歧逻辑
- LLM Judge 只能决定"是否提问"和"怎么问"，不能绕过安全规则

### D7: 记忆系统 —— 结构化优先，分阶段演进

**决定**:
- **Phase 1**: 结构化偏好表 + 行为事件表 + 用户画像摘要，不做向量记忆
- **Phase 2**: 加入 memory_notes + embedding，支持语义召回
- **Phase 3**: 自动偏好归纳，从行为中更新 confidence

MemoryContext 由 Memory Router 根据 intent 动态构造，不同 intent 加载不同内容。严格控制字段数量，不放全量历史数据。

**理由**:
- 结构化记忆足够覆盖 V1 需求，向量记忆增加复杂度但边际收益有限
- 明确偏好结构化（准确），模糊反馈向量化（灵活），历史行为事件化（可追溯）
- 动态构造 MemoryContext 避免把所有历史灌入 prompt
- Agent 看到的是"当前需要知道的"，不是全量记忆

### D8: 元数据 API 选择 TMDB

**决定**: 影视元数据统一使用 TMDB API。

**理由**:
- 免费、API 稳定、多语言支持、社区活跃
- 覆盖率满足 V1-V3 需求
- 相比 Douban（API 受限）、OMDB（英文为主），TMDB 在中文内容和 API 可靠性之间平衡最好

### D9: 文件整理 —— 先检测报告，后执行

**决定**: 采用"检测 + 报告 → 人工确认 → 执行"三步模式。不直接暴露 `rename_file`/`move_file`/`delete_file` 给 Agent。

**理由**:
- 文件操作不可逆，错误代价高
- Agent 负责生成整理计划（generate_organize_plan），用户确认后由后端工具按计划执行（apply_organize_plan）
- 飞牛负责刮削，Agent 只负责文件到位 + Emby refresh 触发

### D10: 通知仅 Web

**决定**: V1 通知仅在 Web UI 展示，不接入微信/Telegram/邮件。

**理由**:
- Web 通知零额外依赖，当下够用
- 微信接入复杂度高且受限
- Telegram bot 可在 V2 评估加入

### D11: Emby 作为只读查询层

**决定**: Emby 仅用作媒体库查询接口（`/Items` 等 REST API），刮削由飞牛完成。若 Emby 不可用，降级为文件系统扫描。Emby 可行性将在独立分支上验证。

**理由**:
- 飞牛无开放查询 API
- Emby REST API 成熟、文档齐全
- 不依赖 Emby 的刮削功能，只利用其媒体库索引

## Consequences

- 架构从单一直线 workflow 演进为多子图 + 意图路由的 Agent 系统
- 当前代码（keyword → search → confirm → download）封装为 `search_download` 子图，其他子图增量添加
- 工具注册和子图白名单需要建立统一的 Tool Registry 机制
- 中断恢复（has_pending_input?）必须在主图入口最先实现，否则多轮对话无法工作
