from summarizer import sum_line


def test_sum_line_spaces() -> None:
    assert sum_line("2 3") == 5


def test_sum_line_two_values() -> None:
    assert sum_line("10 5") == 15
