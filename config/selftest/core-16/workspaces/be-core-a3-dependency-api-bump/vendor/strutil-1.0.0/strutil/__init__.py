"""String field utilities v1."""


def split_fields(text: str, delimiter: str = ",") -> list[str]:
    if delimiter not in text:
        return [text.strip()] if text.strip() else []
    return [part.strip() for part in text.split(delimiter)]
