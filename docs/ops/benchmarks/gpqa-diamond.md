# gpqa-diamond (Inspect Evals)

```bash
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** `inspect eval inspect_evals/gpqa_diamond --limit N` (dataset downloads to host on first live run).
- **Scoring:** BenchEval parses Inspect eval logs written under `--log-dir` (`*.json` / `*.eval` with `results.scores`, or a `Log:` / `log_location` path from Inspect stdout/stderr). Operator-authored `official_scores.json` is ignored for pass authority. Exit code 0 alone is never a pass.
- **Evidence:** one aggregate slice row (`…-aggregate`) with `partial_score` = official accuracy; `primary_pass` only when accuracy is 1.0.
- **Mode:** model-only — refuse `--runtime` / `--agent`.
- **Host deps:** Inspect AI + `inspect_evals` (e.g. `uv sync --extra eval`).
- **Smoke:** limit = slice size → interpretation `adapter_smoke`.
- **Model identity:** the Inspect model is derived from the selected provider and planned model. A legacy `BENCHEVAL_INSPECT_MODEL` value is accepted only when it exactly matches that derived identity; mismatches fail before launch.
- **Dataset identity (pinned):** the catalog `identity:` block pins `inspect-evals` 0.8.0, eval metadata version `2-B`, and the CSV sha256 (`41d1213c…`). Before any launch the adapter verifies the installed dist version, the eval metadata version, and the inspect_evals cache CSV bytes; a missing cache file is downloaded once from the pinned URL, and an existing mismatching file is never silently overwritten — drift fails closed as `runtime_config_drift`, no launch. The verified identity is stamped into evidence as `benchmark_version` (`gpqa-diamond@inspect-evals-0.8.0+eval-2-B+csv-41d1213cd7a49986`).
