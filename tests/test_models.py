from decimal import Decimal

import pytest

from tests.factories import make_summary_row


def test_summary_cost_xor_rejects_both_null() -> None:
    with pytest.raises(ValueError, match="Exactly one of"):
        make_summary_row(actual_cost_usd=None, estimated_api_equivalent_usd=None)


def test_summary_cost_xor_rejects_both_set() -> None:
    with pytest.raises(ValueError, match="Exactly one of"):
        make_summary_row(
            actual_cost_usd=Decimal(1),
            estimated_api_equivalent_usd=Decimal(2),
        )


def test_summary_accepts_estimate_only() -> None:
    row = make_summary_row(
        auth_lane="experimental_gateway",
        actual_cost_usd=None,
        estimated_api_equivalent_usd=Decimal("4.00"),
    )
    assert row.estimated_api_equivalent_usd == Decimal("4.00")
    assert row.actual_cost_usd is None
