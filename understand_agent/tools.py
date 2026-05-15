from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from understand_agent.registry import ToolContext, ToolRegistry, ToolResult, ToolSpec


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_shell_spec())
    return registry


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


def _shell_spec() -> ToolSpec:
    return ToolSpec(
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
