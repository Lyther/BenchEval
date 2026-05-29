# BenchEval vNext — Concept-Zero

**Authoritative design (v0.2, 2026-05-29):** [`docs/context/concept-zero.md`](docs/context/concept-zero.md)

This file is a stable entry point for README links and cross-tool references. The v0.2 document supersedes the 2026-04-15 Inspect/Harbor benchmark-tracker HLD for all new vNext work.

## What changed in v0.2

BenchEval vNext is a private-first, evidence-based evaluation pipeline for coding, tool use, agentic coding, terminal execution, and defensive security engineering. It defines a **BenchEval-native task contract** with adapters to Inspect and Harbor, rather than treating Harbor as the universal substrate.

MVP target: **Core-8 Smoke** + task contract + E0/E1 execution + JSONL evidence store + dry-run planner — not full Core-16 on day one.

**Current status (2026-05-29):** Core-8 is 8/8 admitted offline. P0/P3/P4 complete. Inspect mockllm E0, evidence export/compare, and provider-smoke orchestrator are implemented. Live provider runs, Docker-gated E1, and Harbor jobs remain blocked. Core-16 plan: [`docs/context/core-16-expansion-plan.md`](docs/context/core-16-expansion-plan.md).

## Legacy tracker (2026-04-15)

The prior benchmark-tracker concept (Inspect `.eval` summary rows, SWE-bench Verified, CyBench, Harbor secondary lanes) remains implemented in `src/bencheval/summary.py`, `scripts/extract_summary.py`, and `scripts/compare.py`. Those modules are **legacy score handling** per v0.2 §18; new Core scoring uses the vNext task contract and evidence store.

For the archived 2026-04-15 HLD text, see git history of this file or `docs/architecture.md` (legacy appendix).
