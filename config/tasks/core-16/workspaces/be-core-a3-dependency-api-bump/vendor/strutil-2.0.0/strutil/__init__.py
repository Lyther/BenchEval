"""String field utilities v2."""


def parse_fields(text: str, *, delim: str = ",") -> list[str]:
    if delim not in text:
        return [text.strip()] if text.strip() else []
    return [part.strip() for part in text.split(delim)]
