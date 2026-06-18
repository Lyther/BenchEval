from counter import increment


def test_increment_positive() -> None:
    assert increment(1) == 2


def test_increment_zero() -> None:
    assert increment(0) == 1
