from normalize import parse_tokens


def sum_line(line: str) -> int:
    return sum(parse_tokens(line))
