# swe-bench-verified

```bash
uv run bencheval run swe-bench-verified --runtime claude-code --model kimi-k2.7-code --dry-run
uv run bencheval run swe-bench-verified --runtime claude-code --model kimi-k2.7-code -y
```

- **Harness:** swebench-native adapter (Inspect path).
- **Smoke:** `config/slices/swe-bench-verified-smoke-10.yaml` carries the fixed task ids inline.
- **Caveat:** public calibration / contamination risk high.
