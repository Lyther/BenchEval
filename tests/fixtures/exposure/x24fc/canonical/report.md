# BenchEval Evidence Report

## Summary

- Runs: 1
- Tasks (attempts): 5
- Unique tasks: 5
- Pass rate: 100.00% (5/5)
- Average partial score: 1.0000
- Total cost (USD): 0.0000
- Total latency (sec): 57.68

## Control-plane axes

- Interpretation: `adapter_smoke`
- Benchmark: `bfcl-v4`
- Benchmark version: `bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b`
- Slice: `exposure-plumbing-5`
- Adapter: `bfcl`
- Harness: `bfcl-native`
- Harness version: `bfcl-eval@2026.3.23`
- Runtime: `n/a`
- Runtime version: `n/a`
- Provider: `bytellm`
- Provider config hash: `sha256:9aa16a5d15202c47e2e7dd180f99f4dd22825b30516082d8a9070cdf7f7e7627`
- Judge model: `n/a`
- Contamination: `public_possible`
- Reward-hack risk: `n/a`
- Verifier integrity: `native`
- Access control source: `not_applicable`
- Egress control: `not_applicable`
- Repository history: `not_applicable`
- Retrieval audit: `not_run`

## Attempts

| Task | Model | Backend | Pass | Partial | Cost (USD) | Latency (s) | Verifier log |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| simple_python_0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.45 | artifacts/raw/simple_python_0/scores/gpt-5.2-2025-12-11-FC/non_live/BFCL_v4_simple_python_score.json |
| multiple_0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.20 | artifacts/raw/multiple_0/scores/gpt-5.2-2025-12-11-FC/non_live/BFCL_v4_multiple_score.json |
| parallel_0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 12.25 | artifacts/raw/parallel_0/scores/gpt-5.2-2025-12-11-FC/non_live/BFCL_v4_parallel_score.json |
| parallel_multiple_0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.14 | artifacts/raw/parallel_multiple_0/scores/gpt-5.2-2025-12-11-FC/non_live/BFCL_v4_parallel_multiple_score.json |
| irrelevance_0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.63 | artifacts/raw/irrelevance_0/scores/gpt-5.2-2025-12-11-FC/non_live/BFCL_v4_irrelevance_score.json |

## Failure taxonomy

No failure labels recorded.
