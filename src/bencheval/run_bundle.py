"""Reproducible run bundle export (evidence + report + raw artifacts)."""

from __future__ import annotations

import hashlib
import json
import os
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
# Strip URI userinfo (user:pass@host) without touching ordinary public endpoints.
_URI_USERINFO_PATTERN = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/\s\"'@]+@)",
)
# Secret-indicator words only count when not embedded in a larger alphanumeric
# word, so benign strings like "tokenizer" survive while "api_key" still trips.
_SECRET_SUBSTRING_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(_SECRET_SUBSTRINGS) + r")(?![a-z0-9])",
    re.IGNORECASE,
)
# Query parameters that carry signatures or credentials (URLs and plain k=v).
_SENSITIVE_QUERY_PATTERN = re.compile(
    r"\b(x-amz-signature|x-amz-credential|x-amz-security-token|access_token|api_key|apikey"
    r"|signature|password|secret|token|sig|key)=([^\s&\"']+)",
    re.IGNORECASE,
)
_GITHUB_TOKEN_PATTERN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b",
)
_AWS_KEY_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SLACK_TOKEN_PATTERN = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?\b")
_PRIVATE_KEY_BLOCK_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_PRIVATE_KEY_MARKER_PATTERN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_ENV_ASSIGNMENT_PATTERN = re.compile(r"(^|[\s\"'])([A-Za-z_][A-Za-z0-9_]*)=([^\s\"']+)")
_SECRET_NAME_PATTERN = re.compile(
    r"key|token|secret|password|passwd|credential|proxy",
    re.IGNORECASE,
)
_EXTRA_SECRET_MIN_LEN = 8


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


def _redact_env_assignments(value: str) -> str:
    """Redact ``NAME=value`` pairs whose NAME looks secret-bearing."""

    def repl(match: re.Match[str]) -> str:
        prefix, name = match.group(1), match.group(2)
        if _SECRET_NAME_PATTERN.search(name):
            return f"{prefix}{name}=[redacted]"
        return match.group(0)

    return _ENV_ASSIGNMENT_PATTERN.sub(repl, value)


def _redact_string(value: str, *, extra_secrets: tuple[str, ...] = ()) -> str:
    """Fail-closed redaction for public export.

    Whole-string rules (sk-*, secret-indicator words, absolute paths) preserve the
    historical behavior; in-place rules strip URI userinfo, signed/credential query
    params, common token formats, and secret-looking env assignments while leaving
    the public remainder of the string intact. ``extra_secrets`` are caller-supplied
    literal values (e.g. process env secrets) scrubbed wherever they occur.
    """
    for secret in extra_secrets:
        if len(secret) >= _EXTRA_SECRET_MIN_LEN:
            value = value.replace(secret, "[redacted]")
    if _SK_PATTERN.search(value):
        return "[redacted]"
    if _URI_USERINFO_PATTERN.search(value):
        value = _URI_USERINFO_PATTERN.sub(r"\g<scheme>", value)
    if _SECRET_SUBSTRING_PATTERN.search(value):
        return "[redacted]"
    if value.startswith("/") or ":\\" in value:
        return "[redacted-path]"
    if _ABS_PATH_PATTERN.search(value):
        return "[redacted-path]"
    value = _SENSITIVE_QUERY_PATTERN.sub(r"\1=[redacted]", value)
    value = _GITHUB_TOKEN_PATTERN.sub("[redacted]", value)
    value = _AWS_KEY_PATTERN.sub("[redacted]", value)
    value = _SLACK_TOKEN_PATTERN.sub("[redacted]", value)
    value = _JWT_PATTERN.sub("[redacted]", value)
    value = _PRIVATE_KEY_BLOCK_PATTERN.sub("[redacted]", value)
    if _PRIVATE_KEY_MARKER_PATTERN.search(value):
        # Unterminated key block: ambiguous, fail closed.
        return "[redacted]"
    return _redact_env_assignments(value)


def _env_secret_values() -> tuple[str, ...]:
    """Values of process env vars with secret-looking names.

    Deterministic (sorted) and never logged; used so public export scrubs live
    credential values even when their shape is not a known token format.
    """
    values = {
        value
        for name, value in os.environ.items()
        if len(value) >= _EXTRA_SECRET_MIN_LEN and _SECRET_NAME_PATTERN.search(name)
    }
    return tuple(sorted(values))


def _sanitize_json_value(value: JsonValue, *, extra_secrets: tuple[str, ...] = ()) -> JsonValue:
    if isinstance(value, str):
        return _redact_string(value, extra_secrets=extra_secrets)
    if isinstance(value, dict):
        return {
            str(k): _sanitize_json_value(v, extra_secrets=extra_secrets) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(v, extra_secrets=extra_secrets) for v in value]
    return value


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
    if raw_dir is not None and _paths_nest_or_equal(raw_dir.resolve(), bundle_root):
        raise BenchEvalError(
            "bundle output_dir must not equal or nest under/inside raw_dir "
            f"(raw_dir={raw_dir.resolve()}, output_dir={bundle_root})",
        )
    if bundle_root.exists() and any(bundle_root.iterdir()):
        raise BenchEvalError(
            f"bundle output directory must be empty or missing: {bundle_root}",
        )
    bundle_root.mkdir(parents=True, exist_ok=True)

    evidence_copy = bundle_root / "evidence.jsonl"
    _write_evidence_copy(
        records,
        evidence_copy,
        redaction=redaction,
        extra_secrets=public_secrets,
    )

    report_md = generate_evidence_report_with_runtime_panel(records)
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
    axes = _run_axes(records)
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
