"""A packaged task's own harness must reproduce the organisers' 3-condition matrix on a real checkout.

Builds a tiny repository, packages a task for it, then runs tests/run_tests.sh exactly as a judge would:
1. base repo + PASS_TO_PASS   -> passes
2. patched repo + all tests    -> passes
3. base repo + FAIL_TO_PASS    -> fails
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factory.adapters.swebench_packager import write_task_package
from factory.schemas import (
    ChangePattern, ProofMatrix, ProvenanceRecord, ScopeLevel, TaskMetadata, TaskToml, TaskType, VarietyCell,
)

PRICING = "def subtotal(prices):\n    return sum(prices)\n"
EXISTING_TEST = "from shop.pricing import subtotal\n\n\ndef test_subtotal():\n    assert subtotal([1, 2]) == 3\n"
FEATURE_TEST = (
    "from shop.pricing import apply_percent\n\n\n"
    "def test_percent_off():\n    assert apply_percent(200, 10) == 180\n\n\n"
    "def test_never_negative():\n    assert apply_percent(50, 150) == 0\n"
)
PATCH = (
    "--- a/shop/pricing.py\n+++ b/shop/pricing.py\n@@ -1,2 +1,6 @@\n"
    " def subtotal(prices):\n     return sum(prices)\n+\n+\n"
    "+def apply_percent(amount, pct):\n+    return max(0, amount - amount * pct / 100)\n"
)
F2P = ["tests/test_percent.py::test_percent_off", "tests/test_percent.py::test_never_negative"]
P2P = ["tests/test_pricing.py::test_subtotal"]

needs_tools = pytest.mark.skipif(not (shutil.which("git") and shutil.which("bash")), reason="needs git and bash")


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "shop").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "shop" / "__init__.py").write_text("")
    (repo / "shop" / "pricing.py").write_text(PRICING)
    (repo / "tests" / "test_pricing.py").write_text(EXISTING_TEST)
    return repo


def package(root: Path) -> Path:
    cell = VarietyCell(task_type=TaskType.NEW_FEATURE, change_pattern=ChangePattern.VALIDATION_OR_RULE,
                       scope=ScopeLevel.SINGLE_FUNCTION)
    meta = TaskMetadata(task_id="T-demo", title="Percent discount", variety=cell, difficulty="easy",
                        files_touched=["shop/pricing.py"],
                        provenance=ProvenanceRecord(seed=1, planner_model="m", spec_model="m",
                                                    coder_model="m", tester_model="m"))
    toml = TaskToml(task_id="T-demo", repo_id="mini", repo_source="local", pinned_version="0" * 40,
                    language="python", test_framework="pytest", docker_image="none", test_cmd=["pytest"])
    proof = ProofMatrix(task_id="T-demo", FAIL_TO_PASS=F2P, PASS_TO_PASS=P2P)
    return write_task_package(root / "out", toml, "## Problem Statement\r\nAdd apply_percent.\r\n", PATCH,
                              {"tests/test_percent.py": FEATURE_TEST}, meta, proof)


def run_harness(task_dir: Path, repo: Path, scope: str) -> int:
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(["bash", str(task_dir / "tests" / "run_tests.sh"), str(repo), scope],
                          env=env, capture_output=True, text=True).returncode


def fresh_checkout(root: Path, name: str, patched: bool) -> Path:
    repo = shutil.copytree(make_repo(root / f"src-{name}"), root / name)
    if patched:
        subprocess.run(["git", "apply", str(root / "out" / "T-demo" / "solution" / "patch.diff")],
                       cwd=repo, check=True)
    return repo


@needs_tools
def test_harness_reproduces_the_three_conditions(tmp_path):
    task = package(tmp_path)
    assert run_harness(task, fresh_checkout(tmp_path, "c1", patched=False), "pass_to_pass") == 0
    assert run_harness(task, fresh_checkout(tmp_path, "c2", patched=True), "all") == 0
    assert run_harness(task, fresh_checkout(tmp_path, "c3", patched=False), "fail_to_pass") != 0


@needs_tools
def test_a_missing_pass_to_pass_test_counts_as_failure(tmp_path):
    task = package(tmp_path)
    repo = fresh_checkout(tmp_path, "gone", patched=True)
    (repo / "tests" / "test_pricing.py").unlink()  # as if a patch had hidden the existing test
    assert run_harness(task, repo, "all") != 0


def test_every_packaged_file_uses_lf_and_harness_is_executable(tmp_path):
    task = package(tmp_path)
    for path in task.rglob("*"):
        if path.is_file():
            assert b"\r" not in path.read_bytes(), path
    assert os.access(task / "tests" / "run_tests.sh", os.X_OK)
    assert (task / "tests" / "cases" / "tests" / "test_percent.py").exists()


def test_test_paths_cannot_escape_the_package(tmp_path):
    toml = TaskToml(task_id="x", repo_id="r", repo_source="s", pinned_version="p", language="python",
                    test_framework="pytest", docker_image="i", test_cmd=["pytest"])
    with pytest.raises(ValueError):
        write_task_package(tmp_path, toml, "", PATCH, {"../evil.py": ""}, None, ProofMatrix(task_id="x"))  # type: ignore[arg-type]


@needs_tools
def test_condition_1_leaves_the_base_repository_untouched(tmp_path):
    task = package(tmp_path)
    repo = fresh_checkout(tmp_path, "untouched", patched=False)
    before = sorted(p.relative_to(repo) for p in repo.rglob("*.py"))
    assert run_harness(task, repo, "pass_to_pass") == 0
    assert sorted(p.relative_to(repo) for p in repo.rglob("*.py")) == before


def test_source_date_epoch_fixes_the_timestamp(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1795000000")
    a = TaskToml(task_id="x", repo_id="r", repo_source="s", pinned_version="p", language="python",
                 test_framework="pytest", docker_image="i", test_cmd=["pytest"])
    assert a.created_at == "2026-11-18T11:06:40+00:00"
