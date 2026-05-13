from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


MODEL_NAME = "gpt-5.5"
REASONING_EFFORT = "medium"
OPENAI_BASE_URL = "http://127.0.0.1:8787/v1"


class ModelClient(Protocol):
    def create_response(
        self,
        *,
        instructions: str,
        tools: list[dict[str, Any]],
        input_items: list[dict[str, Any]],
    ) -> ModelResponse:
        ...


@dataclass(frozen=True)
class ModelResponse:
    output: list[dict[str, Any]]
    output_text: str | None
    raw: dict[str, Any]


class ModelClientError(RuntimeError):
    def __init__(self, message: str, error_type: str = "ModelClientError") -> None:
        super().__init__(message)
        self.error_type = error_type


class OpenAIResponsesClient:
    def __init__(
        self,
        model: str = MODEL_NAME,
        reasoning_effort: str = REASONING_EFFORT,
        base_url: str = OPENAI_BASE_URL,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.base_url = base_url

    def create_response(
        self,
        *,
        instructions: str,
        tools: list[dict[str, Any]],
        input_items: list[dict[str, Any]],
    ) -> ModelResponse:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ModelClientError("OPENAI_API_KEY is not set", "MissingApiKeyError")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ModelClientError("openai package is not installed", "ImportError") from exc

        try:
            client = OpenAI(api_key=api_key, base_url=self.base_url)
            response = client.responses.create(
                **build_response_create_kwargs(
                    model=self.model,
                    instructions=instructions,
                    tools=tools,
                    input_items=input_items,
                )
            )
        except Exception as exc:  # noqa: BLE001 - preserve SDK failure details for trace.
            error_type = type(exc).__name__
            raise ModelClientError(f"OpenAI API call failed: {error_type}: {exc}", error_type) from exc

        return _normalize_response(response)


def _normalize_response(response: Any) -> ModelResponse:
    if hasattr(response, "model_dump"):
        raw = response.model_dump(mode="json")
    elif isinstance(response, dict):
        raw = response
    else:
        raw = {"repr": repr(response)}

    output = raw.get("output") if isinstance(raw.get("output"), list) else []
    output_text = raw.get("output_text")
    if output_text is None:
        output_text = getattr(response, "output_text", None)
    return ModelResponse(output=output, output_text=output_text, raw=raw)


def build_response_create_kwargs(
    *,
    model: str,
    instructions: str,
    tools: list[dict[str, Any]],
    input_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "model": model,
        "instructions": instructions,
        "tools": tools,
        "input": input_items,
    }
