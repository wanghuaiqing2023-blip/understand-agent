import json
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from understand_agent.context import ContextBuilder
from understand_agent.context import sanitize_model_output_items
from understand_agent.tools import build_default_registry


ROOT = Path(__file__).resolve().parents[2]


class ContextBuilderTest(TestCase):
    def test_initial_request_has_expected_sections_and_order(self) -> None:
        tmp = _new_tmp_dir()
        project_root = tmp / "understand-agent"
        project_root.mkdir()
        (project_root / "AGENTS.md").write_text("Project rule.", encoding="utf-8")
        builder = ContextBuilder(
            workspace_root=tmp,
            project_root=project_root,
            shell_default_workdir=tmp,
            cwd=project_root,
        )

        request = builder.build_initial_request("Do the task.", build_default_registry())

        payload = request.to_dict()
        self.assertEqual(list(payload), ["instructions", "tools", "input"])
        self.assertIn("local coding and research agent", payload["instructions"])
        self.assertEqual(
            [tool["name"] for tool in payload["tools"]],
            ["list_files", "read_file", "search_text", "shell"],
        )
        self.assertEqual([item["role"] for item in payload["input"]], ["developer", "user", "user", "user"])
        self.assertIn("<permissions instructions>", _text(payload["input"][0]))
        self.assertIn("<INSTRUCTIONS>", _text(payload["input"][1]))
        self.assertIn("Project rule.", _text(payload["input"][1]))
        self.assertIn("<environment_context>", _text(payload["input"][2]))
        self.assertEqual(_text(payload["input"][3]), "Do the task.")

    def test_missing_agents_file_is_skipped(self) -> None:
        tmp = _new_tmp_dir()
        project_root = tmp / "understand-agent"
        project_root.mkdir()
        builder = ContextBuilder(
            workspace_root=tmp,
            project_root=project_root,
            shell_default_workdir=tmp,
            cwd=project_root,
        )

        request = builder.build_initial_request("Task.", build_default_registry())

        self.assertEqual([item["role"] for item in request.input], ["developer", "user", "user"])
        self.assertIn("<environment_context>", _text(request.input[1]))
        self.assertEqual(_text(request.input[2]), "Task.")

    def test_environment_context_contains_runtime_roots_and_timezone(self) -> None:
        workspace_root = _new_tmp_dir()
        project_root = workspace_root / "understand-agent"
        project_root.mkdir()
        builder = ContextBuilder(
            workspace_root=workspace_root,
            project_root=project_root,
            shell_default_workdir=workspace_root,
            cwd=project_root,
        )

        request = builder.build_initial_request("Task.", build_default_registry())
        env_text = next(_text(item) for item in request.input if "<environment_context>" in _text(item))

        self.assertIn(f"<cwd>{project_root.resolve()}</cwd>", env_text)
        self.assertIn(f"<workspace_root>{workspace_root.resolve()}</workspace_root>", env_text)
        self.assertIn(f"<project_root>{project_root.resolve()}</project_root>", env_text)
        self.assertIn(f"<shell_default_workdir>{workspace_root.resolve()}</shell_default_workdir>", env_text)
        self.assertIn("<shell>powershell</shell>", env_text)
        self.assertIn("<timezone>Asia/Singapore</timezone>", env_text)

    def test_append_single_function_call_and_output_preserves_prefix(self) -> None:
        builder = _builder()
        old_input = [{"role": "user", "content": [{"type": "input_text", "text": "Task"}]}]
        old_copy = deepcopy(old_input)
        function_call = {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": json.dumps({"path": "understand-agent/AGENTS.md"}),
        }

        after_model = builder.append_model_output(old_input, [function_call])
        after_tool = builder.append_tool_observation(after_model, "call_1", '{"ok":true}')

        self.assertEqual(old_input, old_copy)
        self.assertEqual(old_input, after_model[: len(old_input)])
        self.assertEqual(after_model, after_tool[: len(after_model)])
        self.assertEqual(after_tool[-2], function_call)
        self.assertEqual(after_tool[-1]["type"], "function_call_output")
        self.assertEqual(after_tool[-1]["call_id"], "call_1")

    def test_append_multiple_function_calls_preserves_model_output_order(self) -> None:
        builder = _builder()
        old_input = [{"role": "user", "content": [{"type": "input_text", "text": "Task"}]}]
        calls = [
            {"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": "{}"},
            {"type": "function_call", "call_id": "call_2", "name": "search_text", "arguments": "{}"},
        ]

        after_model = builder.append_model_output(old_input, calls)
        after_first = builder.append_tool_observation(after_model, "call_1", '{"ok":true}')
        after_second = builder.append_tool_observation(after_first, "call_2", '{"ok":true}')

        self.assertEqual(after_second[1], calls[0])
        self.assertEqual(after_second[2], calls[1])
        self.assertEqual(after_second[3]["call_id"], "call_1")
        self.assertEqual(after_second[4]["call_id"], "call_2")

    def test_append_history_does_not_mutate_existing_items(self) -> None:
        builder = _builder()
        old_input = [{"role": "user", "content": [{"type": "input_text", "text": "Task"}]}]
        old_copy = deepcopy(old_input)

        _ = builder.append_tool_observation(old_input, "call_1", '{"ok":false}')

        self.assertEqual(old_input, old_copy)

    def test_sanitize_model_output_removes_proxy_unsupported_status(self) -> None:
        items = [
            {
                "type": "reasoning",
                "id": "rs_1",
                "status": "completed",
                "summary": [{"type": "summary_text", "text": "Thinking."}],
                "encrypted_content": "opaque",
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "list_files",
                "arguments": '{"path":"."}',
                "status": "completed",
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Done"}],
            },
        ]

        sanitized = sanitize_model_output_items(items)

        self.assertEqual(
            sanitized[0],
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Thinking."}],
                "encrypted_content": "opaque",
            },
        )
        self.assertEqual(
            sanitized[1],
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "list_files",
                "arguments": '{"path":"."}',
            },
        )
        self.assertEqual(
            sanitized[2],
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Done"}],
            },
        )


def _builder() -> ContextBuilder:
    root = Path.cwd()
    return ContextBuilder(workspace_root=root, project_root=root, shell_default_workdir=root)


def _text(item: dict) -> str:
    return item["content"][0]["text"]


def _tmp_parent() -> Path:
    path = ROOT / ".understand-agent" / "test-tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_tmp_dir() -> Path:
    path = _tmp_parent() / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path
