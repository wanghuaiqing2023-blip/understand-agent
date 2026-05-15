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
from understand_agent.session import SessionRecord, SessionStore, turn_from_result
from understand_agent.tools import build_default_registry
from understand_agent.trace import ExecutionLogger, load_log_index, load_trace_events, new_run_id


COMMAND_NAMES = {"tools", "call", "exec", "resume", "archive", "unarchive", "logs"}
REMOVED_COMMAND_NAMES = {"run", "sessions"}


def main(argv: list[str] | None = None) -> int:
    raw_argv = argv if argv is not None else sys.argv[1:]
    workspace_root = Path.cwd()
    project_root = workspace_root.resolve()

    if _looks_like_initial_prompt(raw_argv):
        return _handle_new_session(project_root, initial_prompt=" ".join(raw_argv))

    parser = _build_parser()
    parsed = parser.parse_args(argv)

    if parsed.command is None:
        return _handle_new_session(project_root)

    if parsed.command == "logs":
        return _handle_logs_command(parsed, workspace_root)

    if parsed.command == "resume":
        return _handle_resume_command(parsed, project_root)

    if parsed.command == "archive":
        return _handle_archive_command(parsed)

    if parsed.command == "unarchive":
        return _handle_unarchive_command(parsed)

    logger = _build_logger(workspace_root)
    logger.record("run_started", {"argv": raw_argv})
    logger.record("cli_args_received", vars(parsed))

    registry = build_default_registry()
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

    if parsed.command == "exec":
        result = _handle_exec_command(parsed, registry, logger, project_root)
        _print_json(_with_run_id(result.to_dict(), logger))
        exit_code = 0 if result.ok else 1
        _record_run_finished(logger, exit_code, raw_argv, workspace_root)
        return exit_code

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

    exec_parser = subcommands.add_parser("exec", help="run a one-shot agent task")
    exec_parser.add_argument("task")

    resume_parser = subcommands.add_parser("resume", help="resume an interactive session")
    resume_parser.add_argument("session_id", nargs="?")
    resume_parser.add_argument("--last", action="store_true")
    resume_parser.add_argument("--all", action="store_true", dest="include_all")

    archive_parser = subcommands.add_parser("archive", help="archive a stored session")
    archive_parser.add_argument("session_id")

    unarchive_parser = subcommands.add_parser("unarchive", help="restore an archived session")
    unarchive_parser.add_argument("archive_file_name")

    logs_parser = subcommands.add_parser("logs", help="list or show execution logs")
    logs_subcommands = logs_parser.add_subparsers(dest="logs_command")

    list_parser = logs_subcommands.add_parser("list", help="list recent execution logs")
    list_parser.add_argument("--limit", type=int, default=10)

    show_parser = logs_subcommands.add_parser("show", help="show trace events for one run")
    show_parser.add_argument("run_id")

    return parser


def _looks_like_initial_prompt(args: list[str]) -> bool:
    if not args:
        return False
    first = args[0]
    if first.startswith("-"):
        return False
    if first in COMMAND_NAMES or first in REMOVED_COMMAND_NAMES:
        return False
    return True


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


def _handle_exec_command(
    parsed: argparse.Namespace,
    registry,
    logger: ExecutionLogger | None,
    project_root: Path,
):
    loop = _build_agent_loop(project_root, registry, logger)
    return loop.run(parsed.task)


def _handle_new_session(project_root: Path, initial_prompt: str | None = None) -> int:
    registry = build_default_registry()
    builder = _build_context_builder(project_root)
    store = SessionStore()
    home_root = Path.home().resolve()
    record = store.create(
        project_root=project_root,
        workspace_root=home_root,
        shell_default_workdir=project_root,
        input_items=builder.build_session_seed(),
    )
    print(f"session: {record.session_id}")
    current = record
    if initial_prompt is not None:
        current = _run_session_turn(current, store, registry, initial_prompt)
    return _session_repl(current, store, registry)


def _handle_resume_command(parsed: argparse.Namespace, project_root: Path) -> int:
    store = SessionStore()
    try:
        if parsed.session_id:
            record = store.load(parsed.session_id)
        elif parsed.last:
            summary = store.latest(project_root=project_root, include_all=parsed.include_all)
            if summary is None:
                _print_json(ToolResult.failure("no session found").to_dict())
                return 1
            record = store.load(summary.session_id)
        else:
            summaries = store.list_summaries(project_root=project_root, include_all=parsed.include_all)
            if not summaries:
                _print_json(ToolResult.failure("no session found").to_dict())
                return 1
            record = _select_session(store, summaries)
            if record is None:
                return 1
    except FileNotFoundError as exc:
        _print_json(ToolResult.failure(str(exc)).to_dict())
        return 1

    print(f"session: {record.session_id}")
    print(f"project: {record.project_root}")
    return _session_repl(record, store, build_default_registry())


