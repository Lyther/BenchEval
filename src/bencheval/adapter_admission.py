"""Adapter admission gates (architecture §13.1) for control-plane benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bencheval.benchmark_registry import load_benchmark_catalog
from bencheval.bfcl_native_adapter import BFCL_ADAPTER_ID
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root
from bencheval.slice_manifest import slices_for_benchmark
from bencheval.swebench_adapter import SWEBENCH_ADAPTER_ID


@dataclass(frozen=True, slots=True)
class AdapterAdmissionReport:
    adapter_id: str
    benchmark_id: str
    passed: bool
    checks: tuple[tuple[str, bool, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "benchmark_id": self.benchmark_id,
            "passed": self.passed,
            "checks": [
                {"name": name, "ok": ok, "detail": detail} for name, ok, detail in self.checks
            ],
        }


def _check_slice_manifest(benchmark_id: str, slice_id: str) -> tuple[bool, str]:
    try:
        manifests = slices_for_benchmark(benchmark_id)
    except BenchEvalError as exc:
        return False, str(exc)
    match = next((m for m in manifests if m.slice.id == slice_id), None)
    if match is None:
        return False, f"no typed slice {slice_id!r} for {benchmark_id!r}"
    return True, f"slice {slice_id} source={match.slice.instances_source}"


def _check_instances_source(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing file: {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"cannot read {path}: {exc}"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False, "instances source empty"
    return True, f"{len(lines)} instance ids"


def assess_terminal_bench_harbor_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Evidence-backed admission for P2 Harbor adapter (smoke slice + manifest)."""
    root = repo_root or _repo_root()
    catalog = load_benchmark_catalog()
    benchmark = next((b for b in catalog.benchmarks if b.id == "terminal-bench"), None)
    adapter_id = "terminal-bench-harbor"
    checks: list[tuple[str, bool, str]] = []

    if benchmark is None:
        checks.append(("benchmark_catalog", False, "terminal-bench not in catalog"))
        return AdapterAdmissionReport(adapter_id, "terminal-bench", False, tuple(checks))

    checks.append(
        (
            "catalog_adapter_status",
            benchmark.adapter_status == "manifest_available",
            f"status={benchmark.adapter_status} (flip YAML after artifact gates pass)",
        ),
    )

    slice_ok, slice_detail = _check_slice_manifest("terminal-bench", "smoke-5")
    checks.append(("typed_slice_smoke_5", slice_ok, slice_detail))

    manifest_path = root / "config" / "manifests" / "terminal-bench-smoke-5.txt"
    inst_ok, inst_detail = _check_instances_source(manifest_path)
    checks.append(("smoke_manifest_file", inst_ok, inst_detail))

    adapter_module = root / "src" / "bencheval" / "terminal_bench_harbor.py"
    adapter_ok = adapter_module.is_file()
    checks.append(
        (
            "harbor_adapter_module",
            adapter_ok,
            "src/bencheval/terminal_bench_harbor.py" if adapter_ok else str(adapter_module),
        ),
    )

    executor_module = root / "src" / "bencheval" / "control_plane_executor.py"
    executor_ok = executor_module.is_file()
    checks.append(
        (
            "control_plane_executor",
            executor_ok,
            "src/bencheval/control_plane_executor.py" if executor_ok else str(executor_module),
        ),
    )

    artifact_checks = (
        "typed_slice_smoke_5",
        "smoke_manifest_file",
        "harbor_adapter_module",
        "control_plane_executor",
    )
    passed = all(ok for name, ok, _ in checks if name in artifact_checks)
    return AdapterAdmissionReport(adapter_id, "terminal-bench", passed, tuple(checks))


