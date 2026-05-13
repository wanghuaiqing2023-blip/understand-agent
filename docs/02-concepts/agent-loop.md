# 概念：Agent Loop

## 当前定义

Agent Loop 是智能体的最小行动循环：

```text
用户任务
-> 构建模型输入
-> 调用模型
-> 提取工具行动
-> 执行工具
-> 追加观察结果
-> 再次调用模型
-> 最终回答或失败
```

它不是任务树，也不是递归规划。任务树、记忆、压缩和错误恢复都可以在未来接入，但第一层地基是循环。

## 请求结构

第一版严格沿用 Codex agent loop 的三段式请求：

```text
instructions
tools
input
```

- `instructions`：固定的智能体行为指令。
- `tools`：模型可调用的工具定义。
- `input`：权限说明、项目指令、环境上下文、用户任务和历史工具观察。

## Stateless Context

服务端被视为 stateless。每一轮请求都由本地发送完整 `input_items`，不使用 `previous_response_id`。

历史只能追加：

```text
旧 input
+ 模型输出的 tool action
+ 本地工具观察
= 新 input
```

旧 input 必须保持新 input 的精确前缀，不能重写、重排或修改。

## Tool Action

工具要做广义理解，不等同于 `function_call`。第一版只支持 OpenAI Responses API 中的 `function_call`，但内部概念使用：

```text
ToolAction
ToolObservation
```

未来可以扩展到 web search、file search、computer use、MCP 工具或其他 hosted tools。

## 停止条件

正常完成：

```text
模型不再请求任何 tool action，并且能提取 final answer。
```

失败：

```text
无 tool action 但无 final answer
超过模型调用预算
超过工具调用预算
API key 缺失
API 调用失败
未知 tool action
```

用户拒绝 shell 命令不是停止条件，而是一个观察结果，应回填给模型。

## 当前边界

第一版不实现：

- fake model
- 任务树
- 递归规划
- 记忆检索
- context 压缩
- retry / fallback
- shell 沙箱
- stdout / stderr 截断
