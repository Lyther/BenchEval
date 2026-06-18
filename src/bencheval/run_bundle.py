"""Reproducible run bundle export (evidence + report + raw artifacts)."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import socket
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.report import generate_evidence_report_with_runtime_panel

RedactionMode = Literal["public", "private"]

_SECRET_SUBSTRINGS = (
    "api_key",
    "api-key",
    "secret",
    "token",
    "password",
    "authorization",
    "bearer",
)

_SK_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_ABS_PATH_PATTERN = re.compile(r"(?:^|[\s\"'=])(/[\w./-]+)")


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
                timeout=15,
            )
            line = (proc.stdout or proc.stderr or "").strip().splitlines()
            if line:
                versions[binary] = line[0][:200]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return versions


def _redact_string(value: str) -> str:
    if _SK_PATTERN.search(value):
        return "[redacted]"
    if any(s in value.lower() for s in _SECRET_SUBSTRINGS):
        return "[redacted]"
    if value.startswith("/") or ":\\" in value:
        return "[redacted-path]"
    if _ABS_PATH_PATTERN.search(value):
        return "[redacted-path]"
    return value


def _sanitize_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {str(k): _sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(v) for v in value]
    return value


def _redact_record(record: EvidenceRecord) -> EvidenceRecord:
    data = record.model_dump(mode="json")
    data["artifact_paths"] = []
    data["native_score"] = {}
    data["verifier_log_path"] = None
    data = _sanitize_json_value(data)
    return EvidenceRecord.model_validate(data)


def _write_evidence_copy(
    records: list[EvidenceRecord],
    dest: Path,
    *,
    redaction: RedactionMode,
) -> None:
    rows = records if redaction == "private" else [_redact_record(r) for r in records]
    lines = [r.model_dump_json() for r in rows]
    dest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _run_axes(records: list[EvidenceRecord]) -> dict[str, str | None]:
    if not records:
        return {}
    keys = (
        "benchmark_id",
        "slice_id",
        "runtime_id",
        "model_id",
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


def _redact_compare_markdown(text: str) -> str:
    lines = [_redact_string(line) for line in text.splitlines()]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


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
    bundle_root = output_dir.resolve()
    if bundle_root.exists() and any(bundle_root.iterdir()):
        raise BenchEvalError(
            f"bundle output directory must be empty or missing: {bundle_root}",
        )
    bundle_root.mkdir(parents=True, exist_ok=True)

    evidence_copy = bundle_root / "evidence.jsonl"
    _write_evidence_copy(records, evidence_copy, redaction=redaction)

    report_md = generate_evidence_report_with_runtime_panel(records)
    if redaction == "public":
        report_md = _redact_compare_markdown(report_md)
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
    axes = _run_axes(records)
    if axes:
        summary_lines.append("## Run axes")
        summary_lines.append("")
        for key, val in sorted(axes.items()):
            summary_lines.append(f"- {key}: `{val}`")
        summary_lines.append("")

    if raw_dir is not None:
        if redaction == "public":
            summary_lines.append(
                "- Raw artifacts: omitted in `public` redaction mode "
                "(use `--redaction private` for full raw tree).",
            )
            summary_lines.append("")
        else:
            src = raw_dir.resolve()
            if src.is_dir():
                skipped_raw = _copy_raw_tree(src, bundle_root / "raw")
                if skipped_raw:
                    (bundle_root / "raw_skipped.txt").write_text(
                        "\n".join(skipped_raw) + "\n",
                        encoding="utf-8",
                    )
                    summary_lines.append(
                        f"- Raw artifacts skipped: {len(skipped_raw)} (see `raw_skipped.txt`).",
                    )
                    summary_lines.append("")

    (bundle_root / "SUMMARY.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    if compare_report_path is not None and compare_report_path.is_file():
        compare_text = compare_report_path.read_text(encoding="utf-8")
        if redaction == "public":
            compare_text = _redact_compare_markdown(compare_text)
        (bundle_root / "compare_report.md").write_text(compare_text, encoding="utf-8")

    raw_skipped_path = bundle_root / "raw_skipped.txt"
    raw_skipped_count = (
        len(raw_skipped_path.read_text(encoding="utf-8").splitlines())
        if raw_skipped_path.is_file()
        else 0
    )
    manifest: dict[str, object] = {
        "schema_version": "run_bundle_v1",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "record_count": len(records),
        "redaction": redaction,
        "axes": axes,
        "tool_versions": _collect_tool_versions(),
        "compare": {
            "baseline": "baseline.jsonl" if compare_baseline else None,
            "current": "current.jsonl" if compare_current else None,
        },
        "raw_skipped_count": raw_skipped_count,
    }
    if redaction == "private":
        manifest["host"] = socket.gethostname()
        manifest["evidence_source"] = str(evidence_path)
        if compare_baseline:
            manifest["compare"] = {
                "baseline": str(compare_baseline.resolve()),
                "current": str(compare_current.resolve()) if compare_current else None,
            }
    (bundle_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    checksum_lines: list[str] = []
    for path in sorted(bundle_root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            rel = path.relative_to(bundle_root).as_posix()
            checksum_lines.append(f"{_sha256_file(path)}  {rel}")
    (bundle_root / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    archive = bundle_root.parent / f"{bundle_root.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(bundle_root, arcname=bundle_root.name)
    return archive


__all__ = ["RedactionMode", "export_run_bundle"]
