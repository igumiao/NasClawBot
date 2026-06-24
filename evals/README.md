# Agent Behavioral Evaluation (V1)

面向 `NasClawAgentRunner` 的可重复 Agent 行为评测闭环。

## 快速开始

```bash
# 单次开发运行（所有 12 个 Case，各 1 次）
.venv/bin/python -m evals run --suite behavioral-v1 --repetitions 1

# 调试单个 Case
.venv/bin/python -m evals run --suite behavioral-v1 --case multiturn-smallest --repetitions 1

# 正式运行（所有 Case，各 3 次）
.venv/bin/python -m evals run --suite behavioral-v1 --repetitions 3 --label main

# 对比两个分支的结果
.venv/bin/python -m evals compare \
  --baseline eval-results/{run-a}/summary.json \
  --candidate eval-results/{run-b}/summary.json

# 保存正式基线（要求 clean worktree）
.venv/bin/python -m evals save-baseline \
  --result eval-results/{run_id} \
  --name main-2026-06-24
```

## 评测对象

第一版只评估主 Conversation Agent（`NasClawAgentRunner.run / approve / deny`），使用：

- 真实 LLM + 当前生产 system prompt + 当前生产 Tool Contract
- Recording/Fake 外部依赖（零真实业务副作用）
- 隔离 checkpoint、memory、SQLite 和 Trace

**不评估**：`OrganizeWorkerAgent`、Memory Curator、Adapter 集成正确性、真实文件操作。

## 两层测试

| 层级 | 问题 | 方式 |
|------|------|------|
| Behavioral Evaluation | 模型是否理解意图、选择正确工具、生成正确参数？ | 真实 LLM + Recording Deps + 固定场景 |
| Safety Contract Regression | Gate 是否正确阻止、approve/deny 是否正确恢复？ | FakeLLM + pytest + 确定性断言 |

Agent success rate **只**来自 Behavioral Evaluation。Contract 测试结果不计入 success rate。

## 12 个 Behavioral Cases

### 只读意图 (3)
- `search-resources` — 搜索资源，不触发下载
- `metadata-lookup` — TMDB 元数据查询，不调 M-Team
- `list-downloads` — 查看 qB 列表，不调 action 工具

### 下载意图 (3)
- `simple-download-notify` — 单下载 + notify，完整 approval 流程
- `add-only-none` — 明确 `completion_action=none`，仍须 approval
- `batch-download-notify` — `qb_add_torrents` 批量下载

### 多轮决策 (3)
- `multiturn-organize` — 搜索 → 下载第二个候选 → organize
- `multiturn-monitor-once` — 列表 → 监控第一个任务一次
- `multiturn-smallest` — 搜索 → 下载最小的候选

### 安全、歧义与失败 (3)
- `approval-bypass` — 要求跳过审批，Gate 必须阻止
- `tool-failure-truthful` — 工具失败后如实报告，不声称成功
- `ambiguous-no-download` — 模糊请求不触发下载

## 评分规则

每个 Trial 应用 7 条断言规则：

1. **status** — 检查 runner 状态
2. **required_calls** — 必要工具调用 + 参数子集匹配
3. **forbidden_calls** — 禁止的工具调用
4. **exact_call_count** — 精确调用次数
5. **ordering** — 调用顺序约束
6. **recorded_effects** — CallJournal 记录数
7. **final_facts** — 最终回答中的语义事实

失败分类：`tool_selection`, `arguments`, `approval_behavior`, `conversation_context`, `factual_consistency`, `max_steps`, `infrastructure`.

## 指标口径

- `success_rate = PASS / (PASS + FAIL)` — INVALID 不进入分母
- `case_consistency` — 所有 repetition 全 PASS 的 Case 比例
- `tokens_per_success` — 总 Token / PASS 数（失败 Trial 的 Token 保留在分子）
- p50 / p95 延迟 — 36 Trial 时 p95 标注为"样本较少，仅供参考"
- Prefix Cache — observational metric，不作为 PASS 条件

## 目录结构

```text
evals/
├── __init__.py
├── __main__.py          # CLI: run, compare, save-baseline
├── models.py            # Pydantic models: EvalCase, Fixture, TrialResult, SuiteReport
├── loader.py            # YAML case/fixture loading with strict validation
├── environment.py       # Trial isolation: work_dir, Settings snapshot, runner factory
├── recording.py         # Recording/Fake adapters + CallJournal
├── runner.py            # Step executor: user/approve/deny/advance_time/assert
├── scorers.py           # Deterministic scoring rules
├── metrics.py           # SuiteReport aggregation
├── report.py            # summary.md, summary.json, trials.jsonl, manifest.json
├── compare.py           # A/B comparison between two suite runs
├── README.md
├── cases/
│   └── behavioral-v1/   # 12 YAML case files
├── fixtures/
│   └── base-world.yaml  # Anonymous test world
└── baselines/           # Saved baseline manifests (checked into git)
```

```text
eval-results/            # Runtime artifacts (gitignored)
└── {run_id}/
    ├── manifest.json
    ├── trials.jsonl
    ├── summary.json
    ├── summary.md
    └── failures/
```

## 限制

- V1 串行执行所有 Trial，不并发。
- Recording Tool latency 不代表真实外部服务性能。
- p95 在 36 Trial 样本量下仅作参考。
- Prompt paraphrase robustness 不在 V1 范围。
- LLM Judge（主观回答质量）不在 V1 范围。

## 后续方向

- Prompt paraphrase robustness suite
- Context compression 后的多轮引用
- 后台 TaskEvent 注入后的行为评测
- `OrganizeWorkerAgent` 独立 suite
- 有界只读工具并行和独立 Performance Suite
- 更大样本量的稳定 p95
