# Summary extraction sequence

End-to-end path from a finished eval run to an append-only summary row.

## Diagram

```mermaid
sequenceDiagram
    participant Op as Operator
    participant Sh as run_eval.sh
    participant In as inspect eval
    participant Raw as results/raw/*.eval
    participant Py as extract_summary CLI
    participant ML as ManifestLoader
    participant EL as EvalLogSource
    participant SB as SummaryBuilder
    participant Sk as SummarySink
    participant JL as results/summary/*.jsonl

    Op->>Sh: launch pinned (benchmark, model, stamp)
    Sh->>In: subprocess
    In->>Raw: write .eval
    Op->>Py: uv run extract_summary
    Py->>ML: load manifest → ManifestDigest
    Py->>EL: read_header(.eval)
    Py->>SB: build(stamp, manifest, header)
    SB-->>Py: SummaryRow
    Py->>Sk: append_jsonl(row)
    Sk->>JL: validated line
```

## Notes

- If `SummaryBuilder` raises `SummaryValidationError`, the CLI must exit non-zero and **not** append a partial row.
- `RunStamp.auth_lane` is set by the wrapper, not inferred from the log.
