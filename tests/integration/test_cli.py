import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / ".understand-agent" / "test-logs"


class CliIntegrationTest(TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        run_id = "integration-" + "-".join(args).replace("=", "-").replace("/", "-")
        env = {
            **os.environ,
            "UNDERSTAND_AGENT_LOG_DIR": str(LOG_DIR),
            "UNDERSTAND_AGENT_RUN_ID": run_id,
        }
        log_path = LOG_DIR / f"{run_id}.jsonl"
        log_path.unlink(missing_ok=True)
        index_path = LOG_DIR / "index.jsonl"
        if args and args[0] == "logs":
            env["UNDERSTAND_AGENT_LOG"] = "0"
        return subprocess.run(
            [sys.executable, "-m", "understand_agent", *args],
            cwd=ROOT,
            env=env,
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

    def test_tools_command_lists_registered_tools(self) -> None:
        completed = self.run_cli("tools")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-tools")
        names = [tool["name"] for tool in payload["tools"]]
        self.assertEqual(names, ["list_files", "read_file", "search_text", "shell"])
        self.assert_trace_hint(completed, "integration-tools")
        events = self.read_trace("integration-tools")
        self.assertEqual(
            [event["event_type"] for event in events],
            ["run_started", "cli_args_received", "registry_loaded", "run_finished"],
        )

    def test_call_read_file(self) -> None:
        completed = self.run_cli("call", "read_file", "path=docs/README.md")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-call-read_file-path-docs-README.md")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["path"], "docs/README.md")
        self.assert_trace_hint(completed, "integration-call-read_file-path-docs-README.md")
        events = self.read_trace("integration-call-read_file-path-docs-README.md")
        event_types = [event["event_type"] for event in events]
        self.assertIn("tool_call_requested", event_types)
        self.assertIn("tool_call_started", event_types)
        self.assertIn("tool_call_finished", event_types)
        self.assertEqual(events[-1]["payload"]["exit_code"], 0)

    def test_call_search_text(self) -> None:
        completed = self.run_cli("call", "search_text", "path=docs", "query=Agent")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-call-search_text-path-docs-query-Agent")
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["data"]["count"], 0)
        self.assert_trace_hint(completed, "integration-call-search_text-path-docs-query-Agent")

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
        completed = self.run_cli("call", "read_file", "not-key-value")

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-call-read_file-not-key-value")
        self.assertFalse(payload["ok"])
        self.assertIn("expected key=value", payload["error"])
        self.assert_trace_hint(completed, "integration-call-read_file-not-key-value")
        events = self.read_trace("integration-call-read_file-not-key-value")
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

    def test_run_without_api_key_returns_json_error(self) -> None:
        env_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            completed = self.run_cli("run", "Say hello")
        finally:
            if env_key is not None:
                os.environ["OPENAI_API_KEY"] = env_key

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["run_id"], "integration-run-Say hello")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["model_calls"], 0)
        self.assertEqual(payload["tool_calls"], 0)
        self.assertEqual(payload["error"], "OPENAI_API_KEY is not set")
        self.assert_trace_hint(completed, "integration-run-Say hello")

    def test_run_budget_options_are_accepted(self) -> None:
        env_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            completed = self.run_cli("run", "Say hello", "--max-model-calls", "4", "--max-tool-calls", "4")
        finally:
            if env_key is not None:
                os.environ["OPENAI_API_KEY"] = env_key

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["error"], "OPENAI_API_KEY is not set")
