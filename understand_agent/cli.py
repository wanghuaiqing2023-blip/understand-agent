from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from understand_agent.agent_loop import AgentLoop, AgentRunConfig
from understand_agent.context import ContextBuilder
from understand_agent.model import OpenAIResponsesClient
from understand_agent.registry import ToolContext, ToolResult
from understand_agent.tools import build_default_registry
from understand_agent.trace import ExecutionLogger, load_log_index, load_trace_events, new_run_id


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    parsed = parser.parse_args(argv)
    workspace_root = Path.cwd()
    raw_argv = argv if argv is not None else sys.argv[1:]
    logger = None if parsed.command == "logs" else _build_logger(workspace_root)

    if logger is not None:
        logger.record("run_started", {"argv": raw_argv})
        logger.record("cli_args_received", vars(parsed))

    registry = build_default_registry()
    if logger is not None:
        logger.record(
            "registry_loaded",
            {"tools": registry.list_tools()},
        )
    context = ToolContext(
        workspace_root=workspace_root,
        project_root=workspace_root,
        shell_default_workdir=workspace_root,
        run_id=logger.run_id if logger is not None else None,
        logger=logger,
    )

    if parsed.command == "tools":
        output = _with_run_id({"tools": registry.list_tools()}, logger)
        _print_json(output)
        _record_run_finished(logger, 0, raw_argv, workspace_root)
        return 0

    if parsed.command == "call":
        if logger is not None:
            logger.record(
                "tool_call_requested",
                {
                    "tool_name": parsed.tool_name,
                    "raw_args": parsed.tool_args,
                },
            )
        args_result = _parse_key_values(parsed.tool_args)
        if not args_result.ok:
            _print_json(_with_run_id(args_result.to_dict(), logger))
            _record_run_finished(logger, 2, raw_argv, workspace_root)
            return 2

        result = registry.run(parsed.tool_name, args_result.data, context)
        _print_json(_with_run_id(result.to_dict(), logger))
        exit_code = 0 if result.ok else 1
        _record_run_finished(logger, exit_code, raw_argv, workspace_root)
        return exit_code

    if parsed.command == "run":
        result = _handle_run_command(parsed, registry, logger)
        _print_json(_with_run_id(result.to_dict(), logger))
        exit_code = 0 if result.ok else 1
        _record_run_finished(logger, exit_code, raw_argv, workspace_root)
        return exit_code

    if parsed.command == "logs":
        return _handle_logs_command(parsed, workspace_root)

    parser.print_help()
    _record_run_finished(logger, 2, raw_argv, workspace_root)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m understand_agent")
    subcommands = parser.add_subparsers(dest="command")

    subcommands.add_parser("tools", help="list registered tools")

    call_parser = subcommands.add_parser("call", help="call a registered tool")
    call_parser.add_argument("tool_name")
    call_parser.add_argument("tool_args", nargs="*", help="tool args in key=value form")

    run_parser = subcommands.add_parser("run", help="run an agent loop for a task")
    run_parser.add_argument("task")
    run_parser.add_argument("--max-model-calls", type=int, default=8)
    run_parser.add_argument("--max-tool-calls", type=int, default=8)

    logs_parser = subcommands.add_parser("logs", help="list or show execution logs")
    logs_subcommands = logs_parser.add_subparsers(dest="logs_command")

    list_parser = logs_subcommands.add_parser("list", help="list recent execution logs")
    list_parser.add_argument("--limit", type=int, default=10)

    show_parser = logs_subcommands.add_parser("show", help="show trace events for one run")
    show_parser.add_argument("run_id")

    return parser


def _parse_key_values(items: list[str]) -> ToolResult:
    args: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            return ToolResult.failure(f"invalid arg, expected key=value: {item}")
        key, value = item.split("=", 1)
        if not key:
            return ToolResult.failure(f"invalid arg, empty key: {item}")
        args[key] = value
    return ToolResult.success(args)


def _print_json(value: dict[str, Any]) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _with_run_id(value: dict[str, Any], logger: ExecutionLogger | None) -> dict[str, Any]:
    if logger is None:
        return {"run_id": None, **value}
    return {"run_id": logger.run_id, **value}


def _build_logger(workspace_root: Path) -> ExecutionLogger | None:
    if os.environ.get("UNDERSTAND_AGENT_LOG") == "0":
        return None

    run_id = os.environ.get("UNDERSTAND_AGENT_RUN_ID") or new_run_id()
    log_dir = os.environ.get("UNDERSTAND_AGENT_LOG_DIR")
    if log_dir:
        log_dir_path = Path(log_dir)
        return ExecutionLogger(
            log_path=log_dir_path / f"{run_id}.jsonl",
            run_id=run_id,
            index_path=log_dir_path / "index.jsonl",
        )
    return ExecutionLogger.in_workspace(workspace_root, run_id=run_id)


def _handle_logs_command(parsed: argparse.Namespace, workspace_root: Path) -> int:
    log_dir = _active_log_dir(workspace_root)
    if parsed.logs_command in (None, "list"):
        entries = load_log_index(workspace_root, limit=parsed.limit, log_dir=log_dir)
        _print_json({"logs": entries})
        return 0

    if parsed.logs_command == "show":
        try:
            events = load_trace_events(workspace_root, parsed.run_id, log_dir=log_dir)
        except FileNotFoundError as exc:
            _print_json(ToolResult.failure(str(exc)).to_dict())
            return 1
        _print_json({"run_id": parsed.run_id, "events": events})
        return 0

    _print_json(ToolResult.failure(f"unknown logs command: {parsed.logs_command}").to_dict())
    return 2


def _handle_run_command(
    parsed: argparse.Namespace,
    registry,
    logger: ExecutionLogger | None,
):
    project_root = Path.cwd().resolve()
    home_root = Path.home().resolve()
    context = ToolContext(
        workspace_root=home_root,
        project_root=project_root,
        shell_default_workdir=project_root,
        run_id=logger.run_id if logger is not None else None,
        logger=logger,
    )
    builder = ContextBuilder(
        workspace_root=home_root,
        project_root=project_root,
        shell_default_workdir=project_root,
        cwd=project_root,
    )
    loop = AgentLoop(
        model_client=OpenAIResponsesClient(),
        registry=registry,
        context_builder=builder,
        tool_context=context,
        config=AgentRunConfig(
            max_model_calls=parsed.max_model_calls,
            max_tool_calls=parsed.max_tool_calls,
        ),
    )
    return loop.run(parsed.task)


def _active_log_dir(workspace_root: Path) -> Path:
    log_dir = os.environ.get("UNDERSTAND_AGENT_LOG_DIR")
    if log_dir:
        return Path(log_dir)
    return workspace_root / ".understand-agent" / "logs"


def _record_run_finished(
    logger: ExecutionLogger | None,
    exit_code: int,
    argv: list[str],
    workspace_root: Path,
) -> None:
    if logger is not None:
        logger.record("run_finished", {"exit_code": exit_code})
        logger.record_index(argv=argv, exit_code=exit_code, workspace_root=workspace_root)
        _print_trace_path(logger)


def _print_trace_path(logger: ExecutionLogger) -> None:
    try:
        display_path = logger.log_path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        display_path = str(logger.log_path)
    print(f"trace: {display_path}", file=sys.stderr)
