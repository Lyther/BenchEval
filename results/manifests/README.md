# `results/manifests/` — live run registry (local, gitignored)

This directory is a **local registry** that maps each live run to the exact slice configuration that produced its evidence. It is the per-machine companion to the committed control-plane slice YAMLs under `config/slices/`.

## What lives here

The registry is one append-only JSONL file. Each `live_run_v1` row records `run_id`, timestamp, host, `benchmark` / `slice` / `runtime` / `model` axes, artifact references (evidence/report/bundle), lifecycle status, and non-secret notes. The exact slice definition remains the committed typed YAML under `config/slices/`; the row binds it by `slice_id` rather than copying or symlinking YAML into this directory.

One `run_id` may have multiple lifecycle or correction rows. `append_live_run` already validates the architecture §18.3 event contract on write: optional identity axes may be filled once, then remain immutable; timestamps do not move backward; same-status corrections and documented forward transitions are allowed. The current reader still returns every valid row in append order and does not derive a last-event operational view; consumers must inspect the raw history rather than assuming `run_id` is unique or blindly selecting an arbitrary row. Portable private bundles, inventory digests, and cross-host verification remain roadmap R2 work.

Example layout:

```text
results/manifests/
  README.md
  runs.jsonl                          # one append-only live_run_v1 row per registration
```

## Gitignore policy (the pattern this file documents)

Live-run registries are **machine-local and never committed**. This mirrors the existing `results/raw/*`, `results/evidence/*`, `results/bundles/*` policy in [`.gitignore`](../../.gitignore):

```gitignore
results/manifests/*
!results/manifests/README.md
```

Only this `README.md` is tracked, so the directory exists in a fresh clone as a documented placeholder. The CLI appends real rows to `runs.jsonl`; it is ignored automatically.

## Why local-only

- Live evidence references provider credentials, private bundles, and host paths that are not portable across machines.
- The committed source of truth for **which tasks a slice contains** is [`config/slices/`](../../config/slices) (typed slice manifests). This directory records **what was actually run, when, and against what versions** — a run audit trail, not a slice definition.
- To share a run externally, use the redacted bundle path instead: `bencheval export-run --redaction public` (see [`docs/context/production-v1-pilot.md`](../../docs/context/production-v1-pilot.md) and the [production readiness tiers](../../docs/context/production-readiness.md)).

## Relationship to the readiness tiers

A qualified `passed` row in `results/manifests/runs.jsonl`, backed by complete native-harness `EvidenceRecord` rows, records the **tier 1 (Phase B live evidence)** proof defined in [`docs/context/production-readiness.md`](../../docs/context/production-readiness.md). For the Terminal-Bench adapter the canonical single-instance anchor is the `fix-git` task in the Terminal-Bench smoke slice under `config/slices/`.
