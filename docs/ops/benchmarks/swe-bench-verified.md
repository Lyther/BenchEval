# swe-bench-verified (demoted — diagnostic-only)

Catalog row is `executable: false`. Ordinary `run` still refuses this row. `--diagnostic` is the only legal launch, and it cannot register `passed`.

```bash
# Discovery / dry-run only — live execute is refused without --diagnostic.
# v1 diagnostic is Codex-only; claude-code is rejected before launch.
uv run bencheval run swe-bench-verified --runtime codex-cli --model <model-id> --dry-run

# One-instance diagnostic after the lifecycle is materialized. Never registerable as passed.
uv run bencheval run swe-bench-verified/swe-bench-verified-diagnostic-1 \
  --runtime codex-cli --model <model-id> --diagnostic -y
```

- **Status:** `executable: false` in `config/benchmarks.yaml`. Identity pin is the official `SWE-bench/SWE-bench_Verified` snapshot revision `78f471bf655a3137b2e8a75af1501690ec009ec3`. `--diagnostic` materializes the pinned row and injects a real runner; ordinary `run` still refuses the row.
- **Diagnostic slice:** `config/slices/swe-bench-verified-diagnostic-1.yaml` (`django__django-11099`).
- **Smoke slice:** `config/slices/swe-bench-verified-smoke-10.yaml` retained unchanged for a later promotion decision.
- **Evaluator extra:** exact `swebench==5.0.1` lives in the `swe` group and is launched as `uv run --isolated --project <BenchEval root> --group swe`; the evaluator cwd stays in the run-owned instance directory so relative official logs remain capturable there. Inspect generation uses a separate isolated env with `swebench==4.1.0` because inspect-evals 0.8.0 still imports `MAP_REPO_VERSION_TO_SPECS` to export `model_patch`. Do not install 5.0.1 into the generic `eval` extra.
- **ByteLLM / Codex:** start `python -m bencheval.anthropic_role_shim` on loopback with `--upstream` pointing at ByteLLM. Set `BYTELLM_BASE_URL` to the shim endpoint. Explicit provider resolution overwrites `OPENAI_BASE_URL`; do not rely on ambient `OPENAI_BASE_URL`. inspect_swe 0.2.47 + Claude Code 2.1.235 still sends `--model inspect`, which that Claude pin SDK-rejects, so Claude is not a v1 SWE diagnostic runtime.
- **Caveat:** public calibration / contamination risk high. A real diagnostic does not auto-promote this row.
- **Generation contract:** pin Inspect Evals `inspect_evals/swe_bench` plus the selected Inspect SWE runtime solver, then export exactly one official prediction row (`instance_id`, non-empty `model_name_or_path`, string `model_patch`). Missing, duplicate, extra, or malformed prediction rows fail closed and do not invoke the evaluator.
- **Scoring authority:** after generation, bind official-dataset and prediction inode/digest, copy the official row into a generation-hidden `eval-input`, then run pinned official `swebench eval <run-owned eval-input>` with a unique `--run-id` and run-owned `--report-dir`. Re-bind those identities after scoring. Hub aliases such as `verified` are rejected. Accept only official per-instance boolean `resolved` plus coherent schema-v2 aggregate output. Official `empty_patch_ids` is a valid model failure and is not executed. Local `verifier.json`, `result.json`, stdout, and exit code have no scoring authority.
- **Live diagnostic:** `run-20260826-141431-679309-31a57785` exported a prediction and invoked official `swebench eval <run-owned official-dataset>` (no Hub alias). Official schema-v2 recorded `error_ids` (patch apply failed). Evidence stayed `runtime_output_unparseable` / `diagnostic` with `benchmark_version=swe-bench-verified@78f471bf655a3137+data-030cfd7f2a704c4c`, `harness_version=swebench==5.0.1`, and `runtime_version=0.148.0`. Proof `sha256:5f7f79ce44eb8c00d7ee826914e8d4591206de2d3b876a2524ccad508e373e52` retains `predictions.jsonl`, schema-v2 summary, official/Inspect `test.jsonl`, `transformation-manifest.json`, and the bound Inspect `.eval`. There is no executed per-instance `report.json` because schema-v2 classed the instance as `error_ids`. `cleanup_result=skipped`. Historical Hub-alias `sha256:fcc766f5…235b5` remains in the store. This does not promote the row.
- **Re-admission bar:** capture Inspect task/solver, evaluator, dataset and image identities plus prediction/report digests; then require an explicit catalog promotion. Until then, do not call this lane a native proof or a frontier-quality claim.
- **Upstream contracts:** [official evaluation guide](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/docs/guides/evaluation.md), [official evaluator](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/swebench/harness/run_evaluation.py), [Inspect Evals SWE-bench task](https://github.com/UKGovernmentBEIS/inspect_evals/blob/main/src/inspect_evals/swe_bench/README.md).
