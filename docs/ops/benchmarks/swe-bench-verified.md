# swe-bench-verified (demoted — not executable)

Catalog row only. Control-plane `run` refuses execution until the locked Inspect Evals + Inspect SWE generation path **and** the official SWE-bench evaluator are wired end-to-end (preds → evaluate → per-instance `resolved`).

```bash
# Dry-run / discovery may still resolve the catalog id; live execute is refused.
uv run bencheval run swe-bench-verified --runtime claude-code --model <model-id> --dry-run
```

- **Status:** `executable: false` in `config/benchmarks.yaml`.
- **Smoke slice:** `config/slices/swe-bench-verified-smoke-10.yaml` retained for future re-admission.
- **Caveat:** public calibration / contamination risk high.
- **Generation contract:** pin Inspect Evals `inspect_evals/swe_bench` plus the selected Inspect SWE runtime solver, then export exactly one official prediction row (`instance_id`, `model_name_or_path`, `model_patch`). Missing `predictions.jsonl` fails closed and does not score Inspect leftovers.
- **Scoring authority:** feed those predictions to pinned official `swebench eval verified` with a unique `--run-id` and run-owned `--report-dir`. Accept only the requested instance's boolean `resolved` in official `report.json`. Local `verifier.json`, `result.json`, stdout, and exit code have no scoring authority.
- **Re-admission bar:** capture Inspect task/solver, evaluator, dataset and image identities plus prediction/report digests; run a real diagnostic smoke; then require an explicit catalog promotion. Until then, do not call this lane a native proof or a frontier-quality claim.
- **Upstream contracts:** [official evaluation guide](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/docs/guides/evaluation.md), [official evaluator](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/swebench/harness/run_evaluation.py), [Inspect Evals SWE-bench task](https://github.com/UKGovernmentBEIS/inspect_evals/blob/main/src/inspect_evals/swe_bench/README.md).
