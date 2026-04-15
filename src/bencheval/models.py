from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ModelFamily(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MOONSHOT = "moonshot"
    LOCAL = "local"


class ManifestDigest(BaseModel):
    """Committed task manifest + cryptographic digest (architecture §5, §6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark: str
    manifest_path: str
    content_sha256: str = Field(min_length=64, max_length=64)
    task_ids: tuple[str, ...] = Field(min_length=1)


class RunStamp(BaseModel):
    """Fields the run wrapper must supply; never inferred from the log alone (architecture §6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    auth_lane: str = Field(min_length=1)
    task_manifest_hash: str = Field(min_length=64, max_length=64)
    benchmark_revision: str = Field(min_length=1)
    model_family: ModelFamily


class SummaryRow(BaseModel):
    """Canonical JSONL row (architecture §6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    benchmark: str
    benchmark_revision: str
    task_manifest_hash: str = Field(min_length=64, max_length=64)
    model: str
    model_snapshot: str
    model_family: ModelFamily
    solver: str
    solver_version: str
    auth_lane: str
    reasoning_effort_requested: str | None
    reasoning_tokens_requested: int | None
    reasoning_effort_honored: str | None
    reasoning_tokens_honored: int | None
    provider_model_args: dict[str, JsonValue] = Field(
        ...,
        description=(
            "JSONL-friendly; do not mutate after construction (nested JsonValue not deep-frozen)."
        ),
    )
    n_samples: int = Field(ge=0)
    resolved: int = Field(ge=0)
    resolved_rate: float = Field(ge=0.0, le=1.0)
    total_tokens: int = Field(ge=0)
    wall_time_s: float = Field(ge=0.0)
    actual_cost_usd: Decimal | None
    estimated_api_equivalent_usd: Decimal | None
    inspect_version: str
    inspect_swe_version: str | None
    log_file: str

    @model_validator(mode="after")
    def exactly_one_cost_basis(self) -> Self:
        has_actual = self.actual_cost_usd is not None
        has_estimate = self.estimated_api_equivalent_usd is not None
        if has_actual == has_estimate:
            msg = "Exactly one of actual_cost_usd or estimated_api_equivalent_usd must be non-null"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def counts_coherent(self) -> Self:
        if self.n_samples == 0:
            if self.resolved != 0:
                raise ValueError("When n_samples is 0, resolved must be 0")
            if not math.isclose(self.resolved_rate, 0.0, abs_tol=1e-12, rel_tol=0.0):
                raise ValueError("When n_samples is 0, resolved_rate must be 0")
            return self
        if self.resolved > self.n_samples:
            raise ValueError("resolved cannot be greater than n_samples")
        expected = self.resolved / self.n_samples
        if not math.isclose(self.resolved_rate, expected, rel_tol=0.0, abs_tol=1e-9):
            msg = (
                f"resolved_rate must equal resolved / n_samples ({expected}), "
                f"got {self.resolved_rate}"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def inspect_swe_version_coupled(self) -> Self:
        uses_inspect_swe = self.solver.startswith("inspect_swe")
        if uses_inspect_swe and self.inspect_swe_version is None:
            raise ValueError("inspect_swe_version is required when solver uses inspect_swe")
        if not uses_inspect_swe and self.inspect_swe_version is not None:
            raise ValueError("inspect_swe_version must be null when solver is not inspect_swe")
        if uses_inspect_swe and self.solver_version != self.inspect_swe_version:
            raise ValueError(
                "solver_version must equal inspect_swe_version for inspect_swe scaffolds "
                f"(got solver_version={self.solver_version!r}, "
                f"inspect_swe_version={self.inspect_swe_version!r})",
            )
        return self

    @model_validator(mode="after")
    def cost_basis_matches_auth_lane(self) -> Self:
        if self.auth_lane.startswith("baseline_"):
            if self.actual_cost_usd is None:
                raise ValueError(
                    "baseline_* auth lane requires actual_cost_usd; estimate-only rows are "
                    "only valid in experimental_* lanes",
                )
            if self.estimated_api_equivalent_usd is not None:
                raise ValueError(
                    "baseline_* auth lane must leave estimated_api_equivalent_usd null",
                )
        elif self.auth_lane.startswith("experimental_"):
            if self.actual_cost_usd is not None:
                raise ValueError(
                    "experimental_* auth lane must leave actual_cost_usd null; subscription- "
                    "or gateway-backed runs are not measured spend",
                )
            if self.estimated_api_equivalent_usd is None:
                raise ValueError("experimental_* auth lane requires estimated_api_equivalent_usd")
        else:
            raise ValueError(
                f"auth_lane must start with 'baseline_' or 'experimental_'; got {self.auth_lane!r}",
            )
        return self


class DeltaRow(BaseModel):
    """One row in a comparison table (reports)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    baseline: float
    compare: float
    delta: float
    ci_low: float | None = None
    ci_high: float | None = None


class ComparisonReport(BaseModel):
    """DTO emitted by compare — no file paths, safe to log or paste."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    generated_at: datetime
    equivalence_note: str | None
    metrics: tuple[DeltaRow, ...]
