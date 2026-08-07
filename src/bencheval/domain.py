"""BenchEval v0.3 domain types — single source of truth for the control plane.

This module is the authoritative definition of:
  - Branded identifier aliases (NewType) so ``str`` ids are not freely interchangeable.
  - Shared enum ``Literal`` aliases reused across registries, planner, and evidence.
  - The four-axis identity contract (model_id / runtime_id / harness_kind / adapter_id).
  - v0.3 additive ``EvidenceRecord`` fields (see ``evidence.py`` for the v0.2 base model;
    this module only declares the new field shapes and interpretation labels).

Design rules (enforced by Pydantic + ruff, not by hand):
  - Every public model is ``frozen=True, extra="forbid"``.
  - IDs are plain ``str`` at runtime but tagged with ``NewType`` aliases for static
    distinction. Construction validates via ``Field(pattern=...)``; never cast blindly.
  - Money: recorded spend stays ``float`` (matches the v0.2 evidence store and is not
    a balance ledger). Price rates use ``Decimal`` (see ``pricing.py``). No float money
    arithmetic without explicit rounding.
  - Optionality is explicit: ``X | None``, never implicit ``Optional`` defaults that
    silently accept bare ``None`` where a value is required.
  - ``any`` is forbidden; external data is parsed through a Pydantic model at the
    boundary, never trusted as a raw ``dict``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, NewType, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# 1. BRANDED IDS (anti-string-law, Python adaptation)
# ---------------------------------------------------------------------------
# NewType gives static type-checker distinction without runtime cost. They are
# NOT constructors — build ids as plain ``str`` and let the validator confirm the
# pattern. The aliases exist so a function signature asking for ``SliceId`` rejects
# a ``RuntimeId`` at check time.

BenchmarkId = NewType("BenchmarkId", str)
SliceId = NewType("SliceId", str)
RuntimeId = NewType("RuntimeId", str)
ModelId = NewType("ModelId", str)
AdapterId = NewType("AdapterId", str)
HarnessKind = NewType("HarnessKind", str)
RunId = NewType("RunId", str)
InstanceId = NewType("InstanceId", str)

# Canonical patterns. Keep them in one place so every registry agrees.
_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"

# ---------------------------------------------------------------------------
# 2. SHARED ENUMS (single source — imported by registries/planner/evidence)
# ---------------------------------------------------------------------------
# These intentionally re-declare the v0.2 values where v0.3 reuses them, so the
# control-plane types are self-contained. Existing modules keep their own aliases
# for backward compatibility; new code imports from here.

# Execution profiles (E0–E4).
ExecutionProfile = Literal["E0", "E1", "E2", "E3", "E4"]

# Budget classes (B0–B3).
BudgetClass = Literal["B0", "B1", "B2", "B3"]

# Doctor / legacy backend lane — NOT runtime identity. Product path uses --runtime / --agent.
ExecutionBackend = Literal["local", "inspect", "harbor"]

# Runtime lifecycle shapes.
RuntimeKind = Literal[
    "cli_agent",  # claude-code, codex-cli
    "api_client",
    "harness_agent",
    "selftest_local",
]
RuntimeModelBinding = Literal["runtime_configured", "bencheval_injected", "not_applicable"]
RuntimeLifecycle = Literal["external_process", "in_process", "containerized"]

# Harness kinds — the benchmark execution harness / environment manager.
HarnessKindLiteral = Literal[
    "harbor",
    "swebench-native",
    "bfcl-native",
    "livecodebench-native",
    "inspect",
    "inspect-evals",
    "hle-native",
    "local-harness",
    "cybergym-native",
    "exploitgym-native",
    "bountybench-native",
    "selftest-local",
]

# Adapter kinds — BenchEval glue mapping run spec ↔ native harness ↔ evidence.
AdapterKindLiteral = Literal[
    "terminal-bench-harbor",
    "swebench",
    "swebench-pro-harbor",
    "bfcl",
    "gpqa",
    "hle",
    "livecodebench",
    "bigcodebench",
    "tau-bench",
    "cybench",
    "cybergym",
    "exploitgym",
    "bountybench",
    "cyberseceval-defensive",
    "osworld",
    "selftest",
]

# Slice purpose — drives interpretation labels and comparison validity.
SlicePurpose = Literal[
    "adapter_smoke",
    "rough_regression",
    "benchmark_native_claim",
    "runtime_comparison",
    "model_comparison",
]

# Interpretation label attached to every report / evidence row.
InterpretationLabel = Literal[
    "adapter_smoke",
    "rough_regression",
    "benchmark_native_claim",
    "runtime_comparison",
    "model_comparison",
    "contaminated_or_legacy",
    "defensive_security_only",
]

# Failure taxonomy — must stay distinct per architecture §10. One evidence row
# may carry several labels; the verifier stays scoring authority when a candidate
# artifact exists.
FailureLabel = Literal[
    "harness_failure",
    "runtime_launch_failure",
    "runtime_auth_failure",
    "runtime_permission_block",
    "runtime_output_unparseable",
    "runtime_context_overflow",
    "runtime_tool_failure",
    "runtime_config_drift",
    "runtime_budget_exceeded",
    "runtime_output_cap_reached",
    # Infrastructure stalls: the solver wedged (no progress) or ran past its
    # wall-clock deadline and BenchEval terminated it. Distinct from a
    # task-difficulty failure so a benchmark number never conflates infra
    # flakiness with capability.
    "runtime_no_progress_stall",
    "runtime_wall_clock_timeout",
    "materialization_failure",
    "model_wrong_solution",
    "model_output_invalid",
    "adapter_error",
    "budget_exceeded",
    "wrong_solution",
    "operator_interrupted",
    "interrupted_by_harness",
    "config_failed",
    "remote_infra_failure",
    "evidence_corrupt",
    "duplicate_launch",
]

# Cleanup outcome.
CleanupResult = Literal["success", "partial", "skipped", "failed"]

# Caveat labels preserved alongside native scores.
ContaminationLabel = Literal["none", "public_possible", "known_contaminated", "legacy"]
RewardHackRiskLabel = Literal["none", "known_public_risk", "verified_safe"]
VerifierIntegrityLabel = Literal["native", "bencheval", "unknown"]

# ---------------------------------------------------------------------------
# 3. RUNTIME PROFILE (config/runtimes/<id>.yaml) — new in v0.3
# ---------------------------------------------------------------------------


class RuntimeLaunch(BaseModel):
    """How a runtime is started noninteractively."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_template: tuple[str, ...] = Field(min_length=1)
    working_dir_policy: Literal["ephemeral_workspace", "shared_workspace", "none"]
    env_vars_required: tuple[str, ...] = ()
    env_vars_optional: tuple[str, ...] = ()
    timeout_sec_default: int = Field(gt=0, le=86_400)


class RuntimeCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reads_files: bool
    edits_files: bool
    runs_shell: bool
    supports_mcp: bool
    supports_subagents: bool
    supports_hooks: bool
    supports_noninteractive: bool
    supports_json_output: Literal["full", "partial", "none"]


class RuntimeSafety(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    network_default: Literal["deny", "allow", "benchmark_required"]
    workspace_boundary: Literal["ephemeral_only", "shared_read", "unrestricted"]
    requires_user_approval: bool
    forbidden_features_for_eval: tuple[str, ...] = ()


class RuntimeVersioning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version_command: tuple[str, ...] = Field(min_length=1)
    config_hash_inputs: tuple[str, ...] = ()


class RuntimeProfile(BaseModel):
    """A runtime/scaffold profile (claude-code, codex-cli, ...)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["0.1"]
    runtime: RuntimeProfileRuntime
    launch: RuntimeLaunch
    capabilities: RuntimeCapabilities
    safety: RuntimeSafety
    versioning: RuntimeVersioning
    admission: Literal["draft", "admitted"] = "draft"

    @property
    def id(self) -> RuntimeId:
        return RuntimeId(self.runtime.id)


class RuntimeProfileRuntime(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    kind: RuntimeKind
    display_name: str = Field(min_length=1)
    lifecycle: RuntimeLifecycle
    supported_platforms: tuple[Literal["macos", "linux", "windows"], ...] = Field(min_length=1)
    supported_harnesses: tuple[HarnessKindLiteral, ...] = Field(min_length=1)
    model_binding: RuntimeModelBinding


# Resolve forward reference (RuntimeProfile references RuntimeProfileRuntime).
RuntimeProfile.model_rebuild()


class RuntimeCatalog(BaseModel):
    """Validated collection of runtime profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["0.1"]
    runtimes: tuple[RuntimeProfile, ...] = Field(min_length=1)

    def by_id(self, runtime_id: str) -> RuntimeProfile:
        for rp in self.runtimes:
            if rp.runtime.id == runtime_id:
                return rp
        raise KeyError(f"runtime not found: {runtime_id}")


# ---------------------------------------------------------------------------
# 4. SLICE MANIFEST (typed slice with inline ids or external generated list) — v0.3
# ---------------------------------------------------------------------------


class SliceBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_instances: int = Field(gt=0, le=100_000)
    max_wall_clock_sec_per_instance: int = Field(gt=0, le=86_400)
    max_total_cost_usd: Decimal = Field(gt=0)


class SliceLabels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contamination_warning: bool = False
    public_benchmark: bool = True
    full_suite_required_for_public_claim: bool = False
    planning_placeholder_manifest: bool = False


class SliceManifest(BaseModel):
    """Typed slice over inline instance ids or an external instance manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["0.1"]
    slice: SliceManifestSlice
    budget: SliceBudget
    labels: SliceLabels = Field(default_factory=SliceLabels)


class SliceManifestSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    benchmark_id: str = Field(pattern=_ID_PATTERN)
    purpose: SlicePurpose
    selection_policy: Literal[
        "fixed_instance_ids",
        "native_selector_all",
        "custom",
        "sample_limit",
    ]
    instances: tuple[str, ...] = ()
    instances_source: str | None = Field(default=None, min_length=1)
    # Evaluator identity for benchmarks whose official scorer calls a judge model.
    judge_model_id: str | None = Field(default=None, min_length=1)
    valid_for: tuple[SlicePurpose, ...] = Field(min_length=1)
    invalid_for: tuple[SlicePurpose, ...] = ()

    @model_validator(mode="after")
    def _exactly_one_instance_source(self) -> Self:
        if self.selection_policy == "sample_limit":
            if self.instances or self.instances_source is not None:
                raise ValueError(
                    "sample_limit slices must not declare fixed instances or instances_source",
                )
            return self
        if bool(self.instances) == bool(self.instances_source):
            raise ValueError("slice must set exactly one of instances or instances_source")
        return self


SliceManifest.model_rebuild()


# ---------------------------------------------------------------------------
# 5. RUN PLAN (planner output — DTO, no secrets, no file paths)
# ---------------------------------------------------------------------------


class RunPlanInstance(BaseModel):
    """One instance in a planned run (no artifacts, safe to log/print)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: str = Field(min_length=1)


class RunPlan(BaseModel):
    """Concrete execution plan from benchmark + slice + model + optional scaffold.

    Scaffold is runtime XOR agent (or neither for model-only). No artifact paths,
    secrets, or raw model output. The executor turns a RunPlan into EvidenceRecord rows.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["0.3"]
    benchmark_id: str = Field(pattern=_ID_PATTERN)
    benchmark_version: str | None = None
    slice_id: str = Field(pattern=_ID_PATTERN)
    adapter_id: str = Field(pattern=_ID_PATTERN)
    harness_kind: HarnessKindLiteral
    runtime_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    runtime_kind: RuntimeKind | None = None
    agent_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    provider_id: str = Field(default="bytellm", pattern=_ID_PATTERN)
    model_id: str = Field(min_length=1)
    judge_model_id: str | None = Field(default=None, min_length=1)
    model_binding: RuntimeModelBinding
    instances: tuple[RunPlanInstance, ...] = Field(min_length=1)
    budget_class: BudgetClass
    max_cost_usd: float = Field(ge=0.0)
    max_wall_clock_sec: int = Field(gt=0)
    requires_harbor: bool
    requires_sandbox: bool
    network_policy: Literal["deny", "allow", "benchmark_required"]
    cleanup_policy: Literal["never", "on-success", "always"]
    caveats: tuple[str, ...] = ()
    comparison_validity: Literal[
        "model_comparison",
        "runtime_comparison",
        "adapter_smoke",
        "diagnostic_only",
        "invalid",
    ]

    def model_post_init(self, __context: object) -> None:
        if self.runtime_id is not None and self.agent_id is not None:
            raise ValueError("runtime_id and agent_id are mutually exclusive")
        if self.runtime_id is not None and self.runtime_kind is None:
            raise ValueError("runtime_kind is required when runtime_id is set")
        if self.runtime_id is None and self.runtime_kind is not None:
            raise ValueError("runtime_kind must be null when runtime_id is null")


# ---------------------------------------------------------------------------
# 6. EVIDENCE RECORD v0.3 ADDITIVE FIELDS
# ---------------------------------------------------------------------------
# The v0.2 base model lives in evidence.py and MUST stay unchanged (public export,
# AGENTS.md durable fact). This module only declares the *shapes* of the new
# optional fields so adapters/normalizers construct them consistently. The actual
# field additions are applied in evidence.py via composition, not by duplicating
# the model here.


class TokenUsage(BaseModel):
    """Token accounting for one attempt. All fields non-negative integers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int = Field(ge=0, default=0)
    cached_tokens: int = Field(ge=0, default=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)


class IntegrityMetadata(BaseModel):
    """Caveat + integrity labels preserved alongside the native score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cleanup_result: CleanupResult | None = None
    replayable: bool | None = None
    verifier_integrity_label: VerifierIntegrityLabel | None = None
    reward_hack_risk_label: RewardHackRiskLabel | None = None
    contamination_label: ContaminationLabel | None = None


# ---------------------------------------------------------------------------
# 7. DTO SEPARATION (public vs internal)
# ---------------------------------------------------------------------------
# EvidenceRecord is the *store* (has artifact paths, logs). Report/emission paths
# use these DTOs to avoid leaking paths into comparison tables.


class AttemptSummaryDTO(BaseModel):
    """Public summary of one attempt — no file paths, no raw output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    benchmark_id: str | None
    slice_id: str | None
    runtime_id: str | None
    model_id: str
    instance_id: str | None
    primary_pass: bool
    partial_score: float = Field(ge=0.0, le=1.0)
    cost_usd: float = Field(ge=0.0)
    latency_sec: float = Field(ge=0.0)
    failure_class: FailureLabel | None = None
    interpretation_label: InterpretationLabel | None = None
    contamination_label: ContaminationLabel | None = None


__all__ = [
    # Branded IDs
    "AdapterId",
    # Enums
    "AdapterKindLiteral",
    # Models
    "AttemptSummaryDTO",
    "BenchmarkId",
    "BudgetClass",
    "CleanupResult",
    "ContaminationLabel",
    "ExecutionBackend",
    "ExecutionProfile",
    "FailureLabel",
    "HarnessKind",
    "HarnessKindLiteral",
    "InstanceId",
    "IntegrityMetadata",
    "InterpretationLabel",
    "ModelId",
    "RewardHackRiskLabel",
    "RunId",
    "RunPlan",
    "RunPlanInstance",
    "RuntimeCapabilities",
    "RuntimeCatalog",
    "RuntimeId",
    "RuntimeKind",
    "RuntimeLaunch",
    "RuntimeLifecycle",
    "RuntimeModelBinding",
    "RuntimeProfile",
    "RuntimeProfileRuntime",
    "RuntimeSafety",
    "RuntimeVersioning",
    "SliceBudget",
    "SliceId",
    "SliceLabels",
    "SliceManifest",
    "SliceManifestSlice",
    "SlicePurpose",
    "TokenUsage",
    "VerifierIntegrityLabel",
]
