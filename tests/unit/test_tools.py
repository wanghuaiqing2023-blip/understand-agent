from pathlib import Path
from unittest import TestCase

from understand_agent import ToolContext
from understand_agent.tools import build_default_registry, list_files, read_file, search_text, shell


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


class ReadOnlyToolsTest(TestCase):
    def setUp(self) -> None:
        self.root = FIXTURES / "workspace"
        self.context = ToolContext(workspace_root=self.root)

    def test_default_registry_contains_read_tools_and_shell(self) -> None:
        registry = build_default_registry()
        names = [tool["name"] for tool in registry.list_tools()]

        self.assertEqual(names, ["list_files", "read_file", "search_text", "shell"])
        permissions = {tool["name"]: tool["permission_level"] for tool in registry.list_tools()}
        self.assertEqual(permissions["list_files"], "read")
        self.assertEqual(permissions["read_file"], "read")
        self.assertEqual(permissions["search_text"], "read")
        self.assertEqual(permissions["shell"], "execute")

    def test_list_files_skips_ignored_dirs(self) -> None:
        result = list_files({"path": "."}, self.context)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["files"], ["docs/README.md"])
        self.assertFalse(result.data["truncated"])
        self.assertEqual(result.data["max_results"], 1000)

    def test_list_files_stops_at_max_results(self) -> None:
        result = list_files({"path": ".", "max_results": 1}, self.context)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["count"], 1)
        self.assertTrue(result.data["truncated"])

    def test_list_files_rejects_invalid_max_results(self) -> None:
        result = list_files({"path": ".", "max_results": 0}, self.context)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "max_results must be greater than 0")

    def test_read_file_reads_workspace_file(self) -> None:
        result = read_file({"path": "docs/README.md"}, self.context)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["path"], "docs/README.md")
        self.assertIn("智能体", result.data["content"])

    def test_read_file_rejects_workspace_escape(self) -> None:
        result = read_file({"path": "../outside.txt"}, self.context)

        self.assertFalse(result.ok)
        self.assertIn("escapes workspace", result.error or "")

    def test_search_text_returns_file_and_line(self) -> None:
        result = search_text({"path": "docs", "query": "智能体"}, self.context)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["count"], 1)
        self.assertEqual(
            result.data["matches"][0],
            {"path": "docs/README.md", "line": 2, "text": "智能体"},
        )

    def test_search_text_requires_query(self) -> None:
        result = search_text({"path": "docs"}, self.context)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "query is required")

    def test_shell_rejects_command_without_approval(self) -> None:
        context = ToolContext(
            workspace_root=self.root,
            shell_default_workdir=self.root,
            shell_approver=lambda _request: False,
        )

        result = shell({"command": "Write-Output should-not-run"}, context)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "shell command rejected by user")
        self.assertEqual(result.data["workdir"], str(self.root.resolve()))

    def test_shell_runs_command_after_approval(self) -> None:
        context = ToolContext(
            workspace_root=self.root,
            shell_default_workdir=self.root,
            shell_approver=lambda _request: True,
        )

        result = shell({"command": "Write-Output hello"}, context)

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["exit_code"], 0)
        self.assertIn("hello", result.data["stdout"])
        self.assertEqual(result.data["workdir"], str(self.root.resolve()))

    def test_shell_resolves_relative_workdir_under_default(self) -> None:
        context = ToolContext(
            workspace_root=FIXTURES,
            shell_default_workdir=FIXTURES,
            shell_approver=lambda _request: False,
        )

        result = shell({"command": "Write-Output nope", "workdir": "workspace"}, context)

        self.assertFalse(result.ok)
        self.assertEqual(result.data["workdir"], str(self.root.resolve()))

    def test_shell_rejects_workdir_escape(self) -> None:
        context = ToolContext(
            workspace_root=self.root,
            shell_default_workdir=self.root,
            shell_approver=lambda _request: True,
        )

        result = shell({"command": "Write-Output nope", "workdir": ".."}, context)

        self.assertFalse(result.ok)
        self.assertIn("escapes workspace", result.error or "")
