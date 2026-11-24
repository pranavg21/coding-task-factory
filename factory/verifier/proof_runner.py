"""The organisers' 3-condition proof, judged test by test and repeated to catch flaky tests.

For each run, on a fresh copy of the base repository (git history removed):

    Condition 1 (Baseline Pass):        untouched repo, every PASS_TO_PASS test passes
    Condition 2 (Solution Pass):        patch applied, every PASS_TO_PASS and FAIL_TO_PASS test passes
    Condition 3 (Feature Failure):      untouched repo + new tests, every FAIL_TO_PASS test fails

Exit codes are not trusted on their own: pytest exits non-zero if one of five new tests fails, which
would hide four tests that already pass without the feature. Each test ID's status is read from the
harness output instead, and a test that never ran counts as not passing.

Execution goes through an Executor, so the same proof runs locally or in an offline Docker container.
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from factory.schemas import ProofMatrix, ProofRunRecord

STATUS_LINE = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS) (.+)$")
RUNS = 3


@dataclass
class HarnessResult:
    returncode: int
    output: str
    statuses: dict[str, str] = field(default_factory=dict)


# (task_dir, repo_dir, scope) -> HarnessResult. Swap in a Docker executor without touching the logic.
Executor = Callable[[Path, Path, str], HarnessResult]


def _strip_message(rest: str) -> str:
    """pytest appends " - <message>" to failures. Keep a parametrised ID's brackets intact."""
    if "[" in rest and rest.index("[") < (rest.find(" - ") if " - " in rest else len(rest)):
        depth = 0
        for i, ch in enumerate(rest[rest.index("["):], start=rest.index("[")):
            depth += ch == "["
            depth -= ch == "]"
            if depth == 0:
                return rest[: i + 1]
    return rest.split(" - ", 1)[0]


def parse_statuses(output: str, known: list[str] | None = None) -> dict[str, str]:
    """Test ID -> PASSED/FAILED/ERROR from the harness's normalised lines.

    IDs may contain spaces (parametrised pytest IDs, Vitest test names), so the whole rest of the line
    is used. When the expected IDs are known, a failure line is matched to the longest expected ID it
    starts with, which removes any doubt about where an appended message begins.
    """
    known_set = set(known or [])
    statuses: dict[str, str] = {}
    for line in output.splitlines():
        # Keep the ID exactly: some test names end in a space.
        match = STATUS_LINE.match(line.lstrip().rstrip("\r\n"))
        if not match:
            continue
        status, rest = match.groups()
        if rest in known_set:
            tid = rest
        elif known_set:
            hits = [k for k in known_set if rest.startswith(k + " - ")]
            tid = max(hits, key=len) if hits else _strip_message(rest)
        else:
            tid = rest if status in ("PASSED", "XPASS") else _strip_message(rest)
        statuses[tid] = status
    return statuses


def local_executor(python_bin_dir: Path | None = None) -> Executor:
    """Run the package's own harness with bash on this machine."""

    def run(task_dir: Path, repo_dir: Path, scope: str) -> HarnessResult:
        env = None
        if python_bin_dir is not None:
            env = {**os.environ, "PATH": f"{python_bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        proc = subprocess.run(
            ["bash", str(task_dir / "tests" / "run_tests.sh"), str(repo_dir), scope],
            capture_output=True, text=True, env=env, timeout=900,
        )
        output = proc.stdout + proc.stderr
        return HarnessResult(proc.returncode, output, parse_statuses(output))

    return run


def docker_command(image: str, task_dir: Path, repo_dir: Path, scope: str) -> list[str]:
    """The offline container invocation: no network, resource caps, package mounted read-only."""
    return [
        "docker", "run", "--rm", "--network=none", "--cpus=2", "--memory=2g",
        "-v", f"{repo_dir.resolve()}:/repo",
        "-v", f"{task_dir.resolve()}:/task:ro",
        "-w", "/repo", image,
        "bash", "/task/tests/run_tests.sh", "/repo", scope,
    ]


def docker_executor(image: str) -> Executor:
    """Run the harness inside the task's Docker image. Dependencies must already be installed in the image."""

    def run(task_dir: Path, repo_dir: Path, scope: str) -> HarnessResult:
        proc = subprocess.run(docker_command(image, task_dir, repo_dir, scope),
                              capture_output=True, text=True, timeout=900)
        output = proc.stdout + proc.stderr
        return HarnessResult(proc.returncode, output, parse_statuses(output))

    return run


