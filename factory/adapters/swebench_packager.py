"""Swappable format adapter exporting SWE-bench-style task packages.

Layout (confirmed by the organisers: instruction.md, task.toml, solution/ diff, tests/ with harness and cases):

    <task_id>/
      task.toml  instruction.md  metadata.json
      solution/patch.diff
      tests/run_tests.sh   tests/cases/<repo-relative test files>
      evidence/proof.json

Every file is written with LF line endings and UTF-8, so packages built on Windows still apply with
`git apply` and run under bash inside Linux containers.
"""
from __future__ import annotations

import stat
from pathlib import Path

import tomli_w

from factory.adapters.harness import render_run_tests_sh
from factory.schemas import ProofMatrix, TaskMetadata, TaskToml


def write_lf(path: Path, text: str) -> None:
    """Write UTF-8 text with LF endings only, whatever the host OS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text.replace("\r\n", "\n").replace("\r", "\n"))


def write_task_package(
    output_dir: Path,
    task_toml: TaskToml,
    instruction_md: str,
    patch_diff: str,
    test_files: dict[str, str],
    metadata: TaskMetadata,
    proof: ProofMatrix,
) -> Path:
    """Write one task package. `test_files` maps repository-relative paths to file contents."""
    task_dir = output_dir / task_toml.task_id
    write_lf(task_dir / "task.toml", tomli_w.dumps(task_toml.model_dump()))
    write_lf(task_dir / "instruction.md", instruction_md)
    write_lf(task_dir / "solution" / "patch.diff", patch_diff)
    for rel_name, content in test_files.items():
        rel = Path(rel_name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Test file path must stay inside the repository: {rel_name}")
        write_lf(task_dir / "tests" / "cases" / rel, content)
    harness = task_dir / "tests" / "run_tests.sh"
    write_lf(harness, render_run_tests_sh(task_toml.test_framework, proof.FAIL_TO_PASS, proof.PASS_TO_PASS,
                                           task_toml.test_project))
    harness.chmod(harness.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    write_lf(task_dir / "metadata.json", metadata.model_dump_json(indent=2) + "\n")
    write_lf(task_dir / "evidence" / "proof.json", proof.model_dump_json(indent=2) + "\n")
    return task_dir
