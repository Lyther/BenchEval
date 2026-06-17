"""Task admission checklist loader and offline auditor (Core-8 and expansion)."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

from bencheval.exceptions import BenchEvalError, TaskContractError
from bencheval.task_registry import (
    lint_task_path,
    load_suites,
    load_task_contract,
    resolve_task_path,
    tasks_for_suite,
)

GateStatus = Literal["pass", "fail", "pending"]


class HumanSignOff(BaseModel):
    reviewer: str
    date: str


class TaskAdmissionEntry(BaseModel):
    workspace: str
    reference_solution: str
    negative_control: str
    required_artifacts: list[str]
    no_llm_judge_primary: bool = True
    replay_runs: int = Field(default=2, ge=2)
    human_sign_off: HumanSignOff | None = None


class Core8AdmissionDocument(BaseModel):
    schema_version: Literal["0.1"]
    suite: str
    updated_at: str
    notes: str | None = None
    tasks: dict[str, TaskAdmissionEntry]


@dataclass(frozen=True, slots=True)
class AdmissionGate:
    name: str
    status: GateStatus
    message: str


@dataclass(frozen=True, slots=True)
class TaskAdmissionReport:
    task_id: str
    gates: tuple[AdmissionGate, ...]

    @property
    def automated_pass(self) -> bool:
        automated = [g for g in self.gates if g.name != "human_sign_off"]
        return all(g.status == "pass" for g in automated)

    @property
    def admitted(self) -> bool:
        return all(g.status == "pass" for g in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "automated_pass": self.automated_pass,
            "admitted": self.admitted,
            "gates": [
                {"name": g.name, "status": g.status, "message": g.message} for g in self.gates
            ],
        }


@dataclass(frozen=True, slots=True)
class SuiteAdmissionReport:
    suite: str
    tasks: tuple[TaskAdmissionReport, ...]

    @property
    def admitted(self) -> bool:
        return bool(self.tasks) and all(t.admitted for t in self.tasks)

    @property
    def admitted_count(self) -> int:
        return sum(1 for task in self.tasks if task.admitted)

    @property
    def automated_pass_count(self) -> int:
        return sum(1 for task in self.tasks if task.automated_pass)

    @property
    def failed_count(self) -> int:
        return sum(1 for task in self.tasks if not task.automated_pass)

    @property
    def not_admitted_count(self) -> int:
        return sum(1 for task in self.tasks if not task.admitted)

    @property
    def pending_count(self) -> int:
        return sum(1 for task in self.tasks if any(gate.status == "pending" for gate in task.gates))

    def to_dict(self) -> dict[str, object]:
        return {
            "suite": self.suite,
            "admitted": self.admitted,
            "task_count": len(self.tasks),
            "admitted_count": self.admitted_count,
            "automated_pass_count": self.automated_pass_count,
            "failed_count": self.failed_count,
            "not_admitted_count": self.not_admitted_count,
            "pending_count": self.pending_count,
            "tasks": [t.to_dict() for t in self.tasks],
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_admission_path() -> Path:
    return _repo_root() / "docs" / "context" / "core-8-admission.yaml"


def admission_path_for_suite(suite: str) -> Path:
    if suite == "core-16":
        return _repo_root() / "docs" / "context" / "core-16-admission.yaml"
    return default_admission_path()


def _is_expansion_task(task_id: str) -> bool:
    try:
        path = resolve_task_path(task_id)
    except TaskContractError:
        return False
    return path.parent.name == "core-16"


def admission_path_for_task(task_id: str) -> Path:
    core16_path = admission_path_for_suite("core-16")
    is_expansion = _is_expansion_task(task_id)
    try:
        doc = load_admission_document(core16_path)
    except BenchEvalError:
        if is_expansion:
            raise
        return default_admission_path()
    if task_id in doc.tasks:
        return core16_path
    if is_expansion:
        raise TaskContractError(f"task {task_id} missing from Core-16 admission document")
    return default_admission_path()


def load_admission_document(path: Path | None = None) -> Core8AdmissionDocument:
    admission_path = (path or default_admission_path()).resolve()
    try:
        raw = yaml.safe_load(admission_path.read_text(encoding="utf-8-sig"))
    except OSError as e:
        raise BenchEvalError(f"cannot read admission document {admission_path}: {e}") from e
    except yaml.YAMLError as e:
        raise BenchEvalError(f"{admission_path.name}: invalid YAML: {e}") from e
    try:
        return Core8AdmissionDocument.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{admission_path.name}: {e}") from e


DEFAULT_VERIFIER_TIMEOUT_SEC = 60


class VerifierOutput(BaseModel):
    model_config = ConfigDict(strict=True)

    primary_pass: StrictBool
    partial_score: float = Field(ge=0.0, le=1.0)
    partial_metrics: dict[str, float] = Field(default_factory=dict)

    @field_validator("partial_metrics")
    @classmethod
    def metrics_in_range(cls, value: dict[str, float]) -> dict[str, float]:
        for key, metric in value.items():
            if not 0.0 <= metric <= 1.0:
                raise ValueError(f"partial metric {key!r} out of range [0.0, 1.0]")
        return value


def run_workspace_verifier(
    workspace: Path,
    candidate: Path,
    *,
    timeout_sec: int = DEFAULT_VERIFIER_TIMEOUT_SEC,
) -> VerifierOutput:
    script = workspace / "verify.py"
    if not script.is_file():
        raise BenchEvalError(f"verifier missing: {script}")
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(candidate.resolve())],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise BenchEvalError(
            f"verifier timed out after {timeout_sec}s for {workspace.name}",
        ) from exc
    if proc.returncode not in (0, 1):
        stderr = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise BenchEvalError(f"verifier error for {candidate.name}: {stderr}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise BenchEvalError(f"verifier returned invalid JSON for {candidate.name}: {e}") from e
    try:
        return VerifierOutput.model_validate(payload)
    except ValidationError as e:
        raise BenchEvalError(
            f"verifier output failed schema validation for {candidate.name}: {e}",
        ) from e


def _gate(
    name: str,
    ok: bool | None,
    *,
    pass_msg: str,
    fail_msg: str,
    pending_msg: str,
) -> AdmissionGate:
    if ok is None:
        return AdmissionGate(name, "pending", pending_msg)
    if ok:
        return AdmissionGate(name, "pass", pass_msg)
    return AdmissionGate(name, "fail", fail_msg)


def audit_task_admission(
    task_id: str,
    *,
    admission: Core8AdmissionDocument | None = None,
    admission_path: Path | None = None,
) -> TaskAdmissionReport:
    doc = admission or load_admission_document(admission_path)
    if task_id not in doc.tasks:
        raise TaskContractError(f"task {task_id} missing from admission document")
    entry = doc.tasks[task_id]
    root = _repo_root()
    workspace = (root / entry.workspace).resolve()
    suites = load_suites(root / "config" / "suites.yaml")
    task_path = resolve_task_path(task_id)
    contract_report = lint_task_path(task_path, suites=suites)
    contract = load_task_contract(task_path)

    gates: list[AdmissionGate] = []

    gates.append(
        _gate(
            "contract_lint_clean",
            contract_report.ok,
            pass_msg="task contract lint passed",
            fail_msg="task contract lint reported errors",
            pending_msg="task contract lint not run",
        ),
    )

    ref_path = workspace / entry.reference_solution
    neg_path = workspace / entry.negative_control
    gates.append(
        _gate(
            "reference_solution_exists",
            ref_path.is_file(),
            pass_msg=f"reference present at {ref_path.relative_to(root)}",
            fail_msg=f"reference missing at {ref_path.relative_to(root)}",
            pending_msg="reference path not checked",
        ),
    )
    gates.append(
        _gate(
            "negative_control_exists",
            neg_path.is_file(),
            pass_msg=f"negative control present at {neg_path.relative_to(root)}",
            fail_msg=f"negative control missing at {neg_path.relative_to(root)}",
            pending_msg="negative control path not checked",
        ),
    )

    missing_artifacts = [
        name
        for name in entry.required_artifacts
        if not (workspace / name.removeprefix("./").rstrip("/")).exists()
    ]
    gates.append(
        _gate(
            "required_artifacts_listed",
            not missing_artifacts if entry.required_artifacts else False,
            pass_msg="all required artifacts present",
            fail_msg=f"missing artifacts: {', '.join(missing_artifacts)}",
            pending_msg="required artifacts not checked",
        ),
    )

    gates.append(
        _gate(
            "no_live_internet_required",
            contract.execution.internet is False,
            pass_msg="task contract disables internet",
            fail_msg="task contract enables internet",
            pending_msg="internet requirement not checked",
        ),
    )

    gates.append(
        _gate(
            "no_llm_judge_primary",
            entry.no_llm_judge_primary,
            pass_msg="admission record confirms no LLM judge for primary scoring",
            fail_msg="admission record allows LLM judge for primary scoring",
            pending_msg="LLM judge policy not recorded",
        ),
    )

    ref_passes: bool | None = None
    if ref_path.is_file() and (workspace / "verify.py").is_file():
        try:
            ref_passes = run_workspace_verifier(
                workspace,
                ref_path,
                timeout_sec=contract.constraints.max_wall_clock_sec,
            ).primary_pass
        except BenchEvalError:
            ref_passes = False
    gates.append(
        _gate(
            "reference_passes_verifier",
            ref_passes,
            pass_msg="reference solution passes verifier",
            fail_msg="reference solution fails or verifier errored",
            pending_msg="reference verifier not run",
        ),
    )

    neg_fails: bool | None = None
    if neg_path.is_file() and (workspace / "verify.py").is_file():
        try:
            neg_fails = not run_workspace_verifier(
                workspace,
                neg_path,
                timeout_sec=contract.constraints.max_wall_clock_sec,
            ).primary_pass
        except BenchEvalError:
            neg_fails = False
    gates.append(
        _gate(
            "negative_control_fails_verifier",
            neg_fails,
            pass_msg="negative control fails verifier as expected",
            fail_msg="negative control passes verifier or verifier errored",
            pending_msg="negative control verifier not run",
        ),
    )

    replay_ok: bool | None = None
    if ref_path.is_file() and (workspace / "verify.py").is_file():
        try:
            outcomes = [
                run_workspace_verifier(
                    workspace,
                    ref_path,
                    timeout_sec=contract.constraints.max_wall_clock_sec,
                )
                for _ in range(entry.replay_runs)
            ]
            first = outcomes[0]
            replay_ok = all(
                o.primary_pass == first.primary_pass
                and o.partial_score == first.partial_score
                and o.partial_metrics == first.partial_metrics
                for o in outcomes
            )
        except BenchEvalError:
            replay_ok = False
    gates.append(
        _gate(
            "replay_determinism_checked",
            replay_ok,
            pass_msg=f"verifier replay deterministic across {entry.replay_runs} runs",
            fail_msg="verifier replay not deterministic or errored",
            pending_msg="replay determinism not checked",
        ),
    )

    if entry.human_sign_off is None:
        gates.append(
            AdmissionGate(
                "human_sign_off",
                "pending",
                "awaiting human reviewer sign-off",
            ),
        )
    else:
        gates.append(
            AdmissionGate(
                "human_sign_off",
                "pass",
                f"signed by {entry.human_sign_off.reviewer} on {entry.human_sign_off.date}",
            ),
        )

    return TaskAdmissionReport(task_id=task_id, gates=tuple(gates))


def audit_suite_admission(
    suite: str,
    *,
    admission: Core8AdmissionDocument | None = None,
    admission_path: Path | None = None,
) -> SuiteAdmissionReport:
    if suite == "core-16" and admission is None:
        task_ids = tasks_for_suite(suite)
        reports = tuple(
            audit_task_admission(
                task_id,
                admission_path=admission_path or admission_path_for_task(task_id),
            )
            for task_id in task_ids
        )
        return SuiteAdmissionReport(suite=suite, tasks=reports)

    resolved_path = admission_path or admission_path_for_suite(suite)
    doc = admission or load_admission_document(resolved_path)
    try:
        task_ids = tasks_for_suite(suite)
    except TaskContractError:
        if suite == doc.suite:
            task_ids = sorted(doc.tasks.keys())
        else:
            raise
    reports = tuple(
        audit_task_admission(task_id, admission=doc, admission_path=resolved_path)
        for task_id in task_ids
    )
    return SuiteAdmissionReport(suite=suite, tasks=reports)
