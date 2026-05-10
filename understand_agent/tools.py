from __future__ import annotations

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


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="list_files",
            description="List files under a workspace path.",
            input_schema={"path": "string, optional, defaults to ."},
            permission_level="read",
            handler=list_files,
        )
    )
    registry.register(
        ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file inside the workspace.",
            input_schema={"path": "string, required"},
            permission_level="read",
            handler=read_file,
        )
    )
    registry.register(
        ToolSpec(
            name="search_text",
            description="Search UTF-8 text files inside the workspace.",
            input_schema={
                "path": "string, optional, defaults to .",
                "query": "string, required",
            },
            permission_level="read",
            handler=search_text,
        )
    )
    return registry


def list_files(args: dict[str, Any], context: ToolContext) -> ToolResult:
    try:
        base = _resolve_workspace_path(args.get("path", "."), context)
    except ValueError as exc:
        return ToolResult.failure(str(exc))
    if not base.exists():
        return ToolResult.failure(f"path does not exist: {_display_path(base, context)}")
    if not base.is_dir():
        return ToolResult.failure(f"path is not a directory: {_display_path(base, context)}")

    files = [
        _display_path(path, context)
        for path in sorted(base.rglob("*"))
        if path.is_file() and not _is_ignored(path, context)
    ]
    return ToolResult.success({"files": files, "count": len(files)})


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
