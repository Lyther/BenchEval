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
Slice YAML under `config/slices/` points at these manifests via `instances_source`.

## Committed files

| File | Purpose |
| --- | --- |
| `terminal-bench-smoke-5.txt` | Terminal-Bench Harbor smoke (5 task ids). |
| `swebench-verified-smoke-10.txt` | SWE-bench Verified smoke (10 ids); not the full Verified-500 set. |
| `bfcl-v4-smoke-5.txt` | BFCL v4 smoke (5 category ids). Generation-smoke only until `bfcl evaluate` is wired. |

These manifests back admitted product slices under `config/slices/`. Research
benchmark candidates live in `docs/context/external-benchmark-catalog.md`, not
in the product YAML catalog.

## Product run path

```bash
uv run bencheval run terminal-bench/smoke-5 --runtime claude-code --model gpt-test --dry-run
uv run bencheval run bfcl-v4/smoke-5 --model gpt-test --dry-run
uv run bencheval run swe-bench-verified/swe-bench-verified-smoke-10 \
  --runtime claude-code --model gpt-test --dry-run
```

There is no `run --manifest` / `--mode single` / `--backend` product CLI.
Instance order comes from the slice's manifest file order.
