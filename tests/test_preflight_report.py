from pathlib import Path

from bencheval.preflight_report import load_preflight_report, write_preflight_report


def test_write_and_load_preflight(tmp_path: Path) -> None:
    path = tmp_path / "swe.json"
    write_preflight_report(
        output_path=path,
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="mini-swe-agent",
        model_id="openai/gpt-test",
        ok=False,
        reasons=["docker not available"],
    )
    loaded = load_preflight_report(path)
    assert loaded["ok"] is False
    assert loaded["reasons"] == ["docker not available"]


def test_preflight_extra_json_values(tmp_path: Path) -> None:
    path = tmp_path / "extra.json"
    write_preflight_report(
        output_path=path,
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
        ok=False,
        extra={"harness": "bfcl-eval", "attempt": 1},
    )
    loaded = load_preflight_report(path)
    assert loaded["extra"] == {"harness": "bfcl-eval", "attempt": 1}
