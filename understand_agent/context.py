from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from understand_agent.registry import ToolRegistry


MODEL_INSTRUCTIONS = """You are understand-agent, a local coding and research agent running on the user's Windows machine.

Use shell commands when you need facts from the local filesystem or command execution. Do not guess when a shell command can answer the question. After each tool observation, continue reasoning from the updated context and either request another tool action or provide a final answer.

Shell commands run only after explicit user approval. Do not assume a shell command has executed until you receive its tool observation."""


PERMISSIONS_INSTRUCTIONS = """<permissions instructions>
Only the shell tool is available. Use PowerShell commands such as Get-ChildItem, Get-Content, Select-String, Set-Content, and python when you need to inspect or change local files.

The shell tool runs PowerShell commands on the host machine, not in a sandbox. The shell default working directory is shown in environment_context. Every shell command requires user approval before execution. If the user rejects a command, treat the rejection as an observation and continue if possible.
</permissions instructions>"""


SINGAPORE_TZ = timezone(timedelta(hours=8), name="Asia/Singapore")


@dataclass(frozen=True)
class ContextRequest:
    instructions: str
    tools: list[dict[str, Any]]
    input: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instructions": self.instructions,
            "tools": deepcopy(self.tools),
            "input": deepcopy(self.input),
        }


@dataclass(frozen=True)
class ContextBuilder:
    workspace_root: Path
    project_root: Path
    shell_default_workdir: Path
    cwd: Path | None = None
    shell_name: str = "powershell"
    timezone_label: str = "Asia/Singapore"

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", self.workspace_root.resolve())
        object.__setattr__(self, "project_root", self.project_root.resolve())
        object.__setattr__(self, "shell_default_workdir", self.shell_default_workdir.resolve())
        object.__setattr__(self, "cwd", (self.cwd or self.shell_default_workdir).resolve())

    def build_initial_request(self, task: str, registry: ToolRegistry) -> ContextRequest:
        input_items = self.append_user_turn(self.build_session_seed(), task)
        return self.build_request_from_input(input_items, registry)

    def build_request_from_input(
        self,
        input_items: list[dict[str, Any]],
        registry: ToolRegistry,
    ) -> ContextRequest:
        return ContextRequest(
            instructions=MODEL_INSTRUCTIONS,
            tools=tools_for_responses_api(registry),
            input=deepcopy(input_items),
        )

    def build_session_seed(self) -> list[dict[str, Any]]:
        return [
            _message("developer", PERMISSIONS_INSTRUCTIONS),
            *self._agents_instructions_items(),
        ]

    def append_user_turn(self, input_items: list[dict[str, Any]], task: str) -> list[dict[str, Any]]:
        return [
            *deepcopy(input_items),
            _message("user", self._environment_context()),
            _message("user", task),
        ]

    def append_model_output(
        self,
        input_items: list[dict[str, Any]],
        output_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [*deepcopy(input_items), *sanitize_model_output_items(output_items)]

    def append_tool_observation(
        self,
        input_items: list[dict[str, Any]],
        call_id: str,
        output: str,
    ) -> list[dict[str, Any]]:
        return [
            *deepcopy(input_items),
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            },
        ]

    def append_assistant_message(self, input_items: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
        return [
            *deepcopy(input_items),
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        ]

    def _agents_instructions_items(self) -> list[dict[str, Any]]:
        agents_path = self.project_root / "AGENTS.md"
        if not agents_path.exists():
            return []
        try:
            content = agents_path.read_text(encoding="utf-8-sig")
        except OSError:
            return []
        return [
            _message(
                "user",
                f"# AGENTS.md instructions for {self.project_root}\n\n"
                f"<INSTRUCTIONS>\n{content}\n</INSTRUCTIONS>",
            )
        ]

    def _environment_context(self) -> str:
        current_date = datetime.now(SINGAPORE_TZ).date().isoformat()
        return (
            "<environment_context>\n"
            f"  <cwd>{self.cwd}</cwd>\n"
            f"  <workspace_root>{self.workspace_root}</workspace_root>\n"
            f"  <project_root>{self.project_root}</project_root>\n"
            f"  <shell_default_workdir>{self.shell_default_workdir}</shell_default_workdir>\n"
            f"  <shell>{self.shell_name}</shell>\n"
            f"  <current_date>{current_date}</current_date>\n"
            f"  <timezone>{self.timezone_label}</timezone>\n"
            "</environment_context>"
        )


def tools_for_responses_api(registry: ToolRegistry) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": deepcopy(tool["input_schema"]),
        }
        for tool in registry.list_tools()
    ]


def _message(role: str, text: str) -> dict[str, Any]:
    return {
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }


def sanitize_model_output_items(output_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in output_items:
        item_type = item.get("type")
        if item_type == "function_call":
            sanitized.append(
                {
                    "type": "function_call",
                    "call_id": item.get("call_id"),
                    "name": item.get("name"),
                    "arguments": item.get("arguments", "{}"),
                }
            )
        elif item_type == "message":
            sanitized.append(
                {
                    "type": "message",
                    "role": item.get("role", "assistant"),
                    "content": item.get("content", []),
                }
            )
        elif item_type == "reasoning":
            reasoning_item: dict[str, Any] = {"type": "reasoning"}
            if "summary" in item:
                reasoning_item["summary"] = item["summary"]
            if "encrypted_content" in item:
                reasoning_item["encrypted_content"] = item["encrypted_content"]
            sanitized.append(reasoning_item)
        else:
            sanitized.append(deepcopy(item))
    return sanitized
