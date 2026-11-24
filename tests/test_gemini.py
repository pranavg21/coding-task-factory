"""The Gemini backend: request/response translation, thought signatures, refusals, and a full run.

A scripted stand-in returns real google-genai response objects, so the translation is exercised exactly
as it would be against the API, without calling it.
"""
from pathlib import Path

from google.genai import types

from factory.agents import gemini
from factory.agents.llm import LLM
from tests.test_generate import NEW_PRICING, SPEC, package_digest, run
from tests.test_package_harness import FEATURE_TEST, make_repo, needs_tools


def reply(*parts, finish="STOP"):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=120, candidates_token_count=30,
                                                                  thoughts_token_count=10))


def call(name, args, signature=b"sig"):
    return types.Part(function_call=types.FunctionCall(name=name, args=args), thought_signature=signature)


class ScriptedGemini:
    """Answers each role (from the system instruction) like Gemini, with a thought signature on each call."""

    def __init__(self):
        self.models = self
        self.seen_signatures = []

    def generate_content(self, model, contents, config):
        system, turns = config.system_instruction, len(contents)
        for content in contents:
            if content.role == "model":
                self.seen_signatures += [p.thought_signature for p in content.parts if p.function_call]
        if "You design realistic" in system:
            return reply(call("submit", {"proposals": [{"title": "Percent discount", "summary": "Add apply_percent",
                                                        "task_type": "new_feature",
                                                        "change_pattern": "validation_or_business_rule",
                                                        "scope": "single_function", "files": ["shop/pricing.py"]}]}))
        if "You write the instruction.md" in system:
            return reply(call("submit", {"instruction_md": SPEC}))
        if "Agent A" in system or "You are solving a coding task" in system:
            return reply(call("write_file", {"path": "shop/pricing.py", "content": NEW_PRICING})) if turns == 1 \
                else reply(call("submit", {"notes": "done"}))
        if "Agent B" in system:
            return reply(call("write_file", {"path": "tests/test_percent.py", "content": FEATURE_TEST})) if turns == 1 \
                else reply(call("submit", {"notes": "done"}))
        raise AssertionError("unexpected role")


def test_request_translation_keeps_tools_system_and_effort():
    params = {"model": "gemini-3-pro", "system": "sys", "max_tokens": 100, "output_config": {"effort": "high"},
              "tools": [{"name": "read_file", "description": "d", "strict": True,
                         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                                          "required": ["path"], "additionalProperties": False}}],
              "messages": [{"role": "user", "content": "hello"}]}
    contents, config = gemini.to_gemini(params)
    assert contents[0].parts[0].text == "hello" and config.system_instruction == "sys"
    assert config.tools[0].function_declarations[0].parameters_json_schema["required"] == ["path"]
    assert config.thinking_config.thinking_level == "HIGH"
    assert config.automatic_function_calling.disable is True


def test_tool_calls_results_and_signatures_round_trip():
    first = gemini.from_gemini(reply(call("read_file", {"path": "a.py"}, b"\x01\x02")))
    assert first["stop_reason"] == "tool_use" and first["content"][0]["input"] == {"path": "a.py"}
    messages = [{"role": "user", "content": "go"}, {"role": "assistant", "content": first["content"]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": first["content"][0]["id"],
                                              "content": "file text"}]}]
    contents, _ = gemini.to_gemini({"model": "gemini-2.5-pro", "messages": messages})
    assert contents[1].parts[0].thought_signature == b"\x01\x02"  # sent back unchanged
    response = contents[2].parts[0].function_response
    assert response.name == "read_file" and response.response == {"output": "file text"}


def test_safety_stop_is_a_refusal_and_blocked_prompt_too():
    assert gemini.from_gemini(reply(types.Part(text="no"), finish="SAFETY"))["stop_reason"] == "refusal"
    blocked = types.GenerateContentResponse(candidates=[])
    assert gemini.from_gemini(blocked)["stop_reason"] == "refusal"


@needs_tools
def test_full_run_on_gemini_records_and_replays_identically(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1795000000")
    base = make_repo(tmp_path / "base")
    scripted = ScriptedGemini()
    llm = LLM(mode="record", recordings=tmp_path / "rec", client=scripted, provider="gemini", model="gemini-2.5-pro")
    assert [e.status for e in run(tmp_path, base, llm, "first")] == ["accepted"]
    assert scripted.seen_signatures and all(s == b"sig" for s in scripted.seen_signatures)
    replay = LLM(mode="replay", recordings=tmp_path / "rec", provider="gemini", model="gemini-2.5-pro")
    assert [e.status for e in run(tmp_path, base, replay, "second")] == ["accepted"]
    assert package_digest(tmp_path / "second" / "mini" / "mini-percent-discount") == \
        package_digest(tmp_path / "first" / "mini" / "mini-percent-discount")
