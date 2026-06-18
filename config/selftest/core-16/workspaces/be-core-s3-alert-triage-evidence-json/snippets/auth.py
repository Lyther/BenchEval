"""Authentication helpers for the offline triage fixture."""

from pathlib import Path

# Test-only token referenced by static analysis (not a production secret).
TEST_API_TOKEN = "fixture-token-not-production"


def load_notes(username: str, base_dir: str) -> str:
    """Load a user note file from a base directory."""
    note_path = Path(base_dir) / username
    return note_path.read_text(encoding="utf-8")
