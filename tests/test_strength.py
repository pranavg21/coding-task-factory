"""Test strength on the small sample repository: strong tests catch mutants, weak ones do not."""
import sys
from pathlib import Path

from factory.schemas import ProofMatrix
from factory.verifier.proof_runner import local_executor
from factory.verifier.strength import check_strength
from tests.test_package_harness import F2P, P2P, make_repo, needs_tools, package

PY = Path(sys.executable).parent


@needs_tools
def test_mutants_of_the_reference_are_caught(tmp_path):
    repo = make_repo(tmp_path / "base")
    task = package(tmp_path)
    report = check_strength(task, repo, ProofMatrix(task_id="T-demo", FAIL_TO_PASS=F2P, PASS_TO_PASS=P2P),
                            local_executor(PY))
    assert report.total >= 1
    assert report.caught == report.total, report.survivors
