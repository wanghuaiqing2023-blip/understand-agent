from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path
from typing import Any

from understand_agent.registry import ToolContext, ToolRegistry, ToolResult, ToolSpec


IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "env",
    "venv",
}
DEFAULT_MAX_RESULTS = 1000


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="list_files",
            description="List files under a workspace path.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to list, relative to workspace_root. Defaults to .",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of files to return. Defaults to 1000.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            permission_level="read",
            handler=list_files,
        )
    )
    registry.register(
        ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file inside the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Text file path, relative to workspace_root.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            permission_level="read",
            handler=read_file,
        )
    )
    registry.register(
        ToolSpec(
            name="search_text",
            description="Search UTF-8 text files inside the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File or directory to search, relative to workspace_root. Defaults to .",
                    },
                    "query": {
                        "type": "string",
                        "description": "Exact text to search for.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            permission_level="read",
            handler=search_text,
        )
    )
    registry.register(
        ToolSpec(
            name="shell",
            description="Run a PowerShell command on the host machine after user approval.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "PowerShell command to run on the host machine.",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Working directory. Relative paths resolve from shell_default_workdir.",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Timeout in milliseconds. Defaults to 30000.",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            permission_level="execute",
            handler=shell,
        )
    )
    return registry


def list_files(args: dict[str, Any], context: ToolContext) -> ToolResult:
    try:
        base = _resolve_workspace_path(args.get("path", "."), context)
    except ValueError as exc:
        return ToolResult.failure(str(exc))
    try:
        max_results = _positive_int(args.get("max_results", DEFAULT_MAX_RESULTS), "max_results")
    except ValueError as exc:
        return ToolResult.failure(str(exc))
    if not base.exists():
        return ToolResult.failure(f"path does not exist: {_display_path(base, context)}")
    if not base.is_dir():
        return ToolResult.failure(f"path is not a directory: {_display_path(base, context)}")

    files: list[str] = []
    truncated = False
    for path in _iter_files(base, context):
        files.append(_display_path(path, context))
        if len(files) >= max_results:
            truncated = True
            break
    return ToolResult.success(
        {
            "files": files,
            "count": len(files),
            "truncated": truncated,
            "max_results": max_results,
        }
    )


def read_file(args: dict[str, Any], context: ToolContext) -> ToolResult:
    path_arg = args.get("path")
    if not path_arg:
        return ToolResult.failure("path is required")

    try:
        path = _resolve_workspace_path(path_arg, context)
    except ValueError as exc:
        return ToolResult.failure(str(exc))
    if not path.exists():
        return ToolResult.failure(f"path does not exist: {_display_path(path, context)}")
    if not path.is_file():
        return ToolResult.failure(f"path is not a file: {_display_path(path, context)}")

    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return ToolResult.failure(f"file is not valid UTF-8 text: {_display_path(path, context)}")

    return ToolResult.success({"path": _display_path(path, context), "content": content})


def search_text(args: dict[str, Any], context: ToolContext) -> ToolResult:
    query = args.get("query")
    if not query:
        return ToolResult.failure("query is required")

    try:
        base = _resolve_workspace_path(args.get("path", "."), context)
    except ValueError as exc:
        return ToolResult.failure(str(exc))
    if not base.exists():
        return ToolResult.failure(f"path does not exist: {_display_path(base, context)}")

    files = [base] if base.is_file() else sorted(base.rglob("*"))
    matches: list[dict[str, Any]] = []
    for path in files:
        if not path.is_file() or _is_ignored(path, context):
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if query in line:
                matches.append(
                    {
                        "path": _display_path(path, context),
                        "line": line_number,
                        "text": line,
                    }
                )

    return ToolResult.success({"matches": matches, "count": len(matches)})


