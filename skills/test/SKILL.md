---
name: test
description: 测试用技能，用于验证 skill 加载机制
---

# 测试技能

这是一个用于验证 skill 加载机制正常工作的测试技能。

如果你看到这段内容，说明 `skill_load("test")` 工具调用成功，
L2 内容已注入到对话上下文中。

## 验证清单

- [x] SkillLoader 启动时扫描到了这个文件
- [x] L1 元数据出现在系统提示词中
- [x] Agent 调用了 skill_load 工具
- [x] L2 内容（你正在阅读的这段）成功返回

## 用法

在对话中对 Agent 说："加载 test 技能"，
Agent 应该调用 `skill_load({"name": "test"})` 工具。
