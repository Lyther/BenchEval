# hle (CAIS Humanity's Last Exam)

```bash
export BENCHEVAL_HLE_HOME=/path/to/centerforaisafety/hle
uv run bencheval run hle --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run hle --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** official `hle_eval/run_model_predictions.py` + `run_judge_results.py` under `BENCHEVAL_HLE_HOME`. The adapter executes byte-verified copies materialized into the run artifacts (never the mutable checkout pathnames) and re-verifies both the copies and the source identity after the run; mid-run drift fails the attempt as `evidence_corrupt`.
- **Provenance pin:** captured provenance requires the checkout to match the shipped upstream pin in `hle_adapter._DEFAULT_HLE_PIN` (commit `73ae974`, per-script sha256). A mismatched, drifted, or dirty checkout still runs, but its evidence is uncaptured and cannot qualify for Tier-1 promotion. Re-pin procedure lives in a comment above the constant.
- **Scoring:** the slice pins registered judge `gpt-5.3-chat-2026-03-03`, whose ByteLLM direct-chat route passed the official structured-output call shape (`beta.chat.completions.parse`). BenchEval passes it with `--judge` and records it in evidence. Do not switch this smoke to a Responses-routed model unless that route is live-proven to preserve Chat Completions `response_format`. The official `judged_<predictions>.json` artifact is the only authority; it is read dirfd-pinned and no-follow from the `hle-work` inode captured before harness launch, after a post-run directory-identity re-check (the current CAIS filename ends in `.json.json` because the predictions basename already ends in `.json`). Exact `correct` yes/no is required. Stdout metrics are never scoring authority. Judged count must equal the planned sample limit; exit code 0 alone is never a pass.
- **Small-slice calibration:** the pinned judge writes the complete judged JSON before reporting metrics, but its 100-row calibration bins raise `IndexError` for a smaller smoke. BenchEval accepts that nonzero exit only when the harness identity is captured, the exact judge/dump-metrics/calibration traceback is present, and the judged artifact read from the pinned `hle-work` inode contains every requested row. Any other nonzero exit remains `harness_failure`; the native return code and explicit interpretation stay in evidence.
- **Evidence:** one aggregate slice row with official accuracy in `partial_score`.
- **Mode:** model-only — refuse `--runtime` / `--agent`.
- **Host deps:** clone [CAIS HLE](https://github.com/centerforaisafety/hle); HF access for `cais/hle`; the configured provider must serve both the candidate and slice-pinned judge model. Live compatibility remains unverified until a retained dev-box run succeeds.
- **Dataset override:** `cais/hle` is gated; air-gapped/mirrored hosts can point the official harness at a local parquet export with `BENCHEVAL_HLE_DATASET=/path/to/hle.parquet` (schema must match: `id`, `question`, `image`, `answer`, …). The chosen source is stamped into evidence metadata as `hle_dataset` — a non-official source is never hidden and stays `adapter_smoke`-scoped.
- **Disk:** predictions + dataset cache on host; not vendored here.
- **Smoke:** `--max_samples` = slice size; `adapter_smoke` until full-suite prove. The two-sample aggregate run has one 45-minute deadline across prediction and judging; it is not two independently enforceable per-instance timers.
