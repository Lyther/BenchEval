# Production Readiness Tiers (vNext v0.3)

> **Role:** Canonical definition of what "production-ready" means for BenchEval and how a benchmark adapter graduates from *software* to *live evidence* to *Production v1*.
> **Source of truth:** [`docs/context/concept-hld.md`](concept-hld.md) §11.2 / §14, [`docs/architecture.md`](../architecture.md) §13 (verification gates), [`docs/context/production-v1-pilot.md`](production-v1-pilot.md).
> **Do not edit:** `concept-hld.md`, `concept-zero.md`. This document is a companion, not a replacement for the HLD.

BenchEval is an evaluation **control plane**, not a benchmark author. "Production-ready" therefore has three tiers. A benchmark may sit at Tier 0 (software only) indefinitely; it is never promoted to Tier 2 (Production v1) without real live evidence. There is no partial credit.

```text
Tier 0  Phase A — Software          control plane compiles, plans, and gates correctly with NO live deps
Tier 1  Phase B — Live Evidence     ≥1 real instance ran end-to-end through a native harness (credentials + Docker)
Tier 2  Production v1               adapter admitted + live proof + full checklist satisfied
```

---

## Tier 0 — Phase A: Software (no live dependencies)

**Question answered:** *Does the control plane itself behave correctly, deterministically, and safely with zero network, zero credentials, zero Docker?*

This tier is fully covered by the single command:

```bash
make check-production-v1        # → ./scripts/check-production-v1.sh
```

`check-production-v1.sh` enforces, with `set -euo pipefail`:

1. `uv run --no-sync pytest -q` — full test suite green (software regression of the control plane + selftest plumbing).
2. `uv run --no-sync ruff check src tests scripts/` and `ruff format --check` — lint + format clean.
3. `shellcheck scripts/*.sh` and `bash -n scripts/*.sh` — shell hygiene.
4. `uv lock --check` — lockfile in sync with `pyproject.toml`.
5. **Executable-adapter count = 3.** `bencheval benchmark list --execution-support executable_adapter --format json` must report exactly `terminal-bench`, `swe-bench-verified`, `bfcl-v4`. A drift here means an adapter flipped status without the checklist below.
6. **Negative-evidence gate:** `bencheval run --benchmark cybench --slice cybench-smoke-5 ...` must **fail** before subprocess dispatch, and stderr must contain `metadata_only` / `execution_support`. A metadata-only benchmark that accidentally *runs* is a regression.

**Passing Tier 0 means:** the software is correct. It does **not** mean any benchmark result is real. Non-executable benchmarks stay `metadata_only` / `manifest_only`; reports produced without live deps must carry the `adapter_smoke` interpretation label, never `benchmark_native_claim` (architecture §13.1, §15 risk "Harbor unavailable / Docker absent").

---

## Tier 1 — Phase B: Live Evidence (credentials + Docker required)

**Question answered:** *Did at least one real instance run end-to-end through the native harness and produce a valid `EvidenceRecord`?*

Phase B lifts the Tier 0 live blockers. Gate inputs:

```bash
export BENCHEVAL_PILOT_MODEL='openai/your-model'   # or anthropic/...
./scripts/run-live-pilot-matrix.sh
```

Required host dependencies (see [`docs/roadmap.md`](../roadmap.md) §Live blockers):

- Provider credentials: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …
- Docker daemon (Harbor E1, SWE-bench E1)
- `harbor` CLI installed and contract-stable (roadmap S0.1)
- `claude-code` / `codex-cli` noninteractive launch + auth (roadmap S0.2)
- SWE: `mini-extra`; BFCL: `bfcl-eval` package

Produces under `results/` (gitignored except committed `.gitkeep` / registry READMEs):

- `results/evidence/`, `results/reports/`, `results/bundles/` (default `--redaction private`)
- `results/preflight/*.json` when doctor / Docker / a mini-extra blocks a step — this is **negative evidence** (a real, honest "blocked" record), not a fake pass.

### Peer anchor: the Terminal-Bench `fix-git` pass

The canonical one-instance live-evidence proof for the `terminal-bench-harbor` adapter is the **`fix-git`** instance, the first entry in [`config/manifests/terminal-bench-smoke-5.txt`](../../config/manifests/terminal-bench-smoke-5.txt):

```text
fix-git
overfull-hbox
cobol-modernization
modernize-scientific-stack
log-summary-date-ranges
```

A "Peer TB `fix-git` pass" means: `fix-git` ran through `harbor run --dataset terminal-bench@2.0 ...` and produced an `EvidenceRecord` whose `native_score`, raw result, stdout/stderr, verifier log, and workspace diff are all present and non-fake. This satisfies architecture §13.1's "native harness invocation ≥1 instance" requirement at the minimum bar. The remaining four instances extend smoke coverage but are **not** required for the single-instance admission floor.

