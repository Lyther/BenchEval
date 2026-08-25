# gpqa-diamond (Inspect Evals)

```bash
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** `inspect eval inspect_evals/gpqa_diamond --limit N` (dataset downloads to host on first live run).
- **Scoring:** BenchEval parses Inspect eval logs written under `--log-dir` (`*.json` / `*.eval` with `results.scores`). Official log ownership comes from Inspect `--json` done records: inspect-ai 0.3.x `event=done` / `logs[].location`, or the older `type=done` / `tasks[].log_location`, plus a `Log:` / `log_location` text fallback. Completeness is unique requested samples, not epoch-expanded rows (`gpqa_diamond` defaults to 4 epochs). Operator-authored `official_scores.json` is ignored for pass authority. Exit code 0 alone is never a pass.
- **Evidence:** one aggregate slice row (`…-aggregate`) with `partial_score` = official accuracy; `primary_pass` only when accuracy is 1.0.
- **Mode:** model-only — refuse `--runtime` / `--agent`.
- **Host deps:** Inspect AI + `inspect_evals` (e.g. `uv sync --extra eval`).
- **Smoke:** limit = slice size → interpretation `adapter_smoke`.
- **Tier-1:** registered `passed` run `run-20260825-160511-036214-304c2cee` on dev-box-cpu (`kimi-k2.7-code` / bytellm); official Inspect log accuracy 1.0 over 2 unique samples × 4 official epochs; private proof `sha256:aa19d02b7d1457d0f43d9588b3d08c042e967a981ed8537068412e1797ff0eda`.
- **Model identity:** the Inspect model is derived from the selected provider and planned model. A legacy `BENCHEVAL_INSPECT_MODEL` value is accepted only when it exactly matches that derived identity; mismatches fail before launch.
- **Dataset identity (pinned):** the catalog `identity:` block pins `inspect-evals` 0.8.0, eval metadata version `2-B`, and the CSV sha256 (`41d1213c…`). Before any launch the adapter verifies the installed dist version, the eval metadata version, and the inspect_evals cache CSV bytes; a missing cache file is downloaded once from the pinned URL, and an existing mismatching file is never silently overwritten — drift fails closed as `runtime_config_drift`, no launch. The verified identity is stamped into evidence as `benchmark_version` (`gpqa-diamond@inspect-evals-0.8.0+eval-2-B+csv-41d1213cd7a49986`).
