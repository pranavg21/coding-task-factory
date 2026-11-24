"""Gemini backend (Google AI Studio API key) behind the factory's provider-neutral request format.

The agent loop speaks one format: a system prompt, tools with JSON-schema inputs, and messages whose
content is text, `tool_use` blocks or `tool_result` blocks. This module turns that into a Gemini
`generate_content` call and turns the reply back, so the roles, the loop and record/replay do not depend
on the provider.

Gemini attaches thought signatures to its parts; they must be sent back unchanged on the next turn, so
every block keeps the original part in `raw` and assistant turns are rebuilt from those parts.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
EFFORT_TO_LEVEL = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "HIGH", "max": "HIGH"}
REFUSALS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
MAX_RETRIES = 8


def _schema(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini takes standard JSON Schema; it has no notion of the `strict` flag on the tool itself."""
    return input_schema


def to_gemini(params: dict[str, Any]) -> tuple[list[Any], Any]:
    from google.genai import types

    names: dict[str, str] = {}  # tool_use id -> function name, needed for function responses
    contents: list[types.Content] = []
    for message in params["messages"]:
        content = message["content"]
        if message["role"] == "assistant":
            parts = [types.Part.model_validate(block["raw"]) for block in content if block.get("raw")]
            for block in content:
                if block.get("type") == "tool_use":
                    names[block["id"]] = block["name"]
            contents.append(types.Content(role="model", parts=parts))
            continue
        if isinstance(content, str):
            contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
            continue
        parts = []
        for block in content:
            if block.get("type") == "tool_result":
                key = "error" if block.get("is_error") else "output"
                call_id = block["tool_use_id"]
                parts.append(types.Part(function_response=types.FunctionResponse(
                    id=call_id if not call_id.startswith("fc") else None, name=names.get(call_id, "tool"),
                    response={key: block.get("content", "")})))
            elif block.get("type") == "text":
                parts.append(types.Part(text=block["text"]))
        contents.append(types.Content(role="user", parts=parts))

    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=t["name"], description=t.get("description", ""),
                                  parameters_json_schema=_schema(t["input_schema"]))
        for t in params.get("tools", [])])] if params.get("tools") else None
    effort = (params.get("output_config") or {}).get("effort")
    thinking = None
    if effort and str(params["model"]).startswith("gemini-3"):
        thinking = types.ThinkingConfig(thinking_level=EFFORT_TO_LEVEL.get(effort, "HIGH"))
    config = types.GenerateContentConfig(
        system_instruction=params.get("system"), tools=tools, thinking_config=thinking,
        max_output_tokens=params.get("max_tokens"),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    return contents, config


def from_gemini(response: Any) -> dict[str, Any]:
    """The reply in the factory's format: stop_reason, content blocks (each keeping its raw part), usage."""
    usage = response.usage_metadata
    out_usage = {"input_tokens": (usage.prompt_token_count or 0) if usage else 0,
                 "output_tokens": ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0}
    if not response.candidates:
        block = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
        return {"stop_reason": "refusal", "stop_details": {"category": str(block)}, "content": [], "usage": out_usage}
    candidate = response.candidates[0]
    blocks = []
    for index, part in enumerate((candidate.content.parts if candidate.content else None) or []):
        raw = part.model_dump(mode="json", exclude_none=True)
        if part.function_call:
            call = part.function_call
            blocks.append({"type": "tool_use", "id": call.id or f"fc{index}_{call.name}", "name": call.name,
                           "input": dict(call.args or {}), "raw": raw})
        elif part.thought:
            blocks.append({"type": "thinking", "raw": raw})
        elif part.text is not None:
            blocks.append({"type": "text", "text": part.text, "raw": raw})
        else:
            blocks.append({"type": "other", "raw": raw})
    finish = str(getattr(candidate.finish_reason, "value", candidate.finish_reason) or "")
    if any(b["type"] == "tool_use" for b in blocks):
        stop = "tool_use"
    elif finish in REFUSALS:
        stop = "refusal"
    elif finish == "MAX_TOKENS":
        stop = "max_tokens"
    else:
        stop = "end_turn"
    result = {"stop_reason": stop, "content": blocks, "usage": out_usage, "finish_reason": finish}
    if stop == "refusal":
        result["stop_details"] = {"category": finish}
    return result


def _retry_delay(error: Any, attempt: int) -> float:
    """Google's suggested delay for a 429 (RetryInfo), otherwise exponential backoff."""
    text = str(getattr(error, "details", "") or error)
    match = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s", text)
    return float(match.group(1)) + 1 if match else min(60.0, 2.0 ** attempt)


def call(client: Any, params: dict[str, Any]) -> dict[str, Any]:
    """One generate_content call, retried on rate limits (429) and server errors (5xx)."""
    from google.genai import errors

    contents, config = to_gemini(params)
    for attempt in range(MAX_RETRIES):
        try:
            return from_gemini(client.models.generate_content(model=params["model"], contents=contents, config=config))
        except errors.APIError as exc:
            code = getattr(exc, "code", 0) or 0
            if code != 429 and code < 500 or attempt == MAX_RETRIES - 1:
                raise
            time.sleep(_retry_delay(exc, attempt))
    raise RuntimeError("unreachable")
