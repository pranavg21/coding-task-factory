"""The five agent roles. Each runs in its own copy of the repository with only the tools it needs.

    planner      read-only            proposes changes, one per assigned variety cell
    spec_writer  read-only            writes instruction.md with an exact interface contract
    implementer  edits source only    writes the reference solution (Agent A)
    test_writer  creates new tests    writes tests from the spec, never sees Agent A's code (Agent B)
    judge        no tools             after a failed proof, decides who must revise: tests, code or spec

Prompts describe the goal and the hard limits; the factory's deterministic checks decide acceptance.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.agents.llm import LLM
from factory.agents.loop import run_agent, submit_tool
from factory.agents.workspace import Workspace
from factory.schemas import ChangePattern, ScopeLevel, TaskType, VarietyCell

READ_TOOLS = ["list_files", "read_file", "search"]
REQUIRED_HEADINGS = ["## Problem Statement", "## Acceptance Criteria", "## Interface Contract", "## Non-Goals & Constraints"]

SAFETY = ("Never propose or implement anything that weakens security, reaches the network, runs shell commands, "
          "deletes user data, or exists only to make tests pass. Do not modify existing tests.")


def plan(llm: LLM, ws: Workspace, cells: list[VarietyCell], repo_label: str, avoid: list[str]) -> list[dict[str, Any]]:
    wanted = "\n".join(f"{i + 1}. task_type={c.task_type.value}, change_pattern={c.change_pattern.value}, "
                       f"scope={c.scope.value}" for i, c in enumerate(cells))
    taken = "\n".join(f"- {t}" for t in avoid) or "(none yet)"
    system = ("You design realistic software-engineering tasks for evaluating AI coding systems. A task is one change "
              "a maintainer of this repository could plausibly ask for: a new feature, a change to an existing "
              "feature, or a fix for a real defect you can point to in the code. Each must be implementable in a few "
              "hundred lines at most and checkable by automated tests. " + SAFETY)
    task = (f"Repository: {repo_label}. Explore it with the tools, then propose exactly one task for each of these "
            f"slots, in order:\n{wanted}\n\nThe tasks must differ in what they change and where, not just in names "
            f"or text. Avoid anything equivalent to these existing tasks:\n{taken}\n\nFor a bug_fix slot, only propose "
            "a defect you have confirmed by reading the code; if you cannot find one, propose a feature_change instead "
            "and say so in the summary.")
    proposal = {"type": "object", "additionalProperties": False,
                "required": ["title", "summary", "task_type", "change_pattern", "scope", "files"],
                "properties": {"title": {"type": "string"}, "summary": {"type": "string"},
                               "task_type": {"type": "string", "enum": [t.value for t in TaskType]},
                               "change_pattern": {"type": "string", "enum": [p.value for p in ChangePattern]},
                               "scope": {"type": "string", "enum": [s.value for s in ScopeLevel]},
                               "files": {"type": "array", "items": {"type": "string"}}}}
    submit = submit_tool("Submit the proposals, one per slot, in slot order.",
                         {"proposals": {"type": "array", "items": proposal}}, ["proposals"])
    result = run_agent(llm, system, task, ws, READ_TOOLS, submit,
                       validate=lambda a: None if len(a["proposals"]) == len(cells) else f"need {len(cells)} proposals")
    return result["proposals"]


def _check_spec(text: str) -> str | None:
    missing = [h for h in REQUIRED_HEADINGS if h not in text]
    if missing:
        return "missing headings: " + ", ".join(missing)
    criteria = re.findall(r"^\s*\d+\.", text.split("## Acceptance Criteria", 1)[1].split("##", 1)[0], re.M)
    return None if len(criteria) >= 2 else "Acceptance Criteria needs at least 2 numbered, testable criteria"


def write_spec(llm: LLM, ws: Workspace, proposal: dict[str, Any]) -> str:
    system = ("You write the instruction.md for one coding task. A developer who has never seen any solution must be "
              "able to implement it, and a separate tester must be able to test it, from this text alone. Be exact "
              "about names, signatures, return values, error types and messages that tests will check; say nothing "
              "the tests should not check. " + SAFETY)
    task = (f"Task proposal:\n{json.dumps(proposal, indent=1, sort_keys=True)}\n\nRead the relevant code, then submit instruction.md with exactly these "
            f"sections: {', '.join(REQUIRED_HEADINGS)}. Acceptance criteria are numbered and each is independently "
            "testable. The Interface Contract names the exact files, functions/classes/methods, parameters, return "
            "values and error behaviour.")
    submit = submit_tool("Submit the complete instruction.md.", {"instruction_md": {"type": "string"}}, ["instruction_md"])
    return run_agent(llm, system, task, ws, READ_TOOLS, submit, validate=lambda a: _check_spec(a["instruction_md"]))["instruction_md"]


def implement(llm: LLM, ws: Workspace, instruction: str, feedback: str = "") -> str:
    system = ("You are Agent A, the reference implementer. Implement the specification in the repository's own style. "
              "Change source files only: you cannot edit or add tests, test configuration or build files for tests. "
              "Keep the change focused. You may run the repository's existing tests to check you broke nothing. "
              + SAFETY)
    task = f"Specification (instruction.md):\n\n{instruction}"
    if feedback:
        task += f"\n\nA previous implementation failed these checks. Fix the implementation:\n{feedback}"
    submit = submit_tool("Call when the implementation is complete.", {"notes": {"type": "string"}}, ["notes"])
    run_agent(llm, system, task, ws, [*READ_TOOLS, "write_file", "run"], submit,
              validate=lambda _: None if ws.diff().strip() else "no source change has been made")
    return ws.diff()


def write_tests(llm: LLM, ws: Workspace, instruction: str, guidance: str, feedback: str = "") -> dict[str, str]:
    system = ("You are Agent B, the test writer. Write automated tests for the specification only. You have never "
              "seen any implementation and the feature does not exist yet, so your tests are expected to fail now. "
              "Test every acceptance criterion through the Interface Contract; do not test behaviour the "
              "specification does not state, such as exact wording it does not give. " + SAFETY)
    task = f"Specification (instruction.md):\n\n{instruction}\n\nConventions:\n{guidance}"
    if feedback:
        task += f"\n\nYour previous tests were judged to check something the specification does not require:\n{feedback}"
    submit = submit_tool("Call when the test file is written.", {"notes": {"type": "string"}}, ["notes"])
    run_agent(llm, system, task, ws, [*READ_TOOLS, "write_file", "run"], submit,
              validate=lambda _: None if ws.written else "no test file has been written")
    return dict(ws.written)


def judge(llm: LLM, instruction: str, tests: dict[str, str], patch: str, failures: str) -> dict[str, str]:
    system = ("You review a failed task proof. Decide which artifact is wrong: 'implementation' (the code does not "
              "do what the specification says), 'tests' (a test checks something the specification does not state, "
              "or checks it wrongly), or 'spec' (the specification is ambiguous or contradictory). Judge against the "
              "specification only.")
    task = (f"Specification:\n{instruction}\n\nTests:\n" + "\n\n".join(f"--- {p}\n{c}" for p, c in tests.items())
            + f"\n\nReference patch:\n{patch}\n\nFailures:\n{failures[-8000:]}")
    submit = submit_tool("Submit the verdict.", {
        "verdict": {"type": "string", "enum": ["implementation", "tests", "spec"]},
        "explanation": {"type": "string"}}, ["verdict", "explanation"])
    return run_agent(llm, system, task, Workspace(root=Path(".")), [], submit, max_turns=4)


def blind_solve(llm: LLM, ws: Workspace, instruction: str) -> str:
    """A fresh agent with only the specification: no reference patch, no tests. Returns its diff."""
    system = ("You are solving a coding task in this repository. Implement the specification in the repository's "
              "own style, changing source files only. You may run the repository's existing tests. " + SAFETY)
    submit = submit_tool("Call when your implementation is complete.", {"notes": {"type": "string"}}, ["notes"])
    run_agent(llm, system, f"Task specification:\n\n{instruction}", ws, [*READ_TOOLS, "write_file", "run"], submit,
              validate=lambda _: None if ws.diff().strip() else "no source change has been made")
    return ws.diff()
