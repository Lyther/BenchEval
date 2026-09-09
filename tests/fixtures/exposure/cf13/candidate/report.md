# BenchEval Evidence Report

## Summary

- Runs: 1
- Tasks (attempts): 2
- Unique tasks: 2
- Pass rate: 100.00% (2/2)
- Average partial score: 1.0000
- Total cost (USD): 0.0000
- Total latency (sec): 31.97

## Control-plane axes

- Interpretation: `diagnostic`
- Benchmark: `bfcl-v4-tool-order-v1`
- Benchmark version: `bfcl-v4-tool-order-v1@derived-703a44fc02a8883f07560c5bacb401f9bbda8b9649a74ff30145ef88670e30fe`
- Slice: `tool-order-derived-plumbing-2`
- Adapter: `bfcl`
- Harness: `bfcl-native`
- Harness version: `bfcl-eval@2026.3.23+registration-05b2da6384a295799278ec9efae6a52dde655f7fbd3ab61bd5a3364f1c25a151`
- Runtime: `n/a`
- Runtime version: `n/a`
- Provider: `ollama-cloud`
- Provider config hash: `sha256:3d4a1ee8f420f3fd02ce98554b9575671ceb9e00cdfa570bb3357e1ca400988f`
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
| multiple_19 | ollama-qwen3.5-397b-fc | inspect | yes | 1.0000 | 0.0000 | 12.11 | artifacts/raw/multiple_19/scores/ollama-qwen3.5-397b-fc/non_live/BFCL_v4_multiple_score.json |
| parallel_multiple_125 | ollama-qwen3.5-397b-fc | inspect | yes | 1.0000 | 0.0000 | 19.87 | artifacts/raw/parallel_multiple_125/scores/ollama-qwen3.5-397b-fc/non_live/BFCL_v4_parallel_multiple_score.json |

## Failure taxonomy

No failure labels recorded.
