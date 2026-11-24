"""The proof runner must judge every test individually, not trust one exit code."""
from pathlib import Path

import pytest

from factory.schemas import ProofMatrix
from factory.verifier.proof_runner import (
    HarnessResult, docker_command, local_executor, parse_statuses, prove,
)
from tests.test_package_harness import F2P, P2P, make_repo, needs_tools, package


def test_parse_statuses_reads_each_test():
    out = (
        "PASSED tests/a.py::test_one\nFAILED tests/a.py::test_two - assert 1 == 2\n"
        "ERROR tests/b.py - ImportError: x\n"
    )
    assert parse_statuses(out) == {"tests/a.py::test_one": "PASSED", "tests/a.py::test_two": "FAILED",
                                   "tests/b.py": "ERROR"}


def test_docker_command_is_offline_and_mounts_the_package_read_only(tmp_path):
    cmd = docker_command("img:1", tmp_path / "task", tmp_path / "repo", "all")
    assert "--network=none" in cmd and f"{(tmp_path / 'task').resolve()}:/task:ro" in cmd


def fake_executor(by_scope):
    """Pretend harness: returns fixed statuses per scope, for logic tests without bash or pytest."""
    def run(task_dir, repo_dir, scope):
        statuses = by_scope[scope] if not callable(by_scope[scope]) else by_scope[scope]()
        return HarnessResult(1, "", statuses)
    return run


def proof_with(tmp_path, by_scope, runs=3):
    repo = make_repo(tmp_path / "base")
    task = package(tmp_path)
    return prove(task, repo, ProofMatrix(task_id="T-demo", FAIL_TO_PASS=F2P, PASS_TO_PASS=P2P),
                 fake_executor(by_scope), runs=runs)


GOOD = {
    "pass_to_pass": {P2P[0]: "PASSED"},
    "all": {P2P[0]: "PASSED", F2P[0]: "PASSED", F2P[1]: "PASSED"},
    "fail_to_pass": {F2P[0]: "FAILED", F2P[1]: "FAILED"},
}


def test_all_conditions_met(tmp_path):
    result = proof_with(tmp_path, GOOD)
    assert result.all_checks_passed and result.flake_count == 0


def test_one_new_test_passing_without_the_feature_fails_condition_3(tmp_path):
    weak = {**GOOD, "fail_to_pass": {F2P[0]: "FAILED", F2P[1]: "PASSED"}}
    result = proof_with(tmp_path, weak)
    assert not result.all_checks_passed
    assert any("passed without the feature" in p for p in result.runs[0].problems)


def test_a_test_that_did_not_run_fails_condition_2(tmp_path):
    missing = {**GOOD, "all": {F2P[0]: "PASSED", F2P[1]: "PASSED"}}
    result = proof_with(tmp_path, missing)
    assert not result.runs[0].check2_patched_all_pass
    assert any("did not run" in p for p in result.runs[0].problems)


def test_changing_results_between_runs_are_flakes(tmp_path):
    flips = iter(["PASSED", "FAILED", "PASSED"])
    flaky = {**GOOD, "pass_to_pass": lambda: {P2P[0]: next(flips)}}
    result = proof_with(tmp_path, flaky)
    assert result.flake_count == 1 and not result.all_checks_passed


@needs_tools
def test_real_harness_end_to_end(tmp_path):
    import sys
    repo = make_repo(tmp_path / "base")
    task = package(tmp_path)
    result = prove(task, repo, ProofMatrix(task_id="T-demo", FAIL_TO_PASS=F2P, PASS_TO_PASS=P2P),
                   local_executor(Path(sys.executable).parent), logs_dir=tmp_path / "logs")
    assert result.all_checks_passed, [r.problems for r in result.runs]
    assert len(list((tmp_path / "logs").glob("*.log.gz"))) == 9


def test_ids_with_spaces_and_failure_messages_are_parsed_whole():
    out = (
        "PASSED tests/a.py::test_x[2-a b-expect2]\n"
        "FAILED tests/a.py::test_x[2-a b c-msg] - AssertionError: a - b\n"
        "FAILED tests/b.py::test_plain - boom\n"
        "PASSED packages/z.test.ts::z.string() - email > rejects bad input\n"
        "SKIPPED [1] tests/c.py:3: no reason\n"
    )
    got = parse_statuses(out)
    assert got["tests/a.py::test_x[2-a b-expect2]"] == "PASSED"
    assert got["tests/a.py::test_x[2-a b c-msg]"] == "FAILED"
    assert got["tests/b.py::test_plain"] == "FAILED"
    assert got["packages/z.test.ts::z.string() - email > rejects bad input"] == "PASSED"
    assert len(got) == 4


def test_known_ids_resolve_failure_lines_exactly():
    known = ["packages/z.test.ts::a - b"]
    assert parse_statuses("FAILED packages/z.test.ts::a - b\n", known) == {"packages/z.test.ts::a - b": "FAILED"}


def test_trailing_spaces_in_test_names_are_kept():
    tid = "packages/zod/src/v3/tests/set.test.ts::failing when parsing empty set in nonempty "
    assert parse_statuses(f"PASSED {tid}\n", [tid]) == {tid: "PASSED"}
