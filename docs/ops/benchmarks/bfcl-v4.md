# bfcl-v4 (model-only generate smoke)

```bash
uv run bencheval run bfcl-v4 --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run bfcl-v4 --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** `bfcl generate` only; official `bfcl evaluate` not wired — stay on `adapter_smoke`.
- **Mode:** model-only.
- **Host deps:** BFCL CLI package on PATH for live runs.
