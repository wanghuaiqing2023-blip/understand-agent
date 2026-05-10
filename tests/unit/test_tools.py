from pathlib import Path
from unittest import TestCase

from understand_agent import ToolContext
from understand_agent.tools import build_default_registry, list_files, read_file, search_text


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


class ReadOnlyToolsTest(TestCase):
    def setUp(self) -> None:
        self.root = FIXTURES / "workspace"
        self.context = ToolContext(workspace_root=self.root)

    def test_default_registry_contains_three_read_only_tools(self) -> None:
        registry = build_default_registry()
        names = [tool["name"] for tool in registry.list_tools()]

        self.assertEqual(names, ["list_files", "read_file", "search_text"])
        self.assertTrue(all(tool["permission_level"] == "read" for tool in registry.list_tools()))

    def test_list_files_skips_ignored_dirs(self) -> None:
        result = list_files({"path": "."}, self.context)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["files"], ["docs/README.md"])

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
