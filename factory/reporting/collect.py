"""Collect everything the report shows from the output folders, so no number is typed by hand."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def collect(outputs: Path) -> dict[str, Any]:
    tasks, funnel, runs = [], [], []
    for proof_path in sorted(outputs.rglob("evidence/proof.json")):
        task_dir = proof_path.parents[1]
        proof, meta = _read(proof_path), _read(task_dir / "metadata.json") or {}
        toml = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        strength = _read(task_dir / "evidence" / "strength.json")
        runs_ok = [r["check1_baseline_pass"] and r["check2_patched_all_pass"] and r["check3_unpatched_new_fail"]
                   for r in proof.get("runs", [])]
        tasks.append({
            "task_id": proof["task_id"], "title": meta.get("title", ""), "repo_id": toml["repo_id"],
            "pinned": toml["pinned_version"][:7], "framework": toml["test_framework"],
            "variety": meta.get("variety", {}), "gold": "human (gold)" in json.dumps(meta.get("provenance", {})),
            "fail_to_pass": len(proof.get("FAIL_TO_PASS", [])), "pass_to_pass": len(proof.get("PASS_TO_PASS", [])),
            "runs_passed": sum(runs_ok), "runs": len(runs_ok), "flaky": proof.get("flake_count", 0),
            "accepted": bool(runs_ok) and all(runs_ok) and len(runs_ok) == 3 and proof.get("flake_count", 0) == 0,
            "mutants": strength["total"] if strength else None, "caught": strength["caught"] if strength else None,
            "survivors": strength["survivors"] if strength else [],
            "cost_usd": meta.get("provenance", {}).get("estimated_cost_usd", 0.0),
        })
    for path in sorted(outputs.rglob("funnel.json")):
        funnel += _read(path) or []
    for path in sorted(outputs.rglob("run.json")):
        runs.append(_read(path))
    return {"tasks": tasks, "funnel": funnel, "runs": runs}
