# Internal API contracts

BenchEval has **no public HTTP surface**. Boundaries are **Python protocols** (caller <-> implementation), Python modules, and **DTOs** (Pydantic models) shared by CLI scripts.

> **v0.3 supplement (2026-06-17):** the control-plane pivot adds a four-axis CLI surface (`benchmark/runtime/model/adapter` discovery + `run --benchmark/--slice/--runtime/--model`) and v0.3 Protocols. The legacy selftest/Core/summary contracts below are unchanged. The new contracts are frozen for feature implementation per the `roadmap → model → contract → breakdown → feature` pipeline.

## Frozen contracts

### v0.2 legacy (selftest / Core / summary pipeline)

| Artifact | Role |
| --- | --- |
| [`src/bencheval/models.py`](../../src/bencheval/models.py) | Legacy DTOs: `SummaryRow`, `ManifestDigest`, `RunStamp`, `ComparisonReport`, ... |
| [`src/bencheval/contracts.py`](../../src/bencheval/contracts.py) | Legacy `typing.Protocol` capabilities: load manifest, read `.eval`, build summary, append JSONL, compare runs |
| [`src/bencheval/task_contract.py`](../../src/bencheval/task_contract.py) | Canonical task contract schema v0.2 |
| [`src/bencheval/evidence.py`](../../src/bencheval/evidence.py) | vNext `EvidenceRecord` JSONL schema (v0.3 fields are additive, all optional) |
| [`src/bencheval/evidence_compare.py`](../../src/bencheval/evidence_compare.py) | vNext evidence compare (baseline vs current by task/model/backend) |
| [`src/bencheval/exceptions.py`](../../src/bencheval/exceptions.py) | Normalized error types crossing boundaries (`BenchEvalError`, `AdapterFailureError`, ...) |

### v0.3 control-plane

| Artifact | Role |
| --- | --- |
| [`src/bencheval/domain.py`](../../src/bencheval/domain.py) | Single source of truth: branded IDs (`NewType`), shared enums, `RuntimeProfile`, `SliceManifest`, `RunPlan` (DTO), `TokenUsage`, `AttemptSummaryDTO`, `IntegrityMetadata` |
| [`src/bencheval/contracts.py`](../../src/bencheval/contracts.py) | v0.3 Protocols: `BenchmarkCatalogSource`, `RuntimeCatalogSource`, `SliceManifestSource`, `RunPlanner`, `AdapterDispatcher` (plus the v0.2 Protocols above) |
| [`src/bencheval/runtime_registry.py`](../../src/bencheval/runtime_registry.py) | Loads `config/runtimes/*.yaml` → `RuntimeCatalog` (implements `RuntimeCatalogSource`) |
| [`src/bencheval/slice_manifest.py`](../../src/bencheval/slice_manifest.py) | Typed slice wrapper over `manifest.py` (implements `SliceManifestSource`) |
| [`src/bencheval/benchmark_registry.py`](../../src/bencheval/benchmark_registry.py) | `config/benchmarks.yaml` → `BenchmarkCatalog` (implements `BenchmarkCatalogSource`) |
| [`src/bencheval/planner.py`](../../src/bencheval/planner.py) | Four-axis `RunPlan` builder (implements `RunPlanner`) |
| [`src/bencheval/executor.py`](../../src/bencheval/executor.py) | Adapter dispatch (implements `AdapterDispatcher`) |

## CLI command surface (v0.3, frozen during impl)

BenchEval is a CLI tool. The command tree is the public API. Exit codes are the status contract.

### Command tree

```text
bencheval task lint|validate|audit ...          # selftest lane (v0.2, unchanged)
bencheval benchmark list|show|slices ...         # discovery
bencheval runtime list|show <id>                 # discovery (NEW)
bencheval model list|show <id>                   # discovery (NEW)
bencheval adapter list                           # discovery (NEW)
bencheval doctor [--benchmark <id>] [--runtime <id>]
bencheval run --dry-run --benchmark <id> --slice <id> --runtime <id> --model <id>   # plan (NEW)
bencheval run --benchmark <id> --slice <id> --runtime <id> --model <id> --output <evidence.jsonl> [--cleanup always]   # execute (NEW)
bencheval run --task|--suite|--manifest ... --backend local|inspect|harbor           # selftest compat (v0.2, unchanged)
bencheval report <evidence.jsonl> --output <report.md>
bencheval compare <baseline.jsonl> <current.jsonl> --format md|json
bencheval export <evidence.jsonl> --format parquet|duckdb --output <warehouse/...>
```

### Exit-code contract (frozen)

| Code | Meaning | When |
| ---:|---|---|
| `0` | success | command completed |
| `1` | business/admission failure | admission gates not met; invalid config; provider model mismatch; `BenchEvalError`/`TaskContractError`/`ValueError` caught in `main()` |
| `2` | usage/config error | mutually exclusive flags chosen together; missing required `--output`; `--cleanup` without `--mode single` |

Errors write a single `error: <message>` line to **stderr** and return the code; never a `200`-with-error-body pattern.

### JSON output contract (`--format json`)

