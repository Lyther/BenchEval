# Data Model (ERD)

What this shows: core persisted and planned entities — catalogs feed RunPlan; adapters emit EvidenceRecord and optional run-record streams.

```mermaid
erDiagram
    BENCHMARK_ENTRY ||--o{ SLICE_MANIFEST : "has slices"
    BENCHMARK_ENTRY {
        string id PK
        string adapter_id
        string harness_kind
        bool executable
        string adapter_status
        string tier
    }
    SLICE_MANIFEST {
        string id PK
        string benchmark_id FK
        string purpose
        string instances_source
        int max_instances
    }
    RUNTIME_PROFILE {
        string id PK
        string kind
        string admission
        string supported_harnesses
    }
    MODEL_ENTRY {
        string id PK
        string provider
        string family
    }
    RUN_PLAN {
        string benchmark_id FK
        string slice_id FK
        string runtime_id FK
        string model_id FK
        string adapter_id
        string harness_kind
        string comparison_validity
        bool requires_harbor
    }
    EVIDENCE_RECORD {
        string run_id
        string task_id
        string model_id
        bool primary_pass
        string benchmark_id
        string slice_id
        string runtime_id
        string adapter_id
        string attempt_validity
        bool counts_toward_pass_at_k
        string interpretation_label
    }
    RUN_RECORD_HEADER ||--|{ RUN_RECORD_EVENT : "seq ordered"
    RUN_RECORD_HEADER ||--|| RUN_RECORD_FOOTER : "closes"
    RUN_RECORD_HEADER {
        string run_id PK
        string schema "bencheval_run_record_v1"
        string benchmark_id
        string evidence_sha256
    }
    RUN_RECORD_EVENT {
        int seq
        string type
        string instance_id
        datetime ts
    }
    RUN_RECORD_FOOTER {
        string run_id FK
        string status
    }
    LIVE_STATE {
        string attempt_key PK
        string monitor_status
        datetime updated_at
    }

    BENCHMARK_ENTRY ||--o{ RUN_PLAN : "plans"
    SLICE_MANIFEST ||--o{ RUN_PLAN : "bounds"
    RUNTIME_PROFILE ||--o{ RUN_PLAN : "drives"
    MODEL_ENTRY ||--o{ RUN_PLAN : "binds"
    RUN_PLAN ||--o{ EVIDENCE_RECORD : "executes to"
    RUN_RECORD_HEADER ||--o{ EVIDENCE_RECORD : "may bind"
    RUN_RECORD_EVENT ||--o| LIVE_STATE : "high-volume offload"
```

Notes: `EvidenceRecord` v0.2 fields are a frozen public export; v0.3 fields are additive optional ([`evidence.py`](../../src/bencheval/evidence.py)). No relational DB — JSONL/SQLite files on disk. Legacy `SummaryRow` ([`models.py`](../../src/bencheval/models.py)) remains selftest-only and is not the primary scoring contract.
