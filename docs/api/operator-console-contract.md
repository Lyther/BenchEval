# Operator console contract

Status: **IMPLEMENTED v1 contract; hardening/acceptance limits below**

Last updated: 2026-09-01

Implementation boundary: `src/bencheval/application/` and
`src/bencheval/ui/`, launched through `bencheval ui`. The full page/action
surface is present. Deterministic operation/security tests and a real local
Chromium navigation/plan journey pass; cross-browser accessibility automation,
large-history measurement, and a charged run launched from the console remain
hardening evidence, not implied by this status.

Source concept: [`../context/concept-zero.md`](../context/concept-zero.md)
Source architecture: [`../architecture.md`](../architecture.md), especially §20,
Data and State, and Interfaces and Contracts
Visual coverage: [`../prototypes/frontend-v1.md`](../prototypes/frontend-v1.md)

## Applicability

- **Domain/data track: REQUIRED.** BenchEval owns typed configuration, frozen run
  plans, append-only lifecycle and evidence, derived reports/exports, artifacts,
  and immutable private-proof state. The console adds no authoritative store.
- **Interface track: REQUIRED.** The console is a new caller of typed in-process
  operations and a new local CLI entry point. NiceGUI's browser transport is
  private and is not a supported HTTP/WebSocket API.

## Boundary

```text
CLI handlers ─┐
              ├─ typed application operations ─ existing domain modules ─ canonical files/processes
UI handlers  ─┘
```

The application layer composes existing modules; it does not become a second
planner, executor, qualifier, comparison engine, redactor, or proof verifier.
Pages and components receive only view DTOs and action descriptors.

Explicitly outside the contract:

- storage rows serialized directly to a browser;
- public REST, GraphQL, RPC, SSE, or WebSocket compatibility;
- remote or multi-user access, identities, roles, or accounts;
- config/credential editing, arbitrary shell, or browser-owned paths;
- parallel scheduling, durable jobs, resume after process restart;
- proof deletion/replacement/expiry or benchmark admission/promotion.

## Canonical domain and state

| Concept | Canonical representation and owner | Identity/lifecycle invariant | Sensitivity and retention |
|---|---|---|---|
| Catalog entries | Pydantic registries over `config/**/*.yaml` | IDs/aliases unique; executable/admission/identity validated by registry and planner | Public; versioned with config; UI read-only |
| Run plan | `RunPlan` in `domain.py` and anchored `run-plan.json` | Runtime XOR agent; model/provider/harness/slice/budget/network/diagnostic constraints; written before launch | Private operational metadata; retained with run/proof |
| Run lifecycle | `LiveRunRecord` append-only `runs.jsonl` plus validated projection | Immutable run/model, fill-once axes, monotonic time, legal transitions, locked append | Local private; permanent unless operator manages filesystem outside BenchEval |
| Attempt evidence | frozen `EvidenceRecord` JSONL plus owned artifacts | Official authority and exact bytes, captured provenance, validity/failure/interpretation/cost basis | Private by default; public only through sanitizer/export |
| Comparison | canonical comparison functions/results | Shared eligible intersection and constant non-varied axes before headline | Derived, reproducible; no authority over source evidence |
| Report/export | Markdown/JSON/Parquet/DuckDB/run bundle | Exclusive destination; public/private visibility and caveats preserved | Derived; operator-owned retention |
| Private proof | `private_proof_v1`, inventory digest, `proofs.jsonl` | Exact inventory/file-set/hash/identity/history; verified-before-import; digest-idempotent | Private permanent local retention; no delete lifecycle |
| Readiness | Catalog/software gates, registered live proof, benchmark-specific ledger docs | Tier-0, Tier-1, Tier-2 are independent; no tier inferred from UI or tests | Public/project state plus private proof references |
| Run session | implemented `ui.session.RunSessionController` in memory | At most one active mutation; one run ID; explicit cancel; no automatic retry/resume | Ephemeral; never serialized or treated as lifecycle truth |

Existing files and models remain canonical. No schema or migration is introduced
by this design. A future database requires a superseding architecture decision.

## View DTO contract

All DTOs are frozen Pydantic models with `extra="forbid"`. Request DTOs accept
only JSON-compatible scalar/list/map data needed for the operation. View DTOs
are deliberate projections and carry `contract_version: Literal["ui_v1"]`.

```python
class OperationErrorDTO:
    contract_version: Literal["ui_v1"]
    code: str
    message: str                 # concise, redacted, actionable
    retryable: bool
    human_action_required: bool

class ActionDTO:
    contract_version: Literal["ui_v1"]
    id: str
    allowed: bool
    disabled_reason: str | None

class CatalogPageDTO:
    contract_version: Literal["ui_v1"]
    items: tuple[CatalogItemDTO, ...]
    next_cursor: str | None
    source_revision: str         # source fingerprint, not a filesystem inode/path
```

Operations raise `BenchEvalError` at the in-process boundary. UI handlers map
that error to a redacted notification; there is no serialized generic
`OperationResult` wrapper or public transport error schema in v1.

