# BenchEval Evidence Report

## Summary

- Runs: 1
- Tasks (attempts): 6
- Unique tasks: 6
- Pass rate: 66.67% (4/6)
- Average partial score: 0.6667
- Total cost (USD): 0.0000
- Total latency (sec): 68.26

## Control-plane axes

- Interpretation: `diagnostic`
- Benchmark: `bfcl-v4-live`
- Benchmark version: `bfcl-v4-live@bfcl-eval-2026.3.23+data-939b6ed93f816d9b`
- Slice: `plumbing-6`
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
| live_simple_0-0-0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.52 | artifacts/raw/live_simple_0-0-0/scores/gpt-5.2-2025-12-11-FC/live/BFCL_v4_live_simple_score.json |
| live_multiple_0-0-0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.59 | artifacts/raw/live_multiple_0-0-0/scores/gpt-5.2-2025-12-11-FC/live/BFCL_v4_live_multiple_score.json |
| live_parallel_0-0-0 | gpt-5.2-2025-12-11-FC | inspect | no | 0.0000 | 0.0000 | 10.42 | artifacts/raw/live_parallel_0-0-0/scores/gpt-5.2-2025-12-11-FC/live/BFCL_v4_live_parallel_score.json |
| live_parallel_multiple_0-0-0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.23 | artifacts/raw/live_parallel_multiple_0-0-0/scores/gpt-5.2-2025-12-11-FC/live/BFCL_v4_live_parallel_multiple_score.json |
| live_irrelevance_0-0-0 | gpt-5.2-2025-12-11-FC | inspect | no | 0.0000 | 0.0000 | 11.51 | artifacts/raw/live_irrelevance_0-0-0/scores/gpt-5.2-2025-12-11-FC/live/BFCL_v4_live_irrelevance_score.json |
| live_relevance_0-0-0 | gpt-5.2-2025-12-11-FC | inspect | yes | 1.0000 | 0.0000 | 11.99 | artifacts/raw/live_relevance_0-0-0/scores/gpt-5.2-2025-12-11-FC/live/BFCL_v4_live_relevance_score.json |

## Failure taxonomy

| Label | Count |
| --- | ---: |
| model_wrong_solution | 2 |
