"""Task contract loader, suite registry, and offline linter."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from bencheval.exceptions import BenchEvalError, TaskContractError
from bencheval.paths import repo_root as _repo_root
from bencheval.task_contract import TaskContract

LintSeverity = Literal["error", "warning"]

_SOURCE_HASH_PATTERN = re.compile(r'(source_hash:\s*)"[^"]*"')


@dataclass(frozen=True, slots=True)
class TaskLintIssue:
    severity: LintSeverity
    code: str
    message: str
    path: str


@dataclass(frozen=True, slots=True)
class TaskLintReport:
    path: str
    issues: tuple[TaskLintIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


@dataclass(frozen=True, slots=True)
class SuiteDefinition:
    name: str
    task_ids: tuple[str, ...]
    weighted_in_core: bool


def compute_source_hash(content: bytes) -> str:
    text = content.decode("utf-8")
    canonical = _SOURCE_HASH_PATTERN.sub(r'\1""', text)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def selftest_tasks_root() -> Path:
    """Canonical selftest lane root (P9.2); falls back to legacy ``config/tasks``."""
    root = _repo_root()
    selftest = root / "config" / "selftest"
    if selftest.is_dir():
        return selftest
    legacy = root / "config" / "tasks"
    return legacy


def default_tasks_root() -> Path:
    return selftest_tasks_root()


def default_suites_path() -> Path:
    return _repo_root() / "config" / "suites.yaml"


def load_task_contract(path: Path, *, raw_bytes: bytes | None = None) -> TaskContract:
    p = path.resolve()
    try:
        data = raw_bytes if raw_bytes is not None else p.read_bytes()
    except OSError as e:
        raise TaskContractError(f"cannot read task contract {p}: {e}") from e
    try:
        parsed = yaml.safe_load(data.decode("utf-8"))
    except yaml.YAMLError as e:
        raise TaskContractError(f"{p.name}: invalid YAML: {e}") from e
    if not isinstance(parsed, dict):
        raise TaskContractError(f"{p.name}: task contract must be a mapping")
    try:
        return TaskContract.model_validate(parsed)
    except ValidationError as e:
        raise TaskContractError(f"{p.name}: {e}") from e


def _iter_task_contract_paths(root: Path) -> list[Path]:
    """Yield task contract YAML paths; ignore workspace fixture trees."""
    resolved = root.resolve()
    if not resolved.is_dir():
        return []
    direct = sorted(resolved.glob("*.yaml"))
    if direct:
        return direct
    paths: list[Path] = []
    for suite_dir in sorted(resolved.iterdir()):
        if suite_dir.is_dir():
            paths.extend(sorted(suite_dir.glob("*.yaml")))
    return paths


def load_task_dir(path: Path) -> list[TaskContract]:
    root = path.resolve()
    if not root.is_dir():
        raise TaskContractError(f"task directory not found: {root}")
    files = _iter_task_contract_paths(root)
    contracts: list[TaskContract] = []
    for fp in files:
        contracts.append(load_task_contract(fp))
    contracts.sort(key=lambda c: c.task.id)
    return contracts


def load_suites(path: Path | None = None) -> dict[str, SuiteDefinition]:
    suites_path = (path or default_suites_path()).resolve()
    try:
        raw = yaml.safe_load(suites_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise TaskContractError(f"cannot read suites file {suites_path}: {e}") from e
    except yaml.YAMLError as e:
        raise TaskContractError(f"{suites_path.name}: invalid YAML: {e}") from e
    if not isinstance(raw, dict) or "suites" not in raw:
        raise TaskContractError(f"{suites_path.name}: missing top-level 'suites' key")
    suites_raw = raw["suites"]
    if not isinstance(suites_raw, dict):
        raise TaskContractError(f"{suites_path.name}: 'suites' must be a mapping")
    suites: dict[str, SuiteDefinition] = {}
    for name, body in sorted(suites_raw.items()):
        if not isinstance(body, dict):
            raise TaskContractError(f"{suites_path.name}: suite {name!r} must be a mapping")
        if "alias" in body:
            alias = body["alias"]
            if not isinstance(alias, str) or alias not in suites_raw:
                raise TaskContractError(
                    f"{suites_path.name}: suite {name!r} alias {alias!r} invalid",
                )
            continue
        task_ids = body.get("tasks", [])
        if not isinstance(task_ids, list) or not all(isinstance(t, str) for t in task_ids):
            raise TaskContractError(
                f"{suites_path.name}: suite {name!r} tasks must be a string list",
            )
        weighted = body.get("weighted_in_core", False)
        if not isinstance(weighted, bool):
            raise TaskContractError(
                f"{suites_path.name}: suite {name!r} weighted_in_core must be boolean",
            )
        suites[name] = SuiteDefinition(
            name=name,
            task_ids=tuple(task_ids),
            weighted_in_core=weighted,
        )
    for name, body in suites_raw.items():
        if isinstance(body, dict) and "alias" in body:
            alias = body["alias"]
            if isinstance(alias, str) and alias in suites:
                suites[name] = SuiteDefinition(
                    name=name,
                    task_ids=suites[alias].task_ids,
                    weighted_in_core=suites[alias].weighted_in_core,
                )
    return suites


def resolve_task_path(task_id_or_path: str, tasks_root: Path | None = None) -> Path:
    root = (tasks_root or default_tasks_root()).resolve()
    candidate = Path(task_id_or_path)
    if candidate.exists():
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as e:
            raise TaskContractError(
                f"task path {resolved} is outside tasks root {root}",
            ) from e
        return resolved
    if not root.is_dir():
        raise TaskContractError(f"tasks root not found: {root}")
    matches: list[Path] = []
    for fp in _iter_task_contract_paths(root):
        try:
            contract = load_task_contract(fp)
        except TaskContractError:
            continue
        if contract.task.id == task_id_or_path:
            matches.append(fp.resolve())
    if not matches:
        raise TaskContractError(f"task not found: {task_id_or_path}")
    if len(matches) > 1:
        paths = ", ".join(str(m) for m in matches)
        raise TaskContractError(f"ambiguous task id {task_id_or_path}: {paths}")
    return matches[0]


def _core_task_ids(suites: dict[str, SuiteDefinition]) -> frozenset[str]:
    ids: set[str] = set()
    for suite in suites.values():
        if suite.weighted_in_core:
            ids.update(suite.task_ids)
    return frozenset(ids)


def lint_task_contract(
    contract: TaskContract,
    *,
    path: str = "",
    source_bytes: bytes | None = None,
    is_core: bool = False,
) -> list[TaskLintIssue]:
    issues: list[TaskLintIssue] = []
    loc = path or contract.task.id

    if is_core:
        try:
            contract.validate_core_membership(is_core=True)
        except ValueError as e:
            issues.append(TaskLintIssue("error", "core_invariant", str(e), loc))

    if source_bytes is not None:
        expected = compute_source_hash(source_bytes)
        if contract.provenance.source_hash != expected:
            issues.append(
                TaskLintIssue(
                    "warning",
                    "source_hash_mismatch",
                    f"expected {expected}, got {contract.provenance.source_hash}",
                    loc,
                ),
            )

    prov = contract.provenance
    if prov.source_type == "public_calibration" and prov.public_indexed:
        issues.append(
            TaskLintIssue(
                "warning",
                "calibration_public_indexed",
                "public_calibration tasks should document contamination risk",
                loc,
            ),
        )

    try:
        contract.execution.profiles()
    except ValueError as e:
        issues.append(TaskLintIssue("error", "invalid_profile", str(e), loc))

    if contract.is_stretch and contract.constraints.budget_class != "B3":
        issues.append(
            TaskLintIssue(
                "warning",
                "stretch_budget_class",
                "stretch tasks should use budget class B3",
                loc,
            ),
        )

    return issues


def lint_task_path(
    path: Path,
    *,
    suites: dict[str, SuiteDefinition] | None = None,
) -> TaskLintReport:
    p = path.resolve()
    try:
        raw = p.read_bytes()
    except OSError as e:
        return TaskLintReport(
            str(p),
            (
                TaskLintIssue(
                    "error",
                    "read_error",
                    f"cannot read task contract: {e}",
                    str(p),
                ),
            ),
        )
    try:
        contract = load_task_contract(p, raw_bytes=raw)
    except TaskContractError as e:
        return TaskLintReport(str(p), (TaskLintIssue("error", "load_error", str(e), str(p)),))

    suite_map = suites if suites is not None else load_suites()
    core_ids = _core_task_ids(suite_map)
    is_core = contract.task.id in core_ids
    issues = lint_task_contract(contract, path=str(p), source_bytes=raw, is_core=is_core)
    return TaskLintReport(str(p), tuple(issues))


def index_tasks(tasks_root: Path | None = None) -> dict[str, Path]:
    root = (tasks_root or default_tasks_root()).resolve()
    index: dict[str, Path] = {}
    for fp in _iter_task_contract_paths(root):
        contract = load_task_contract(fp)
        if contract.task.id in index:
            raise BenchEvalError(f"duplicate task id {contract.task.id}")
        index[contract.task.id] = fp.resolve()
    return index


def tasks_for_suite(suite_name: str, suites: dict[str, SuiteDefinition] | None = None) -> list[str]:
    suite_map = suites if suites is not None else load_suites()
    if suite_name not in suite_map:
        raise TaskContractError(f"unknown suite: {suite_name}")
    return list(suite_map[suite_name].task_ids)
