# cybergym (catalog pending)

CyberGym is **not** a Tier-0 executable adapter yet. Catalog status: `adapter_pending` / `executable: false`.

Official lifecycle (required before re-admission) includes data download, server startup, `--data-dir` / `--server` / `--mask-map` / `--difficulty`, agent PoC submission, and official result parsing — not only `python -m cybergym.task.gen_task`.

```bash
# Dry-run / live run should fail until executable is re-enabled:
uv run bencheval run cybergym --agent momo --model kimi-k2.7-code --dry-run
```

- **Host deps (post-v1 research only):** clone [CyberGym](https://github.com/sunblaze-ucb/cybergym), Docker, local/private server, and host task data/images (upstream documents roughly 240 GB before full server data); `BENCHEVAL_CYBERGYM_HOME`.
- **Product decision:** catalog-only and non-executable for v1. The official task is PoC generation against benchmark-owned vulnerable/fixed builds, and no official lifecycle implementation or live run is planned for this release. Any later reconsideration requires a new explicit product decision; do not relabel the official PoC lifecycle as an ordinary defensive task.
- **Claim:** do not emit scored pass rates until the official submit/`verify_agent_result.py` path is wired and live-proven on an authorized host.
