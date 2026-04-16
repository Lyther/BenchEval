"""Offline summary builder: ``header`` is a ``Mapping[str, JsonValue]``, not an ``.eval`` file."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from pydantic import JsonValue, ValidationError

from bencheval.exceptions import SummaryValidationError
from bencheval.models import ManifestDigest, ModelFamily, RunStamp, SummaryRow

_REPO_ROOT = Path(__file__).resolve().parents[2]

_REQUIRED_HEADER_KEYS: tuple[str, ...] = (
    "model",
    "model_snapshot",
    "solver",
    "solver_version",
    "inspect_version",
    "inspect_swe_version",
    "reasoning_effort_requested",
    "reasoning_tokens_requested",
    "reasoning_effort_honored",
    "reasoning_tokens_honored",
    "provider_model_args",
    "n_samples",
    "resolved",
    "resolved_rate",
    "total_tokens",
    "wall_time_s",
    "actual_cost_usd",
    "estimated_api_equivalent_usd",
    "timestamp",
)


def _require(header: Mapping[str, JsonValue], key: str) -> JsonValue:
    if key not in header:
        raise SummaryValidationError(f"missing required header key: {key}")
    return header[key]


def _derive_family(model: str) -> ModelFamily:
    if "/" not in model:
        return ModelFamily.LOCAL
    prefix, _, _ = model.partition("/")
    if prefix == "anthropic":
        return ModelFamily.ANTHROPIC
    if prefix == "openai":
        return ModelFamily.OPENAI
    if prefix == "moonshot":
        return ModelFamily.MOONSHOT
    return ModelFamily.LOCAL


def _parse_timestamp(value: JsonValue) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(s)
        except ValueError as e:
            raise SummaryValidationError(f"invalid timestamp: {value!r}") from e
    raise SummaryValidationError(f"timestamp must be str or datetime, got {type(value).__name__}")


def _parse_decimal(value: JsonValue) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise SummaryValidationError("decimal fields cannot be bool")
    if isinstance(value, (str, int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation as e:
            raise SummaryValidationError(f"invalid decimal value: {value!r}") from e
    raise SummaryValidationError(
        f"decimal fields must be str, int, float, or null, got {type(value).__name__}",
    )


def _derive_log_file(path: Path) -> str:
    repo = _REPO_ROOT.resolve()
    resolved = path.resolve()
    raw_dir = (repo / "results" / "raw").resolve()
    try:
        rel_in_raw = resolved.relative_to(raw_dir)
    except ValueError:
        return resolved.as_posix()
    return (Path("results") / "raw" / rel_in_raw).as_posix()


class StrictSummaryBuilder:
    """Strict, offline mapping from header dict + stamp + manifest → ``SummaryRow``."""

    def build(
        self,
        eval_log_path: Path,
        stamp: RunStamp,
        manifest: ManifestDigest,
        header: Mapping[str, JsonValue],
    ) -> SummaryRow:
        if stamp.task_manifest_hash != manifest.content_sha256:
            raise SummaryValidationError(
                "task_manifest_hash does not match manifest.content_sha256",
            )

        for key in _REQUIRED_HEADER_KEYS:
            _require(header, key)

        model = cast("str", _require(header, "model"))
        if not isinstance(model, str):
            raise SummaryValidationError("header['model'] must be a string")

        derived_family = _derive_family(model)
        if derived_family != stamp.model_family:
            raise SummaryValidationError(
                f"model_family mismatch: derived {derived_family!s} from model prefix, "
                f"stamp has {stamp.model_family!s}",
            )

        provider_raw = _require(header, "provider_model_args")
        if not isinstance(provider_raw, dict):
            raise SummaryValidationError("header['provider_model_args'] must be an object")
        provider_model_args = cast("dict[str, JsonValue]", provider_raw)

        timestamp = _parse_timestamp(_require(header, "timestamp"))
        actual_cost = _parse_decimal(_require(header, "actual_cost_usd"))
        estimated_cost = _parse_decimal(_require(header, "estimated_api_equivalent_usd"))

        log_file = _derive_log_file(eval_log_path)

        def _str_field(k: str) -> str:
            v = _require(header, k)
            if not isinstance(v, str):
                raise SummaryValidationError(f"header[{k!r}] must be a string")
            return v

        def _opt_str(k: str) -> str | None:
            v = _require(header, k)
            if v is None:
                return None
            if not isinstance(v, str):
                raise SummaryValidationError(f"header[{k!r}] must be a string or null")
            return v

        def _opt_int(k: str) -> int | None:
            v = _require(header, k)
            if v is None:
                return None
            if isinstance(v, bool) or not isinstance(v, int):
                raise SummaryValidationError(f"header[{k!r}] must be an integer or null")
            return v

        def _int_field(k: str) -> int:
            v = _require(header, k)
            if isinstance(v, bool) or not isinstance(v, int):
                raise SummaryValidationError(f"header[{k!r}] must be an integer")
            return v

        def _float_field(k: str) -> float:
            v = _require(header, k)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise SummaryValidationError(f"header[{k!r}] must be a number")
            return float(v)

        kwargs: dict[str, object] = {
            "timestamp": timestamp,
            "benchmark": manifest.benchmark,
            "benchmark_revision": stamp.benchmark_revision,
            "task_manifest_hash": stamp.task_manifest_hash,
            "model": model,
            "model_snapshot": _str_field("model_snapshot"),
            "model_family": stamp.model_family,
            "solver": _str_field("solver"),
            "solver_version": _str_field("solver_version"),
            "auth_lane": stamp.auth_lane,
            "reasoning_effort_requested": _opt_str("reasoning_effort_requested"),
            "reasoning_tokens_requested": _opt_int("reasoning_tokens_requested"),
            "reasoning_effort_honored": _opt_str("reasoning_effort_honored"),
            "reasoning_tokens_honored": _opt_int("reasoning_tokens_honored"),
            "provider_model_args": provider_model_args,
            "n_samples": _int_field("n_samples"),
            "resolved": _int_field("resolved"),
            "resolved_rate": _float_field("resolved_rate"),
            "total_tokens": _int_field("total_tokens"),
            "wall_time_s": _float_field("wall_time_s"),
            "actual_cost_usd": actual_cost,
            "estimated_api_equivalent_usd": estimated_cost,
            "inspect_version": _str_field("inspect_version"),
            "inspect_swe_version": _opt_str("inspect_swe_version"),
            "log_file": log_file,
        }

        try:
            return SummaryRow(**kwargs)
        except ValidationError as e:
            raise SummaryValidationError(str(e)) from e
