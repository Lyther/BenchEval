# terminal-bench (Harbor 2.1)

```bash
uv run bencheval run terminal-bench --runtime claude-code --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run terminal-bench --runtime claude-code --model kimi-k2.7-code --provider bytellm -y
```

- **Harness:** Harbor dataset `terminal-bench/terminal-bench-2-1` (host pull).
- **Tier-1 one-instance:** `config/slices/terminal-bench-tier1-one.yaml` is `fix-git` only (`adapter_smoke`). Registered 2026-08-25 on dev-box-cpu for both admitted runtimes (`claude-code` `run-20260825-173913-754489-4f43e296`, `codex-cli` `run-20260825-171829-685914-aa08dd1d`). Official `reward == 0.0` is a valid `model_wrong_solution`.
- **Smoke:** `config/slices/terminal-bench-smoke-5.yaml` remains optional broader coverage.
- **Host deps:** Harbor, Docker, provider credentials / proxy as needed. Harbor Claude needs `ANTHROPIC_CUSTOM_MODEL_OPTION` for non-Anthropic catalog ids; Codex needs HTTP `wire_api=responses` and cleared container proxy for `172.17.0.1`.
- **Disk:** task images land under Harbor’s cache on the host — not in this repo.
- **Claim:** `adapter_smoke` until a full-suite prove. The runtime compare is axis/plumbing proof, not a quality ranking.
