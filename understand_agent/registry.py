from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from understand_agent.trace import ExecutionLogger


@dataclass(frozen=True)
class ToolContext:
    """Runtime context shared by local tools."""

    workspace_root: Path
    run_id: str | None = None
    logger: ExecutionLogger | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", self.workspace_root.resolve())


@dataclass(frozen=True)
class ToolResult:
    """Standard result envelope for tool calls."""

    ok: bool
    data: Any = None
    error: str | None = None

    @classmethod
    def success(cls, data: Any = None) -> ToolResult:
        return cls(ok=True, data=data, error=None)

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, data=None, error=error)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "error": self.error}


ToolHandler = Callable[[dict[str, Any], ToolContext], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    """Description and executor for one registered tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    permission_level: str
    handler: ToolHandler

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "permission_level": self.permission_level,
        }


class ToolRegistry:
    """Registry that lets an agent discover and call tools by name."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name:
            raise ValueError("tool name is required")
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [self._tools[name].to_dict() for name in sorted(self._tools)]

    def run(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        started_at = perf_counter()
        spec = self.get(name)
        if context.logger is not None:
            context.logger.record(
                "tool_call_started",
                {
                    "tool_name": name,
                    "args": args,
                    "permission_level": spec.permission_level if spec is not None else None,
                },
            )

        if spec is None:
            result = ToolResult.failure(f"unknown tool: {name}")
            self._record_tool_finished(name, args, context, result, started_at, None)
            return result
        if not isinstance(args, dict):
            result = ToolResult.failure("tool args must be a dict")
            self._record_tool_finished(name, args, context, result, started_at, spec)
            return result

        try:
            result = spec.handler(args, context)
        except Exception as exc:  # noqa: BLE001 - tool errors must be isolated.
            result = ToolResult.failure(f"tool failed: {exc}")

        if not isinstance(result, ToolResult):
            result = ToolResult.success(result)
        self._record_tool_finished(name, args, context, result, started_at, spec)
        return result

    def _record_tool_finished(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolContext,
        result: ToolResult,
        started_at: float,
        spec: ToolSpec | None,
    ) -> None:
        if context.logger is None:
            return
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        context.logger.record(
            "tool_call_finished",
            {
                "tool_name": name,
                "args": args,
                "permission_level": spec.permission_level if spec is not None else None,
                "duration_ms": duration_ms,
                "result": result.to_dict(),
            },
        )
