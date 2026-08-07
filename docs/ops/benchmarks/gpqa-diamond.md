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
- **Model identity:** the Inspect model is derived from the selected provider and
  planned model. A legacy `BENCHEVAL_INSPECT_MODEL` value is accepted only when it
  exactly matches that derived identity; mismatches fail before launch.
