"""Blind solve: can an independent agent solve the task from instruction.md alone?

The solver never sees the reference patch or the tests. Its patch is applied to a fresh copy and the
task's own harness runs every test (Condition 2 with the solver's code instead of the reference).
- Solved: the specification is sufficient and the tests do not depend on one particular implementation.
- Not solved: the judge decides whether the solver erred (a hard but valid task) or the tests or
  specification are at fault (the task is rejected).
Difficulty comes from the pass rate over the attempts: all passed -> easy, some -> medium, none -> hard.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from factory.agents import roles
from factory.agents.llm import LLM
from factory.agents.loop import AgentFailedError
from factory.agents.workspace import Workspace
from factory.schemas import ProofMatrix
from factory.stacks import Stack, implementer_can_write
from factory.verifier.proof_runner import Executor, fresh_copy, parse_statuses


@dataclass
class BlindResult:
    attempts: int
    solved: int
    diagnosis: str  # solved | agent_error | spec_problem
    difficulty: str  # easy | medium | hard
    detail: str = ""


def blind_solve(task_dir: Path, base: Path, proof: ProofMatrix, stack: Stack, execute: Executor, llm: LLM,
                attempts: int = 1) -> BlindResult:
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    solved, last_failure, last_patch = 0, "", ""
    ids = proof.PASS_TO_PASS + proof.FAIL_TO_PASS
    for attempt in range(attempts):
        with tempfile.TemporaryDirectory(prefix="blind_") as tmp:
            ws = Workspace(root=fresh_copy(base, Path(tmp) / "solver", None), can_write=implementer_can_write,
                           run_tests=stack.run_for_agent)
            ws.snapshot()
            try:
                patch = roles.blind_solve(llm, ws, instruction)
            except AgentFailedError as exc:
                last_failure = f"solver gave up: {exc}"
                continue
            patch_file = Path(tmp) / "solver.diff"
            patch_file.write_text(patch, encoding="utf-8", newline="\n")
            try:
                repo = fresh_copy(base, Path(tmp) / f"check{attempt}", patch_file)
            except Exception as exc:  # noqa: BLE001 - an unappliable patch is the solver's failure
                last_failure = f"solver patch did not apply: {exc}"
                continue
            result = execute(task_dir, repo, "all")
        statuses = parse_statuses(result.output, ids) if result.output else result.statuses
        bad = [f"{tid} ({statuses.get(tid, 'did not run')})" for tid in ids if statuses.get(tid) != "PASSED"]
        if not bad:
            solved += 1
        else:
            last_failure, last_patch = "\n".join(bad[:40]), patch
    difficulty = "easy" if solved == attempts else ("medium" if solved else "hard")
    if solved:
        return BlindResult(attempts, solved, "solved", difficulty)
    tests = {p.relative_to(task_dir / "tests" / "cases").as_posix(): p.read_text(encoding="utf-8")
             for p in sorted((task_dir / "tests" / "cases").rglob("*")) if p.is_file()}
    verdict = roles.judge(llm, instruction, tests, last_patch or "(no usable patch)", last_failure)
    diagnosis = "agent_error" if verdict["verdict"] == "implementation" else "spec_problem"
    return BlindResult(attempts, 0, diagnosis, "hard", verdict["explanation"])
