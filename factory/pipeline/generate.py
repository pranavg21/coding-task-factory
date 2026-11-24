"""The factory: from one repository to accepted, proven task packages.

    1. Baseline        once per repository (3 untouched runs -> PASS_TO_PASS)
    2. Variety cells   chosen deterministically from the seed, spreading across task type x pattern x scope
    3. Plan            one proposal per cell; near-duplicates of earlier tasks are rejected before any spend
    4. Spec            instruction.md with an exact interface contract
    5. Agents A and B  reference patch and tests, written in separate copies of the repository
    6. Assemble        patch guard, new-test discovery, packaging, Conditions 1-3 on 3 fresh runs
    7. Revise          after a failed proof, a judge decides whether code, tests or spec is wrong (max 2 rounds)
    8. Strength        mutants of the reference patch must fail the new tests (reported, not hidden)
    9. Blind solve     an agent with only instruction.md must solve it, or the failure must be the agent's

Every candidate ends in funnel.json as accepted or rejected with the stage and reason.
"""
from __future__ import annotations

import itertools
import json
import random
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from factory.agents import roles
from factory.agents.llm import LLM
from factory.agents.loop import AgentFailedError
from factory.agents.workspace import Workspace
from factory.onboarding.baseline import Baseline
from factory.pipeline.assemble import Candidate, assemble, baseline_for
from factory.sandbox.patch_guard import extract_diff_files
from factory.schemas import (ChangePattern, FunnelEvent, ProvenanceRecord, ScopeLevel, TaskMetadata, TaskToml,
                             TaskType, VarietyCell)
from factory.stacks import Stack, implementer_can_write
from factory.verifier.proof_runner import Executor, fresh_copy
from factory.verifier.blind_solve import blind_solve
from factory.verifier.strength import check_strength
from factory.verifier.variety_scorer import check_candidate_uniqueness


@dataclass
class RepoContext:
    repo_id: str
    repo_source: str
    base: Path
    pinned_version: str
    language: str
    stack: Stack
    executor: Executor
    docker_image: str = ""
    test_cmd: tuple[str, ...] = ()
    test_project: str = ""


def pick_cells(n: int, seed: int, used: list[VarietyCell]) -> list[VarietyCell]:
    """n distinct cells, spreading over change patterns first, then task types and scopes; reproducible."""
    grid = [VarietyCell(task_type=t, change_pattern=p, scope=s)
            for t, p, s in itertools.product(TaskType, ChangePattern, ScopeLevel)]
    rng = random.Random(seed)
    rng.shuffle(grid)
    remaining = [c for c in grid if c not in used]
    chosen: list[VarietyCell] = []
    while len(chosen) < n and remaining:
        seen_patterns = {c.change_pattern for c in used + chosen}
        seen_types = {c.task_type for c in used + chosen}
        remaining.sort(key=lambda c: (c.change_pattern in seen_patterns, c.task_type in seen_types))
        chosen.append(remaining.pop(0))
    return chosen


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _workspace(ctx: RepoContext, tmp: Path, name: str, **kwargs) -> Workspace:
    return Workspace(root=fresh_copy(ctx.base, tmp / name, None), **kwargs)


def _failures(outcome) -> str:
    return "\n".join(sorted({p for run in outcome.proof.runs for p in run.problems})) if outcome.proof else outcome.reason


