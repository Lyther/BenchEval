# terminal-bench (Harbor 2.1)

```bash
uv run bencheval run terminal-bench --runtime claude-code --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run terminal-bench --runtime claude-code --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** Harbor dataset `terminal-bench/terminal-bench-2-1` (host pull).
- **Smoke:** `config/slices/terminal-bench-smoke-5.yaml` carries the fixed task ids inline.
- **Host deps:** Harbor, Docker, provider credentials / proxy as needed.
- **Disk:** task images land under Harbor’s cache on the host — not in this repo.
- **Claim:** smoke → `adapter_smoke` until a full-suite prove.
