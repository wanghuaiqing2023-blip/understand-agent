# GPT-5.5 Agent Loop Implementation Plan

## Summary

This plan records the next implementation stage for `understand-agent`.

The goal is to implement a real agent loop based on OpenAI's Codex agent loop design: use GPT-5.5 through the OpenAI Responses API, expose local tools to the model, execute requested tool actions locally, append observations back into the local context, and continue until the model stops requesting tool actions and produces a final answer.

The first version should be simple, direct, and close to the official loop shape. It should not introduce fake models, task trees, recursive planning, context compression, retries, or fallback models.

## Key Decisions

- Use the OpenAI official Python SDK.
- Use `gpt-5.5` as the fixed model.
- Do not allow overriding the model from the CLI.
- Hard-code reasoning effort in code.
- Assume the OpenAI server side is stateless.
- Maintain full `input_items` locally.
- Do not use `previous_response_id`.
- Do not implement context compression in the first version.
- Use `OPENAI_API_KEY` from the environment.
- If `OPENAI_API_KEY` is missing, fail honestly with a JSON error.
- If the OpenAI API call fails, fail honestly without retry or fallback.

## CLI Interface

Add:

```powershell
python -m understand_agent run "<task>"
```

Supported options:

```powershell
--max-model-calls <int>
--max-tool-calls <int>
```

Defaults:

```text
max_model_calls = 8
max_tool_calls = 8
```

Do not add:

```text
--model
--reasoning-effort
--provider fake
```

The `run` command should output JSON to stdout:

```json
{
  "run_id": "...",
  "ok": true,
  "status": "done",
  "final_answer": "...",
  "model_calls": 3,
  "tool_calls": 2,
  "error": null
}
```

On failure:

```json
{
  "run_id": "...",
  "ok": false,
  "status": "failed",
  "final_answer": null,
  "model_calls": 0,
  "tool_calls": 0,
  "error": "OPENAI_API_KEY is not set"
}
```

stderr should continue to print the trace path.

## Context Construction

Follow the Codex agent loop request shape:

```text
instructions
tools
input
```

Do not collapse everything into one prompt string.

### instructions

Use fixed base agent instructions that tell the model:

- It is a local agent running on the user's Windows machine.
- It can use tools to inspect files and request shell commands.
- It should use tools when needed instead of guessing.
- It should continue after tool observations until it can answer.
- Shell commands require user approval before execution.

### tools

Expose these tools to the model as function tools:

```text
list_files
read_file
search_text
shell
```

Keep tool order stable.

### input

Initial input order must be:

```text
1. permissions instructions
2. AGENTS.md instructions, if project_root/AGENTS.md exists
3. environment_context
4. user task
```

If `AGENTS.md` exists, inject it automatically. If it does not exist, skip it. Missing `AGENTS.md` must not fail the run.

Use this environment model:

```xml
<environment_context>
  <cwd>C:\Users\27605\understand-agent</cwd>
  <workspace_root>C:\Users\27605</workspace_root>
  <project_root>C:\Users\27605\understand-agent</project_root>
  <shell_default_workdir>C:\Users\27605\understand-agent</shell_default_workdir>
  <shell>powershell</shell>
  <current_date>2026-05-13</current_date>
  <timezone>Asia/Singapore</timezone>
</environment_context>
```

The first implementation can generate `current_date` dynamically from local time, but the timezone label should be `Asia/Singapore`.

## Append-Only Loop History

After each model response:

- Append all model output items to `input_items`.
- Extract supported tool actions.
- Execute tool actions locally.
- Append tool observations as tool output items.
- Send the full updated `input_items` on the next model call.

The old input must remain an exact prefix of the new input:

```python
old_input == new_input[:len(old_input)]
```

Never rewrite, reorder, or mutate existing input items during the first version.

## Tool Action Semantics

Use broad internal names:

```text
ToolAction
ToolObservation
extract_tool_actions()
execute_tool_action()
append_tool_observation()
```

First version only supports OpenAI `function_call` items.

If the model returns any unsupported tool action type:

```text
fail the run directly
do not execute tools
do not ignore the action
record unsupported_tool_action in trace
```

## Stop Conditions

The loop stops successfully when:

```text
the model no longer requests any supported tool action
and a final answer can be extracted
```

The loop fails when:

- The model no longer requests a tool action but no final answer can be extracted.
- `max_model_calls` is exceeded.
- `max_tool_calls` is exceeded.
- `OPENAI_API_KEY` is missing.
- The OpenAI SDK call raises an exception.
- The model returns an unsupported tool action type.

