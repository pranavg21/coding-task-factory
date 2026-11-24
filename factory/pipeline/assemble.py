"""Assemble one candidate (spec + reference patch + new tests) into a proven task package.

Stages, each of which can reject the candidate:
  1. Baseline   run the untouched repository's suite 3 times -> PASS_TO_PASS (only tests passing every time)
  2. Guard      the reference patch may not touch existing tests or test configuration
  3. New tests  run them on the patched repository -> FAIL_TO_PASS (the new test IDs)
  4. Package    SWE-bench-style folder with tests/run_tests.sh
  5. Prove      the organisers' Conditions 1-3, per test, on 3 fresh runs; any flaky test rejects

Used for hand-built gold tasks today and by the AI generation stage later, so both go through
exactly the same checks.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from factory.adapters.swebench_packager import write_task_package
from factory.onboarding.baseline import Baseline, discover
from factory.sandbox.patch_guard import validate_reference_patch
from factory.schemas import ProofMatrix, TaskMetadata, TaskToml
from factory.verifier.proof_runner import Executor, fresh_copy, prove


@dataclass
class Candidate:
    task_toml: TaskToml
    metadata: TaskMetadata
    instruction_md: str
    patch_diff: str
    test_files: dict[str, str]  # repository-relative path -> content


@dataclass
class Outcome:
    accepted: bool
    stage: str
    reason: str
    task_dir: Path | None
    proof: ProofMatrix | None


def _copy_with_cases(base: Path, into: Path, candidate: Candidate, patched: bool) -> Path:
    patch = None
    if patched:
        patch = into.parent / f"{into.name}.diff"
        patch.write_text(candidate.patch_diff, encoding="utf-8", newline="\n")
    repo = fresh_copy(base, into, patch)
    for rel, content in candidate.test_files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return repo


def new_test_ids(statuses: dict[str, str], candidate: Candidate) -> list[str]:
    """IDs of tests that live in the candidate's new test files (pytest/vitest) or its feature binary."""
    files = {p.replace("\\", "/") for p in candidate.test_files}
    return sorted(tid for tid in statuses if tid.split("::", 1)[0] in files or tid.startswith("feature::"))


def assemble(candidate: Candidate, base_repo: Path, out_dir: Path, baseline: Baseline,
             statuses_of: "callable[[Path], dict[str, str]]", execute: Executor,
             existing_test_paths: list[str]) -> Outcome:
    """Run stages 2-5 for one candidate. `baseline` comes from stage 1, shared by all candidates of a repo."""
    task_id = candidate.task_toml.task_id
    guard = validate_reference_patch(candidate.patch_diff, existing_test_paths=existing_test_paths)
    if not guard.passed:
        return Outcome(False, "patch_guard", "; ".join(guard.violations), None, None)

    with tempfile.TemporaryDirectory(prefix="assemble_") as tmp:
        try:
            patched = _copy_with_cases(base_repo, Path(tmp) / "patched", candidate, patched=True)
        except subprocess.CalledProcessError as exc:
            return Outcome(False, "apply_patch", exc.stderr.strip()[:500], None, None)
        statuses = statuses_of(patched)
    fail_to_pass = new_test_ids(statuses, candidate)
    if not fail_to_pass:
        return Outcome(False, "new_tests", "no new tests were found or run on the patched repository", None, None)

    proof = ProofMatrix(task_id=task_id, PASS_TO_PASS=baseline.pass_to_pass, FAIL_TO_PASS=fail_to_pass,
                        excluded_baseline_tests=sorted(baseline.excluded))
    task_dir = write_task_package(out_dir, candidate.task_toml, candidate.instruction_md, candidate.patch_diff,
                                  candidate.test_files, candidate.metadata, proof)
    proven = prove(task_dir, base_repo, proof, execute, logs_dir=task_dir / "evidence" / "logs")
    (task_dir / "evidence" / "proof.json").write_text(proven.model_dump_json(indent=2) + "\n",
                                                      encoding="utf-8", newline="\n")
    if not proven.all_checks_passed:
        problems = sorted({p for run in proven.runs for p in run.problems})[:10]
        return Outcome(False, "proof", f"flaky={proven.flake_count}; " + "; ".join(problems), task_dir, proven)
    return Outcome(True, "accepted", "passed Conditions 1-3 on all runs", task_dir, proven)


def baseline_for(statuses_of: "callable[[Path], dict[str, str]]", base_repo: Path, runs: int = 3) -> Baseline:
    """Stage 1: run the untouched suite `runs` times on fresh copies and keep only tests passing every time."""
    results = []
    for index in range(runs):
        with tempfile.TemporaryDirectory(prefix=f"baseline{index}_") as tmp:
            empty = Candidate(None, None, "", "", {})  # type: ignore[arg-type]
            results.append(statuses_of(_copy_with_cases(base_repo, Path(tmp) / "repo", empty, patched=False)))
    return discover(results)
