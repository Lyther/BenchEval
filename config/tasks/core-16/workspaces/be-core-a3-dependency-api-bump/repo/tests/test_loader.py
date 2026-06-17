from loader import load_records


def test_load_records_smoke() -> None:
    rows = load_records("a,b\nc,d")
    assert rows == [["a", "b"], ["c", "d"]]