### Catalog DTOs

`CatalogItemDTO(kind="benchmark")` exposes ID/name, execution support,
category/tier/adapter state, default slice, and whether the row is runnable. It
never exposes executable command templates or config file
paths. Model/runtime/agent/provider DTOs expose public capability/admission and
credential environment-variable names only; provider launch URLs, credentials,
proxy credentials, and environment values never cross.

### Plan and preflight DTOs

`PlanRequestDTO` contains target benchmark/slice, model, optional runtime XOR
agent, optional provider, diagnostic flag, and operator-selected output paths.
It maps to the existing planner and returns:

- `PlanPreviewDTO`: benchmark/adapter/harness/runtime/agent/provider/model axes,
  benchmark identity, planned instance count, execution support, cost/wall
  envelopes, network policy, diagnostic state, caveats, and a stable fingerprint
  over canonical plan bytes. The nested request retains operator-selected paths;
- `DoctorViewDTO`: backend, overall state, and ordered
  `DoctorCheckDTO{name,status,message}` values;
- actions for Dry run and Start. Start requires the same plan fingerprint and
  expires if config/source revision changes.

The UI cannot post a serialized `RunPlan` as authority. The operation replans
from request axes and compares the fingerprint before charge.

### Run, evidence, and artifact DTOs

`RunSummaryDTO` exposes lifecycle registration, identity axes, evidence/report/
bundle locators, event count, host, and the last event time. `RunDetailDTO` adds
the validated raw-history projection, bounded `EvidenceSummaryDTO` rows,
qualification reasons, and legal actions. Task outcome, failure class, attempt
validity, interpretation, cost, cost basis, and artifact locators live on those
evidence summaries rather than on the lifecycle summary.

`EvidenceSummaryDTO.artifacts` contains bounded local artifact locators, while
`ArtifactResultDTO` contains role, path, size, digest, visibility, validity, and
bounded details for a newly generated artifact. The local private console may
show operator-owned absolute paths so the operator can locate evidence; public
reports and bundles remain subject to the existing sanitizer. No DTO contains
arbitrary HTML, credential values, or artifact bytes.

### Comparison/report/export DTOs

Comparison operations return `ArtifactResultDTO`: canonical comparison modules
render the Markdown/JSON artifact, while `valid` and `detail` expose whether a
headline is allowed and why an invalid comparison was rejected. The UI does not
recalculate comparison metrics.

Report/export results contain output role, local path, size, digest, visibility,
validity, and bounded details. They do not embed Parquet/DuckDB or
private bundle bytes in application state.

### Proof and readiness DTOs

`ProofViewDTO` exposes proof ID, run ID, local path, classification and reason,
verification result, and optional benchmark ID. “Verified” means inventory/
content integrity, not creator authenticity or signature. There is no delete
action ID. An indexed object that fails verification is returned as
`classification="corrupt"`, `verified=false`, with the proof ID, local path,
and bounded verifier reason so healthy sibling proofs remain usable. Corruption
of the shared proof index remains a page-level typed error because row identity
cannot then be trusted.

Each `ReadinessItemDTO` exposes benchmark software state, registered Tier-1
state, Tier-2 claim state, ledger link, and blockers. A verified proof without a
qualified registered `passed` event is explicitly `proof-present-not-tier1`.
Missing or unparseable ledger material yields unknown/blocked;
the UI never upgrades a tier by inference.

## Operation contracts

| Stable operation | Input → output | Validation owner | Idempotency/retry |
|---|---|---|---|
| `catalog.list/show` | kind/filter/page or kind/id → catalog DTO/page | registries + application projection | Read-only; repeatable |
| `run.plan` | `PlanRequestDTO` → `PlanPreviewDTO` | planner/domain | Pure; repeatable |
| `doctor.run` | backend/profile/model → `DoctorViewDTO` | doctor | Read-only probe; explicit repeat |
| `run.start` | plan request + fingerprint + confirmation → `RunSessionView` | replan, executor, output claim | Never auto-retry; duplicate/session conflict typed |
| `run.session` | none/run ID → current session view | session owner + durable projection | Read-only |
| `run.cancel` | session/run ID → cancellation result | session owner + adapter/process lifecycle | Explicit once; repeated terminal cancel is no-op result, not relaunch |
| `runs.list/get` | filters/page or run ID → summary/detail | full history/evidence readers | Read-only; source-bound cursor |
| `evidence.qualify` | run/evidence/selectors → qualification view | `live_proof`/provenance gates | Read-only |
| `evidence.register` | run ID, target status, optional axes/locators/notes/host → run detail | live-run transition/identity/qualification | Locked append; never blind retry |
| `analysis.compare` | baseline/current/mode → comparison view | canonical compare modules | Read-only; repeatable |
| `report.generate` | evidence/output → artifact result | report module + exclusive path | No overwrite/retry after ambiguity |
| `warehouse.export` | evidence/format/output → artifact result | export module | Exclusive destination |
| `bundle.export` | evidence/raw/visibility/optional comparison/output → artifact result | run bundle/redaction | Exclusive, no partial output |
| `proof.list/inspect` | page or proof ID → proof page/view | proof index/verifier | Read-only; object corruption is isolated to a typed row; index corruption fails the page closed |
| `proof.export` | run/evidence/artifacts/manifest/capture/output → proof view | proof exporter | Exclusive destination |
| `proof.verify` | path/optional expected digest → verification result | proof verifier | Read-only |
| `proof.import` | path/store → proof view | verify then atomic store/index | Idempotent only on identical full row/digest |
| `readiness.get` | optional benchmark → readiness view | catalog/proof/ledger projection | Read-only; no inferred claim |