def shell(args: dict[str, Any], context: ToolContext) -> ToolResult:
    command = args.get("command")
    if not command:
        return ToolResult.failure("command is required")

    try:
        workdir = _resolve_shell_workdir(args.get("workdir"), context)
    except ValueError as exc:
        return ToolResult.failure(str(exc))

    try:
        timeout_ms = int(args.get("timeout_ms", 30000))
    except (TypeError, ValueError):
        return ToolResult.failure("timeout_ms must be an integer")
    if timeout_ms <= 0:
        return ToolResult.failure("timeout_ms must be greater than 0")

    request = {
        "command": str(command),
        "workdir": str(workdir),
        "timeout_ms": timeout_ms,
    }
    if context.logger is not None:
        context.logger.record("shell_approval_requested", request)

    approved = _approve_shell_command(request, context)
    if not approved:
        if context.logger is not None:
            context.logger.record("shell_approval_rejected", request)
        return ToolResult(
            ok=False,
            data={"command": str(command), "workdir": str(workdir)},
            error="shell command rejected by user",
        )

    if context.logger is not None:
        context.logger.record("shell_approval_granted", request)
        context.logger.record("shell_command_started", request)

    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                str(command),
            ],
            cwd=workdir,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_ms / 1000,
            check=False,
        )
        data = {
            "command": str(command),
            "workdir": str(workdir),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if context.logger is not None:
            context.logger.record("shell_command_finished", data)
        return ToolResult.success(data)
    except subprocess.TimeoutExpired as exc:
        data = {
            "command": str(command),
            "workdir": str(workdir),
            "timeout_ms": timeout_ms,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
        if context.logger is not None:
            context.logger.record("shell_command_finished", {"timed_out": True, **data})
        return ToolResult(ok=False, data=data, error="shell command timed out")
    except FileNotFoundError as exc:
        data = {"command": str(command), "workdir": str(workdir)}
        if context.logger is not None:
            context.logger.record("shell_command_finished", {"error": str(exc), **data})
        return ToolResult(ok=False, data=data, error=f"shell executable not found: {exc}")


def _resolve_workspace_path(raw_path: Any, context: ToolContext) -> Path:
    path = (context.workspace_root / str(raw_path)).resolve()
    try:
        path.relative_to(context.workspace_root)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {raw_path}") from exc
    return path


def _display_path(path: Path, context: ToolContext) -> str:
    return path.relative_to(context.workspace_root).as_posix()


def _is_ignored(path: Path, context: ToolContext) -> bool:
    relative = path.relative_to(context.workspace_root)
    return any(part in IGNORED_DIRS for part in relative.parts)


def _iter_files(base: Path, context: ToolContext):
    for root, dirnames, filenames in os.walk(base, topdown=True, onerror=lambda _error: None):
        root_path = Path(root)
        dirnames[:] = [
            dirname
            for dirname in sorted(dirnames)
            if not _is_ignored(root_path / dirname, context)
        ]
        for filename in sorted(filenames):
            path = root_path / filename
            if path.is_file() and not _is_ignored(path, context):
                yield path


def _positive_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return number


def _resolve_shell_workdir(raw_workdir: Any, context: ToolContext) -> Path:
    base = context.shell_default_workdir or context.workspace_root
    if raw_workdir in (None, ""):
        workdir = base
    else:
        raw_path = Path(str(raw_workdir))
        workdir = raw_path if raw_path.is_absolute() else base / raw_path
    workdir = workdir.resolve()
    try:
        workdir.relative_to(context.workspace_root)
    except ValueError as exc:
        raise ValueError(f"shell workdir escapes workspace: {raw_workdir}") from exc
    if not workdir.exists():
        raise ValueError(f"shell workdir does not exist: {workdir}")
    if not workdir.is_dir():
        raise ValueError(f"shell workdir is not a directory: {workdir}")
    return workdir


def _approve_shell_command(request: dict[str, Any], context: ToolContext) -> bool:
    if context.shell_approver is not None:
        return context.shell_approver(request)

    print("Model requested shell command:", file=sys.stderr)
    print(file=sys.stderr)
    print("workdir:", file=sys.stderr)
    print(request["workdir"], file=sys.stderr)
    print(file=sys.stderr)
    print("command:", file=sys.stderr)
    print(request["command"], file=sys.stderr)
    print(file=sys.stderr)
    try:
        answer = input("Execute? [y/N]: ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}
