"""Measure test strength for an existing task package: plant bugs in the reference patch, count catches.

    python scripts/strength_check.py --task outputs/gold/<task> --repo <checkout> [--python <venv python>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.schemas import ProofMatrix  # noqa: E402
from factory.verifier.proof_runner import local_executor  # noqa: E402
from factory.verifier.strength import check_strength  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--task", type=Path, required=True)
ap.add_argument("--repo", type=Path, required=True)
ap.add_argument("--python", default=None)
ap.add_argument("--max", type=int, default=8)
args = ap.parse_args()
proof = ProofMatrix.model_validate_json((args.task / "evidence" / "proof.json").read_text(encoding="utf-8"))
report = check_strength(args.task, args.repo, proof, local_executor(Path(args.python).parent if args.python else None),
                        args.max)
result = {"total": report.total, "caught": report.caught, "catch_rate": report.catch_rate, "survivors": report.survivors}
(args.task / "evidence" / "strength.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
proof = proof.model_copy(update={"mutants_total": report.total, "mutants_killed": report.caught})
(args.task / "evidence" / "proof.json").write_text(proof.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(result, indent=1))
