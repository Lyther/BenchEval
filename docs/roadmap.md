# Execution Roadmap

> **Operator contract:** [`README.md`](../README.md), [`docs/architecture.md`](architecture.md), [`docs/api/internal-contracts.md`](api/internal-contracts.md).
> **Production bar:** [`production-readiness.md`](context/production-readiness.md) + `make check-production-v1`.
> **Principle:** Prefer official harnesses and evidence-bound claims. BFCL stays
> non-executable until generation and official evaluation form one bounded lifecycle.

## Current roadmap (2026-07)

### Tier-0 executable product surface

```text
benchmark  →  (runtime | agent)?  →  model via provider  →  evidence
```

| Axis | Tier-0 executable ids |
|------|-----------------------|
| Benchmarks | `terminal-bench`, `gpqa-diamond`, `hle`, `bfcl-v4` |
| Runtimes | `claude-code`, `codex-cli` |
| Agents | `momo` |
| Providers | `bytellm`, `ollama-cloud` |
| CLI | `list`, `catalog …`, `run <benchmark>/<slice> [--runtime\|--agent] --model … [--provider] [--dry-run\|-y]` |

Runtime XOR agent. Omit both for model-only (GPQA, HLE). Unknown ids fail before subprocess.

**Tiers** (definitions: [`production-readiness.md`](context/production-readiness.md)): **Tier-0 executable** = software gate — the control plane compiles, plans, and gates with no live deps. **Tier-1 live-proven** = ≥1 real instance end-to-end via the benchmark's native harness. **Tier-2 Production v1** = adapter admitted + Tier-1 live proof + full checklist. All three benchmarks above are Tier-0 executable; none currently holds Tier-1/Tier-2 proof.

### Near-term work

- [ ] **C1** Tier-1 live proof for at least one Tier-0 executable path with registered evidence (`docs/ops/dev-box-pilot.md`).
- [x] **C2** Wire `bfcl generate` + official `bfcl evaluate` as one bounded lifecycle before making BFCL executable (admitted 2026-08-24 via `run-20260824-040631-228703-4756f857`).
- [ ] **C3** Harbor CLI contract spike for Terminal-Bench (`harbor run --dataset terminal-bench/terminal-bench-2-1`) if live TB is blocked.
- [ ] **C4** Admit the next benchmark to Tier-2 Production v1 only via deliberate YAML + adapter + live proof — research catalog stays docs-only.

### Hot files

- `README.md`, `docs/architecture.md`, `docs/api/internal-contracts.md`
- `config/benchmarks.yaml`, `config/runtimes/{claude-code,codex-cli}.yaml`, `config/agents/`, `config/providers/`, `config/slices/`, `config/models.yaml`
- `src/bencheval/`: `cli.py`, `benchmark_plan.py`, `control_plane_executor.py`, `doctor.py`, registries, `terminal_bench_harbor.py`, `gpqa_adapter.py`, `hle_adapter.py`, `external_agent_adapter.py`, `evidence.py`, `report.py`, `evidence_compare.py`, `export.py` (the SWE module is diagnostic and non-executable; BFCL is executable)
- Pilot: `scripts/run-live-pilot-matrix.sh`, `scripts/doctor-pilot.sh`
- Hygiene: `tests/regressions/test_peer_ship_hygiene.py`

### Live blockers

| Gate | Status |
|------|--------|
| Provider credentials | Required for live runs |
| Harbor / harness sandbox on **dev-box** | Required for TB / harness-owned sandboxes — not a BenchEval Docker plane |
| `claude-code` / `codex-cli` / `momo` noninteractive auth | Required for scaffolded live runs |

---

## Historical ledger (do not execute)

> Archive of v0.3 phase checkboxes. Names deleted modules/commands (`planner.py`, `inspect-api`, `harbor-agent`, `run --config`, Core selftest). **Not** operator instructions.

<details>
<summary>P0–P9 historical milestones (click to expand)</summary>

### Phase 0 — Validation (research spikes)

- [ ] **S0.1** Harbor CLI spike for Terminal-Bench.
- [ ] **S0.2** `claude-code` / `codex-cli` noninteractive + version capture.
- [ ] **S0.3** EvidenceRecord v0.3 additive parse of v0.2 fixtures.
- [x] **S0.4** Product catalog expanded to **8** catalog rows (later demoted to **3** Tier-0 executables: TB / GPQA / HLE; SWE/BFCL wait on official evaluate); ops manuals under `docs/ops/benchmarks/`.

### Phase 1 — MVP skeleton (historical CLI shapes)

- [x] **P1.1** Runtime registry + profiles (admitted set later pruned to `claude-code` / `codex-cli`).
- [x] **P1.2–P1.6** Catalog/list/show + dry-run planning (commands since collapsed into `catalog` / `run --dry-run`).
- [x] **P1.7** Additive `EvidenceRecord` v0.3 fields.
- [x] **P1.8–P1.9** Selftest / external-command lanes (since removed from product CLI).

### Phase 2–6 — Adapters and warehouse

- [x] **P2** Terminal-Bench Harbor adapter + smoke slice.
- [x] **P3** Runtime comparison report / compare gates.
- [x] **P4.1/P4.3/P4.4** SWE-bench Verified adapter + contamination caveats (SWE-rebench slice later removed).
- [x] **P5.1/P5.3** BFCL generation adapter + model compare (evaluate not wired).
- [ ] **P5.2** LiveCodeBench / BigCodeBench (not admitted).
- [x] **P6** Parquet/DuckDB export.

### Phase 7–9 — Deferred / removed

- [ ] **P7–P8** Defensive / offensive Stretch adapters (research only).
- [x] **P9** Core-8/16 selftest lane (removed from product surface).

</details>
