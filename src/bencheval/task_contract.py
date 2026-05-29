"""BenchEval vNext canonical task contract (schema v0.2)."""

from __future__ import annotations

import re
from typing import Literal, cast

from pydantic import BaseModel, Field, field_validator, model_validator

SourceType = Literal["synthetic", "internal", "public_calibration", "transformed_public"]
LeakRisk = Literal["low", "medium", "high"]
ExecutionProfile = Literal["E0", "E1", "E2", "E3", "E4"]
OutputType = Literal["json", "text", "patch", "artifact", "mixed"]
VerificationMode = Literal["deterministic", "replay", "hybrid"]
BudgetClass = Literal["B0", "B1", "B2", "B3"]
TaskCategory = Literal[
    "coding",
    "tool_usage",
    "agentic_coding",
    "defensive_security",
    "calibration",
    "stretch",
]
VariantGenerator = Literal["manual", "templated", "seeded"]

_PROFILE_SPLIT = re.compile(r"\s*/\s*")
_AGENTIC_CATEGORIES = frozenset({"agentic_coding", "defensive_security"})
_ALLOWED_PROFILES = frozenset({"E0", "E1", "E2", "E3", "E4"})


def _parse_profile_string(value: str) -> list[ExecutionProfile]:
    parts = [p.strip() for p in _PROFILE_SPLIT.split(value) if p.strip()]
    if not parts:
        raise ValueError("execution.profile must contain at least one profile")
    unknown = [p for p in parts if p not in _ALLOWED_PROFILES]
    if unknown:
        raise ValueError(f"unknown execution profiles: {', '.join(unknown)}")
    return cast("list[ExecutionProfile]", parts)


class TaskMeta(BaseModel):
    id: str
    version: str
    family_id: str
    category: TaskCategory
    title: str
    intent: str

    @field_validator("id", "version")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value


class Provenance(BaseModel):
    source_type: SourceType
    license: str
    spdx: str
    source_hash: str
    leak_risk: LeakRisk
    public_indexed: bool
    created_at: str
    reviewed_by: list[str] = Field(default_factory=list)

    @field_validator("spdx")
    @classmethod
    def spdx_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("spdx must be non-empty")
        return value


class Variant(BaseModel):
    variant_id: str
    generator: VariantGenerator
    seed: int | None = None
    stable_for_regression: bool
    rotation_group: str


class InputContract(BaseModel):
    provided: list[str]
    hidden: list[str]


class OutputContract(BaseModel):
    type: OutputType
    schema_path: str = Field(alias="schema")

    model_config = {"populate_by_name": True}


class Execution(BaseModel):
    profile: str
    allowed_tools: list[str]
    forbidden_tools: list[str]
    internet: bool

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        _parse_profile_string(value)
        return value

    def profiles(self) -> list[ExecutionProfile]:
        return _parse_profile_string(self.profile)


class Constraints(BaseModel):
    budget_class: BudgetClass
    max_steps: int = Field(gt=0)
    max_wall_clock_sec: int = Field(gt=0)
    max_cost_usd: float = Field(gt=0)
    must_not_modify_tests: bool = False


class Verification(BaseModel):
    mode: VerificationMode
    verifier: str
    replay_required: bool
    primary_pass_metric: str
    partial_metrics: list[str] = Field(default_factory=list)


class TaskContract(BaseModel):
    schema_version: Literal["0.2"]
    task: TaskMeta
    provenance: Provenance
    variant: Variant
    input_contract: InputContract
    output_contract: OutputContract
    execution: Execution
    constraints: Constraints
    verification: Verification
    risk_tags: list[str]

    @property
    def is_agentic_or_defensive(self) -> bool:
        return self.task.category in _AGENTIC_CATEGORIES

    @property
    def is_calibration(self) -> bool:
        return (
            self.task.category == "calibration"
            or self.provenance.source_type == "public_calibration"
        )

    @property
    def is_stretch(self) -> bool:
        return self.task.category == "stretch" or self.constraints.budget_class == "B3"

    @model_validator(mode="after")
    def core_invariants(self) -> TaskContract:
        if self.provenance.public_indexed and self.provenance.source_type != "public_calibration":
            raise ValueError(
                "provenance.public_indexed must be false unless source_type is public_calibration",
            )
        if self.is_agentic_or_defensive and not self.verification.partial_metrics:
            raise ValueError(
                "verification.partial_metrics must be non-empty for agentic and defensive tasks",
            )
        return self

    def validate_core_membership(self, *, is_core: bool) -> None:
        if not is_core:
            return
        if self.provenance.public_indexed and self.provenance.source_type != "public_calibration":
            raise ValueError("Core tasks cannot be public_indexed unless public_calibration")
        if self.execution.internet:
            raise ValueError("Core tasks must not enable internet")
        if not self.verification.replay_required:
            raise ValueError("Core tasks must set verification.replay_required=true")
        if self.is_calibration:
            raise ValueError("Calibration tasks cannot belong to weighted Core suites")
