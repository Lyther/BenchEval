# gpqa-diamond (Inspect Evals)

```bash
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** `inspect eval inspect_evals/gpqa_diamond --limit N` (dataset downloads to host on first live run).
- **Scoring:** BenchEval parses official Inspect metrics (`official_scores.json` or Inspect results JSON under `--log-dir`). Exit code 0 alone is never a pass.
- **Evidence:** one aggregate slice row (`…-aggregate`) with `partial_score` = official accuracy; `primary_pass` only when accuracy is 1.0.
- **Mode:** model-only — refuse `--runtime` / `--agent`.
- **Host deps:** Inspect AI + `inspect_evals` (e.g. `uv sync --extra eval`).
- **Smoke:** limit = slice size → interpretation `adapter_smoke`.
- **Optional:** `BENCHEVAL_INSPECT_MODEL` overrides the Inspect model string.
