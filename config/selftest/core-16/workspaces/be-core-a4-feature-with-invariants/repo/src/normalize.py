def parse_tokens(line: str) -> list[int]:
    parts = line.split()
    return [int(part) for part in parts if part]