def _handle_archive_command(parsed: argparse.Namespace) -> int:
    store = SessionStore()
    try:
        data = store.archive(parsed.session_id)
    except (FileNotFoundError, FileExistsError) as exc:
        _print_json(ToolResult.failure(str(exc)).to_dict())
        return 1
    _print_json(ToolResult.success(data).to_dict())
    return 0


def _handle_unarchive_command(parsed: argparse.Namespace) -> int:
    store = SessionStore()
    try:
        data = store.restore_archived(parsed.archive_file_name)
    except (FileNotFoundError, FileExistsError, OSError, json.JSONDecodeError) as exc:
        _print_json(ToolResult.failure(str(exc)).to_dict())
        return 1
    _print_json(ToolResult.success(data).to_dict())
    return 0


def _session_repl(record: SessionRecord, store: SessionStore, registry) -> int:
    current = record
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            print()
            return 0
        text = user_input.strip()
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            return 0

        current = _run_session_turn(current, store, registry, user_input)


def _run_session_turn(record: SessionRecord, store: SessionStore, registry, user_input: str) -> SessionRecord:
    project_root = Path(record.project_root)
    builder = _build_context_builder(
        project_root=project_root,
        workspace_root=Path(record.workspace_root),
        shell_default_workdir=Path(record.shell_default_workdir),
    )
    input_items = builder.append_user_turn(record.input_items, user_input)
    logger = _build_logger(project_root)
    logger.record("run_started", {"argv": ["session", record.session_id, user_input]})
    logger.record(
        "session_turn_started",
        {"session_id": record.session_id, "user_input": user_input},
    )
    logger.record("registry_loaded", {"tools": registry.list_tools()})

    loop = _build_agent_loop(project_root, registry, logger, builder=builder)
    result = loop.run_with_input_items(input_items)
    exit_code = 0 if result.ok else 1
    _record_run_finished(logger, exit_code, ["session", record.session_id, user_input], project_root)

    if result.ok and result.final_answer:
        print(result.final_answer)
    else:
        _print_json(_with_run_id(result.to_dict(), logger))

    if _should_save_session_turn(record, input_items, result):
        return store.append_turn(
            record,
            input_items=result.input_items or input_items,
            turn=turn_from_result(
                run_id=logger.run_id,
                user_input=user_input,
                result=result,
                trace_path=_trace_display_path(logger),
            ),
        )
    return record


def _should_save_session_turn(
    record: SessionRecord,
    turn_input_items: list[dict[str, Any]],
    result,
) -> bool:
    if result.input_items is None:
        return False
    if result.ok:
        return True
    return len(result.input_items) > len(turn_input_items)


def _select_session(store: SessionStore, summaries) -> SessionRecord | None:
    for index, summary in enumerate(summaries, start=1):
        label = summary.last_user_input or "(no turns)"
        print(f"{index}. {summary.session_id} [{summary.project_root}] {label}")
    try:
        selected = input("Select session: ").strip()
    except EOFError:
        return None
    try:
        index = int(selected)
    except ValueError:
        _print_json(ToolResult.failure(f"invalid session selection: {selected}").to_dict())
        return None
    if index < 1 or index > len(summaries):
        _print_json(ToolResult.failure(f"invalid session selection: {selected}").to_dict())
        return None
    return store.load(summaries[index - 1].session_id)


def _build_agent_loop(
    project_root: Path,
    registry,
    logger: ExecutionLogger | None,
    builder: ContextBuilder | None = None,
) -> AgentLoop:
    context_builder = builder or _build_context_builder(project_root)
    context = ToolContext(
        workspace_root=context_builder.workspace_root,
        project_root=context_builder.project_root,
        shell_default_workdir=context_builder.shell_default_workdir,
        run_id=logger.run_id if logger is not None else None,
        logger=logger,
    )
    return AgentLoop(
        model_client=OpenAIResponsesClient(),
        registry=registry,
        context_builder=context_builder,
        tool_context=context,
        config=AgentRunConfig(),
    )


def _build_context_builder(
    project_root: Path,
    workspace_root: Path | None = None,
    shell_default_workdir: Path | None = None,
) -> ContextBuilder:
    home_root = (workspace_root or Path.home()).resolve()
    shell_root = (shell_default_workdir or project_root).resolve()
    return ContextBuilder(
        workspace_root=home_root,
        project_root=project_root,
        shell_default_workdir=shell_root,
        cwd=project_root,
    )


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
    print(f"trace: {_trace_display_path(logger)}", file=sys.stderr)


def _trace_display_path(logger: ExecutionLogger) -> str:
    try:
        display_path = logger.log_path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        display_path = str(logger.log_path)
    return display_path
