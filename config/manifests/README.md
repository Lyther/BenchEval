# Task manifests

## Text format

- UTF-8, LF line endings.
- One task id per non-empty line.
- Lines whose first non-whitespace character is `#` are comments.
- Blank lines are ignored.
- Duplicate ids are preserved (they appear multiple times in the sorted canonical form).

## Canonical hash

`load_manifest` in `src/bencheval/manifest.py` builds canonical bytes as:

1. Collect task ids from non-comment, non-blank lines (strip each line; no further normalization).
2. Sort lexicographically.
3. Join with `\n`, then append a final `\n`.
4. SHA-256 over UTF-8 bytes → lowercase hex (64 chars).

The hash is **independent of comment or blank-line drift** and **independent of line order** in the file.

Execution order is different from hash canonicalization: `bencheval run
--manifest` preserves file order so operators can control cheap-first, shard, or
resume order without changing the manifest hash.

## Committed files

| File | Purpose |
| --- | --- |
| `cybench-smoke-5.txt` | Offline smoke (5 ids); not the canonical CyBench-39 set. |
| `swebench-verified-smoke-10.txt` | Offline smoke (10 ids); not the full Verified-500 set. |

These manifests are accepted by `bencheval run --manifest` as task-id lists.
Native BenchEval task ids can execute today through `local`, `inspect`, or
`harbor` when the selected backend supports them. Public benchmark ids such as
SWE-bench or CyBench are currently provenance/control-plane inputs: they can be
hashed, dry-run counted, and used by future Calibration/Stretch adapters, but
they are not executable until an adapter maps each id to a concrete task
workspace, candidate format, verifier, and cleanup lifecycle.

## Single lifecycle mode

Use this shape for large external suites once the selected backend adapter
supports the manifest ids:

```bash
uv run bencheval run \
  --manifest config/manifests/swebench-verified-smoke-10.txt \
  --mode single \
  --cleanup always \
  --model openai/gpt-test \
  --backend inspect \
  --output results/evidence/swebench-smoke-10.jsonl \
  --artifacts-dir results/raw/swebench-smoke-10
```

`--mode single` executes one id, appends one `EvidenceRecord`, removes
BenchEval-owned transient directories according to `--cleanup`, and then moves
to the next id. It preserves evidence JSONL, verifier logs, and candidate
artifacts. Docker image pruning is intentionally not part of the generic
cleanup policy; external adapters must own image names/cache levels before
adding Docker cleanup.

## Deferred (credentialed spike)

Generate and commit after `inspect-evals` / Harbor access:

- `cybench-39.txt` — exact task list from inspect-evals CyBench package.
- `swebench-verified-500.txt` — full Verified manifest.
- `swe-bench-pro-public-r2.txt` — Harbor `scale-ai/swe-bench-pro@2` id list.

Document each file’s provenance and recompute `ManifestDigest` hashes in summary rows.
