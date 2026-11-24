"""The whole generation flow on the sample repository, with a scripted stand-in for Claude.

No API is called: the stand-in answers each role the way a model would (tool calls, then submit).
The same run is then replayed from its recordings with no client at all, and the task packages must
come out byte-identical, which is the repeatability guarantee.
"""
import hashlib
import sys
from pathlib import Path

from factory.agents.llm import LLM
from factory.pipeline.generate import RepoContext, generate, pick_cells
from factory.stacks import stack_for
from factory.verifier.proof_runner import local_executor
from tests.test_package_harness import FEATURE_TEST, PRICING, make_repo, needs_tools

SPEC = """## Problem Statement
Add percentage discounts.

## Acceptance Criteria
1. apply_percent(200, 10) returns 180.
2. The result is never negative.

## Interface Contract
- shop/pricing.py: apply_percent(amount, pct) -> number

## Non-Goals & Constraints
- No currency handling.
"""
NEW_PRICING = PRICING + "\n\ndef apply_percent(amount, pct):\n    return max(0, amount - amount * pct / 100)\n"


class Reply:
    def __init__(self, data):
        self.data = data

    def model_dump(self, **_):
        return self.data


def tool(name, args, n=1):
    return Reply({"stop_reason": "tool_use", "usage": {"input_tokens": 100, "output_tokens": 50},
                  "content": [{"type": "tool_use", "id": f"call{n}", "name": name, "input": args}]})


class ScriptedClaude:
    """Answers by role (recognised from the system prompt) and by how far the conversation has got."""

    def __init__(self):
        self.messages = self

    def create(self, **params):
        system, turns = params["system"], len(params["messages"])
        if "You design realistic" in system:
            return tool("submit", {"proposals": [{"title": "Percent discount", "summary": "Add apply_percent to pricing",
                                                  "task_type": "new_feature", "change_pattern": "validation_or_business_rule",
                                                  "scope": "single_function", "files": ["shop/pricing.py"]}]})
        if "You write the instruction.md" in system:
            return tool("submit", {"instruction_md": SPEC})
        if "Agent A" in system or "You are solving a coding task" in system:
            return tool("write_file", {"path": "shop/pricing.py", "content": NEW_PRICING}) if turns == 1 \
                else tool("submit", {"notes": "done"}, 2)
        if "Agent B" in system:
            return tool("write_file", {"path": "tests/test_percent.py", "content": FEATURE_TEST}) if turns == 1 \
                else tool("submit", {"notes": "done"}, 2)
        raise AssertionError("unexpected role")


def run(tmp_path: Path, base: Path, llm: LLM, name: str):
    ctx = RepoContext(repo_id="mini", repo_source="local", base=base, pinned_version="0" * 40, language="python",
                      stack=stack_for("pytest", python=sys.executable),
                      executor=local_executor(Path(sys.executable).parent), test_cmd=("pytest",))
    return generate(ctx, n=1, seed=7, llm=llm, out_dir=tmp_path / name, max_mutants=2)


def package_digest(task_dir: Path) -> dict[str, str]:
    """Hashes of everything except evidence (which records timings)."""
    return {p.relative_to(task_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(task_dir.rglob("*")) if p.is_file() and "evidence" not in p.parts}


@needs_tools
def test_generate_accepts_a_task_and_replays_identically(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1795000000")
    base = make_repo(tmp_path / "base")
    recorded = LLM(mode="record", recordings=tmp_path / "rec", client=ScriptedClaude(), provider="anthropic")
    funnel = run(tmp_path, base, recorded, "first")
    assert [e.status for e in funnel] == ["accepted"], funnel
    first = package_digest(tmp_path / "first" / "mini" / "mini-percent-discount")
    assert "solution/patch.diff" in first and "tests/run_tests.sh" in first

    replay = LLM(mode="replay", recordings=tmp_path / "rec", provider="anthropic")  # no client: any live call would fail
    assert [e.status for e in run(tmp_path, base, replay, "second")] == ["accepted"]
    assert package_digest(tmp_path / "second" / "mini" / "mini-percent-discount") == first


def test_variety_cells_are_distinct_spread_and_reproducible():
    cells = pick_cells(7, seed=3, used=[])
    assert len({c.change_pattern for c in cells}) == 7  # one per change pattern before any repeats
    assert pick_cells(7, seed=3, used=[]) == cells


class BlindFails(ScriptedClaude):
    """The blind solver writes a wrong implementation; the judge returns the configured verdict."""

    def __init__(self, verdict):
        super().__init__()
        self.verdict = verdict

    def create(self, **params):
        system, turns = params["system"], len(params["messages"])
        if "You are solving a coding task" in system:
            wrong = PRICING + "\n\ndef apply_percent(amount, pct):\n    return amount\n"
            return tool("write_file", {"path": "shop/pricing.py", "content": wrong}) if turns == 1 \
                else tool("submit", {"notes": "done"}, 2)
        if "You review a failed task proof" in system:
            return tool("submit", {"verdict": self.verdict, "explanation": "scripted verdict"})
        return super().create(**params)


@needs_tools
def test_blind_solve_rejects_when_the_tests_are_at_fault(tmp_path):
    base = make_repo(tmp_path / "base")
    llm = LLM(mode="live", client=BlindFails("tests"), provider="anthropic")
    funnel = run(tmp_path, base, llm, "out")
    assert funnel[0].status == "rejected" and funnel[0].final_stage == "blind_solve"


@needs_tools
def test_blind_solver_error_keeps_the_task_and_marks_it_hard(tmp_path):
    import json

    base = make_repo(tmp_path / "base")
    llm = LLM(mode="live", client=BlindFails("implementation"), provider="anthropic")
    assert [e.status for e in run(tmp_path, base, llm, "out")] == ["accepted"]
    task = tmp_path / "out" / "mini" / "mini-percent-discount"
    assert json.loads((task / "metadata.json").read_text())["difficulty"] == "hard"
    assert json.loads((task / "evidence" / "proof.json").read_text())["blind_solve_diagnosis"] == "agent_error"
