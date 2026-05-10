import json
from pathlib import Path
from unittest import TestCase

from understand_agent import ToolContext, ToolRegistry, ToolResult, ToolSpec
from understand_agent.trace import ExecutionLogger


ROOT = Path(__file__).resolve().parents[2]


class ToolRegistryTest(TestCase):
    def setUp(self) -> None:
        self.context = ToolContext(workspace_root=Path.cwd())

    def test_register_and_run_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="echo",
                description="Echo args.",
                input_schema={"value": "string"},
                permission_level="read",
                handler=lambda args, _context: ToolResult.success(args),
            )
        )

        result = registry.run("echo", {"value": "hello"}, self.context)

        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"value": "hello"})

    def test_duplicate_registration_raises(self) -> None:
        registry = ToolRegistry()
        spec = ToolSpec(
            name="echo",
            description="Echo args.",
            input_schema={},
            permission_level="read",
            handler=lambda _args, _context: ToolResult.success(),
        )
        registry.register(spec)

        with self.assertRaises(ValueError):
            registry.register(spec)

    def test_unknown_tool_returns_failure(self) -> None:
        result = ToolRegistry().run("missing", {}, self.context)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unknown tool: missing")

    def test_handler_exception_is_wrapped(self) -> None:
        def broken(_args, _context):
            raise RuntimeError("boom")

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="broken",
                description="Broken tool.",
                input_schema={},
                permission_level="read",
                handler=broken,
            )
        )

        result = registry.run("broken", {}, self.context)

        self.assertFalse(result.ok)
        self.assertIn("boom", result.error or "")

    def test_list_tools_hides_handler(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="echo",
                description="Echo args.",
                input_schema={},
                permission_level="read",
                handler=lambda _args, _context: ToolResult.success(),
            )
        )

        tools = registry.list_tools()

        self.assertEqual(tools[0]["name"], "echo")
        self.assertNotIn("handler", tools[0])

    def test_run_records_tool_trace_events(self) -> None:
        log_path = ROOT / ".understand-agent" / "test-logs" / "registry-trace.jsonl"
        log_path.unlink(missing_ok=True)
        logger = ExecutionLogger(log_path=log_path, run_id="registry-trace")
        context = ToolContext(workspace_root=ROOT, run_id=logger.run_id, logger=logger)
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="echo",
                description="Echo args.",
                input_schema={},
                permission_level="read",
                handler=lambda args, _context: ToolResult.success(args),
            )
        )

        result = registry.run("echo", {"value": "hello"}, context)

        self.assertTrue(result.ok)
        events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["event_type"] for event in events], ["tool_call_started", "tool_call_finished"])
        self.assertEqual(events[1]["payload"]["result"]["data"], {"value": "hello"})

    def test_unknown_tool_records_failure_trace(self) -> None:
        log_path = ROOT / ".understand-agent" / "test-logs" / "missing-tool-trace.jsonl"
        log_path.unlink(missing_ok=True)
        logger = ExecutionLogger(log_path=log_path, run_id="missing-tool-trace")
        context = ToolContext(workspace_root=ROOT, run_id=logger.run_id, logger=logger)

        result = ToolRegistry().run("missing", {}, context)

        self.assertFalse(result.ok)
        events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[-1]["payload"]["result"]["error"], "unknown tool: missing")