## Error model

```text
invalid_request          syntax, missing field, bounded UI validation
domain_rejected          axis, plan, transition, eligibility, or admission failure
not_executable           catalog-only, scaffold, or unavailable diagnostic path
preflight_failed         dependency, credential presence, daemon, runtime, or profile
human_action_required    literal device/subscription/CAPTCHA/hardware/admin action
conflict                 active run, duplicate ID, existing output, stale fingerprint/cursor
integrity_failed         canonical history, evidence, artifact, path, or proof corruption
not_found                catalog/run/evidence/proof/source absent
dependency_missing       optional UI/export/harness package absent
cancelled                explicit operator cancellation completed
timeout                  operation/session envelope elapsed
operation_failed         bounded unexpected failure; trace remains server-side
refresh_required         cursor/fingerprint source revision changed
```

`retryable=true` is limited to read probes, refresh-required reads, or operations
whose domain contract explicitly permits retry. State-changing UI never retries
automatically. `human_action_required` follows the existing narrow HITL policy.

## Pagination, ordering, and live updates

- Catalogs order by stable ID; runs/evidence/proofs default newest-first with ID
  tie-break. The selected order is included in cursor semantics.
- Cursor is opaque, versioned, and bound to a source fingerprint and position.
  A changed source returns `refresh_required`, preventing skips/duplicates.
- Limits are 1–200; default 50. Artifact preview defaults 128 KiB and has a hard
  design cap of 1 MiB pending the U3 measurement gate.
- Live RunSession events are bounded, monotonic sequence records for
  presentation only. Lost UI events trigger refresh from durable state; they do
  not mutate evidence or manifest history.

## Validation and entity-to-DTO mapping

| Internal source | Boundary projection | Boundary validation | Domain validation | Must never cross |
|---|---|---|---|---|
| Benchmark/model/runtime/agent/provider profiles | catalog DTOs | filters, page limit | registry schema/admission/identity | secret env values, launch commands, private URLs |
| `RunPlan` | plan preview/run detail | request syntax, fingerprint shape | planner axis/budget/harness/diagnostic rules | mutable plan accepted as authority |
| `DoctorReport` | preflight/environment DTO | selected profile/model syntax | real checks/provider routing | credential values, raw import tracebacks |
| `LiveRunRecord` + projection | run summary/detail/history | filters/cursor | full-history validation/transition rules | unvalidated row, lock/path internals |
| `EvidenceRecord` | evidence/task outcome DTO | preview bounds | evidence schema, official authority, eligibility | raw secret metadata, arbitrary HTML, unredacted public paths |
| Comparison report | comparison DTO | selection/mode syntax | shared eligibility and provenance gates | page-recomputed headline/ranking |
| Report/export result path | artifact result DTO | output-role/format/path syntax | exclusive writer/redactor/exporter | server file bytes in state, overwrite shortcut |
| Proof inventory/index | proof DTO | expected digest/path syntax | verifier/file-set/history/identity/store rules | delete action, signature/authenticity claim |
| Tier ledger and proof references | readiness DTO | benchmark selector | claim/proof/ledger projection | inferred Tier-2 or green-test readiness |

## Local browser capability contract

- Listener is `127.0.0.1` only. `Host` and `Origin` must match the effective
  loopback origin; no wildcard CORS, proxy trust, iframe, or remote bind.
- Startup creates a random per-process capability. The opened local URL exchanges
  it once for a strict HttpOnly session cookie and removes it from visible
  history. The token is never logged or persisted.
- Every event still validates its request DTO and domain invariants. Possession
  of the local capability is not permission to bypass non-executable, transition,
  qualification, path, diagnostic, or proof rules.
- This is process-local capability protection, not user authentication. Any
  remote or multi-user requirement invalidates this contract.

## Compatibility and change policy

- CLI grammar, persisted JSONL/YAML, proof formats, and exported domain DTOs keep
  their existing compatibility policies and remain independent of UI releases.
- Application operation names and `ui_v1` DTOs are internal until the first
  shipped console release. After that, changes are additive within v1; removals
  or semantic changes require a versioned DTO/operation and migration period.
- NiceGUI routes/events/transport are not supported contracts. A replacement UI
  may reuse the application operations without compatibility with browser frames.
- Every UI mutation must have a CLI or application-operation equivalent. A UI-
  exclusive feature requires concept and contract review before implementation.
