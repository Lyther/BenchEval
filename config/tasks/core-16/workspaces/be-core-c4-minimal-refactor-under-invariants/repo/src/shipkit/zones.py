"""Zone listing with duplicated inline validation."""

from shipkit.models import ShipKitError

_ZONES = ("local", "regional", "national")


def list_service_zones() -> list[str]:
    return list(_ZONES)


def _zone_index(zone: str) -> int:
    normalized = zone.strip().lower()
    if not normalized:
        raise ShipKitError("zone required")
    try:
        return _ZONES.index(normalized)
    except ValueError as exc:
        raise ShipKitError("unknown zone") from exc
