# ADR-0006: Shell-Only Tool Surface

## Status

accepted

## Context

The project originally implemented three custom read-only filesystem tools: `list_files`, `read_file`, and `search_text`. After introducing a real agent loop and a host PowerShell tool, those custom tools became redundant for the current learning goal.

The important capability is not a large catalog of hand-written tools, but whether the model can use a general execution tool to inspect files, write small programs, run tests, and recover from observations.

## Decision

Expose only `shell` as the default tool.

- `build_default_registry()` registers only `shell`.
- `list_files`, `read_file`, and `search_text` are removed from code and tests.
- The `--toolset shell-only` experiment flag is removed because shell-only is now the default.
- File listing, file reading, text search, file writing, and test execution are expected to happen through PowerShell commands.

## Consequences

The tool surface is smaller and closer to the core Codex-style loop we want to study: model action, local execution, observation, continuation.

This increases the importance of shell approval and trace logs, because shell is broader and more powerful than read-only helpers. The project still rejects shell workdirs outside `workspace_root`, but the shell itself is not a sandbox.

If future failures show that the model repeatedly struggles with common shell operations, we can add narrow helper tools later based on evidence rather than assumption.
