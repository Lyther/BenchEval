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

## Committed files

| File | Purpose |
| --- | --- |
| `cybench-smoke-5.txt` | Offline smoke (5 ids); not the canonical CyBench-39 set. |
| `swebench-verified-smoke-10.txt` | Offline smoke (10 ids); not the full Verified-500 set. |

## Deferred (credentialed spike)

Generate and commit after `inspect-evals` / Harbor access:

- `cybench-39.txt` — exact task list from inspect-evals CyBench package.
- `swebench-verified-500.txt` — full Verified manifest.
- `swe-bench-pro-public-r2.txt` — Harbor `scale-ai/swe-bench-pro@2` id list.

Document each file’s provenance and recompute `ManifestDigest` hashes in summary rows.
