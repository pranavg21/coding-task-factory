"""Run one hand-built gold task through the factory's own assemble-and-prove pipeline.

Gold tasks are written by people as a calibration reference (see gold/README.md); they are not
counted as factory output. Usage:

    python scripts/build_gold_task.py --gold gold/click-duration --repo <checkout> --out outputs/gold [--python <venv python>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.onboarding.baseline import jsontest_statuses, pytest_statuses, vitest_statuses  # noqa: E402
from factory.pipeline.assemble import Candidate, assemble, baseline_for  # noqa: E402
from factory.schemas import ProvenanceRecord, TaskMetadata, TaskToml, VarietyCell  # noqa: E402
from factory.verifier.proof_runner import local_executor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--python", default=sys.executable, help="Python with the repository installed (pytest repos)")
    args = ap.parse_args()

    spec = json.loads((args.gold / "gold.json").read_text(encoding="utf-8"))
    tests = {p.relative_to(args.gold / "cases").as_posix(): p.read_text(encoding="utf-8")
             for p in sorted((args.gold / "cases").rglob("*"))
             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    framework = spec["test_framework"]
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=args.repo, capture_output=True, text=True).stdout.strip()
    if sha != spec["pinned_version"]:
        print(f"Repository is at {sha}, but the task is pinned to {spec['pinned_version']}", file=sys.stderr)
        return 2

    if framework == "pytest":
        statuses_of = partial(pytest_statuses, python=args.python)
    elif framework == "vitest":
        statuses_of = partial(vitest_statuses, project=spec.get("test_project", ""))
    else:
        sources = [p for p in tests if p.endswith(".cpp")]
        statuses_of = lambda repo: jsontest_statuses(repo, sources)  # noqa: E731
    baseline_statuses = (lambda repo: jsontest_statuses(repo)) if framework == "jsontest" else statuses_of

    started = time.monotonic()
    baseline = baseline_for(baseline_statuses, args.repo)
    print(f"baseline: {len(baseline.pass_to_pass)} PASS_TO_PASS, {len(baseline.excluded)} excluded "
          f"({time.monotonic() - started:.0f}s)")
    toml = TaskToml(task_id=spec["task_id"], repo_id=spec["repo_id"], repo_source=spec["repo_source"],
                    pinned_version=spec["pinned_version"], language=spec["language"], test_framework=framework,
                    docker_image=spec["docker_image"], test_cmd=spec["test_cmd"],
                    test_project=spec.get("test_project", ""))
    meta = TaskMetadata(task_id=spec["task_id"], title=spec["title"], variety=VarietyCell(**spec["variety"]),
                        difficulty=spec["difficulty"], files_touched=spec["files_touched"],
                        provenance=ProvenanceRecord(seed=0, planner_model="human (gold)", spec_model="human (gold)",
                                                    coder_model="human (gold)", tester_model="human (gold)"))
    candidate = Candidate(toml, meta, (args.gold / "instruction.md").read_text(encoding="utf-8"),
                          (args.gold / "solution.patch").read_text(encoding="utf-8"), tests)
    python_dir = Path(args.python).parent if framework == "pytest" else None
    existing = [tid.split("::", 1)[0] for tid in baseline.pass_to_pass]
    outcome = assemble(candidate, args.repo, args.out, baseline, statuses_of, local_executor(python_dir), existing)
    print(f"{'ACCEPTED' if outcome.accepted else 'REJECTED'} at {outcome.stage}: {outcome.reason}")
    if outcome.proof:
        print(f"FAIL_TO_PASS={len(outcome.proof.FAIL_TO_PASS)} PASS_TO_PASS={len(outcome.proof.PASS_TO_PASS)} "
              f"flaky={outcome.proof.flake_count} total {time.monotonic() - started:.0f}s")
    return 0 if outcome.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
