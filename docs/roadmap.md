# Execution Roadmap

> **Operator contract:** [`README.md`](../README.md), [`docs/architecture.md`](architecture.md), [`docs/api/internal-contracts.md`](api/internal-contracts.md).
> **Production bar:** [`production-readiness.md`](context/production-readiness.md) + `make check-production-v1`.
> **Principle:** Prefer official harnesses and evidence-bound claims. BFCL is `bfcl generate` adapter smoke until official `bfcl evaluate` is wired.

## Current roadmap (2026-07)

### Admitted product surface

```text
benchmark  →  (runtime | agent)?  →  model via provider  →  evidence
```

| Axis | Admitted ids |
|------|----------------|
| Benchmarks | `terminal-bench`, `swe-bench-verified`, `bfcl-v4` |
| Runtimes | `claude-code`, `codex-cli` |
| Agents | `momo` |
| Providers | `bytellm`, `ollama-cloud` |
| CLI | `list`, `catalog …`, `run <benchmark>/<slice> [--runtime\|--agent] --model … [--provider] [--dry-run\|-y]` |

Runtime XOR agent. Omit both for model-only (BFCL generation smoke). Unknown ids fail before subprocess.

### Near-term work

- [ ] **C1** Dev-box live proof for at least one admitted path with registered evidence (`docs/ops/dev-box-pilot.md`).
- [ ] **C2** Wire official `bfcl evaluate` (or keep BFCL labeled `adapter_smoke` forever until then).
- [ ] **C3** Harbor CLI contract spike for Terminal-Bench (`harbor run --dataset terminal-bench@2.0`) if live TB is blocked.
- [ ] **C4** Admit the next benchmark only via deliberate YAML + adapter + live proof — research catalog stays docs-only.

### Hot files

- `README.md`, `docs/architecture.md`, `docs/api/internal-contracts.md`
- `config/benchmarks.yaml`, `config/runtimes/{claude-code,codex-cli}.yaml`, `config/agents/`, `config/providers/`, `config/slices/`, `config/models.yaml`
- `src/bencheval/`: `cli.py`, `benchmark_plan.py`, `control_plane_executor.py`, `doctor.py`, registries, `terminal_bench_harbor.py`, `swebench_adapter.py`, `bfcl_native_adapter.py`, `external_agent_adapter.py`, `evidence.py`, `report.py`, `evidence_compare.py`, `export.py`
- Pilot: `scripts/run-live-pilot-matrix.sh`, `scripts/doctor-pilot.sh`
- Hygiene: `tests/regressions/test_peer_ship_hygiene.py`

### Live blockers

| Gate | Status |
|------|--------|
| Provider credentials | Required for live runs |
| Harbor / harness sandbox on **dev-box** | Required for TB / harness-owned sandboxes — not a BenchEval Docker plane |
| `claude-code` / `codex-cli` / `momo` noninteractive auth | Required for scaffolded live runs |
| Official BFCL evaluate | Not wired; generation smoke only |

---

## Historical ledger (do not execute)

> Archive of v0.3 phase checkboxes. Names deleted modules/commands (`planner.py`, `inspect-api`, `harbor-agent`, `run --config`, Core selftest). **Not** operator instructions.

<details>
<summary>P0–P9 historical milestones (click to expand)</summary>

### Phase 0 — Validation (research spikes)

- [ ] **S0.1** Harbor CLI spike for Terminal-Bench.
- [ ] **S0.2** `claude-code` / `codex-cli` noninteractive + version capture.
- [ ] **S0.3** EvidenceRecord v0.3 additive parse of v0.2 fixtures.
- [x] **S0.4** Product catalog pruned to **3** executables; research candidates docs-only.

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
