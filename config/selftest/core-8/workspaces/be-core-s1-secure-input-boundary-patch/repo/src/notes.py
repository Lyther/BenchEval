from pathlib import Path

_NOTES_DIR = Path(__file__).resolve().parent.parent / "notes"


def read_note(note_id: str) -> str:
    path = _NOTES_DIR / note_id
    return path.read_text(encoding="utf-8")
