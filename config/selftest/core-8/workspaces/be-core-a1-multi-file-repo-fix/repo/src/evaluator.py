from tokenizer import tokenize


def sum_tokens(line: str) -> int:
    tokens = tokenize(line)
    return sum(int(token) for token in tokens)
