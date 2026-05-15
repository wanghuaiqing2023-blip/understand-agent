from __future__ import annotations

import gzip
import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_session_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def default_session_dir(home: Path | None = None) -> Path:
    override = os.environ.get("UNDERSTAND_AGENT_SESSION_DIR")
    if override:
        return Path(override)
    return (home or Path.home()) / ".understand-agent" / "sessions"


def default_archived_session_dir(home: Path | None = None) -> Path:
    override = os.environ.get("UNDERSTAND_AGENT_ARCHIVED_SESSION_DIR")
    if override:
        return Path(override)
    return (home or Path.home()) / ".understand-agent" / "archived_sessions"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SessionTurn:
    run_id: str
    user_input: str
    ok: bool
    status: str
    final_answer: str | None
    model_calls: int
    tool_calls: int
    error: str | None
    trace_path: str | None
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_input": self.user_input,
            "ok": self.ok,
            "status": self.status,
            "final_answer": self.final_answer,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "error": self.error,
            "trace_path": self.trace_path,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SessionTurn:
        return cls(
            run_id=str(value["run_id"]),
            user_input=str(value.get("user_input", "")),
            ok=bool(value.get("ok", False)),
            status=str(value.get("status", "")),
            final_answer=value.get("final_answer"),
            model_calls=int(value.get("model_calls", 0)),
            tool_calls=int(value.get("tool_calls", 0)),
            error=value.get("error"),
            trace_path=value.get("trace_path"),
            timestamp=str(value.get("timestamp") or _now()),
        )