def generate(ctx: RepoContext, n: int, seed: int, llm: LLM, out_dir: Path, max_revisions: int = 2,
             existing: list[str] | None = None, max_mutants: int = 6, blind_attempts: int = 1) -> list[FunnelEvent]:
    out = out_dir / ctx.repo_id
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # On the untouched repository there are no feature tests, so the stack's statuses are the baseline.
    baseline: Baseline = baseline_for(ctx.stack.statuses, ctx.base)
    existing_tests = sorted({tid.split("::", 1)[0] for tid in baseline.pass_to_pass})
    funnel: list[FunnelEvent] = []
    accepted_specs: list[str] = list(existing or [])
    accepted_files: list[list[str]] = [[] for _ in accepted_specs]
    used: list[VarietyCell] = []
    attempts = 0

    def record(event: FunnelEvent) -> None:
        funnel.append(event)
        (out / "funnel.json").write_text(json.dumps([e.model_dump(mode="json") for e in funnel], indent=1) + "\n",
                                         encoding="utf-8", newline="\n")

    while sum(e.status == "accepted" for e in funnel) < n and attempts < 2 * n:
        cells = pick_cells(min(3, n), seed + attempts, used)
        if not cells:
            break
        used += cells
        with tempfile.TemporaryDirectory(prefix="plan_") as tmp:
            try:
                proposals = roles.plan(llm, _workspace(ctx, Path(tmp), "repo"), cells, ctx.repo_id,
                                       accepted_specs[-20:])
            except AgentFailedError as exc:
                record(FunnelEvent(candidate_id=f"plan-{attempts}", title="(planning)", variety=cells[0],
                                   final_stage="plan", status="rejected", rejection_reason=str(exc)))
                attempts += len(cells)
                continue
        for cell, proposal in zip(cells, proposals):
            attempts += 1
            spent = llm.usage.cost_usd
            task_id = f"{ctx.repo_id}-{slug(proposal['title'])}"
            event = dict(candidate_id=task_id, title=proposal["title"], variety=cell)
            dedup = check_candidate_uniqueness(proposal["summary"], proposal.get("files", []), accepted_specs,
                                               accepted_files)
            if dedup.is_duplicate:
                record(FunnelEvent(**event, final_stage="dedup", status="rejected", rejection_reason=dedup.reason))
                continue
            outcome, reason = None, ""
            try:
                with tempfile.TemporaryDirectory(prefix="gen_") as tmp:
                    tmp_path = Path(tmp)
                    spec = roles.write_spec(llm, _workspace(ctx, tmp_path, "spec"), proposal)
                    patch, tests, code_feedback, test_feedback = "", {}, "", ""
                    for round_no in range(max_revisions + 1):
                        if not patch or code_feedback:
                            ws_a = _workspace(ctx, tmp_path, f"a{round_no}", can_write=implementer_can_write,
                                              run_tests=ctx.stack.run_for_agent)
                            ws_a.snapshot()
                            patch = roles.implement(llm, ws_a, spec, code_feedback)
                        if not tests or test_feedback:
                            ws_b = _workspace(ctx, tmp_path, f"b{round_no}",
                                              can_write=lambda rel: ctx.stack.is_new_test_path(rel, ctx.base),
                                              run_tests=ctx.stack.run_for_agent)
                            tests = roles.write_tests(llm, ws_b, spec, ctx.stack.test_guidance, test_feedback)
                        code_feedback = test_feedback = ""
                        candidate = _candidate(ctx, task_id, proposal, cell, spec, patch, tests, seed, llm, round_no)
                        outcome = assemble(candidate, ctx.base, out, baseline, ctx.stack.statuses, ctx.executor,
                                           existing_tests)
                        if outcome.accepted or outcome.stage != "proof" or round_no == max_revisions:
                            break
                        verdict = roles.judge(llm, spec, tests, patch, _failures(outcome))
                        if verdict["verdict"] == "spec":
                            reason = f"judge: specification problem: {verdict['explanation']}"
                            break
                        if verdict["verdict"] == "implementation":
                            code_feedback = _failures(outcome) + "\n" + verdict["explanation"]
                        else:
                            test_feedback = verdict["explanation"]
            except AgentFailedError as exc:
                record(FunnelEvent(**event, final_stage="agent", status="rejected", rejection_reason=str(exc),
                                   cost_usd=round(llm.usage.cost_usd - spent, 4)))
                continue
            cost = round(llm.usage.cost_usd - spent, 4)
            if outcome is None or not outcome.accepted:
                stage = outcome.stage if outcome else "agent"
                record(FunnelEvent(**event, final_stage=stage, status="rejected",
                                   rejection_reason=reason or (outcome.reason if outcome else "no outcome"),
                                   cost_usd=cost))
                continue
            report = check_strength(outcome.task_dir, ctx.base, outcome.proof, ctx.executor, max_mutants)
            update = {"mutants_total": report.total, "mutants_killed": report.caught}
            if blind_attempts:
                blind = blind_solve(outcome.task_dir, ctx.base, outcome.proof, ctx.stack, ctx.executor, llm,
                                    blind_attempts)
                update |= {"blind_solve_passed": blind.solved > 0, "blind_solve_diagnosis": blind.diagnosis}
                meta_path = outcome.task_dir / "metadata.json"
                meta = TaskMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
                meta_path.write_text(meta.model_copy(update={"difficulty": blind.difficulty}).model_dump_json(indent=2)
                                     + "\n", encoding="utf-8", newline="\n")
                if blind.diagnosis == "spec_problem":
                    record(FunnelEvent(**event, final_stage="blind_solve", status="rejected",
                                       rejection_reason=f"independent solver failed; judged a spec/test problem: "
                                                        f"{blind.detail}", cost_usd=round(llm.usage.cost_usd - spent, 4)))
                    continue
            proof = outcome.proof.model_copy(update=update)
            (outcome.task_dir / "evidence" / "proof.json").write_text(proof.model_dump_json(indent=2) + "\n",
                                                                      encoding="utf-8", newline="\n")
            (outcome.task_dir / "evidence" / "strength.json").write_text(
                json.dumps({"total": report.total, "caught": report.caught, "survivors": report.survivors}, indent=1)
                + "\n", encoding="utf-8", newline="\n")
            accepted_specs.append(spec)
            accepted_files.append(extract_diff_files(patch))
            record(FunnelEvent(**event, final_stage="accepted", status="accepted",
                               cost_usd=round(llm.usage.cost_usd - spent, 4)))
    (out / "run.json").write_text(json.dumps({
        "repo_id": ctx.repo_id, "pinned_version": ctx.pinned_version, "seed": seed, "target": n,
        "accepted": sum(e.status == "accepted" for e in funnel), "candidates": len(funnel),
        "excluded_baseline_tests": baseline.excluded, "api_calls": llm.usage.calls,
        "cost_usd": llm.usage.cost_usd, "runtime_sec": round(time.monotonic() - started, 1)}, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    return funnel


def _candidate(ctx: RepoContext, task_id: str, proposal: dict, cell: VarietyCell, spec: str, patch: str,
               tests: dict[str, str], seed: int, llm: LLM, rounds: int) -> Candidate:
    model = f"{llm.provider}:{llm.model or 'default'}"
    toml = TaskToml(task_id=task_id, repo_id=ctx.repo_id, repo_source=ctx.repo_source,
                    pinned_version=ctx.pinned_version, language=ctx.language, test_framework=ctx.stack.framework,
                    docker_image=ctx.docker_image, test_cmd=list(ctx.test_cmd), test_project=ctx.test_project)
    meta = TaskMetadata(task_id=task_id, title=proposal["title"], variety=cell, difficulty="medium",
                        files_touched=extract_diff_files(patch),
                        provenance=ProvenanceRecord(seed=seed, planner_model=model, spec_model=model,
                                                    coder_model=model, tester_model=model,
                                                    revision_rounds=min(rounds, 2),
                                                    estimated_cost_usd=llm.usage.cost_usd))
    return Candidate(toml, meta, spec, patch, tests)
