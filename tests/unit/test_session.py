import gzip
import json
import os
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from understand_agent.session import (
    SessionStore,
    SessionTurn,
    default_archived_session_dir,
    default_session_dir,
)


ROOT = Path(__file__).resolve().parents[2]


class SessionStoreTest(TestCase):
    def test_default_session_dir_is_under_home(self) -> None:
        old = os.environ.pop("UNDERSTAND_AGENT_SESSION_DIR", None)
        try:
            home = ROOT / ".understand-agent" / "test-home"
            self.assertEqual(default_session_dir(home), home / ".understand-agent" / "sessions")
        finally:
            if old is not None:
                os.environ["UNDERSTAND_AGENT_SESSION_DIR"] = old

    def test_default_archived_session_dir_is_under_home(self) -> None:
        old = os.environ.pop("UNDERSTAND_AGENT_ARCHIVED_SESSION_DIR", None)
        try:
            home = ROOT / ".understand-agent" / "test-home"
            self.assertEqual(
                default_archived_session_dir(home),
                home / ".understand-agent" / "archived_sessions",
            )
        finally:
            if old is not None:
                os.environ["UNDERSTAND_AGENT_ARCHIVED_SESSION_DIR"] = old

    def test_create_save_and_load_session(self) -> None:
        store = SessionStore(_new_tmp_dir())
        input_items = [_message("developer", "rules")]

        record = store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=input_items,
            session_id="session-create-load",
        )
        loaded = store.load("session-create-load")

        self.assertEqual(loaded.session_id, record.session_id)
        self.assertEqual(loaded.project_root, str(ROOT.resolve()))
        self.assertEqual(loaded.workspace_root, str(ROOT.parent.resolve()))
        self.assertEqual(loaded.shell_default_workdir, str(ROOT.resolve()))
        self.assertEqual(loaded.input_items, input_items)

    def test_append_turn_does_not_mutate_old_history(self) -> None:
        store = SessionStore(_new_tmp_dir())
        record = store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[_message("developer", "rules")],
            session_id="session-append-only",
        )
        old_items = deepcopy(record.input_items)
        new_items = [*record.input_items, _message("user", "next")]

        updated = store.append_turn(
            record,
            input_items=new_items,
            turn=_turn("run-1", "next"),
        )

        self.assertEqual(record.input_items, old_items)
        self.assertEqual(updated.input_items[: len(old_items)], old_items)
        self.assertEqual(updated.turns[0].run_id, "run-1")

    def test_list_filters_by_project_root(self) -> None:
        store = SessionStore(_new_tmp_dir())
        other = _new_tmp_dir()
        first = store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[],
            session_id="session-current-project",
        )
        store.create(
            project_root=other,
            workspace_root=other.parent,
            shell_default_workdir=other,
            input_items=[],
            session_id="session-other-project",
        )

        summaries = store.list_summaries(project_root=ROOT)

        self.assertEqual([summary.session_id for summary in summaries], [first.session_id])

    def test_list_all_crosses_project_roots(self) -> None:
        store = SessionStore(_new_tmp_dir())
        other = _new_tmp_dir()
        store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[],
            session_id="session-all-current",
        )
        store.create(
            project_root=other,
            workspace_root=other.parent,
            shell_default_workdir=other,
            input_items=[],
            session_id="session-all-other",
        )

        summaries = store.list_summaries(project_root=ROOT, include_all=True)

        self.assertEqual(
            {summary.session_id for summary in summaries},
            {"session-all-current", "session-all-other"},
        )

    def test_latest_returns_most_recent_session(self) -> None:
        store = SessionStore(_new_tmp_dir())
        store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[],
            session_id="session-old",
        )
        latest = store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[],
            session_id="session-new",
        )

        summary = store.latest(project_root=ROOT)

        self.assertIsNotNone(summary)
        self.assertEqual(summary.session_id, latest.session_id)

    def test_load_by_id_does_not_depend_on_current_project(self) -> None:
        store = SessionStore(_new_tmp_dir())
        other = _new_tmp_dir()
        store.create(
            project_root=other,
            workspace_root=other.parent,
            shell_default_workdir=other,
            input_items=[],
            session_id="session-direct-load",
        )

        loaded = store.load("session-direct-load")

        self.assertEqual(loaded.session_id, "session-direct-load")

    def test_archive_moves_session_out_of_active_store(self) -> None:
        root = _new_tmp_dir()
        session_dir = root / "sessions"
        store = SessionStore(session_dir)
        store.create(
            project_root=ROOT,
            workspace_root=ROOT.parent,
            shell_default_workdir=ROOT,
            input_items=[_message("developer", "rules")],
            session_id="session-to-archive",
        )

        result = store.archive("session-to-archive")

        self.assertEqual(result["session_id"], "session-to-archive")
        self.assertFalse(store.path_for("session-to-archive").exists())
        archived_path = Path(result["archived_path"])
        self.assertTrue(archived_path.exists())
        self.assertEqual(archived_path.suffix, ".gzip")
        self.assertEqual(archived_path.name, "session-to-archive.gzip")
        with self.assertRaises(FileNotFoundError):
            store.load("session-to-archive")
        self.assertEqual(store.list_summaries(project_root=ROOT), [])

    def test_archive_moves_session_logs_and_indexes_then_restore_reverses_it(self) -> None:
        root = _new_tmp_dir()
        project = root / "project"
        session_dir = root / "sessions"
        log_dir = project / ".understand-agent" / "logs"
        log_dir.mkdir(parents=True)
        log_path = log_dir / "run-archive.jsonl"
        log_path.write_text('{"event":"kept"}\n', encoding="utf-8")
        log_index_path = log_dir / "index.jsonl"
        log_index_line = json.dumps(
            {
                "run_id": "run-archive",
                "timestamp": "1",
                "argv": ["session"],
                "exit_code": 0,
                "log_path": ".understand-agent/logs/run-archive.jsonl",
            },
            ensure_ascii=False,
        )
        log_index_path.write_text(log_index_line + "\n", encoding="utf-8")
        store = SessionStore(session_dir)
        record = store.create(
            project_root=project,
            workspace_root=root,
            shell_default_workdir=project,
            input_items=[_message("developer", "rules")],
            session_id="session-full-archive",
        )
        record = store.append_turn(
            record,
            input_items=[*record.input_items, _message("user", "next")],
            turn=_turn(
                "run-archive",
                "next",
                trace_path=".understand-agent/logs/run-archive.jsonl",
            ),
        )

        archived = store.archive("session-full-archive")

        archived_path = Path(archived["archived_path"])
        self.assertEqual(archived["archived_log_count"], 1)
        self.assertFalse(store.path_for("session-full-archive").exists())
        self.assertFalse(log_path.exists())
        self.assertFalse(log_index_path.exists())
        self.assertTrue(archived_path.exists())
        self.assertEqual(archived_path.suffix, ".gzip")
        self.assertEqual(archived_path.name, "session-full-archive.gzip")
        with self.assertRaises(UnicodeDecodeError):
            archived_path.read_text(encoding="utf-8")
        with gzip.open(archived_path, "rt", encoding="utf-8") as file:
            payload = json.load(file)
        self.assertEqual(payload["manifest"]["session_id"], "session-full-archive")
        self.assertEqual(payload["session"]["session_id"], "session-full-archive")
        self.assertEqual(len(payload["session_index_lines"]), 2)
        self.assertEqual(payload["log_files"][0]["run_id"], "run-archive")
        self.assertIn("kept", payload["log_files"][0]["content"])
        self.assertEqual(len(payload["log_index_entries"]), 1)

        restored = store.restore_archived(archived_path.name)

        self.assertEqual(restored["session_id"], "session-full-archive")
        self.assertEqual(restored["restored_log_count"], 1)
        self.assertTrue(store.path_for("session-full-archive").exists())
        self.assertTrue(log_path.exists())
        self.assertIn("run-archive", log_index_path.read_text(encoding="utf-8"))
        self.assertFalse(archived_path.exists())
        loaded = store.load("session-full-archive")
        self.assertEqual(loaded.turns[0].trace_path, ".understand-agent/logs/run-archive.jsonl")


def _turn(run_id: str, user_input: str, trace_path: str | None = None) -> SessionTurn:
    return SessionTurn(
        run_id=run_id,
        user_input=user_input,
        ok=True,
        status="done",
        final_answer="ok",
        model_calls=1,
        tool_calls=0,
        error=None,
        trace_path=trace_path,
    )


def _message(role: str, text: str) -> dict:
    return {
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }


def _new_tmp_dir() -> Path:
    path = ROOT / ".understand-agent" / "test-tmp" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path
