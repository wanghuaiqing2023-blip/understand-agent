import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from understand_agent.agent_loop import AgentRunResult
from understand_agent.cli import _run_session_turn, _session_repl, _trace_display_path
from understand_agent.registry import ToolRegistry
from understand_agent.session import SessionStore
from understand_agent.tools import build_default_registry
from understand_agent.trace import ExecutionLogger


ROOT = Path(__file__).resolve().parents[2]


class CliSessionTest(TestCase):
    def test_trace_display_path_returns_relative_path_when_possible(self) -> None:
        log_path = ROOT / ".understand-agent" / "test-tmp" / uuid4().hex / "run.jsonl"
        logger = ExecutionLogger(log_path=log_path, run_id="unit-trace-path")

        expected = log_path.relative_to(Path.cwd()).as_posix()

        self.assertEqual(_trace_display_path(logger), expected)

    def test_successful_session_turn_is_saved_with_trace_path(self) -> None:
        temp_root = ROOT / ".understand-agent" / "test-tmp" / uuid4().hex
        session_dir = temp_root / "sessions"
        log_dir = temp_root / "logs"
        store = SessionStore(session_dir)
        record = store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[_message("developer", "rules")],
            session_id="session-success-turn",
        )
        env = {
            **os.environ,
            "UNDERSTAND_AGENT_LOG_DIR": str(log_dir),
            "UNDERSTAND_AGENT_RUN_ID": "unit-session-turn",
        }
        env.pop("UNDERSTAND_AGENT_LOG", None)

        with patch.dict(os.environ, env, clear=True):
            with patch("understand_agent.cli._build_agent_loop", return_value=_SuccessfulLoop()):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    updated = _run_session_turn(record, store, ToolRegistry(), "hello")

        expected_trace = (log_dir / "unit-session-turn.jsonl").relative_to(Path.cwd()).as_posix()
        self.assertEqual(len(updated.turns), 1)
        self.assertEqual(updated.turns[0].run_id, "unit-session-turn")
        self.assertEqual(updated.turns[0].trace_path, expected_trace)
        self.assertEqual(updated.turns[0].final_answer, "saved")
        self.assertEqual(store.load("session-success-turn").turns[0].trace_path, expected_trace)

    def test_context_command_prints_request_without_running_or_saving_turn(self) -> None:
        temp_root = ROOT / ".understand-agent" / "test-tmp" / uuid4().hex
        store = SessionStore(temp_root / "sessions")
        input_items = [_message("developer", "rules")]
        record = store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=input_items,
            session_id="session-context-command",
        )

        stdout = io.StringIO()
        with patch("builtins.input", side_effect=["/context", "/exit"]):
            with patch("understand_agent.cli._run_session_turn") as run_turn:
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    exit_code = _session_repl(record, store, build_default_registry())

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(list(payload), ["instructions", "tools", "input"])
        self.assertIn("local coding and research agent", payload["instructions"])
        self.assertEqual([tool["name"] for tool in payload["tools"]], ["shell"])
        self.assertEqual(payload["input"], input_items)
        run_turn.assert_not_called()
        loaded = store.load("session-context-command")
        self.assertEqual(loaded.input_items, input_items)
        self.assertEqual(loaded.turns, [])


class _SuccessfulLoop:
    def run_with_input_items(self, input_items):
        return AgentRunResult(
            ok=True,
            status="done",
            final_answer="saved",
            model_calls=1,
            tool_calls=0,
            error=None,
            input_items=[*input_items, _message("assistant", "saved")],
        )


def _message(role: str, text: str) -> dict:
    content_type = "output_text" if role == "assistant" else "input_text"
    return {
        "role": role,
        "content": [{"type": content_type, "text": text}],
    }
