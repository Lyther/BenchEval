# swe-bench-verified (demoted — not executable)

Catalog row only. Control-plane `run` refuses execution until the official
mini-SWE-agent generation path **and** SWE-bench evaluator are wired end-to-end
(preds → evaluate → per-instance `resolved`).

```bash
# Dry-run / discovery may still resolve the catalog id; live execute is refused.
uv run bencheval run swe-bench-verified --runtime claude-code --model <model-id> --dry-run
```

- **Status:** `executable: false` in `config/benchmarks.yaml`.
- **Smoke slice:** `config/slices/swe-bench-verified-smoke-10.yaml` retained for
  future re-admission.
- **Caveat:** public calibration / contamination risk high.
- **Re-admission bar:** pin supported mini-SWE-agent revision; invoke official
  evaluator; bind evaluation report to the requested instance; capture dataset
  provenance. Until then, do not call this lane a native proof.
