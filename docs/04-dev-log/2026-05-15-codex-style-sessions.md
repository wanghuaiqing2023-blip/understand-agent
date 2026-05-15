# 2026-05-15 Codex-Style Sessions

## Summary

This iteration introduced durable interactive sessions and Codex-style resume behavior.

## Changes

- Added HOME-based session storage under `.understand-agent/sessions`.
- Added `SessionStore`, `SessionRecord`, and turn summaries.
- Changed one-shot execution from `run` to `exec`.
- Removed the old `run` command.
- Added bare prompt startup: `python -m understand_agent "<task>"` creates a session, runs the first turn, and keeps the session open.
- Added `resume`, `resume --last`, `resume --all`, `resume --last --all`, and `resume <SESSION_ID>`.
- Added `archive <SESSION_ID>` and `unarchive <ARCHIVE_FILE_NAME>` after explicit user approval for non-Codex session management commands.
- Updated archive semantics so session JSON, related trace logs, session index entries, and log index entries move into one `.gzip` archive file.
- Simplified archive file names to `<SESSION_ID>.gzip`; the archive timestamp remains inside the manifest.
- Added local `/context` in interactive sessions to print the saved context as a full `instructions / tools / input` request without calling the model or saving a turn.
- Updated the agent loop so completed runs return final `input_items`.
- Added support for continuing from existing `input_items`.

## Reasoning

Session history is the visible context that lets the user keep talking to the same agent state. It is also the basis for asking why the model selected a tool, because the model can inspect the prior user request, tool call, tool observation, and final answer.

## Verification

Run:

```powershell
python -m unittest discover -s tests
```
