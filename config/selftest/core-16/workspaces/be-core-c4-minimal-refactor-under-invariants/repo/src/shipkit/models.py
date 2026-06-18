from dataclasses import dataclass


@dataclass(frozen=True)
class Parcel:
    weight_oz: int
    length_in: int
    width_in: int
    height_in: int


@dataclass(frozen=True)
class RateQuote:
    zone: str
    rate_cents: int
    billable_weight_oz: int


class ShipKitError(Exception):
    """Raised when parcel or zone inputs are invalid."""