User rejection of a shell command is not a stop condition. It is a tool observation and should be returned to the model.

## Workspace And Shell Roots

Use separate concepts:

```text
workspace_root = C:\Users\27605
project_root = C:\Users\27605\understand-agent
shell_default_workdir = C:\Users\27605
```

Meaning:

- `workspace_root`: root allowed for `list_files`, `read_file`, and `search_text`.
- `project_root`: the `understand-agent` project location, used for `AGENTS.md`, docs, tests, and project context.
- `shell_default_workdir`: default shell execution directory.

Paths outside `workspace_root` should be rejected by file tools.

## Shell Tool

Expose `shell` to the model as a function tool.

Parameters:

```json
{
  "command": "string, required",
  "workdir": "string, optional, defaults to C:\\Users\\27605",
  "timeout_ms": "integer, optional, defaults to 30000"
}
```

Behavior:

- Execute commands in the host environment, not in a sandbox.
- Use Windows PowerShell.
- If `workdir` is omitted, use `C:\Users\27605`.
- Resolve relative `workdir` paths against `C:\Users\27605`.
- Reject final workdirs outside `C:\Users\27605`.
- Before execution, show the resolved workdir and command to the user.
- Only `y` or `yes` confirms execution.
- Any other input rejects execution.
- Rejected shell commands become tool observations.
- First version does not truncate stdout or stderr.

Confirmation prompt:

```text
Model requested shell command:

workdir:
C:\Users\27605\understand-agent

command:
python -m unittest discover -s tests

Execute? [y/N]:
```

Successful shell result:

```json
{
  "ok": true,
  "data": {
    "command": "python -m unittest discover -s tests",
    "workdir": "C:\\Users\\27605\\understand-agent",
    "exit_code": 0,
    "stdout": "...",
    "stderr": "..."
  },
  "error": null
}
```

Rejected shell result:

```json
{
  "ok": false,
  "data": {
    "command": "...",
    "workdir": "..."
  },
  "error": "shell command rejected by user"
}
```

## Trace Events

Extend the existing trace system with events such as:

```text
agent_run_started
context_built
model_call_started
model_call_finished
model_call_failed
model_output_appended
tool_action_extracted
tool_observation_appended
unsupported_tool_action
shell_approval_requested
shell_approval_granted
shell_approval_rejected
shell_command_started
shell_command_finished
agent_run_finished
```

Existing `tool_call_started` and `tool_call_finished` events should continue to work.

Trace should record real failure reasons. Do not hide or over-polish errors.

## Tests

Add strict unit tests for context construction:

- Request has separate `instructions`, `tools`, and `input`.
- Initial input order is exactly permissions, optional `AGENTS.md`, environment, user task.
- `AGENTS.md` is injected when present.
- Missing `AGENTS.md` is skipped.
- Environment context contains cwd, workspace root, project root, shell default workdir, shell, date, and `Asia/Singapore`.
- User task is the final initial input item.
- Tool list order is stable.

Add strict append-history tests:

- Single function call and tool output append correctly.
- Multiple function calls preserve model output order.
- Failed tool output is appended as an observation.
- Rejected shell output is appended as an observation.
- Bad JSON arguments produce a clear tool observation error.
- Final assistant message ends the loop.
- Multi-round history remains append-only.
- Existing input items are not mutated.

Add shell tests:

- Default workdir is `C:\Users\27605`.
- Relative workdir resolves under Home.
- Workdir outside Home is rejected.
- User confirmation `y` and `yes` execute.
- Other input rejects.
- stdout, stderr, and exit code are returned in full.

Add OpenAI/client behavior tests:

- Missing `OPENAI_API_KEY` returns JSON failure and does not call the API.
- SDK exceptions are reported as run failures.
- Unsupported tool action fails the run.
- `max_model_calls` and `max_tool_calls` default to 8 and can be set from CLI.

Keep existing tests passing:

```powershell
python -m unittest discover -s tests
```

## Documentation Updates During Implementation

When implementing this plan, also update:

- `docs/01-requirements/requirement-list.md`
- `docs/02-concepts/agent-loop.md`
- `docs/03-decisions/` with an ADR for the GPT-5.5 Responses API loop
- `docs/04-dev-log/` with the implementation log

## Non-Goals For First Version

Do not implement:

- Fake model provider.
- Rule-based fake model.
- Task tree.
- Recursive planning.
- Memory retrieval.
- Context compression.
- Retry or fallback model.
- Model override CLI flag.
- Reasoning effort CLI flag.
- Shell sandboxing.
- stdout/stderr truncation.
- Hosted OpenAI tools such as web search, file search, or code interpreter.
