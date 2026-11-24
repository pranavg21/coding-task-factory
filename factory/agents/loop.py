"""The tool loop every agent role runs: explore with workspace tools, then call `submit` exactly once.

The loop is ours (not the SDK's tool runner) because every request goes through the recording client,
which is what makes a run replayable. Forced tool choice is not available on the model, so the prompt
asks for `submit` and the loop nudges once if the model ends its turn without it.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from factory.agents.llm import LLM
from factory.agents.workspace import ToolError, Workspace, tool_definitions


class AgentFailedError(RuntimeError):
    """The agent refused, ran out of turns, or never submitted a valid result."""


def submit_tool(description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"name": "submit", "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": properties, "required": required,
                             "additionalProperties": False}}


def run_agent(llm: LLM, system: str, task: str, workspace: Workspace, tools: list[str], submit: dict[str, Any],
              validate: Callable[[dict[str, Any]], str | None] = lambda _: None,
              max_turns: int = 40, effort: str = "high") -> dict[str, Any]:
    """Run one agent until it submits a result that passes `validate` (which returns an error or None)."""
    definitions = [*tool_definitions(tools), submit]
    messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
    nudged = False
    for _ in range(max_turns):
        response = llm.create(max_tokens=16000, system=system, tools=definitions, messages=messages,
                              output_config={"effort": effort})
        stop = response.get("stop_reason")
        if stop == "refusal":
            raise AgentFailedError(f"model declined: {response.get('stop_details')}")
        content = response.get("content", [])
        messages.append({"role": "assistant", "content": content})
        calls = [b for b in content if b.get("type") == "tool_use"]
        if not calls:
            if stop == "max_tokens" or nudged:
                raise AgentFailedError(f"agent stopped without submitting (stop_reason={stop})")
            nudged = True
            messages.append({"role": "user", "content": "Finish by calling the submit tool with your result."})
            continue
        results = []
        for call in calls:
            name, args = call["name"], call.get("input") or {}
            if name == "submit":
                problem = validate(args)
                if problem is None:
                    return args
                results.append({"type": "tool_result", "tool_use_id": call["id"], "is_error": True,
                                "content": f"Not accepted: {problem}. Fix it and call submit again."})
                continue
            try:
                output = getattr(workspace, name)(**args)
                results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
            except (ToolError, TypeError, OSError, ValueError) as exc:
                results.append({"type": "tool_result", "tool_use_id": call["id"], "is_error": True,
                                "content": f"Error: {exc}"})
        messages.append({"role": "user", "content": results})
    raise AgentFailedError(f"no valid submission within {max_turns} turns")


def as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, indent=1)
