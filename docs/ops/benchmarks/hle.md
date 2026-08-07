# hle (CAIS Humanity's Last Exam)

```bash
export BENCHEVAL_HLE_HOME=/path/to/centerforaisafety/hle
uv run bencheval run hle --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run hle --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** official `hle_eval/run_model_predictions.py` + `run_judge_results.py` under `BENCHEVAL_HLE_HOME` (cwd = `hle_eval`).
- **Scoring:** the slice pins a registered `judge_model_id`; BenchEval passes it with `--judge` and records it in evidence. The identity-bound official `judged_<predictions>.json` artifact is the only authority (the current CAIS filename ends in `.json.json` because the predictions basename already ends in `.json`). Exact `correct` yes/no is required. Stdout metrics are never scoring authority. Judged count must equal the planned sample limit; exit code 0 alone is never a pass.
- **Evidence:** one aggregate slice row with official accuracy in `partial_score`.
- **Mode:** model-only — refuse `--runtime` / `--agent`.
- **Host deps:** clone [CAIS HLE](https://github.com/centerforaisafety/hle); HF access for `cais/hle`; the configured provider must serve both the candidate and slice-pinned judge model. Live compatibility remains unverified until a retained dev-box run succeeds.
- **Disk:** predictions + dataset cache on host; not vendored here.
- **Smoke:** `--max_samples` = slice size; `adapter_smoke` until full-suite prove.