def assert_terminal_bench_harbor_admitted(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    report = assess_terminal_bench_harbor_admission(repo_root=repo_root)
    if not report.passed:
        failed = [f"{name}: {detail}" for name, ok, detail in report.checks if not ok]
        msg = "terminal-bench-harbor admission failed: " + "; ".join(failed)
        raise BenchEvalError(msg)
    return report


def assess_swebench_verified_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Evidence-backed admission for P4 native SWE adapter (smoke slice + module)."""
    root = repo_root or _repo_root()
    catalog = load_benchmark_catalog()
    benchmark = next((b for b in catalog.benchmarks if b.id == "swe-bench-verified"), None)
    adapter_id = SWEBENCH_ADAPTER_ID
    checks: list[tuple[str, bool, str]] = []

    if benchmark is None:
        checks.append(("benchmark_catalog", False, "swe-bench-verified not in catalog"))
        return AdapterAdmissionReport(adapter_id, "swe-bench-verified", False, tuple(checks))

    checks.append(
        (
            "catalog_adapter_status",
            benchmark.adapter_status == "manifest_available",
            f"status={benchmark.adapter_status}",
        ),
    )

    slice_ok, slice_detail = _check_slice_manifest(
        "swe-bench-verified",
        "swe-bench-verified-smoke-10",
    )
    checks.append(("typed_slice_smoke_10", slice_ok, slice_detail))

    manifest_path = root / "config" / "manifests" / "swebench-verified-smoke-10.txt"
    inst_ok, inst_detail = _check_instances_source(manifest_path)
    checks.append(("smoke_manifest_file", inst_ok, inst_detail))

    adapter_module = root / "src" / "bencheval" / "swebench_adapter.py"
    adapter_ok = adapter_module.is_file()
    checks.append(
        (
            "swebench_adapter_module",
            adapter_ok,
            "src/bencheval/swebench_adapter.py" if adapter_ok else str(adapter_module),
        ),
    )

    executor_module = root / "src" / "bencheval" / "control_plane_executor.py"
    executor_ok = executor_module.is_file()
    checks.append(
        (
            "control_plane_executor",
            executor_ok,
            "src/bencheval/control_plane_executor.py" if executor_ok else str(executor_module),
        ),
    )

    artifact_checks = (
        "typed_slice_smoke_10",
        "smoke_manifest_file",
        "swebench_adapter_module",
        "control_plane_executor",
    )
    passed = all(ok for name, ok, _ in checks if name in artifact_checks)
    return AdapterAdmissionReport(adapter_id, "swe-bench-verified", passed, tuple(checks))


def assert_swebench_verified_admitted(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    report = assess_swebench_verified_admission(repo_root=repo_root)
    if not report.passed:
        failed = [f"{name}: {detail}" for name, ok, detail in report.checks if not ok]
        msg = "swe-bench-verified admission failed: " + "; ".join(failed)
        raise BenchEvalError(msg)
    return report


def assess_bfcl_v4_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Evidence-backed admission for P5.1 BFCL adapter (smoke slice + module)."""
    root = repo_root or _repo_root()
    catalog = load_benchmark_catalog()
    benchmark = next((b for b in catalog.benchmarks if b.id == "bfcl-v4"), None)
    adapter_id = BFCL_ADAPTER_ID
    checks: list[tuple[str, bool, str]] = []

    if benchmark is None:
        checks.append(("benchmark_catalog", False, "bfcl-v4 not in catalog"))
        return AdapterAdmissionReport(adapter_id, "bfcl-v4", False, tuple(checks))

    checks.append(
        (
            "catalog_adapter_status",
            benchmark.adapter_status == "manifest_available",
            f"status={benchmark.adapter_status} (flip YAML after artifact gates)",
        ),
    )

    slice_ok, slice_detail = _check_slice_manifest("bfcl-v4", "smoke-5")
    checks.append(("typed_slice_smoke_5", slice_ok, slice_detail))

    manifest_path = root / "config" / "manifests" / "bfcl-v4-smoke-5.txt"
    inst_ok, inst_detail = _check_instances_source(manifest_path)
    checks.append(("smoke_manifest_file", inst_ok, inst_detail))

    adapter_module = root / "src" / "bencheval" / "bfcl_native_adapter.py"
    adapter_ok = adapter_module.is_file()
    checks.append(
        (
            "bfcl_adapter_module",
            adapter_ok,
            "src/bencheval/bfcl_native_adapter.py" if adapter_ok else str(adapter_module),
        ),
    )

    executor_module = root / "src" / "bencheval" / "control_plane_executor.py"
    executor_ok = executor_module.is_file()
    checks.append(
        (
            "control_plane_executor",
            executor_ok,
            "src/bencheval/control_plane_executor.py" if executor_ok else str(executor_module),
        ),
    )

    artifact_checks = (
        "typed_slice_smoke_5",
        "smoke_manifest_file",
        "bfcl_adapter_module",
        "control_plane_executor",
    )
    passed = all(ok for name, ok, _ in checks if name in artifact_checks)
    return AdapterAdmissionReport(adapter_id, "bfcl-v4", passed, tuple(checks))


def assert_bfcl_v4_admitted(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    report = assess_bfcl_v4_admission(repo_root=repo_root)
    if not report.passed:
        failed = [f"{name}: {detail}" for name, ok, detail in report.checks if not ok]
        msg = "bfcl-v4 admission failed: " + "; ".join(failed)
        raise BenchEvalError(msg)
    return report
