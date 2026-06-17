import pytest
from shipkit import Parcel, RateQuote, ShipKitError, compute_rate, list_service_zones


def test_list_service_zones() -> None:
    assert list_service_zones() == ["local", "regional", "national"]


def test_compute_rate_local_small_parcel() -> None:
    parcel = Parcel(weight_oz=10, length_in=8, width_in=6, height_in=4)
    quote = compute_rate(parcel, "local")
    assert isinstance(quote, RateQuote)
    assert quote.zone == "local"
    assert quote.rate_cents == 950
    assert quote.billable_weight_oz == 10


def test_compute_rate_rejects_invalid_weight() -> None:
    parcel = Parcel(weight_oz=0, length_in=8, width_in=6, height_in=4)
    with pytest.raises(ShipKitError, match="weight must be positive"):
        compute_rate(parcel, "local")
