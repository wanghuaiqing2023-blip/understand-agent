from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


@dataclass(frozen=True)
class TraceEvent:
    run_id: str
    event_id: int
    event_type: str
    timestamp: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


class ExecutionLogger:
    """Append-only JSONL logger for one execution trace."""

    def __init__(self, log_path: Path, run_id: str | None = None, index_path: Path | None = None) -> None:
        self.run_id = run_id or new_run_id()
        self.log_path = log_path
        self.index_path = index_path
        self._event_id = 0
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.index_path is not None:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def in_workspace(cls, workspace_root: Path, run_id: str | None = None) -> ExecutionLogger:
        actual_run_id = run_id or new_run_id()
        log_path = workspace_root / ".understand-agent" / "logs" / f"{actual_run_id}.jsonl"
        index_path = workspace_root / ".understand-agent" / "logs" / "index.jsonl"
        return cls(log_path=log_path, run_id=actual_run_id, index_path=index_path)

    def record(self, event_type: str, payload: dict[str, Any] | None = None) -> TraceEvent:
        self._event_id += 1
        event = TraceEvent(
            run_id=self.run_id,
            event_id=self._event_id,
            event_type=event_type,
            timestamp=datetime.now(UTC).isoformat(),
            payload=_json_safe(payload or {}),
        )
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def record_index(self, argv: list[str], exit_code: int, workspace_root: Path) -> None:
        if self.index_path is None:
            return
        entry = {
            "run_id": self.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "argv": argv,
            "exit_code": exit_code,
            "log_path": _relative_or_absolute(self.log_path, workspace_root),
        }
        with self.index_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(_json_safe(entry), ensure_ascii=False) + "\n")


def load_log_index(
    workspace_root: Path,
    limit: int | None = None,
    log_dir: Path | None = None,
) -> list[dict[str, Any]]:
    index_path = (log_dir or _default_log_dir(workspace_root)) / "index.jsonl"
    if not index_path.exists():
        return []
    entries = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entries.reverse()
    if limit is not None:
        return entries[:limit]
    return entries


def load_trace_events(
    workspace_root: Path,
    run_id: str,
    log_dir: Path | None = None,
) -> list[dict[str, Any]]:
    log_path = (log_dir or _default_log_dir(workspace_root)) / f"{run_id}.jsonl"
    if not log_path.exists():
        raise FileNotFoundError(f"trace log not found: {run_id}")
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return repr(value)


def _relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _default_log_dir(workspace_root: Path) -> Path:
    return workspace_root / ".understand-agent" / "logs"
