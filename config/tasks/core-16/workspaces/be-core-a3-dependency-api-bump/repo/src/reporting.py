"""Reporting helpers not exercised by visible tests."""

from strutil import split_fields


def field_count(line: str) -> int:
    return len(split_fields(line, delimiter="|"))
