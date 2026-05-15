# Concept: Session

## Definition

A session is a durable context container for multiple agent turns.

It is different from a trace:

```text
trace   = evidence for one execution run
session = visible context that can be sent back to the model
```

## Current Design

Session files are stored under the user's HOME directory:

```text
C:\Users\27605\.understand-agent\sessions\
```

Archived session files are stored under:

```text
C:\Users\27605\.understand-agent\archived_sessions\<SESSION_ID>.gzip
```

Each session stores:

- `session_id`
- root paths such as `project_root`, `workspace_root`, and `shell_default_workdir`
- full append-only `input_items`
- turn summaries linking each turn to a `run_id` and trace path

## Append-Only Rule

Old context items are not rewritten, deleted, or reordered.

Each new user turn appends:

```text
latest environment_context
new user message
model output
tool observations
final assistant message
```

This preserves the visible context needed for follow-up questions and tool-choice attribution.

## Boundary

A session does not expose hidden model reasoning. It only lets the model explain prior behavior from visible history: user requests, tool calls, observations, and assistant messages.

## Local Inspection

Interactive sessions support a local `/context` command. It prints the complete JSON request shape rebuilt from the currently saved session context:

```text
instructions
tools
input
```

This command does not call the model, does not append a user turn, and does not modify the session file. It exists so the project can inspect what visible context would be sent to the model.

## Archive

Archiving a session moves all session-owned information out of the active stores and into one reversible gzip archive file.

```powershell
python -m understand_agent archive <SESSION_ID>
```

The `.gzip` file contains compressed JSON with:

```text
manifest.json
session
session_index_lines
log_files
log_index_entries
```

An archived session is no longer available through `resume` because the active context file, related logs, and related index entries have moved into the archive file.

Use `unarchive` to restore one archive file:

```powershell
python -m understand_agent unarchive <ARCHIVE_FILE_NAME>
```

Restoring writes the session JSON, related trace logs, and related index entries back to their active locations, then deletes the `.gzip` file.
