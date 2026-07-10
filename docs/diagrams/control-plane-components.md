# Control-Plane Components (C4 L3)

What this shows: internal components of the BenchEval library for four-axis discovery, planning, preflight, execution, and evidence/report.

```mermaid
flowchart TB
    CLI["cli.py<br/>plan · run · doctor · compare · …"]

    subgraph Discovery["Discovery registries"]
        BR["benchmark_registry.py<br/>config/benchmarks.yaml"]
        SM["slice_manifest.py<br/>config/slices/*.yaml + manifests/*.txt"]
        RR["runtime_registry.py<br/>config/runtimes/*.yaml"]
        MR["model_registry.py<br/>config/models.yaml"]
        BP["benchmark_plan.py<br/>AdapterDescriptor catalog"]
    end

    subgraph PlanExec["Plan → execute"]
        Plan["planner.py / ControlPlanePlanner<br/>→ domain.RunPlan"]
        Doc["doctor.py<br/>preflight; no secrets in output"]
        CPE["control_plane_executor.py<br/>dispatch by adapter_id"]
        Life["lifecycle.py · workspace_staging.py<br/>BenchEval-owned temp dirs only"]
    end

    subgraph EvidenceOut["Evidence + analytics"]
        Ev["evidence.py<br/>EvidenceRecord + JsonlEvidenceSink"]
        Rep["report.py"]
        Cmp["evidence_compare.py<br/>runtime_compare · model_compare"]
        Exp["export.py · run_bundle.py"]
    end

    Paths["paths.py<br/>repo_root / wheel bundle"]

    CLI --> Paths
    Paths --> Discovery
    CLI --> BR & SM & RR & MR & BP
    CLI -->|plan / run dry| Plan
    BR & SM & RR & MR --> Plan
    CLI -->|live run| Doc
    Plan --> Doc
    Doc --> CPE
    CPE --> Life
    CPE --> Ev
    Ev --> Rep & Cmp & Exp
    CLI --> Rep & Cmp & Exp
```

Notes: `executor.py` / `backends.py` / `runner.py` remain the **selftest** dispatch path (`--task`/`--backend`). Production four-axis live runs go through `control_plane_executor.py`. Domain DTOs live in [`domain.py`](../../src/bencheval/domain.py); Protocols in [`contracts.py`](../../src/bencheval/contracts.py).