@dataclass
class SessionRecord:
    session_id: str
    created_at: str
    updated_at: str
    project_root: str
    workspace_root: str
    shell_default_workdir: str
    input_items: list[dict[str, Any]]
    turns: list[SessionTurn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_root": self.project_root,
            "workspace_root": self.workspace_root,
            "shell_default_workdir": self.shell_default_workdir,
            "input_items": deepcopy(self.input_items),
            "turns": [turn.to_dict() for turn in self.turns],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SessionRecord:
        return cls(
            session_id=str(value["session_id"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            project_root=str(value["project_root"]),
            workspace_root=str(value["workspace_root"]),
            shell_default_workdir=str(value["shell_default_workdir"]),
            input_items=deepcopy(value.get("input_items", [])),
            turns=[SessionTurn.from_dict(turn) for turn in value.get("turns", [])],
        )


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    created_at: str
    updated_at: str
    project_root: str
    workspace_root: str
    shell_default_workdir: str
    turn_count: int
    last_user_input: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_root": self.project_root,
            "workspace_root": self.workspace_root,
            "shell_default_workdir": self.shell_default_workdir,
            "turn_count": self.turn_count,
            "last_user_input": self.last_user_input,
        }


class SessionStore:
    def __init__(self, session_dir: Path | None = None, archive_dir: Path | None = None) -> None:
        self.session_dir = session_dir or default_session_dir()
        if archive_dir is not None:
            self.archive_dir = archive_dir
        elif session_dir is not None or os.environ.get("UNDERSTAND_AGENT_SESSION_DIR"):
            self.archive_dir = self.session_dir.parent / "archived_sessions"
        else:
            self.archive_dir = default_archived_session_dir()
        self.index_path = self.session_dir / "index.jsonl"

    def create(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        shell_default_workdir: Path,
        input_items: list[dict[str, Any]],
        session_id: str | None = None,
    ) -> SessionRecord:
        now = _now()
        record = SessionRecord(
            session_id=session_id or new_session_id(),
            created_at=now,
            updated_at=now,
            project_root=str(project_root.resolve()),
            workspace_root=str(workspace_root.resolve()),
            shell_default_workdir=str(shell_default_workdir.resolve()),
            input_items=deepcopy(input_items),
            turns=[],
        )
        self.save(record)
        return record

    def save(self, record: SessionRecord) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(record.session_id)
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._append_index(record)

    def load(self, session_id: str) -> SessionRecord:
        path = self.path_for(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        return SessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def append_turn(
        self,
        record: SessionRecord,
        *,
        input_items: list[dict[str, Any]],
        turn: SessionTurn,
    ) -> SessionRecord:
        updated = SessionRecord(
            session_id=record.session_id,
            created_at=record.created_at,
            updated_at=_now(),
            project_root=record.project_root,
            workspace_root=record.workspace_root,
            shell_default_workdir=record.shell_default_workdir,
            input_items=deepcopy(input_items),
            turns=[*record.turns, turn],
        )
        self.save(updated)
        return updated

    def list_summaries(
        self,
        *,
        project_root: Path | None = None,
        include_all: bool = False,
    ) -> list[SessionSummary]:
        summaries = self._summaries_from_index()
        if not summaries:
            summaries = self._summaries_from_files()
        if not include_all and project_root is not None:
            target = str(project_root.resolve())
            summaries = [summary for summary in summaries if summary.project_root == target]
        return sorted(summaries, key=lambda summary: summary.updated_at, reverse=True)

    def latest(
        self,
        *,
        project_root: Path | None = None,
        include_all: bool = False,
    ) -> SessionSummary | None:
        summaries = self.list_summaries(project_root=project_root, include_all=include_all)
        return summaries[0] if summaries else None

    def path_for(self, session_id: str) -> Path:
        return self.session_dir / f"{session_id}.json"

    def archive(self, session_id: str) -> dict[str, Any]:
        source = self.path_for(session_id)
        if not source.exists():
            raise FileNotFoundError(f"session not found: {session_id}")
        session = json.loads(source.read_text(encoding="utf-8"))
        record = SessionRecord.from_dict(session)
        archived_file = self._new_archive_file_path(session_id)
        if archived_file.exists():
            raise FileExistsError(f"archived session already exists: {archived_file.name}")

        session_index_lines = _select_jsonl_entries(self.index_path, "session_id", {session_id})
        log_files, log_index_entries = self._collect_related_logs(record)
        manifest = {
            "session_id": session_id,
            "archived_at": _now(),
            "session_source_path": str(source),
            "session_index_path": str(self.index_path),
            "session_index_entry_count": len(session_index_lines),
            "archive_file": archived_file.name,
            "format": "gzip-json-v1",
        }
        archive_payload = {
            "manifest": manifest,
            "session": session,
            "session_index_lines": session_index_lines,
            "log_files": log_files,
            "log_index_entries": log_index_entries,
        }
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(archived_file, "wt", encoding="utf-8") as file:
            json.dump(archive_payload, file, ensure_ascii=False, separators=(",", ":"))

        source.unlink()
        self._remove_from_index(session_id)
        self._remove_related_logs(record)
        return {
            "session_id": session_id,
            "source_path": str(source),
            "archived_file": archived_file.name,
            "archived_path": str(archived_file),
            "archived_log_count": len(log_files),
            "archived_log_index_entry_count": len(log_index_entries),
        }

    def restore_archived(self, archive_file_name: str) -> dict[str, Any]:
        archive_file = self._resolve_archive_file_path(archive_file_name)
        if not archive_file.exists():
            raise FileNotFoundError(f"archived session not found: {archive_file_name}")
        with gzip.open(archive_file, "rt", encoding="utf-8") as file:
            archive_payload = json.load(file)

        manifest = archive_payload["manifest"]
        session_id = str(manifest["session_id"])
        session_destination = self.path_for(session_id)
        if session_destination.exists():
            raise FileExistsError(f"active session already exists: {session_id}")

        log_files = archive_payload.get("log_files", [])
        for item in log_files:
            restore_path = Path(str(item["source_path"]))
            if restore_path.exists():
                raise FileExistsError(f"trace log already exists: {restore_path}")

        self.session_dir.mkdir(parents=True, exist_ok=True)
        session_destination.write_text(
            json.dumps(archive_payload["session"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        session_index_lines = archive_payload.get("session_index_lines", [])
        if session_index_lines:
            _append_lines(self.index_path, session_index_lines)
        else:
            self._append_index(SessionRecord.from_dict(json.loads(session_destination.read_text(encoding="utf-8"))))

        restored_logs = []
        for item in log_files:
            restore_path = Path(str(item["source_path"]))
            restore_path.parent.mkdir(parents=True, exist_ok=True)
            restore_path.write_text(str(item["content"]), encoding="utf-8")
            restored_logs.append(str(restore_path))

        log_index_entries = archive_payload.get("log_index_entries", [])
        by_index_path: dict[str, list[str]] = {}
        for entry in log_index_entries:
            by_index_path.setdefault(str(entry["index_path"]), []).append(str(entry["line"]))
        for index_path, lines in by_index_path.items():
            _append_lines(Path(index_path), lines)

        archive_file.unlink()
        return {
            "session_id": session_id,
            "restored_path": str(session_destination),
            "restored_log_count": len(restored_logs),
            "archive_file": str(archive_file),
        }

    def _new_archive_file_path(self, session_id: str) -> Path:
        return self.archive_dir / f"{session_id}.gzip"

    def _resolve_archive_file_path(self, archive_file_name: str) -> Path:
        path = Path(archive_file_name)
        if path.is_absolute():
            return path
        return self.archive_dir / path.name

    def _collect_related_logs(self, record: SessionRecord) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        log_files = []
        log_index_entries = []
        run_ids = {turn.run_id for turn in record.turns if turn.run_id}
        index_paths = set()
        for turn in record.turns:
            source_log = _resolve_trace_path(record, turn)
            if source_log is None:
                continue
            index_paths.add(source_log.parent / "index.jsonl")
            if not source_log.exists():
                continue
            log_files.append(
                {
                    "run_id": turn.run_id,
                    "source_path": str(source_log),
                    "content": source_log.read_text(encoding="utf-8"),
                }
            )

        for index_path in index_paths:
            selected_lines = _select_jsonl_entries(index_path, "run_id", run_ids)
            for line in selected_lines:
                log_index_entries.append({"index_path": str(index_path), "line": line})
        return log_files, log_index_entries

    def _remove_related_logs(self, record: SessionRecord) -> None:
        run_ids = {turn.run_id for turn in record.turns if turn.run_id}
        index_paths = set()
        for turn in record.turns:
            source_log = _resolve_trace_path(record, turn)
            if source_log is None:
                continue
            index_paths.add(source_log.parent / "index.jsonl")
            if source_log.exists():
                source_log.unlink()
        for index_path in index_paths:
            _remove_jsonl_entries(index_path, "run_id", run_ids)

    def _append_index(self, record: SessionRecord) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(_summary_for(record).to_dict(), ensure_ascii=False) + "\n")

    def _remove_from_index(self, session_id: str) -> list[str]:
        return _remove_jsonl_entries(self.index_path, "session_id", {session_id})

    def _summaries_from_index(self) -> list[SessionSummary]:
        if not self.index_path.exists():
            return []
        by_id: dict[str, SessionSummary] = {}
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            summary = SessionSummary(
                session_id=str(raw["session_id"]),
                created_at=str(raw["created_at"]),
                updated_at=str(raw["updated_at"]),
                project_root=str(raw["project_root"]),
                workspace_root=str(raw["workspace_root"]),
                shell_default_workdir=str(raw["shell_default_workdir"]),
                turn_count=int(raw.get("turn_count", 0)),
                last_user_input=raw.get("last_user_input"),
            )
            previous = by_id.get(summary.session_id)
            if previous is None or previous.updated_at <= summary.updated_at:
                by_id[summary.session_id] = summary
        return list(by_id.values())

    def _summaries_from_files(self) -> list[SessionSummary]:
        if not self.session_dir.exists():
            return []
        summaries = []
        for path in self.session_dir.glob("*.json"):
            try:
                summaries.append(_summary_for(SessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return summaries


def turn_from_result(
    *,
    run_id: str,
    user_input: str,
    result,
    trace_path: str | None,
) -> SessionTurn:
    return SessionTurn(
        run_id=run_id,
        user_input=user_input,
        ok=result.ok,
        status=result.status,
        final_answer=result.final_answer,
        model_calls=result.model_calls,
        tool_calls=result.tool_calls,
        error=result.error,
        trace_path=trace_path,
    )


def _summary_for(record: SessionRecord) -> SessionSummary:
    last_turn = record.turns[-1] if record.turns else None
    return SessionSummary(
        session_id=record.session_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        project_root=record.project_root,
        workspace_root=record.workspace_root,
        shell_default_workdir=record.shell_default_workdir,
        turn_count=len(record.turns),
        last_user_input=last_turn.user_input if last_turn is not None else None,
    )


def _resolve_trace_path(record: SessionRecord, turn: SessionTurn) -> Path | None:
    if turn.trace_path:
        trace_path = Path(turn.trace_path)
        if trace_path.is_absolute():
            return trace_path
        return Path(record.project_root) / trace_path
    if turn.run_id:
        return Path(record.project_root) / ".understand-agent" / "logs" / f"{turn.run_id}.jsonl"
    return None


def _remove_jsonl_entries(path: Path, key: str, values: set[str]) -> list[str]:
    if not path.exists():
        return []
    kept_lines = []
    removed_lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            kept_lines.append(line)
            continue
        if str(raw.get(key)) in values:
            removed_lines.append(line)
        else:
            kept_lines.append(line)
    if kept_lines:
        _write_lines(path, kept_lines)
    else:
        path.unlink()
    return removed_lines


def _select_jsonl_entries(path: Path, key: str, values: set[str]) -> list[str]:
    if not path.exists():
        return []
    selected_lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(raw.get(key)) in values:
            selected_lines.append(line)
    return selected_lines


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_lines(path: Path, lines: list[str]) -> None:
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for line in lines:
            file.write(line.rstrip("\n") + "\n")
