import json
from pathlib import Path
from unittest import TestCase

from understand_agent.agent_loop import (
    AgentLoop,
    AgentRunConfig,
    execute_tool_action,
    extract_final_answer,
    extract_tool_actions,
    find_unsupported_tool_action,
)
from understand_agent.context import ContextBuilder
from understand_agent.model import ModelClientError, ModelResponse
from understand_agent.registry import ToolContext, ToolRegistry, ToolResult, ToolSpec


class AgentLoopTest(TestCase):
    def test_extract_tool_actions_supports_function_call(self) -> None:
        actions = extract_tool_actions(
            [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                }
            ]
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].call_id, "call_1")
        self.assertEqual(actions[0].name, "read_file")

    def test_find_unsupported_tool_action(self) -> None:
        unsupported = find_unsupported_tool_action([{"type": "web_search_call", "id": "ws_1"}])

        self.assertEqual(unsupported, {"type": "web_search_call", "id": "ws_1"})

    def test_bad_arguments_become_tool_result_error(self) -> None:
        action = extract_tool_actions(
            [{"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": "{bad json"}]
        )[0]

        result = execute_tool_action(action, ToolRegistry(), ToolContext(workspace_root=Path.cwd()))

        self.assertFalse(result.ok)
        self.assertIn("not valid JSON", result.error or "")

    def test_failed_tool_output_can_be_serialized_as_observation(self) -> None:
        result = ToolResult.failure("unknown tool: missing")
        output = json.dumps(result.to_dict(), ensure_ascii=False)

        self.assertIn('"ok": false', output)
        self.assertIn("unknown tool: missing", output)

    def test_extract_final_answer_from_output_text(self) -> None:
        answer = extract_final_answer({"output": []}, "Done.")

        self.assertEqual(answer, "Done.")

    def test_extract_final_answer_from_message_content(self) -> None:
        answer = extract_final_answer(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Done from message."}],
                    }
                ]
            },
            None,
        )

        self.assertEqual(answer, "Done from message.")

    def test_loop_stops_when_model_returns_final_answer(self) -> None:
        loop = _loop([ModelResponse(output=[], output_text="Done.", raw={"output": []})])

        result = loop.run("Say done.")

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "done")
        self.assertEqual(result.final_answer, "Done.")
        self.assertEqual(result.model_calls, 1)
        self.assertEqual(result.tool_calls, 0)

    def test_loop_executes_tool_and_continues_to_final_answer(self) -> None:
        loop = _loop(
            [
                ModelResponse(
                    output=[
                        {
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "echo",
                            "arguments": '{"value":"hello"}',
                        }
                    ],
                    output_text=None,
                    raw={"output": []},
                ),
                ModelResponse(output=[], output_text="Observed hello.", raw={"output": []}),
            ]
        )

        result = loop.run("Echo hello.")

        self.assertTrue(result.ok)
        self.assertEqual(result.model_calls, 2)
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(result.final_answer, "Observed hello.")

    def test_loop_fails_on_unsupported_tool_action(self) -> None:
        loop = _loop([ModelResponse(output=[{"type": "web_search_call"}], output_text=None, raw={"output": []})])

        result = loop.run("Search web.")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unsupported tool action type: web_search_call")

    def test_loop_fails_when_model_client_raises(self) -> None:
        loop = _loop([], client=_FailingClient())

        result = loop.run("Task.")

        self.assertFalse(result.ok)
        self.assertIn("boom", result.error or "")

    def test_loop_enforces_model_call_budget(self) -> None:
        loop = _loop(
            [
                ModelResponse(
                    output=[
                        {
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "echo",
                            "arguments": '{"value":"hello"}',
                        }
                    ],
                    output_text=None,
                    raw={"output": []},
                ),
                ModelResponse(output=[], output_text="Too late.", raw={"output": []}),
            ],
            config=AgentRunConfig(max_model_calls=1, max_tool_calls=8),
        )

        result = loop.run("Task.")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "max_model_calls exceeded")

    def test_loop_enforces_tool_call_budget(self) -> None:
        loop = _loop(
            [
                ModelResponse(
                    output=[
                        {
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "echo",
                            "arguments": '{"value":"hello"}',
                        }
                    ],
                    output_text=None,
                    raw={"output": []},
                )
            ],
            config=AgentRunConfig(max_model_calls=8, max_tool_calls=0),
        )

        result = loop.run("Task.")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "max_tool_calls exceeded")


class _Client:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses
        self.index = 0

    def create_response(self, **_kwargs) -> ModelResponse:
        response = self.responses[self.index]
        self.index += 1
        return response


class _FailingClient:
    def create_response(self, **_kwargs) -> ModelResponse:
        raise ModelClientError("boom", "BoomError")


def _loop(
    responses: list[ModelResponse],
    client=None,
    config: AgentRunConfig | None = None,
) -> AgentLoop:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="Echo input.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            permission_level="read",
            handler=lambda args, _context: ToolResult.success(args),
        )
    )
    root = Path.cwd()
    return AgentLoop(
        model_client=client or _Client(responses),
        registry=registry,
        context_builder=ContextBuilder(workspace_root=root, project_root=root, shell_default_workdir=root),
        tool_context=ToolContext(workspace_root=root),
        config=config,
    )
