# ADR-0007: Codex-Style Sessions And Resume

## Status

accepted

## Context

One-shot execution is not enough for studying agent behavior. We need to keep the visible context so the user can continue asking follow-up questions such as why the model chose `shell` instead of answering directly.

Codex's split between interactive sessions, one-shot `exec`, and `resume` is a good model for this project.

## Decision

Adopt Codex-style session semantics.

- `python -m understand_agent` starts a new interactive session.
- `python -m understand_agent "<task>"` starts a new interactive session and uses `<task>` as the first user turn.
- `python -m understand_agent exec "<task>"` runs a one-shot task.
- `python -m understand_agent run "<task>"` is removed.
- `resume`, `resume --last`, `resume --all`, `resume --last --all`, and `resume <SESSION_ID>` restore saved sessions.
- Session files live under the user's HOME directory at `.understand-agent/sessions`.
- With explicit user permission, add `python -m understand_agent archive <SESSION_ID>` for moving an active session into one `.gzip` archive file under `.understand-agent/archived_sessions`.
- Add `python -m understand_agent unarchive <ARCHIVE_FILE_NAME>` to restore one archive file.
- Archive file names use `<SESSION_ID>.gzip`; archive time is kept inside the manifest instead of the file name.
- Sessions store full append-only `input_items`, not just summaries.
- `AGENTS.md` is injected only when the session is created; each later turn appends fresh `environment_context` and the new user message.

## Consequences

The project now has a durable context layer separate from trace logs. A trace explains one execution run; a session preserves the conversation state that can be sent back to the model.

This enables follow-up questions and tool-choice attribution based on visible history. It does not expose hidden model reasoning.

The context can now grow across turns, so context size measurement and compaction become natural follow-up requirements.

Archived sessions are removed from the active resume set together with their related trace logs and index entries. The `.gzip` file keeps compressed JSON containing the session, related logs, related index entries, and a manifest, so restoring the file can put the session back into the active stores.
