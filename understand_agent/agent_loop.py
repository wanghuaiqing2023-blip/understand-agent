from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from understand_agent.context import ContextBuilder
from understand_agent.model import MODEL_NAME, REASONING_EFFORT, ModelClient, ModelClientError
from understand_agent.registry import ToolContext, ToolRegistry, ToolResult


SUPPORTED_TOOL_ACTION_TYPES = {"function_call"}


@dataclass(frozen=True)
class ToolAction:
    type: str
    call_id: str
    name: str
    arguments: str
    item: dict[str, Any]


@dataclass(frozen=True)
class AgentRunConfig:
    max_model_calls: int = 8
    max_tool_calls: int = 8
    model: str = MODEL_NAME
    reasoning_effort: str = REASONING_EFFORT


@dataclass(frozen=True)
class AgentRunResult:
    ok: bool
    status: str
    final_answer: str | None
    model_calls: int
    tool_calls: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "final_answer": self.final_answer,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "error": self.error,
        }


class AgentLoop:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        registry: ToolRegistry,
        context_builder: ContextBuilder,
        tool_context: ToolContext,
        config: AgentRunConfig | None = None,
    ) -> None:
        self.model_client = model_client
        self.registry = registry
        self.context_builder = context_builder
        self.tool_context = tool_context
        self.config = config or AgentRunConfig()

    def run(self, task: str) -> AgentRunResult:
        logger = self.tool_context.logger
        if logger is not None:
            logger.record(
                "agent_run_started",
                {
                    "model": self.config.model,
                    "reasoning_effort": self.config.reasoning_effort,
                    "max_model_calls": self.config.max_model_calls,
                    "max_tool_calls": self.config.max_tool_calls,
                },
            )

        request = self.context_builder.build_initial_request(task, self.registry)
        input_items = deepcopy(request.input)
        if logger is not None:
            logger.record(
                "context_built",
                {
                    "input_count": len(input_items),
                    "tool_names": [tool["name"] for tool in request.tools],
                },
            )

        model_calls = 0
        tool_calls = 0

        while True:
            if model_calls >= self.config.max_model_calls:
                return self._finish(False, "failed", None, model_calls, tool_calls, "max_model_calls exceeded")

            model_calls += 1
            if logger is not None:
                logger.record(
                    "model_call_started",
                    {
                        "model": self.config.model,
                        "model_call_index": model_calls,
                        "input_count": len(input_items),
                    },
                )
            try:
                response = self.model_client.create_response(
                    instructions=request.instructions,
                    tools=request.tools,
                    input_items=input_items,
                )
            except ModelClientError as exc:
                failed_model_calls = (
                    model_calls - 1
                    if exc.error_type in {"MissingApiKeyError", "ImportError"}
                    else model_calls
                )
                if logger is not None:
                    logger.record(
                        "model_call_failed",
                        {
                            "provider": "openai",
                            "model": self.config.model,
                            "model_call_index": model_calls,
                            "error_type": exc.error_type,
                            "error": str(exc),
                        },
                    )
                return self._finish(False, "failed", None, failed_model_calls, tool_calls, str(exc))

            if logger is not None:
                logger.record(
                    "model_call_finished",
                    {
                        "model": self.config.model,
                        "model_call_index": model_calls,
                        "output_count": len(response.output),
                        "output_text": response.output_text,
                    },
                )

            input_items = self.context_builder.append_model_output(input_items, response.output)
            if logger is not None:
                logger.record(
                    "model_output_appended",
                    {"model_call_index": model_calls, "input_count": len(input_items)},
                )

            unsupported = find_unsupported_tool_action(response.output)
            if unsupported is not None:
                error = f"unsupported tool action type: {unsupported.get('type')}"
                if logger is not None:
                    logger.record("unsupported_tool_action", {"item": unsupported, "error": error})
                return self._finish(False, "failed", None, model_calls, tool_calls, error)

            actions = extract_tool_actions(response.output)
            if logger is not None:
                logger.record(
                    "tool_action_extracted",
                    {"model_call_index": model_calls, "count": len(actions)},
                )

            if actions:
                for action in actions:
                    if tool_calls >= self.config.max_tool_calls:
                        return self._finish(False, "failed", None, model_calls, tool_calls, "max_tool_calls exceeded")
                    tool_calls += 1
                    result = execute_tool_action(action, self.registry, self.tool_context)
                    output = json.dumps(result.to_dict(), ensure_ascii=False)
                    input_items = self.context_builder.append_tool_observation(
                        input_items,
                        action.call_id,
                        output,
                    )
                    if logger is not None:
                        logger.record(
                            "tool_observation_appended",
                            {
                                "call_id": action.call_id,
                                "tool_name": action.name,
                                "input_count": len(input_items),
                                "result": result.to_dict(),
                            },
                        )
                continue

            final_answer = extract_final_answer(response.raw, response.output_text)
            if final_answer:
                return self._finish(True, "done", final_answer, model_calls, tool_calls, None)
            return self._finish(
                False,
                "failed",
                None,
                model_calls,
                tool_calls,
                "model returned no tool action and no final answer",
            )

    def _finish(
        self,
        ok: bool,
        status: str,
        final_answer: str | None,
        model_calls: int,
        tool_calls: int,
        error: str | None,
    ) -> AgentRunResult:
        result = AgentRunResult(
            ok=ok,
            status=status,
            final_answer=final_answer,
            model_calls=model_calls,
            tool_calls=tool_calls,
            error=error,
        )
        if self.tool_context.logger is not None:
            self.tool_context.logger.record("agent_run_finished", result.to_dict())
        return result


def extract_tool_actions(output_items: list[dict[str, Any]]) -> list[ToolAction]:
    actions: list[ToolAction] = []
    for item in output_items:
        if item.get("type") != "function_call":
            continue
        actions.append(
            ToolAction(
                type="function_call",
                call_id=str(item.get("call_id", "")),
                name=str(item.get("name", "")),
                arguments=str(item.get("arguments", "{}")),
                item=deepcopy(item),
            )
        )
    return actions


def find_unsupported_tool_action(output_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in output_items:
        item_type = item.get("type")
        if not isinstance(item_type, str):
            continue
        if item_type in SUPPORTED_TOOL_ACTION_TYPES:
            continue
        if item_type.endswith("_call"):
            return item
    return None


def execute_tool_action(action: ToolAction, registry: ToolRegistry, context: ToolContext) -> ToolResult:
    if not action.call_id:
        return ToolResult.failure("tool action call_id is required")
    if not action.name:
        return ToolResult.failure("tool action name is required")
    try:
        args = json.loads(action.arguments or "{}")
    except json.JSONDecodeError as exc:
        return ToolResult.failure(f"tool arguments are not valid JSON: {exc}")
    if not isinstance(args, dict):
        return ToolResult.failure("tool arguments must decode to a JSON object")
    return registry.run(action.name, args, context)


def extract_final_answer(raw_response: dict[str, Any], output_text: str | None) -> str | None:
    if output_text:
        return output_text

    texts: list[str] = []
    for item in raw_response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(str(content["text"]))
    if texts:
        return "\n".join(texts)
    return None
