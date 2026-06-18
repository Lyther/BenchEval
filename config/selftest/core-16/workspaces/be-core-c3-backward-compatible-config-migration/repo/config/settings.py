"""Load and normalize application configuration from YAML or JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_DEFAULTS: dict[str, Any] = {
    "app_name": "app",
    "debug": False,
    "feature_flags": {},
}


def _read_raw(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return data


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Return canonical config dict with defaults applied."""
    out = dict(_DEFAULTS)
    out.update(raw)
    if not isinstance(out.get("feature_flags"), dict):
        out["feature_flags"] = {}
    return out


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a config file and return normalized settings."""
    return normalize(_read_raw(Path(path)))
