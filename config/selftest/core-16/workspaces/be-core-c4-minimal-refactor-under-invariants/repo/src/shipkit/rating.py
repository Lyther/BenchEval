"""Rate computation with duplicated inline validation."""

from shipkit.models import Parcel, RateQuote, ShipKitError

_BASE_RATE = {"local": 500, "regional": 800, "national": 1200}


def compute_rate(parcel: Parcel, dest_zone: str) -> RateQuote:
    if parcel.weight_oz <= 0:
        raise ShipKitError("weight must be positive")
    if parcel.length_in <= 0 or parcel.width_in <= 0 or parcel.height_in <= 0:
        raise ShipKitError("dimensions must be positive")
    weight = int(parcel.weight_oz)
    if weight > 1000:
        raise ShipKitError("weight exceeds limit")

    zone = dest_zone.strip().lower()
    if not zone:
        raise ShipKitError("zone required")
    if zone not in _BASE_RATE:
        raise ShipKitError("unknown zone")

    dim_weight = (parcel.length_in * parcel.width_in * parcel.height_in) // 166
    billable = max(weight, dim_weight)
    rate = _BASE_RATE[zone] + (billable - 1) * 50
    return RateQuote(zone=zone, rate_cents=rate, billable_weight_oz=billable)