> Reference unit coverage for the `fix-git` command shape: [`tests/test_terminal_bench_harbor.py`](../../tests/test_terminal_bench_harbor.py) asserts the `--task-name fix-git` argument, version-capture fields, and Harbor agent/import-path wiring. These are Tier 0 (software) proofs of the *plumbing*; the Peer pass is the Tier 1 proof of the *live run*.

### Phase B comparison rule

Only treat `bencheval compare` as a **runtime_comparison** when both evidence files share the same `model_id` (architecture §13.3). Harbor agents may bind models differently; if the model axis drifts, `compare` exits with a dual-axis error rather than emitting a misleading runtime-only delta.

---

## Tier 2 — Production v1: full checklist

**Question answered:** *Is this benchmark adapter ready to be a first-class, publicly-comparable benchmark — evidence complete, versions pinned, caveats labelled, comparison valid?*

A benchmark graduates to **Production v1** only when **all** of the following hold. This is the union of Tier 0 + Tier 1 + the architecture §13 gates, with no waivers.

### A. Catalog state
- [ ] `execution_support` = `executable_adapter` in `config/benchmarks.yaml` (Tier 0 gate already asserts exactly 3 today).
- [ ] `adapter_status` flipped to `manifest_available` (not `cataloged` / `adapter_pending` / `unverified`).
- [ ] `safety_review` set correctly (`standard` / `dual_use` / `offensive_restricted`); offensive tasks Stretch-only behind `--allow-stretch`.

### B. Adapter admission (architecture §13.1)
- [ ] Native harness invoked on ≥1 real instance (Phase B; for TB the Peer `fix-git` pass).
- [ ] Version capture on every `EvidenceRecord`: benchmark, harness, adapter, runtime, model.
- [ ] Evidence completeness: raw result, stdout, stderr, verifier logs, candidate artifacts, run config.
- [ ] Failure separation: failed attempts written with a failure label, never silently dropped.
- [ ] Cleanup replay: `--cleanup always|on-success` removes transient dirs (`agent-workspace`, `harbor-package`, `materialized-workspace`) **without** deleting evidence; Docker image pruning deliberately **not** owned by BenchEval (external adapters must document it).
- [ ] ≥1 smoke manifest committed under `config/manifests/`.
- [ ] Dry-run accuracy: `run --dry-run` plan matches the real envelope (instance count, cost, caveats).
- [ ] Caveat labels attached (e.g. `contaminated_or_legacy` for SWE-bench-family).

### C. Runtime admission (architecture §13.2) — when a runtime CLI is the scaffold
- [ ] Noninteractive launch; version captured; ephemeral workspace + config isolation (no global mutation unless explicitly allowed).
- [ ] Known/controllable network; budget enforcement; failure mapped to standard classes.

### D. Report validity (architecture §13.3)
- [ ] Any model/runtime superiority claim is gated by identical benchmark/slice/adapter/harness version.
- [ ] Failed/invalid attempts reported, not dropped.
- [ ] Interpretation label present: `adapter_smoke` · `rough_regression` · `benchmark_native_claim` · `runtime_comparison` · `model_comparison` · `contaminated_or_legacy` · `defensive_security_only` · `offensive_restricted`.

### E. Honest-labelling floor (non-negotiable)
- [ ] **No `benchmark_native_claim` label without a real Phase B run.** While live blockers hold, adapter-smoke with deterministic stand-ins (`local/harness`, `mockllm/model`) is acceptable for admission gates but must be labelled `adapter_smoke`.
- [ ] No statistical-significance claim from smoke/lite slices alone (VETO, architecture §14).
- [ ] No mixing of Calibration / Stretch / selftest tasks into weighted public-benchmark totals.

---

## 中文摘要（bilingual summary）

BenchEval 的"生产就绪"分三个层级，逐级递进，不可跳级：

| 层级 | 名称 | 含义 | 退出标准 |
|------|------|------|----------|
| Tier 0 | Phase A 软件 | 控制平面本身在零依赖下正确、确定、安全 | `make check-production-v1` 全绿（pytest / ruff / shellcheck / uv lock / 可执行适配器=3 / cybench 必须在执行前失败） |
| Tier 1 | Phase B 实证据 | 至少 1 个真实实例端到端跑通原生 harness（需要凭据 + Docker） | Peer 锚点：Terminal-Bench 的 `fix-git` 实例通过 Harbor 产出完整 `EvidenceRecord` |
| Tier 2 | Production v1 | 适配器被准入 + 实证据 + 全清单满足 | 上文 §A–§E 全部勾选，且无豁免 |

**关键红线：** 没有 Phase B 真实运行，绝不能打 `benchmark_native_claim` 标签。live blockers 期间可用 `local/harness`、`mockllm/model` 做适配器 smoke，但必须标注 `adapter_smoke`。smoke/lite 切片不得声称统计显著性；Calibration / Stretch / selftest 任务不得混入公开基准加权总分（architecture §14 VETO）。

**不要编辑** `concept-hld.md` 与 `concept-zero.md`；本文档是它们的配套说明，非规格替代。
