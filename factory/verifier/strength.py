"""Test strength: do the new tests catch a broken implementation?

Each mutant is the reference patch with one small change to an added line (for example `>=` -> `>`,
`True` -> `False`). The mutated patch is applied to a fresh copy of the base repository and the new
tests (FAIL_TO_PASS) are run. A mutant is caught if any new test does not pass. Surviving mutants are
reported with the exact line changed, because some are equivalent (they do not change behaviour) and a
person or a later stage should judge them rather than the score hiding them.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from factory.schemas import ProofMatrix
from factory.verifier.diff_mutator import generate_diff_mutants
from factory.verifier.proof_runner import Executor, fresh_copy, parse_statuses


@dataclass
class StrengthReport:
    total: int = 0
    caught: int = 0
    survivors: list[str] = field(default_factory=list)  # "rule: original -> mutated"

    @property
    def catch_rate(self) -> float:
        return round(self.caught / self.total, 4) if self.total else 0.0


def check_strength(task_dir: Path, base_repo: Path, proof: ProofMatrix, execute: Executor,
                   max_mutants: int = 8) -> StrengthReport:
    patch_text = (task_dir / "solution" / "patch.diff").read_text(encoding="utf-8")
    report = StrengthReport()
    for mutant in generate_diff_mutants(patch_text, max_mutants=max_mutants):
        with tempfile.TemporaryDirectory(prefix="mutant_") as tmp:
            patch = Path(tmp) / "mutant.diff"
            patch.write_text(mutant.mutated_diff, encoding="utf-8", newline="\n")
            try:
                repo = fresh_copy(base_repo, Path(tmp) / "repo", patch)
            except Exception:  # noqa: BLE001 - a mutant that no longer applies is not a test result
                continue
            result = execute(task_dir, repo, "fail_to_pass")
        statuses = parse_statuses(result.output, proof.FAIL_TO_PASS) if result.output else result.statuses
        report.total += 1
        if any(statuses.get(tid) != "PASSED" for tid in proof.FAIL_TO_PASS):
            report.caught += 1
        else:
            report.survivors.append(f"{mutant.rule_name}: {mutant.original_line} -> {mutant.mutated_line}")
    return report
