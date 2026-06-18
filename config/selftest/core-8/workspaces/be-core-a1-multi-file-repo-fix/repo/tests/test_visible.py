from evaluator import sum_tokens


def test_sum_tokens_single_spaces() -> None:
    assert sum_tokens("2 2") == 4
