"""Locked Day-1 Pydantic v2 schemas shared across all 4 team tracks."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class TaskType(str, Enum):
    NEW_FEATURE = "new_feature"
    FEATURE_CHANGE = "feature_change"
    BUG_FIX = "bug_fix"


class ChangePattern(str, Enum):
    NEW_ENDPOINT_OR_CMD = "new_endpoint_or_command"
    VALIDATION_OR_RULE = "validation_or_business_rule"
    DATA_MODEL_EXTENSION = "data_model_extension"
    ERROR_HANDLING = "error_handling_path"
    CONFIG_OPTION = "configuration_option"
    CROSS_MODULE_WORKFLOW = "cross_module_workflow"
    ALGORITHM_EDGE_CASE = "algorithm_or_edge_case"


class ScopeLevel(str, Enum):
    SINGLE_FUNCTION = "single_function"
    MULTI_FILE = "multi_file"
    CROSS_LAYER = "cross_layer"


class VarietyCell(BaseModel):
    task_type: TaskType
    change_pattern: ChangePattern
    scope: ScopeLevel


class RepoProfile(BaseModel):
    repo_id: str
    source_type: Literal["git", "zip"]
    source_ref: str
    pinned_version: str = Field(..., description="Git commit SHA or ZIP SHA-256 content hash")
    language: Literal["python", "javascript", "typescript", "cpp"]
    test_framework: Literal["pytest", "vitest", "jsontest"]
    build_cmd: list[str]
    test_cmd: list[str]
    baseline_test_count: int
    generated_characterization_tests: bool = False
    modules: list[str] = Field(default_factory=list)
    existing_test_paths: list[str] = Field(default_factory=list)


def build_timestamp() -> str:
    """Now in UTC, or SOURCE_DATE_EPOCH when set, so a replayed run writes byte-identical packages."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.isoformat()


class TaskToml(BaseModel):
    task_id: str
    repo_id: str
    repo_source: str
    pinned_version: str
    language: str
    test_framework: str
    docker_image: str
    test_cmd: list[str]
    test_project: str = Field("", description="Vitest project name, when the repository has several")
    created_at: str = Field(default_factory=build_timestamp)


class ProofRunRecord(BaseModel):
    run_index: int = Field(..., ge=1, le=3)
    check1_baseline_pass: bool
    check2_patched_all_pass: bool
    check3_unpatched_new_fail: bool
    duration_sec: float
    problems: list[str] = Field(default_factory=list, description="Test IDs that broke a condition, with why")


class ProofMatrix(BaseModel):
    task_id: str
    PASS_TO_PASS: list[str] = Field(default_factory=list)
    excluded_baseline_tests: list[str] = Field(
        default_factory=list, description="Existing tests that did not pass reliably before any change, left out of PASS_TO_PASS"
    )
    FAIL_TO_PASS: list[str] = Field(default_factory=list)
    runs: list[ProofRunRecord] = Field(default_factory=list)
    flake_count: int = 0
    patch_guard_passed: bool = True
    mutants_total: int = 0
    mutants_killed: int = 0
    adversary_total: int = 0
    adversary_caught: int = 0
    blind_solve_passed: bool | None = None
    blind_solve_diagnosis: Literal["solved", "agent_error", "spec_problem", "not_run"] = "not_run"

    @property
    def all_checks_passed(self) -> bool:
        return (
            len(self.runs) == 3
            and self.flake_count == 0
            and self.patch_guard_passed
            and len(self.FAIL_TO_PASS) > 0
            and all(
                r.check1_baseline_pass and r.check2_patched_all_pass and r.check3_unpatched_new_fail
                for r in self.runs
            )
        )

    @property
    def kill_rate(self) -> float:
        denom = self.mutants_total + self.adversary_total
        if denom == 0:
            return 0.0
        return round((self.mutants_killed + self.adversary_caught) / denom, 4)


class ProvenanceRecord(BaseModel):
    seed: int
    planner_model: str
    spec_model: str
    coder_model: str
    tester_model: str
    revision_rounds: int = Field(0, ge=0, le=2)
    estimated_cost_usd: float = 0.0
    total_runtime_sec: float = 0.0


class TaskMetadata(BaseModel):
    task_id: str
    title: str
    variety: VarietyCell
    difficulty: Literal["easy", "medium", "hard"]
    files_touched: list[str]
    symbols_touched: list[str] = Field(default_factory=list)
    max_similarity_to_accepted: float = 0.0
    safety_passed: bool = True
    provenance: ProvenanceRecord


class FunnelEvent(BaseModel):
    candidate_id: str
    title: str
    variety: VarietyCell
    final_stage: str
    status: Literal["accepted", "rejected"]
    rejection_reason: str | None = None
    cost_usd: float = 0.0
