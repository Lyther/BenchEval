# Internal API contracts

BenchEval has **no public HTTP surface**. Boundaries are **Python protocols** (caller <-> implementation), Python modules, and **DTOs** (Pydantic models) shared by CLI scripts.

## Frozen contracts

| Artifact | Role |
| --- | --- |
| [`src/bencheval/models.py`](../../src/bencheval/models.py) | Legacy DTOs: `SummaryRow`, `ManifestDigest`, `RunStamp`, `ComparisonReport`, ... |
| [`src/bencheval/contracts.py`](../../src/bencheval/contracts.py) | Legacy `typing.Protocol` capabilities: load manifest, read `.eval`, build summary, append JSONL, compare runs |
| [`src/bencheval/task_contract.py`](../../src/bencheval/task_contract.py) | Canonical task contract schema v0.2 |
| [`src/bencheval/evidence.py`](../../src/bencheval/evidence.py) | vNext `EvidenceRecord` JSONL schema |
| [`src/bencheval/evidence_compare.py`](../../src/bencheval/evidence_compare.py) | vNext evidence compare (baseline vs current by task/model/backend) |
| [`src/bencheval/exceptions.py`](../../src/bencheval/exceptions.py) | Normalized error types crossing boundaries (`BenchEvalError`, `AdapterFailureError`, ...) |

## Coupling rules

- **Callers** depend on protocols, DTOs, and CLI/library entrypoints — not on Inspect/Harbor SDK classes directly.
- **Adapters** implement execution backends (`inspect_adapter`, `harbor_adapter`, local harness).
- **Shell scripts** (`scripts/*.sh`) orchestrate process boundaries; legacy `.eval` parsing and vNext scoring stay in Python entrypoints.
- **`SummaryBuilder.build`** takes a `ManifestDigest` so implementers can verify `stamp.task_manifest_hash`, align `n_samples` with `len(manifest.task_ids)`, and refuse inconsistent rows before writing JSONL.

## Error shape

- Recoverable validation failures -> `SummaryValidationError` / `EvidenceValidationError` / `ComparisonError` with a single human-readable message.
- Scripts and CLI exit non-zero on any `BenchEvalError` subclass.

## Versioning

- Breaking changes to `SummaryRow` require a new JSONL file stem or a documented migration in `docs/architecture.md`; treat the schema as a public contract for longitudinal analysis.

## Related

- Canonical field definitions: [`docs/architecture.md`](../architecture.md)
- Diagrams: [`docs/diagrams/`](../diagrams/)
