import json
from pathlib import Path
from unittest import TestCase

from understand_agent.agent_loop import (
    AgentLoop,
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
                    "name": "shell",
                    "arguments": '{"command":"Get-Content README.md"}',
                }
            ]
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].call_id, "call_1")
        self.assertEqual(actions[0].name, "shell")

    def test_find_unsupported_tool_action(self) -> None:
        unsupported = find_unsupported_tool_action([{"type": "web_search_call", "id": "ws_1"}])

        self.assertEqual(unsupported, {"type": "web_search_call", "id": "ws_1"})

    def test_bad_arguments_become_tool_result_error(self) -> None:
        action = extract_tool_actions(
            [{"type": "function_call", "call_id": "call_1", "name": "shell", "arguments": "{bad json"}]
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
        self.assertIsNotNone(result.input_items)
        self.assertEqual(result.input_items[-1]["role"], "assistant")
        self.assertEqual(result.input_items[-1]["content"][0]["text"], "Done.")

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
        self.assertIsNotNone(result.input_items)
        self.assertEqual(result.input_items[-2]["type"], "function_call_output")
        self.assertEqual(result.input_items[-1]["role"], "assistant")

    def test_default_loop_has_no_eight_call_cap(self) -> None:
        responses = [
            ModelResponse(
                output=[
                    {
                        "type": "function_call",
                        "call_id": f"call_{index}",
                        "name": "echo",
                        "arguments": f'{{"value":"{index}"}}',
                    }
                ],
                output_text=None,
                raw={"output": []},
            )
            for index in range(9)
        ]
        responses.append(ModelResponse(output=[], output_text="Done after many calls.", raw={"output": []}))
        loop = _loop(responses)

        result = loop.run("Use many calls.")

        self.assertTrue(result.ok)
        self.assertEqual(result.model_calls, 10)
        self.assertEqual(result.tool_calls, 9)
        self.assertEqual(result.final_answer, "Done after many calls.")

    def test_loop_continues_from_existing_input_items(self) -> None:
        root = Path.cwd()
        builder = ContextBuilder(workspace_root=root, project_root=root, shell_default_workdir=root)
        existing = [{"role": "user", "content": [{"type": "input_text", "text": "Earlier"}]}]
        turn_input = builder.append_user_turn(existing, "Continue.")
        loop = _loop([ModelResponse(output=[], output_text="Continued.", raw={"output": []})])

        result = loop.run_with_input_items(turn_input)

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.input_items)
        self.assertEqual(result.input_items[: len(turn_input)], turn_input)
        self.assertEqual(result.input_items[-1]["content"][0]["text"], "Continued.")

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
    )