# Installed dependencies are linked, not copied: zod's node_modules alone is over 1 GB. They are
# read-only inputs prepared when the environment was built, never part of a task's change.
LINKED_DIRS = ("node_modules",)


def fresh_copy(base_repo: Path, into: Path, patch: Path | None) -> Path:
    """Copy the repository without .git, linking dependency folders, and optionally apply a patch."""
    repo = Path(shutil.copytree(base_repo, into, symlinks=True,
                                ignore=shutil.ignore_patterns(".git", *LINKED_DIRS)))
    for dirpath, dirnames, _ in os.walk(base_repo):
        for name in [d for d in dirnames if d in LINKED_DIRS or d == ".git"]:
            dirnames.remove(name)  # never walk into dependency trees
            if name in LINKED_DIRS:
                source = Path(dirpath) / name
                target = repo / source.relative_to(base_repo)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(source.resolve(), target_is_directory=True)
    if patch is not None:
        subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch.resolve())],
                       cwd=repo, check=True, capture_output=True, text=True)
    return repo


def _not_passed(ids: list[str], statuses: dict[str, str]) -> list[str]:
    return [f"{tid} ({statuses.get(tid, 'did not run')})" for tid in ids if statuses.get(tid) != "PASSED"]


def _passed(ids: list[str], statuses: dict[str, str]) -> list[str]:
    return [f"{tid} (passed without the feature)" for tid in ids if statuses.get(tid) == "PASSED"]


def run_once(task_dir: Path, base_repo: Path, proof: ProofMatrix, execute: Executor,
             run_index: int, logs_dir: Path | None = None) -> tuple[ProofRunRecord, dict[str, dict[str, str]]]:
    """One pass of all three conditions, each on its own fresh copy of the base repository."""
    started = time.monotonic()
    patch = task_dir / "solution" / "patch.diff"
    with tempfile.TemporaryDirectory(prefix="proof_") as tmp:
        root = Path(tmp)
        c1 = execute(task_dir, fresh_copy(base_repo, root / "c1", None), "pass_to_pass")
        c2 = execute(task_dir, fresh_copy(base_repo, root / "c2", patch), "all")
        c3 = execute(task_dir, fresh_copy(base_repo, root / "c3", None), "fail_to_pass")
    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        for name, result in (("condition1", c1), ("condition2", c2), ("condition3", c3)):
            # Compressed: a full Zod run lists every one of its ~5,500 tests.
            with gzip.open(logs_dir / f"run{run_index}_{name}.log.gz", "wt", encoding="utf-8", newline="\n") as log:
                log.write(result.output)
    known = proof.PASS_TO_PASS + proof.FAIL_TO_PASS
    for result in (c1, c2, c3):
        if result.output:
            result.statuses = parse_statuses(result.output, known)
    c1_bad = _not_passed(proof.PASS_TO_PASS, c1.statuses)
    c2_bad = _not_passed(proof.PASS_TO_PASS + proof.FAIL_TO_PASS, c2.statuses)
    c3_bad = _passed(proof.FAIL_TO_PASS, c3.statuses)
    record = ProofRunRecord(
        run_index=run_index,
        check1_baseline_pass=bool(proof.PASS_TO_PASS) and not c1_bad,
        check2_patched_all_pass=not c2_bad,
        check3_unpatched_new_fail=bool(proof.FAIL_TO_PASS) and not c3_bad,
        duration_sec=round(time.monotonic() - started, 2),
        problems=[f"Condition 1: {p}" for p in c1_bad] + [f"Condition 2: {p}" for p in c2_bad]
        + [f"Condition 3: {p}" for p in c3_bad],
    )
    return record, {"c1": c1.statuses, "c2": c2.statuses, "c3": c3.statuses}


def prove(task_dir: Path, base_repo: Path, proof: ProofMatrix, execute: Executor,
          runs: int = RUNS, logs_dir: Path | None = None) -> ProofMatrix:
    """Run the 3-condition proof `runs` times. A test whose status differs between runs is a flake."""
    records, seen = [], []
    for index in range(1, runs + 1):
        record, statuses = run_once(task_dir, base_repo, proof, execute, index, logs_dir)
        records.append(record)
        seen.append(statuses)
    flaky = set()
    for condition in ("c1", "c2", "c3"):
        ids = set().union(*(s[condition] for s in seen))
        flaky |= {(condition, tid) for tid in ids if len({s[condition].get(tid) for s in seen}) > 1}
    return proof.model_copy(update={"runs": records, "flake_count": len(flaky)})
