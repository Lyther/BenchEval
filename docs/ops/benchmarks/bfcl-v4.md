# bfcl-v4 (demoted — not executable)

Catalog row only. Control-plane `run` refuses execution until `bfcl generate`
**and** `bfcl evaluate` are one bounded lifecycle with official score artifacts
(no BenchEval-invented `verdict.json` pass authority).

```bash
# Dry-run / discovery may still resolve the catalog id; live execute is refused.
uv run bencheval run bfcl-v4 --model <model-id> --provider bytellm --dry-run
```

- **Status:** `executable: false` in `config/benchmarks.yaml`.
- **Prior adapter:** generation-only; package version must not become
  `benchmark_version`.
- **Re-admission bar:** official evaluate score for model/category; reject
  incomplete category results; capture git/dataset revision for benchmark
  identity. Until then, do not include BFCL in live-pilot exit-0.
