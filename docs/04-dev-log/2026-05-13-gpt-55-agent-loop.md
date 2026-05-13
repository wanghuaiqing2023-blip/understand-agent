# 2026-05-13：GPT-5.5 Agent Loop

## 完成内容

- 新增 `run` 命令，进入真实 Agent Loop。
- 新增 OpenAI Responses API 客户端，固定使用 `gpt-5.5`。
- 新增 context builder，按 `instructions / tools / input` 构建请求。
- `AGENTS.md` 存在时自动注入模型输入。
- 本地维护完整 `input_items`，工具历史 append-only。
- 新增 `ToolAction` / `ToolObservation` 概念，第一版只支持 `function_call`。
- 新增主机 `shell` 工具，暴露给模型，执行前人工确认。
- 将 `workspace_root` 提升为 Windows Home，将 `project_root` 保留为项目目录。
- 将 `cwd` 和 `shell_default_workdir` 设置为真实启动目录，让模型理解用户当前所在目录。
- 扩展 trace 事件，记录模型调用、tool action、shell 审批和 run 结果。
- 增加 context、agent loop、shell、无 API key 等单元和集成测试。

## 验证

```powershell
python -m unittest discover -s tests
```

本地通过 49 个测试。

## 关键收获

Agent Loop 的地基不是任务树，而是：

```text
模型输出行动
-> 本地执行工具
-> 观察回填 context
-> 模型继续推理
```

context 拼接是核心基础设施，必须用严格测试保护。只要输入顺序、工具定义或历史追加不稳定，模型行为就会变得不可解释。

## 后续方向

- 手动设置 `OPENAI_API_KEY` 后运行真实 `run` 任务。
- 观察 GPT-5.5 是否会主动使用 shell 进行项目分析和测试。
- 基于真实 trace 决定是否引入 context 压缩、输出截断、写文件工具和权限策略。
