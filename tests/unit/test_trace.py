import json
from pathlib import Path
from unittest import TestCase

from understand_agent.trace import ExecutionLogger, load_log_index, load_trace_events


ROOT = Path(__file__).resolve().parents[2]


class ExecutionLoggerTest(TestCase):
    def test_record_creates_jsonl_events(self) -> None:
        log_path = ROOT / ".understand-agent" / "test-logs" / "unit-trace.jsonl"
        log_path.unlink(missing_ok=True)
        logger = ExecutionLogger(log_path=log_path, run_id="unit-trace")

        first = logger.record("run_started", {"argv": ["tools"]})
        second = logger.record("run_finished", {"exit_code": 0})

        self.assertEqual(first.event_id, 1)
        self.assertEqual(second.event_id, 2)

        lines = log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        events = [json.loads(line) for line in lines]
        self.assertEqual(events[0]["run_id"], "unit-trace")
        self.assertEqual(events[0]["event_type"], "run_started")
        self.assertEqual(events[1]["event_type"], "run_finished")

    def test_record_makes_payload_json_safe(self) -> None:
        log_path = ROOT / ".understand-agent" / "test-logs" / "json-safe.jsonl"
        log_path.unlink(missing_ok=True)
        logger = ExecutionLogger(log_path=log_path, run_id="json-safe")

        logger.record("path_seen", {"path": ROOT})

        event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(event["payload"]["path"], str(ROOT))

    def test_record_index_and_load_trace(self) -> None:
        workspace = ROOT / ".understand-agent" / "test-trace-workspace"
        log_dir = workspace / ".understand-agent" / "logs"
        log_path = log_dir / "indexed-run.jsonl"
        index_path = log_dir / "index.jsonl"
        log_path.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)
        logger = ExecutionLogger(log_path=log_path, run_id="indexed-run", index_path=index_path)

        logger.record("run_started", {"argv": ["tools"]})
        logger.record_index(argv=["tools"], exit_code=0, workspace_root=ROOT)

        entries = [
            json.loads(line)
            for line in index_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(entries[0]["run_id"], "indexed-run")
        self.assertEqual(entries[0]["argv"], ["tools"])
        self.assertEqual(entries[0]["exit_code"], 0)

        events = load_trace_events(workspace, "indexed-run")
        self.assertEqual(events[0]["event_type"], "run_started")

    def test_load_log_index_returns_recent_first(self) -> None:
        workspace = ROOT / ".understand-agent" / "test-index-workspace"
        index_path = workspace / ".understand-agent" / "logs" / "index.jsonl"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            '{"run_id":"old","timestamp":"1","argv":["old"],"exit_code":0,"log_path":"old.jsonl"}\n'
            '{"run_id":"new","timestamp":"2","argv":["new"],"exit_code":1,"log_path":"new.jsonl"}\n',
            encoding="utf-8",
        )

        entries = load_log_index(workspace, limit=1)

        self.assertEqual(entries[0]["run_id"], "new")
