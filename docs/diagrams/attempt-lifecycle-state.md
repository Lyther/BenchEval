# Attempt Lifecycle State

What this shows: how a physical launch becomes a scored attempt — validity, pass@k eligibility, and distinct failure classes.

```mermaid
stateDiagram-v2
    [*] --> Preflight
    Preflight --> Aborted: doctor / materialization fail\n(no EvidenceRecord)
    Preflight --> Launching: preflight ok

    Launching --> Running: process started
    Launching --> Invalid: runtime_launch_failure

    Running --> Scoring: process exited / stream complete
    Running --> Invalid: runtime_no_progress_stall\nruntime_output_cap_reached\noperator_interrupted
    Running --> FailedInfra: runtime_tool_failure\nharness_failure\nadapter_error

    Scoring --> ValidPass: primary_pass=true\nattempt_validity=valid
    Scoring --> ValidFail: primary_pass=false\nmodel_wrong_solution / …\nattempt_validity=valid
    Scoring --> Invalid: verification gap / policy invalid

    ValidPass --> PassAtK: counts_toward_pass_at_k=true
    ValidFail --> PassAtK: counts_toward_pass_at_k=true
    Invalid --> Excluded: counts_toward_pass_at_k=false
    FailedInfra --> Excluded: reported, not dropped

    PassAtK --> [*]
    Excluded --> [*]
    Aborted --> [*]
```

Notes: Preflight aborts leave no evidence row; everything after launch should be attributable ([architecture §10](../architecture.md)). Compare/report must not drop failed/invalid attempts when claiming superiority ([§13.3](../architecture.md)). `eligible_for_pass_at_k()` in `evidence.py` is the denominator gate.
