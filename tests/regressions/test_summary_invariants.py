"""Regression: architecture §6 summary row invariants (post /arch review)."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from bencheval.models import ManifestDigest
from tests.factories import make_summary_row


def test_rejects_resolved_gt_n_samples() -> None:
    with pytest.raises(ValueError, match="resolved cannot be greater than n_samples"):
        make_summary_row(resolved=600, n_samples=500, resolved_rate=0.6)


def test_rejects_resolved_rate_not_equal_ratio() -> None:
    with pytest.raises(ValueError, match="resolved_rate must equal resolved / n_samples"):
        make_summary_row(n_samples=100, resolved=30, resolved_rate=0.5)


def test_n_samples_zero_requires_zero_resolved_and_rate() -> None:
    with pytest.raises(ValueError, match="resolved must be 0"):
        make_summary_row(n_samples=0, resolved=1, resolved_rate=0.0)
    with pytest.raises(ValueError, match="resolved_rate must be 0"):
        make_summary_row(n_samples=0, resolved=0, resolved_rate=0.1)
    row = make_summary_row(
        n_samples=0,
        resolved=0,
        resolved_rate=0.0,
        actual_cost_usd=Decimal(0),
    )
    assert row.n_samples == 0


def test_manifest_digest_rejects_empty_task_ids() -> None:
    with pytest.raises(ValidationError):
        ManifestDigest(
            benchmark="x",
            manifest_path="config/manifests/x.txt",
            content_sha256="a" * 64,
            task_ids=(),
        )


def test_summary_json_mode_serializes_decimal_cost_as_string() -> None:
    row = make_summary_row()
    payload = row.model_dump(mode="json")
    assert isinstance(payload["actual_cost_usd"], str)
    assert Decimal(payload["actual_cost_usd"]) == Decimal("1.23")


def test_inspect_swe_version_required_when_solver_is_inspect_swe() -> None:
    with pytest.raises(ValueError, match="inspect_swe_version is required"):
        make_summary_row(solver="inspect_swe.claude_code", inspect_swe_version=None)


def test_inspect_swe_version_forbidden_when_solver_not_inspect_swe() -> None:
    with pytest.raises(ValueError, match="inspect_swe_version must be null"):
        make_summary_row(
            solver="inspect_ai.builtin",
            solver_version="1.0.0",
            inspect_swe_version="0.2.47",
        )


def test_positive_experimental_lane_estimate_cost_xor() -> None:
    row = make_summary_row(
        auth_lane="experimental_cursor",
        actual_cost_usd=None,
        estimated_api_equivalent_usd=Decimal("12.34"),
        solver="cursor_cli",
        solver_version="cursor-agent@1.0.0",
        inspect_swe_version=None,
    )
    assert row.actual_cost_usd is None
    assert row.estimated_api_equivalent_usd == Decimal("12.34")
    assert row.auth_lane == "experimental_cursor"


def test_baseline_lane_rejects_estimate_only_cost() -> None:
    with pytest.raises(ValueError, match="baseline_.* auth lane requires actual_cost_usd"):
        make_summary_row(
            auth_lane="baseline_api",
            actual_cost_usd=None,
            estimated_api_equivalent_usd=Decimal("12.34"),
        )


def test_experimental_lane_rejects_actual_cost() -> None:
    pattern = "experimental_.* auth lane must leave actual_cost_usd null"
    with pytest.raises(ValueError, match=pattern):
        make_summary_row(
            auth_lane="experimental_cursor",
            actual_cost_usd=Decimal("1.23"),
            estimated_api_equivalent_usd=None,
            solver="cursor_cli",
            solver_version="cursor-agent@1.0.0",
            inspect_swe_version=None,
        )


def test_unknown_auth_lane_prefix_rejected() -> None:
    with pytest.raises(ValueError, match="auth_lane must start with"):
        make_summary_row(auth_lane="sandbox_whatever")


def test_inspect_swe_solver_version_must_equal_inspect_swe_version() -> None:
    with pytest.raises(ValueError, match="solver_version must equal inspect_swe_version"):
        make_summary_row(
            solver="inspect_swe.claude_code",
            solver_version="bogus-version",
            inspect_swe_version="0.2.47",
        )
