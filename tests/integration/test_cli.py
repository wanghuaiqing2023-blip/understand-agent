import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

from understand_agent.session import SessionStore


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / ".understand-agent" / "test-logs"
SESSION_DIR = ROOT / ".understand-agent" / "test-sessions"


class CliIntegrationTest(TestCase):
    def run_cli(
        self,
        *args: str,
        input_text: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        run_id = "integration-" + "-".join(args).replace("=", "-").replace("/", "-")
        env = {
            **os.environ,
            "UNDERSTAND_AGENT_LOG_DIR": str(LOG_DIR),
            "UNDERSTAND_AGENT_RUN_ID": run_id,
        }
        if extra_env:
            env.update(extra_env)
        log_path = LOG_DIR / f"{run_id}.jsonl"
        log_path.unlink(missing_ok=True)
        index_path = LOG_DIR / "index.jsonl"
        if args and args[0] == "logs":
            env["UNDERSTAND_AGENT_LOG"] = "0"
        return subprocess.run(
            [sys.executable, "-m", "understand_agent", *args],
            cwd=ROOT,
            env=env,
            input=input_text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def read_trace(self, run_id: str) -> list[dict]:
        log_path = LOG_DIR / f"{run_id}.jsonl"
        self.assertTrue(log_path.exists(), f"missing trace log: {log_path}")
        return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    def assert_trace_hint(self, completed: subprocess.CompletedProcess[str], run_id: str) -> None:
        expected = f"trace: .understand-agent/test-logs/{run_id}.jsonl"
        self.assertIn(expected, completed.stderr)

    def test_help_lists_exec_and_resume_not_run(self) -> None:
        completed = self.run_cli("--help")

        self.assertEqual(completed.returncode, 0)
        self.assertIn("exec", completed.stdout)
        self.assertIn("resume", completed.stdout)
        self.assertIn("archive", completed.stdout)
        self.assertIn("unarchive", completed.stdout)
        self.assertNotIn("sessions", completed.stdout)
        self.assertNotIn("context", completed.stdout)
        self.assertNotIn("run an agent loop", completed.stdout)

    def test_tools_command_lists_registered_tools(self) -> None:
        completed = self.run_cli("tools")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-tools")
        names = [tool["name"] for tool in payload["tools"]]
        self.assertEqual(names, ["shell"])
        self.assert_trace_hint(completed, "integration-tools")
        events = self.read_trace("integration-tools")
        self.assertEqual(
            [event["event_type"] for event in events],
            ["run_started", "cli_args_received", "registry_loaded", "run_finished"],
        )

    def test_removed_read_file_tool_returns_unknown_tool(self) -> None:
        completed = self.run_cli("call", "read_file", "path=docs/README.md")

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-call-read_file-path-docs-README.md")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "unknown tool: read_file")
        self.assert_trace_hint(completed, "integration-call-read_file-path-docs-README.md")
        events = self.read_trace("integration-call-read_file-path-docs-README.md")
        event_types = [event["event_type"] for event in events]
        self.assertIn("tool_call_requested", event_types)
        self.assertIn("tool_call_started", event_types)
        self.assertIn("tool_call_finished", event_types)
        self.assertEqual(events[-1]["payload"]["exit_code"], 1)

    def test_unknown_tool_returns_nonzero_and_json_error(self) -> None:
        completed = self.run_cli("call", "missing_tool")

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-call-missing_tool")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "unknown tool: missing_tool")
        self.assert_trace_hint(completed, "integration-call-missing_tool")
        events = self.read_trace("integration-call-missing_tool")
        self.assertEqual(events[-2]["event_type"], "tool_call_finished")
        self.assertEqual(events[-2]["payload"]["result"]["error"], "unknown tool: missing_tool")

    def test_invalid_arg_returns_nonzero_and_json_error(self) -> None:
        completed = self.run_cli("call", "shell", "not-key-value")

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-call-shell-not-key-value")
        self.assertFalse(payload["ok"])
        self.assertIn("expected key=value", payload["error"])
        self.assert_trace_hint(completed, "integration-call-shell-not-key-value")
        events = self.read_trace("integration-call-shell-not-key-value")
        self.assertEqual(events[-1]["event_type"], "run_finished")
        self.assertEqual(events[-1]["payload"]["exit_code"], 2)

    def test_logs_list_returns_recent_index_entries(self) -> None:
        index_path = LOG_DIR / "index.jsonl"
        index_path.unlink(missing_ok=True)
        first = self.run_cli("tools")
        second = self.run_cli("call", "missing_tool")

        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 1)

        completed = self.run_cli("logs", "list", "--limit", "2")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("trace:", completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(len(payload["logs"]), 2)
        self.assertEqual(payload["logs"][0]["run_id"], "integration-call-missing_tool")
        self.assertEqual(payload["logs"][1]["run_id"], "integration-tools")

    def test_logs_show_returns_trace_events(self) -> None:
        completed = self.run_cli("call", "missing_tool")
        self.assertEqual(completed.returncode, 1)

        shown = self.run_cli("logs", "show", "integration-call-missing_tool")

        self.assertEqual(shown.returncode, 0, shown.stderr)
        payload = json.loads(shown.stdout)
        self.assertEqual(payload["run_id"], "integration-call-missing_tool")
        event_types = [event["event_type"] for event in payload["events"]]
        self.assertIn("tool_call_finished", event_types)

    def test_logs_show_missing_run_returns_error(self) -> None:
        completed = self.run_cli("logs", "show", "missing-run")

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("trace log not found", payload["error"])

    def test_exec_without_api_key_returns_json_error(self) -> None:
        env_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            completed = self.run_cli("exec", "Say hello")
        finally:
            if env_key is not None:
                os.environ["OPENAI_API_KEY"] = env_key

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-exec-Say hello")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["model_calls"], 0)
        self.assertEqual(payload["tool_calls"], 0)
        self.assertEqual(payload["error"], "OPENAI_API_KEY is not set")
        self.assert_trace_hint(completed, "integration-exec-Say hello")

    def test_bare_prompt_starts_session_and_runs_first_turn(self) -> None:
        session_dir = SESSION_DIR / "bare-prompt"
        shutil.rmtree(session_dir, ignore_errors=True)
        env_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            completed = self.run_cli(
                "Say hello",
                input_text="/exit\n",
                extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(session_dir)},
            )
        finally:
            if env_key is not None:
                os.environ["OPENAI_API_KEY"] = env_key

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("session:", completed.stdout)
        self.assertIn('"run_id": "integration-Say hello"', completed.stdout)
        self.assertIn('"error": "OPENAI_API_KEY is not set"', completed.stdout)
        self.assert_trace_hint(completed, "integration-Say hello")
        session_files = list(session_dir.glob("*.json"))
        self.assertEqual(len(session_files), 1)
        payload = json.loads(session_files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["project_root"], str(ROOT.resolve()))

    def test_run_command_is_removed(self) -> None:
        completed = self.run_cli("run", "Say hello")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("invalid choice", completed.stderr)

    def test_sessions_command_is_removed(self) -> None:
        completed = self.run_cli("sessions", "archive", "missing")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("invalid choice", completed.stderr)

    def test_resume_last_without_sessions_returns_error(self) -> None:
        empty_dir = SESSION_DIR / "empty"
        shutil.rmtree(empty_dir, ignore_errors=True)

        completed = self.run_cli(
            "resume",
            "--last",
            extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(empty_dir)},
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "no session found")

    def test_resume_by_id_loads_session_metadata(self) -> None:
        session_dir = SESSION_DIR / "by-id"
        shutil.rmtree(session_dir, ignore_errors=True)
        store = SessionStore(session_dir)
        store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[],
            session_id="integration-session",
        )

        completed = self.run_cli(
            "resume",
            "integration-session",
            input_text="/exit\n",
            extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(session_dir)},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("session: integration-session", completed.stdout)
        self.assertIn(f"project: {ROOT.resolve()}", completed.stdout)

    def test_context_slash_command_dumps_request_without_creating_turn(self) -> None:
        session_dir = SESSION_DIR / "context"
        shutil.rmtree(session_dir, ignore_errors=True)
        store = SessionStore(session_dir)
        input_items = [{"role": "developer", "content": [{"type": "input_text", "text": "rules"}]}]
        store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=input_items,
            session_id="integration-context-session",
        )

        completed = self.run_cli(
            "resume",
            "integration-context-session",
            input_text="/context\n/exit\n",
            extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(session_dir)},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = _first_json_object(completed.stdout)
        self.assertEqual(list(payload), ["instructions", "tools", "input"])
        self.assertEqual([tool["name"] for tool in payload["tools"]], ["shell"])
        self.assertEqual(payload["input"], input_items)
        loaded = store.load("integration-context-session")
        self.assertEqual(loaded.input_items, input_items)
        self.assertEqual(loaded.turns, [])

    def test_archive_and_unarchive_move_session_out_of_resume_set(self) -> None:
        session_dir = SESSION_DIR / "archive"
        shutil.rmtree(session_dir, ignore_errors=True)
        shutil.rmtree(session_dir.parent / "archived_sessions", ignore_errors=True)
        store = SessionStore(session_dir)
        store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[],
            session_id="integration-archive-session",
        )

        completed = self.run_cli(
            "archive",
            "integration-archive-session",
            extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(session_dir)},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["session_id"], "integration-archive-session")
        self.assertFalse(store.path_for("integration-archive-session").exists())
        archived_file = payload["data"]["archived_file"]
        archived_path = session_dir.parent / "archived_sessions" / archived_file
        self.assertTrue(archived_path.exists())
        self.assertEqual(archived_path.suffix, ".gzip")
        self.assertEqual(archived_file, "integration-archive-session.gzip")

        resumed = self.run_cli(
            "resume",
            "integration-archive-session",
            input_text="/exit\n",
            extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(session_dir)},
        )

        self.assertEqual(resumed.returncode, 1)
        self.assertIn("session not found", json.loads(resumed.stdout)["error"])

        restored = self.run_cli(
            "unarchive",
            archived_file,
            extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(session_dir)},
        )

        self.assertEqual(restored.returncode, 0, restored.stderr)
        restored_payload = json.loads(restored.stdout)
        self.assertTrue(restored_payload["ok"])
        self.assertEqual(restored_payload["data"]["session_id"], "integration-archive-session")
        self.assertTrue(store.path_for("integration-archive-session").exists())
        self.assertFalse(archived_path.exists())

        resumed_after_restore = self.run_cli(
            "resume",
            "integration-archive-session",
            input_text="/exit\n",
            extra_env={"UNDERSTAND_AGENT_SESSION_DIR": str(session_dir)},
        )

        self.assertEqual(resumed_after_restore.returncode, 0, resumed_after_restore.stderr)


def _first_json_object(text: str) -> dict:
    start = text.index("{")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    return value
