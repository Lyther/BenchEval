from notes import read_note


def test_read_welcome() -> None:
    assert "BenchEval" in read_note("welcome")


def test_read_roadmap() -> None:
    assert "Core-8" in read_note("roadmap")
