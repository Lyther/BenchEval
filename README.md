# BenchEval

Private, version-controlled tracker for **LLM benchmark evaluation** (Inspect AI + Harbor ecosystem). Goals and stack are documented in [`concept-zero.md`](concept-zero.md).

## Layout

- `config/` — benchmark suites, model registry (no secrets), experiment matrix
- `src/bencheval/` — Python package (logic core)
- `scripts/` — automation entrypoints (to be added)
- `results/raw/` — Inspect `.eval` logs (ignored by git)
- `results/summary/` — committed JSONL rollups
- `results/reports/` — generated comparison reports
- `docs/context/` — informal context dumps for agents

## Setup

```bash
uv sync
uv sync --extra eval # Inspect / Harbor stack (optional; heavier). `concept-zero.md` may target newer pins than PyPI; see `uv.lock`.
```

Copy `.env.example` to `.env` and fill in values. Never commit `.env`.

## Commands

```bash
make lint
make test
make build
```

## License

MIT — see [`LICENSE`](LICENSE).
