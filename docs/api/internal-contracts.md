# Internal API contracts

BenchEval has **no public HTTP surface**. Boundaries are **Python protocols** (caller ↔ implementation) and **DTOs** (Pydantic models) shared by CLI scripts.

## Frozen contracts

| Artifact | Role |
| --- | --- |
| [`src/bencheval/models.py`](../../src/bencheval/models.py) | DTOs: `SummaryRow`, `ManifestDigest`, `RunStamp`, `ComparisonReport`, … |
| [`src/bencheval/contracts.py`](../../src/bencheval/contracts.py) | `typing.Protocol` capabilities: load manifest, read `.eval`, build summary, append JSONL, compare runs |
| [`src/bencheval/exceptions.py`](../../src/bencheval/exceptions.py) | Normalized error types crossing boundaries |

## Coupling rules

- **Callers** depend on protocols + DTOs only — not on Inspect/Harbor SDK classes.
- **Adapters** implement protocols (e.g. `EvalLogSource` backed by Inspect’s on-disk format).
- **Shell scripts** (`scripts/*.sh`) orchestrate process boundaries; they must not parse `.eval` themselves — delegate to `uv run python …` entrypoints that use `SummaryBuilder`.
- **`SummaryBuilder.build`** takes a `ManifestDigest` so implementers can verify `stamp.task_manifest_hash`, align `n_samples` with `len(manifest.task_ids)`, and refuse inconsistent rows before writing JSONL.

## Error shape

- Recoverable validation failures → `SummaryValidationError` / `ComparisonError` with a **single** human-readable message; no nested RPC-style payloads.
- Scripts exit non-zero on any `BenchEvalError` subclass.

## Versioning

- Breaking changes to `SummaryRow` require a **new JSONL file stem** or a documented migration in `docs/architecture.md` §6 — treat the schema as a public contract for longitudinal analysis.

## Related

- Canonical field definitions: [`docs/architecture.md`](../architecture.md) §6–§7
- Diagrams: [`docs/diagrams/`](../diagrams/)
