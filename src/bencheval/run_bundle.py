"""Reproducible run bundle export (evidence + report + raw artifacts)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError

# The redaction pipeline lives in bencheval.redaction (shared with preflight and
# other local-artifact writers); these private aliases preserve this module's
# historical internal/test surface.
from bencheval.redaction import env_secret_values as _env_secret_values
from bencheval.redaction import redact_string as _redact_string
from bencheval.redaction import sanitize_json_value as _sanitize_json_value
from bencheval.report import generate_evidence_report_with_runtime_panel

RedactionMode = Literal["public", "private"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": platform.python_version()}
    commands = (
        ("harbor", ("--version",)),
        ("uv", ("--version",)),
        ("bfcl", ("version",)),
    )
    for binary, args in commands:
        try:
            proc = subprocess.run(
                [binary, *args],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            line = (proc.stdout or proc.stderr or "").strip().splitlines()
            if line:
                versions[binary] = line[0][:200]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return versions


def _redact_record(
    record: EvidenceRecord,
    *,
    extra_secrets: tuple[str, ...] = (),
) -> EvidenceRecord:
    data = record.model_dump(mode="json")
    data["artifact_paths"] = []
    data["native_score"] = {}
    data["verifier_log_path"] = None
    data = _sanitize_json_value(data, extra_secrets=extra_secrets)
    return EvidenceRecord.model_validate(data)


def _write_evidence_copy(
    records: list[EvidenceRecord],
    dest: Path,
    *,
    redaction: RedactionMode,
    extra_secrets: tuple[str, ...] = (),
) -> None:
    if redaction == "private":
        rows = records
    else:
        rows = [_redact_record(r, extra_secrets=extra_secrets) for r in records]
    lines = [r.model_dump_json() for r in rows]
    dest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _bundle_local_artifact_path(
    value: str,
    *,
    raw_root: Path,
    capture_root: Path,
) -> str:
    """Map an absolute run-owned artifact path to its location in the bundle."""
    path = Path(value)
    if not path.is_absolute():
        return value
    # Collapse lexical ``..`` segments without following symlinks so an
    # untrusted evidence string cannot become a bundle-relative traversal.
    path = Path(os.path.abspath(path))
    for source, destination in ((raw_root, Path("raw")), (capture_root, Path("capture"))):
        try:
            relative = path.relative_to(source)
        except ValueError:
            continue
        return (destination / relative).as_posix()
    return value


def _relocate_private_artifact_paths(
    records: list[EvidenceRecord],
    *,
    raw_root: Path,
    capture_root: Path,
) -> list[EvidenceRecord]:
    """Return private-bundle rows whose copied artifacts use portable paths."""
    relocated: list[EvidenceRecord] = []
    for record in records:
        verifier_log_path = record.verifier_log_path
        if verifier_log_path is not None:
            verifier_log_path = _bundle_local_artifact_path(
                verifier_log_path,
                raw_root=raw_root,
                capture_root=capture_root,
            )
        relocated.append(
            record.model_copy(
                update={
                    "artifact_paths": [
                        _bundle_local_artifact_path(
                            path,
                            raw_root=raw_root,
                            capture_root=capture_root,
                        )
                        for path in record.artifact_paths
                    ],
                    "verifier_log_path": verifier_log_path,
                },
            ),
        )
    return relocated


def _records_reference_root(records: list[EvidenceRecord], root: Path) -> bool:
    """Whether any evidence artifact path is lexically contained by ``root``."""
    for record in records:
        values = [*record.artifact_paths]
        if record.verifier_log_path is not None:
            values.append(record.verifier_log_path)
        for value in values:
            path = Path(value)
            if not path.is_absolute():
                continue
            try:
                Path(os.path.abspath(path)).relative_to(root)
            except ValueError:
                continue
            return True
    return False


def _run_axes(records: list[EvidenceRecord]) -> dict[str, str | None]:
    if not records:
        return {}
    keys = (
        "benchmark_id",
        "slice_id",
        "runtime_id",
        "model_id",
        "provider_id",
        "provider_config_hash",
        "judge_model_id",
        "adapter_id",
        "harness_kind",
        "harness_version",
    )

    def axis(name: str) -> str | None:
        vals = {getattr(r, name) for r in records if getattr(r, name)}
        if len(vals) == 1:
            return next(iter(vals))
        return None

    return {k: axis(k) for k in keys}


def _redact_compare_markdown(text: str, *, extra_secrets: tuple[str, ...] = ()) -> str:
    lines = [_redact_string(line, extra_secrets=extra_secrets) for line in text.splitlines()]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


_SECRET_RAW_NAME_MARKERS: frozenset[str] = frozenset(
    {
        ".bencheval-harbor-proxy.env",
        "bencheval-harbor-proxy-",
    },
)


def _is_secret_raw_path(path: Path) -> bool:
    name = path.name
    if name in _SECRET_RAW_NAME_MARKERS:
        return True
    return any(marker in name for marker in _SECRET_RAW_NAME_MARKERS if marker.endswith("-"))


def _paths_nest_or_equal(a: Path, b: Path) -> bool:
    try:
        a.resolve().relative_to(b.resolve())
        return True
    except ValueError:
        pass
    try:
        b.resolve().relative_to(a.resolve())
        return True
    except ValueError:
        return False


def _copy_raw_tree(src: Path, dest: Path) -> list[str]:
    skipped: list[str] = []

    def copy_path(path: Path) -> None:
        rel = path.relative_to(src)
        target = dest / rel
        if path.is_symlink():
            skipped.append(f"{rel.as_posix()}\tsymlink")
            return
        try:
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                for child in path.iterdir():
                    copy_path(child)
                return
            if path.is_file():
                if _is_secret_raw_path(path):
                    skipped.append(f"{rel.as_posix()}\tsecret-bearing")
                    return
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        except OSError as e:
            reason = e.strerror or str(e)
            skipped.append(f"{rel.as_posix()}\t{reason}")

    copy_path(src)
    return skipped


def export_run_bundle(
    *,
    evidence_path: Path,
    output_dir: Path,
    raw_dir: Path | None = None,
    redaction: RedactionMode = "private",
    compare_baseline: Path | None = None,
    compare_current: Path | None = None,
    compare_report_path: Path | None = None,
) -> Path:
    """Materialize bundle directory and return path to ``bundle.tar.gz``."""
    evidence_path = evidence_path.resolve()
    if not evidence_path.is_file():
        raise BenchEvalError(f"evidence file not found: {evidence_path}")

    records = read_evidence_jsonl(evidence_path)
    public_secrets = _env_secret_values() if redaction == "public" else ()
    bundle_root = output_dir.resolve()
    raw_src = raw_dir.resolve() if raw_dir is not None else None
    capture_src = raw_src.parent / f"{raw_src.name}.capture" if raw_src is not None else None
    include_capture = (
        redaction == "private"
        and capture_src is not None
        and _records_reference_root(records, capture_src)
    )
    if raw_src is not None and _paths_nest_or_equal(raw_src, bundle_root):
        raise BenchEvalError(
            "bundle output_dir must not equal or nest under/inside raw_dir "
            f"(raw_dir={raw_src}, output_dir={bundle_root})",
        )
    if include_capture and _paths_nest_or_equal(capture_src, bundle_root):
        raise BenchEvalError(
            "bundle output_dir must not equal or nest under/inside the agent capture tree "
            f"(capture_dir={capture_src}, output_dir={bundle_root})",
        )
    if bundle_root.exists():
        if not bundle_root.is_dir():
            raise BenchEvalError(
                f"bundle output path exists but is not a directory: {bundle_root}",
            )
        try:
            occupied = any(bundle_root.iterdir())
        except OSError as e:
            raise BenchEvalError(
                f"cannot inspect bundle output directory {bundle_root}: {e}",
            ) from e
        if occupied:
            raise BenchEvalError(
                f"bundle output directory must be empty or missing: {bundle_root}",
            )
    try:
        bundle_root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BenchEvalError(
            f"cannot create bundle output directory {bundle_root}: {e}",
        ) from e

    bundle_records = records
    if redaction == "private" and raw_src is not None and capture_src is not None:
        bundle_records = _relocate_private_artifact_paths(
            records,
            raw_root=raw_src,
            capture_root=capture_src,
        )

    evidence_copy = bundle_root / "evidence.jsonl"
    _write_evidence_copy(
        bundle_records,
        evidence_copy,
        redaction=redaction,
        extra_secrets=public_secrets,
    )

    report_md = generate_evidence_report_with_runtime_panel(bundle_records)
    if redaction == "public":
        report_md = _redact_compare_markdown(report_md, extra_secrets=public_secrets)
    (bundle_root / "report.md").write_text(report_md, encoding="utf-8")

    evidence_label = "evidence.jsonl" if redaction == "public" else str(evidence_path)
    summary_lines = [
        "# Run bundle summary",
        "",
        f"- Evidence source: `{evidence_label}`",
        f"- Record count: {len(records)}",
        f"- Redaction: `{redaction}`",
        f"- Generated: {datetime.now(tz=UTC).isoformat()}",
        "",
    ]
    axes = _run_axes(bundle_records)
    if redaction == "public":
        axes = {
            key: (
                _redact_string(value, extra_secrets=public_secrets) if value is not None else None
            )
            for key, value in axes.items()
        }
    if axes:
        summary_lines.append("## Run axes")
        summary_lines.append("")
        for key, val in sorted(axes.items()):
            summary_lines.append(f"- {key}: `{val}`")
        summary_lines.append("")

    if raw_src is not None:
        if redaction == "public":
            summary_lines.append(
                "- Raw artifacts: omitted in `public` redaction mode "
                "(use `--redaction private` for full raw tree).",
            )
            summary_lines.append("")
        else:
            skipped_raw: list[str] = []
            if raw_src.is_dir():
                skipped_raw.extend(_copy_raw_tree(raw_src, bundle_root / "raw"))
            if include_capture and (capture_src.exists() or capture_src.is_symlink()):
                skipped_raw.extend(
                    f"capture/{entry}"
                    for entry in _copy_raw_tree(
                        capture_src,
                        bundle_root / "capture",
                    )
                )
            if skipped_raw:
                (bundle_root / "raw_skipped.txt").write_text(
                    "\n".join(skipped_raw) + "\n",
                    encoding="utf-8",
                )
                summary_lines.append(
                    f"- Raw artifacts skipped: {len(skipped_raw)} (see `raw_skipped.txt`).",
                )
                summary_lines.append("")

    summary_text = "\n".join(summary_lines) + "\n"
    if redaction == "public":
        summary_text = _redact_compare_markdown(summary_text, extra_secrets=public_secrets)
    (bundle_root / "SUMMARY.md").write_text(summary_text, encoding="utf-8")

    if compare_report_path is not None and compare_report_path.is_file():
        compare_text = compare_report_path.read_text(encoding="utf-8")
        if redaction == "public":
            compare_text = _redact_compare_markdown(compare_text, extra_secrets=public_secrets)
        (bundle_root / "compare_report.md").write_text(compare_text, encoding="utf-8")

    compare_manifest: dict[str, str | None] = {"baseline": None, "current": None}
    if (compare_baseline is None) ^ (compare_current is None):
        raise BenchEvalError("compare_baseline and compare_current must be provided together")
    if compare_baseline is not None and compare_current is not None:
        baseline_src = compare_baseline.resolve()
        current_src = compare_current.resolve()
        if not baseline_src.is_file() or not current_src.is_file():
            raise BenchEvalError("compare baseline/current evidence files must exist")
        baseline_rows = read_evidence_jsonl(baseline_src)
        current_rows = read_evidence_jsonl(current_src)
        _write_evidence_copy(
            baseline_rows,
            bundle_root / "baseline.jsonl",
            redaction=redaction,
            extra_secrets=public_secrets,
        )
        _write_evidence_copy(
            current_rows,
            bundle_root / "current.jsonl",
            redaction=redaction,
            extra_secrets=public_secrets,
        )
        compare_manifest = {"baseline": "baseline.jsonl", "current": "current.jsonl"}

    raw_skipped_path = bundle_root / "raw_skipped.txt"
    raw_skipped_count = (
        len(raw_skipped_path.read_text(encoding="utf-8").splitlines())
        if raw_skipped_path.is_file()
        else 0
    )
    tool_versions = _collect_tool_versions()
    if redaction == "public":
        tool_versions = {
            key: _redact_string(value, extra_secrets=public_secrets)
            for key, value in tool_versions.items()
        }
    manifest: dict[str, object] = {
        "schema_version": "run_bundle_v1",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "record_count": len(records),
        "redaction": redaction,
        "axes": axes,
        "tool_versions": tool_versions,
        "compare": compare_manifest,
        "raw_skipped_count": raw_skipped_count,
    }
    if redaction == "private":
        manifest["host"] = socket.gethostname()
        manifest["evidence_source"] = str(evidence_path)
    manifest_text = json.dumps(manifest, indent=2) + "\n"
    if redaction == "public":
        manifest_text = _redact_compare_markdown(manifest_text, extra_secrets=public_secrets)
    (bundle_root / "manifest.json").write_text(manifest_text, encoding="utf-8")

    checksum_lines: list[str] = []
    for path in sorted(bundle_root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            rel = path.relative_to(bundle_root).as_posix()
            checksum_lines.append(f"{_sha256_file(path)}  {rel}")
    (bundle_root / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    archive = bundle_root.parent / f"{bundle_root.name}.tar.gz"
    if archive.exists() or archive.is_symlink():
        raise BenchEvalError(f"bundle archive already exists: {archive}")
    # Exclusive create avoids clobbering an existing file or following a symlink.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(archive, flags, 0o644)
    except FileExistsError as e:
        raise BenchEvalError(f"bundle archive already exists: {archive}") from e
    try:
        with os.fdopen(fd, "wb") as handle, tarfile.open(fileobj=handle, mode="w:gz") as tar:
            tar.add(bundle_root, arcname=bundle_root.name)
    except Exception:
        try:
            archive.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return archive


__all__ = ["RedactionMode", "export_run_bundle"]
