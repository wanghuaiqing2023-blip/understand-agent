# 2026-05-15 Remove Call Budget Parameters

## Summary

This iteration removed model/tool call budget parameters from the first agent loop.

## Changes

- Removed `max_model_calls` and `max_tool_calls` from `AgentRunConfig`.
- Removed `--max-model-calls` and `--max-tool-calls` from the `run` CLI.
- Removed budget-exceeded stop conditions from the loop.
- Updated tests and docs to treat call count as telemetry, not a control surface.

## Reasoning

The first loop should stay close to the natural Codex-style action/observation cycle. A hard call-count budget adds an artificial stop condition before we have enough evidence about real failure modes.

Future context-size tracking or compaction should be designed from trace evidence rather than by keeping a generic call-count limit.
