"""F001: public export-run must not leak sk- keys, absolute paths, host, artifact_paths."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from bencheval.evidence import JsonlEvidenceSink
from bencheval.run_bundle import export_run_bundle
from tests.factories import make_control_plane_evidence_record as _cp_record


def test_public_bundle_redacts_secrets_paths_and_metadata(tmp_path: Path) -> None:
    evidence = tmp_path / "ev.jsonl"
    row = _cp_record(instance_id="tb-001").model_copy(
        update={
            "artifact_paths": ["/secret/abs/path/to/artifact.log"],
            "verifier_log_path": "/var/tmp/verifier.log",
            "adapter_metadata": {"command": "run --key sk-bytellm-demo-2026"},
            "native_score": {"detail": "sk-leak-in-score"},
        },
    )
    JsonlEvidenceSink().append_jsonl(evidence, row)
    compare_src = tmp_path / "compare.md"
    compare_src.write_text(
        f"host={socket.gethostname()}\npath={evidence}\n",
        encoding="utf-8",
    )
    bundle_dir = tmp_path / "pub"
    export_run_bundle(
        evidence_path=evidence,
        output_dir=bundle_dir,
        redaction="public",
        compare_report_path=compare_src,
    )
    blob = "\n".join(
        [
            (bundle_dir / "evidence.jsonl").read_text(encoding="utf-8"),
            (bundle_dir / "SUMMARY.md").read_text(encoding="utf-8"),
            (bundle_dir / "manifest.json").read_text(encoding="utf-8"),
            (bundle_dir / "compare_report.md").read_text(encoding="utf-8")
            if (bundle_dir / "compare_report.md").exists()
            else "",
        ],
    )
    assert "sk-bytellm-demo-2026" not in blob
    assert "sk-leak-in-score" not in blob
    assert "/secret/abs/path" not in blob
    assert "/var/tmp/verifier" not in blob
    assert socket.gethostname() not in (bundle_dir / "manifest.json").read_text(encoding="utf-8")
    ev_lines = (bundle_dir / "evidence.jsonl").read_text(encoding="utf-8")
    parsed = json.loads(ev_lines.strip().splitlines()[0])
    assert parsed.get("artifact_paths") == []
    assert parsed.get("native_score") == {}
