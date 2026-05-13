# ADR-0005：使用 GPT-5.5 Responses API 实现真实 Agent Loop

## 状态

accepted

## 背景

项目已经完成工具注册、只读工具、CLI 和执行轨迹日志。下一步目标是验证 Codex agent loop 的核心判断：真实模型在工具循环中能根据观察结果继续行动，从而表现出工程型智能体能力。

本阶段不再继续做固定任务工作流，也不引入 fake model 作为主要路径，而是直接接入真实 GPT-5.5。

## 决策

实现 `python -m understand_agent run "<task>"`：

- 使用 OpenAI 官方 Python SDK。
- 固定模型为 `gpt-5.5`。
- reasoning effort 固定写在代码里。
- 不提供 `--model` 或 `--reasoning-effort`。
- 使用 Responses API 的 `instructions / tools / input` 结构。
- 本地维护完整 `input_items`，不使用 `previous_response_id`。
- 服务端按 stateless 假设处理。
- 暴露 `list_files / read_file / search_text / shell` 为 function tools。
- `shell` 在主机 PowerShell 中执行，每次执行前要求用户确认。
- `max_model_calls` 和 `max_tool_calls` 默认 8，可在 CLI 设置。

## 原因

固定 GPT-5.5 和 reasoning effort 可以减少实验变量，让我们专注验证 loop 本身。

本地维护完整 context 可以让行为更可观察，也符合 Codex agent loop 文章中展示的无状态请求方式。

第一版加入 shell 工具，是为了让模型具备通过编程和命令解决问题的能力；人工确认保留人类控制权。

不实现 fake model，是为了避免把重点放到模拟行为上。自动化测试覆盖确定性的 context、schema、tool action、shell 和错误处理；真实智能水平通过手动实验观察。

## 后果

`run` 命令需要 `OPENAI_API_KEY`。缺失 key 或 API 调用失败时，系统直接返回真实错误，不自动重试、不 fallback。

shell 在主机环境执行，可能访问 Home 目录下的真实文件和命令，因此必须保留确认机制和 trace 记录。

第一版不做 context 压缩，长任务可能导致 token 增长过快。后续需要基于真实运行日志设计 compaction。

## 复审条件

当出现以下情况时复审：

- 真实 run 的上下文过长或成本过高。
- shell 输出过大导致 trace 或 context 不可控。
- 模型频繁请求未知 tool action。
- 需要加入写文件、patch、git、browser 或 hosted tools。
