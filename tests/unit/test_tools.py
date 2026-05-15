from pathlib import Path
from unittest import TestCase

from understand_agent import ToolContext
from understand_agent.tools import build_default_registry, shell


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


class ShellToolTest(TestCase):
    def setUp(self) -> None:
        self.root = FIXTURES / "workspace"

    def test_default_registry_contains_only_shell(self) -> None:
        registry = build_default_registry()
        tools = registry.list_tools()

        self.assertEqual([tool["name"] for tool in tools], ["shell"])
        self.assertEqual(tools[0]["permission_level"], "execute")

    def test_shell_requires_command(self) -> None:
        result = shell({}, ToolContext(workspace_root=self.root))

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "command is required")

    def test_shell_rejects_invalid_timeout(self) -> None:
        context = ToolContext(
            workspace_root=self.root,
            shell_default_workdir=self.root,
            shell_approver=lambda _request: True,
        )

        result = shell({"command": "Write-Output nope", "timeout_ms": "bad"}, context)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout_ms must be an integer")

    def test_shell_rejects_non_positive_timeout(self) -> None:
        context = ToolContext(
            workspace_root=self.root,
            shell_default_workdir=self.root,
            shell_approver=lambda _request: True,
        )

        result = shell({"command": "Write-Output nope", "timeout_ms": 0}, context)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout_ms must be greater than 0")

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