Discovery and dry-run commands emit a single JSON object to **stdout** (indented, stable key order). Text format is the default for humans; JSON is the machine contract.

- `benchmark list --format json` → `{ "benchmarks": [ <BenchmarkEntry dict>, ... ] }`
- `benchmark show <id> --format json` → `<BenchmarkEntry dict>`
- `runtime list --format json` → `{ "runtimes": [ { "id", "kind", "display_name", "admission" }, ... ] }`
- `runtime show <id> --format json` → `<RuntimeProfile dict>` (no secrets — env var names only, never values)
- `run --dry-run ...` → `<RunPlan dict>` (see `domain.RunPlan`; `comparison_validity` is one of `model_comparison|runtime_comparison|adapter_smoke|diagnostic_only|invalid`)

**Never leaked** in any JSON output: secret values (`*_API_KEY` contents), artifact file contents, raw model outputs, `password_hash`-equivalents. Env vars are represented by **name only**.

### Dry-run output fields (frozen)

`run --dry-run` emits these fields (per HLD §8.2), all derived from the `RunPlan` DTO:

`schema_version`, `benchmark_id`, `benchmark_version`, `slice_id`, `adapter_id`, `harness_kind`, `runtime_id`, `runtime_kind`, `model_id`, `model_binding`, `instance_count`, `instances`, `budget_class`, `max_cost_usd`, `max_wall_clock_sec`, `requires_harbor`, `requires_sandbox`, `network_policy`, `cleanup_policy`, `caveats`, `comparison_validity`, plus additive `slice_resolution` (instance manifest SHA256, `execution_support`, resolved ids).

Evidence JSONL v0.3 additive fields may include `attempt_validity`, `invalid_reason`, `counts_toward_pass_at_k`, `physical_launch_id`, `logical_attempt_number`, `runtime_output_cap`, and extended `failure_class` values (`runtime_output_cap_reached`, `operator_interrupted`, …). See `docs/context/runtime-invocation-contracts.md`.

## Coupling rules

- **Callers** depend on Protocols, DTOs, and CLI/library entrypoints — not on Inspect/Harbor SDK classes directly.
- **Adapters** implement execution backends (`inspect_adapter`, `harbor_adapter`, native, runtime-CLI, local harness). They return `EvidenceRecord` rows; they never return native SDK objects across the boundary.
- **Services return domain objects / DTOs, never DB/native entities.** `RunPlan` is a DTO (no paths, no secrets). `EvidenceRecord` is the store (has artifact paths). `AttemptSummaryDTO` is the public report row (no paths). Map entity → DTO at the boundary.
- **Shell scripts** (`scripts/*.sh`) orchestrate process boundaries; legacy `.eval` parsing and vNext scoring stay in Python entrypoints.
- **`SummaryBuilder.build`** takes a `ManifestDigest` so implementers can verify `stamp.task_manifest_hash`, align `n_samples` with `len(manifest.task_ids)`, and refuse inconsistent rows before writing JSONL.
- **v0.3 planner** takes the four-axis tuple and returns a frozen `RunPlan`; it performs NO execution and touches NO filesystem artifacts. The executor turns a `RunPlan` into `EvidenceRecord` rows.

## Error shape (standardized)

- Recoverable validation failures → `SummaryValidationError` / `EvidenceValidationError` / `ComparisonError` / `TaskContractError` with a single human-readable message.
- Adapter preflight/infrastructure failures → `AdapterFailureError` (abort, no evidence) or a post-preflight `EvidenceRecord` with `primary_pass=False` + canonical `FailureLabel`.
- Scripts and CLI exit non-zero on any `BenchEvalError` subclass. One error shape, everywhere.

## Versioning

- Breaking changes to `SummaryRow` require a new JSONL file stem or a documented migration in `docs/architecture.md`; treat the schema as a public contract for longitudinal analysis.
- **`EvidenceRecord` v0.3 is additive only.** v0.2 fields and the permissive model config (no `extra="forbid"`) are a frozen contract; v0.3 optional fields default to `None`/absent so v0.2 JSONL rows keep parsing. New domain models (`RuntimeProfile`, `SliceManifest`, `RunPlan`, `TokenUsage`, `AttemptSummaryDTO`) use `frozen=True, extra="forbid"`.
- CLI commands are versioned by behavior, not a `/v1/` prefix (there is no HTTP layer). New flags are additive; removing/renaming a flag is a breaking change documented in `docs/architecture.md` §16 Changelog.

## Idempotency & safety

- `run --dry-run` is idempotent and side-effect-free (no filesystem writes, no network). Safe to retry.
- `run` (execute) is **not idempotent** — it writes evidence and may mutate transient workspaces. Documented. `--cleanup always` with `--mode single` is the bounded-lifecycle path.
- `report` / `compare` / `export` are read-only over evidence files; idempotent.
- `doctor` is read-only preflight; idempotent.

## Related

- Canonical field definitions: [`docs/architecture.md`](../architecture.md)
- Domain types (single source of truth): [`src/bencheval/domain.py`](../../src/bencheval/domain.py)
- Diagrams: [`docs/diagrams/`](../diagrams/)
