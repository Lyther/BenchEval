# cybergym (catalog pending)

CyberGym is **not** a Tier-0 executable adapter yet. Catalog status: `adapter_pending` / `executable: false`.

Official lifecycle (required before re-admission) includes data download, server startup, `--data-dir` / `--server` / `--mask-map` / `--difficulty`, agent PoC submission, and official result parsing — not only `python -m cybergym.task.gen_task`.

```bash
# Dry-run / live run should fail until executable is re-enabled:
uv run bencheval run cybergym --agent momo --model kimi-k2.7-code --dry-run
```

- **Host deps (future):** clone [CyberGym](https://github.com/sunblaze-ucb/cybergym), Docker, host task data / images; `BENCHEVAL_CYBERGYM_HOME`.
- **Authorization:** cybersecurity evaluation follows the official CyberGym host/harness policy; BenchEval adds no separate policy layer.
- **Claim:** do not emit scored pass rates until the official submit/score path is wired.
