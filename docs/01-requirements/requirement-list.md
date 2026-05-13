# 需求池

这个文件记录所有待实现、已实现、暂缓和废弃的需求。

## 状态说明

- idea：想法阶段
- planned：已计划
- in-progress：实现中
- done：已完成
- paused：暂缓
- rejected：不做

## 需求驱动原则

本项目以实现需求为根本驱动力。概念文档、ADR、开发日志和认知突破都应服务于需求的识别、实现、验证和演化。

新增能力不能只以“看起来先进”或“模仿成熟智能体”为理由进入实现阶段。每个重要能力都应尽量回答：

- 它对应哪个用户需求或阶段目标？
- 它解决什么具体问题？
- 它的验收标准是什么？
- 它会改变哪些已有概念、风险或技术取舍？
- 它是否应该先进入需求池，而不是直接进入代码实现？

## 需求来源

当前阶段应主动从以下来源收集需求：

1. 本项目狗粮任务：围绕 `AGENTS.md`、`docs/`、代码结构和开发日志产生的真实任务。
2. 行为观察降级：观察 Codex / OpenCode 等智能体的执行流程，再拆成当前阶段可实现的小能力。
3. 专业评测基准：从 Terminal-Bench、SWE-bench、AgentBench、WebArena、OSWorld、GAIA 等 benchmark 中提炼任务类型、验收方式和失败模式。
4. 自建基础任务集：文件读取、搜索、修改、命令执行、总结、验证等最小任务。
5. 失败案例：把智能体无法完成、完成不稳或无法解释的地方记录为新需求。
6. 成熟项目 issue：从 Codex、OpenCode 等项目 issue 中降级提炼适合本阶段的需求。

专业评测基准不能直接等同于产品需求。它们更适合作为需求矿场：先抽取能力结构，再转化为本项目当前阶段的小需求和验收标准。

## v0.1：最小智能体

| ID | 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| R-001 | 用户输入一个任务 | planned | 初始入口可以是 CLI |
| R-002 | 智能体生成简短计划 | planned | 先支持文本计划 |
| R-003 | 智能体读取当前目录文件 | done | v0.1-alpha 已实现 `read_file` 只读工具，限制工作区边界 |
| R-004 | 智能体搜索代码或文本 | done | v0.1-alpha 已实现 `search_text` 只读工具 |
| R-005 | 智能体修改文件 | planned | 需要变更摘要 |
| R-006 | 智能体运行命令 | planned | 需要安全确认机制 |
| R-007 | 智能体完成后输出总结 | planned | 总结结果、风险、验证情况 |
| R-008 | 工具注册系统最小版 | done | 实现 `ToolSpec`、`ToolRegistry`、`ToolResult`、`ToolContext` |
| R-009 | 只读工具集 | done | 实现 `list_files`、`read_file`、`search_text` |
| R-010 | 工具展示与调用 CLI | done | 支持 `python -m understand_agent tools` 和 `call` |
| R-011 | 自动化单元测试与集成测试 | done | 使用标准库 `unittest`，统一命令为 `python -m unittest discover -s tests` |
| R-012 | GitHub Actions 自动测试 | done | push / PR 时运行 unittest |
| R-013 | 执行轨迹日志 | done | 默认写入 `.understand-agent/logs/*.jsonl`，每个关键动作记录为 TraceEvent |
| R-014 | 工具调用失败归因证据 | done | 记录工具请求、开始、结束、耗时、完整结果和原始错误 |
| R-015 | 执行结束后暴露 trace 日志位置 | done | CLI 在 stdout 输出 `run_id`，并在 stderr 输出本次 trace 文件路径 |
| R-016 | 最近执行日志索引与查询命令 | done | 已提供 `index.jsonl`、`logs list` 和 `logs show <run_id>` |
| R-017 | GPT-5.5 Agent Loop | done | 新增 `run` 命令，使用 OpenAI Responses API、本地 stateless context、工具行动和观察回填循环 |
| R-018 | Codex 风格 context 拼接 | done | 请求分为 `instructions / tools / input`，初始 input 注入权限、AGENTS、环境和用户任务，历史保持 append-only |
| R-019 | 主机 shell 工具 | done | 将 `shell` 暴露为模型可调用 function tool，主机 PowerShell 执行，执行前人工确认 |

## v0.2：任务工作流

| ID | 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| R-101 | 任务状态管理 | idea | pending / running / blocked / done |
| R-102 | 工具注册系统 | done | v0.1-alpha 已完成最小版，后续可扩展权限、日志和 adapter |
| R-103 | 操作日志 | done | v0.2-alpha 已实现本地 JSONL 执行轨迹 |
| R-104 | 错误恢复 | idea | 失败后能解释和重试 |
| R-105 | 简单记忆文件 | idea | 先用本地文件沉淀长期信息 |
| R-106 | 模型工具循环停止条件 | done | 无 tool action 且有 final answer 时完成；预算耗尽、API 失败或未知 tool action 时失败 |

## v0.3：工程能力

| ID | 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| R-201 | 代码库问答 | idea | 根据项目文件回答问题 |
| R-202 | 自动修 bug | idea | 需要定位、修改、验证闭环 |
| R-203 | 自动运行测试并修复 | idea | 根据测试错误继续迭代 |
| R-204 | 生成 changelog | idea | 从代码变更归纳用户可读说明 |
| R-205 | Git 工作流 | idea | 分支、提交、PR、回滚策略 |

## 新需求模板

```text
ID：
标题：
状态：
背景：
用户价值：
能力层级：
验收标准：
相关概念：
风险：
备注：
```
