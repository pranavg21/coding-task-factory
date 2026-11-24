"""Stage 1 baseline: which existing tests pass reliably on the untouched repository.

The full suite runs `runs` times. Tests that pass every time become PASS_TO_PASS. Tests that fail,
error or change result between runs are excluded and reported, so Condition 1 ("the unmodified base
repository passes all existing tests") is checked against tests that genuinely pass before any change.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from factory.verifier.proof_runner import parse_statuses


@dataclass
class Baseline:
    pass_to_pass: list[str]
    excluded: dict[str, str] = field(default_factory=dict)  # test id -> why it was left out


def _run(cmd: list[str], cwd: Path, timeout: int = 1800, env: dict[str, str] | None = None
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def pytest_statuses(repo: Path, python: str = "python") -> dict[str, str]:
    # Same rule as the harness: this checkout's code wins over an installed copy.
    env = {**os.environ, "PYTHONPATH": f"{repo / 'src'}{os.pathsep}{repo}"}
    proc = _run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA", "--tb=no"], repo, env=env)
    return parse_statuses(proc.stdout + proc.stderr)


def vitest_statuses(repo: Path, project: str) -> dict[str, str]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        report = Path(handle.name)
    _run(["node_modules/.bin/vitest", "run", "--project", project, "--reporter=json", f"--outputFile={report}"], repo)
    statuses: dict[str, str] = {}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return statuses
    finally:
        report.unlink(missing_ok=True)
    for file in data.get("testResults", []):
        rel = Path(file["name"]).resolve().relative_to(repo.resolve()).as_posix()
        for test in file.get("assertionResults", []):
            status = {"passed": "PASSED", "failed": "FAILED"}.get(test["status"], "SKIPPED")
            statuses[f"{rel}::{test['fullName']}"] = status
    return statuses


def jsontest_statuses(repo: Path, feature_sources: list[str] | None = None) -> dict[str, str]:
    """Build jsoncpp, run every existing unit test by name, and the task's feature tests if given."""
    build = repo / "build-factory"
    configure = ["cmake", "-S", str(repo), "-B", str(build), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                 "-DJSONCPP_WITH_POST_BUILD_UNITTEST=OFF", "-DJSONCPP_WITH_PKGCONFIG_SUPPORT=OFF",
                 "-DBUILD_SHARED_LIBS=OFF"]
    if _run(configure, repo).returncode or _run(["ninja", "-C", str(build)], repo).returncode:
        return {}
    statuses: dict[str, str] = {}
    binaries = [("jsoncpp_test", build / "bin" / "jsoncpp_test")]
    if feature_sources:
        feature = build / "feature_test"
        compiled = _run(["g++", "-std=c++17", "-O1", "-I", "include", "-I", "src/test_lib_json", *feature_sources,
                         "src/test_lib_json/jsontest.cpp", str(build / "lib" / "libjsoncpp.a"), "-o", str(feature)],
                        repo)
        if compiled.returncode == 0:
            binaries.append(("feature", feature))
    for label, exe in binaries:
        for name in _run([str(exe), "--list-tests"], repo).stdout.split():
            ok = _run([str(exe), "--test", name], repo).returncode == 0
            statuses[f"{label}::{name}"] = "PASSED" if ok else "FAILED"
    return statuses


def discover(statuses_per_run: list[dict[str, str]]) -> Baseline:
    """PASS_TO_PASS = tests that passed in every run; everything else is excluded with a reason."""
    ids = set().union(*statuses_per_run) if statuses_per_run else set()
    keep, excluded = [], {}
    for tid in sorted(ids):
        seen = [run.get(tid, "did not run") for run in statuses_per_run]
        if all(s == "PASSED" for s in seen):
            keep.append(tid)
        elif len(set(seen)) > 1:
            excluded[tid] = "flaky: " + ", ".join(seen)
        else:
            excluded[tid] = seen[0].lower()
    return Baseline(keep, excluded)
