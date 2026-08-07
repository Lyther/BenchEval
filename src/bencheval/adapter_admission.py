"""Adapter admission gates (architecture §13.1) for control-plane benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bencheval.benchmark_registry import load_benchmark_catalog
from bencheval.bfcl_native_adapter import BFCL_ADAPTER_ID
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root
from bencheval.slice_manifest import (
    default_slices_dir,
    list_slice_manifest_paths,
    load_slice_manifest,
    slice_instance_ids,
)
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
        matches = []
        for path in list_slice_manifest_paths(default_slices_dir()):
            manifest = load_slice_manifest(path)
            if manifest.slice.benchmark_id == benchmark_id and manifest.slice.id == slice_id:
                matches.append((manifest, path))
    except BenchEvalError as exc:
        return False, str(exc)
    if not matches:
        return False, f"no typed slice {slice_id!r} for {benchmark_id!r}"
    match, path = matches[0]
    try:
        ids = slice_instance_ids(match, path)
    except BenchEvalError as exc:
        return False, str(exc)
    if not ids:
        return False, f"slice {slice_id} has no instance ids"
    source = "inline" if match.slice.instances_source is None else match.slice.instances_source
    return True, f"slice {slice_id} source={source} count={len(ids)}"


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


def assess_software_wiring(
    *,
    benchmark_id: str,
    adapter_id: str,
    slice_id: str,
    adapter_module_relpath: str,
    adapter_check_name: str,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Tier-0 software wiring only (catalog row + slice ids + module files).

    ``passed`` means files and catalog wiring exist — not native CLI availability,
    score parsing, version capture, or a live Phase B evidence row. Do not treat
    this as Production v1 / Tier 1 adapter admission.
    """
    root = repo_root or _repo_root()
    catalog = load_benchmark_catalog()
    benchmark = next((b for b in catalog.benchmarks if b.id == benchmark_id), None)
    checks: list[tuple[str, bool, str]] = []
    if benchmark is None:
        checks.append(("benchmark_catalog", False, f"{benchmark_id} not in catalog"))
        return AdapterAdmissionReport(adapter_id, benchmark_id, False, tuple(checks))

    checks.append(
        (
            "catalog_adapter_status",
            benchmark.adapter_status == "manifest_available",
            f"status={benchmark.adapter_status}",
        ),
    )
    checks.append(
        (
            "catalog_executable",
            bool(benchmark.executable),
            f"executable={benchmark.executable}",
        ),
    )
    slice_ok, slice_detail = _check_slice_manifest(benchmark_id, slice_id)
    checks.append((f"typed_slice_{slice_id}", slice_ok, slice_detail))

    adapter_module = root / adapter_module_relpath
    adapter_ok = adapter_module.is_file()
    checks.append(
        (
            adapter_check_name,
            adapter_ok,
            adapter_module_relpath if adapter_ok else str(adapter_module),
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

    required_checks = (
        "catalog_adapter_status",
        "catalog_executable",
        f"typed_slice_{slice_id}",
        adapter_check_name,
        "control_plane_executor",
    )
    passed = all(ok for name, ok, _ in checks if name in required_checks)
    return AdapterAdmissionReport(adapter_id, benchmark_id, passed, tuple(checks))


def assess_swebench_pro_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Software wiring for swe-bench-pro (see ``assess_software_wiring``)."""
    return assess_software_wiring(
        benchmark_id="swe-bench-pro",
        adapter_id="swebench-pro-harbor",
        slice_id="smoke",
        adapter_module_relpath="src/bencheval/swebench_pro_harbor.py",
        adapter_check_name="swebench_pro_adapter_module",
        repo_root=repo_root,
    )


def assess_gpqa_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Software wiring for gpqa-diamond (see ``assess_software_wiring``)."""
    return assess_software_wiring(
        benchmark_id="gpqa-diamond",
        adapter_id="gpqa",
        slice_id="smoke",
        adapter_module_relpath="src/bencheval/gpqa_adapter.py",
        adapter_check_name="gpqa_adapter_module",
        repo_root=repo_root,
    )


def assess_hle_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Software wiring for hle (see ``assess_software_wiring``)."""
    return assess_software_wiring(
        benchmark_id="hle",
        adapter_id="hle",
        slice_id="smoke",
        adapter_module_relpath="src/bencheval/hle_adapter.py",
        adapter_check_name="hle_adapter_module",
        repo_root=repo_root,
    )


def assess_cybergym_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Software wiring for cybergym WIP module (not executable; see notes)."""
    return assess_software_wiring(
        benchmark_id="cybergym",
        adapter_id="cybergym",
        slice_id="smoke",
        adapter_module_relpath="src/bencheval/cybergym_adapter.py",
        adapter_check_name="cybergym_adapter_module",
        repo_root=repo_root,
    )


def assess_exploitgym_admission(
    *,
    repo_root: Path | None = None,
) -> AdapterAdmissionReport:
    """Software wiring for exploitgym (see ``assess_software_wiring``)."""
    return assess_software_wiring(
        benchmark_id="exploitgym",
        adapter_id="exploitgym",
        slice_id="smoke",
        adapter_module_relpath="src/bencheval/exploitgym_adapter.py",
        adapter_check_name="exploitgym_adapter_module",
        repo_root=repo_root,
    )
