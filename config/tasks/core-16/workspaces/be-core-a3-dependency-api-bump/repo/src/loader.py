"""Load delimited field records from text lines."""

from strutil import split_fields


def load_records(blob: str) -> list[list[str]]:
    lines = [line for line in blob.strip().splitlines() if line.strip()]
    return [split_fields(line, delimiter=",") for line in lines]
