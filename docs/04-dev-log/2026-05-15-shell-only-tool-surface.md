# 2026-05-15 Shell-Only Tool Surface

## Summary

This iteration reduced the model-facing tool surface to a single `shell` tool.

## Changes

- Removed the custom `list_files`, `read_file`, and `search_text` tools.
- Kept `ToolRegistry`, `ToolSpec`, `ToolResult`, and `ToolContext` as the core tool protocol.
- Removed the temporary `--toolset shell-only` run option because shell-only is now the default.
- Updated tests so `python -m understand_agent tools` returns only `shell`.
- Added coverage that old custom tool names now return `unknown tool`.

## Reasoning

For this stage, a general shell tool is enough to test whether the agent loop can solve real local tasks through command execution and observation. Keeping separate read-only helpers would make the system look more capable while hiding whether the loop itself can drive a general tool effectively.

## Verification

Run:

```powershell
python -m unittest discover -s tests
```
