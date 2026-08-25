# swe-bench-verified (demoted — not executable)

Catalog row only. Control-plane `run` refuses execution until the official mini-SWE-agent generation path **and** SWE-bench evaluator are wired end-to-end (preds → evaluate → per-instance `resolved`).

```bash
# Dry-run / discovery may still resolve the catalog id; live execute is refused.
uv run bencheval run swe-bench-verified --runtime claude-code --model <model-id> --dry-run
```

- **Status:** `executable: false` in `config/benchmarks.yaml`.
- **Smoke slice:** `config/slices/swe-bench-verified-smoke-10.yaml` retained for future re-admission.
- **Caveat:** public calibration / contamination risk high.
- **Generation contract:** pin mini-SWE-agent and use its batch SWE-bench interface to produce predictions for the exact typed slice ids (`instance_id`, `model_name_or_path`, `model_patch`).
- **Scoring authority:** feed those predictions to a pinned official SWE-bench evaluator and accept only the requested instance's boolean `resolved` in the official `report.json`. Local `verifier.json`, `result.json`, stdout, and exit code have no scoring authority.
- **Re-admission bar:** capture mini-SWE, evaluator, dataset and image identities plus prediction/report digests; run a real diagnostic smoke; then require an explicit catalog promotion. Until then, do not call this lane a native proof or a frontier-quality claim.
- **Upstream contracts:** [official evaluation guide](https://github.com/SWE-bench/SWE-bench/blob/main/docs/guides/evaluation.md), [official evaluator](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/run_evaluation.py), [mini-SWE batch runner](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/run/benchmarks/swebench.py).
