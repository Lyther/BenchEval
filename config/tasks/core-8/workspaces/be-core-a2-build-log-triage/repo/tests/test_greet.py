from greeter import greet


def test_greet_smoke() -> None:
    assert greet("Bench") == "Hello, Bench!"
