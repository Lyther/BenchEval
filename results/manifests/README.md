# `results/manifests/` — live run registry (local, gitignored)

This directory is a **local registry** that maps each live run to the exact slice
manifest + run configuration that produced its evidence. It is the per-machine
companion to the committed control-plane manifests.

## What lives here

Each entry is a small, human-readable record tying a live run to its inputs:

- a copy (or symlink) of the slice manifest actually used for that run
  (e.g. the 5 task ids fed to `--manifest`), and
- a run manifest (`*.json`) capturing: `run_id`, timestamp, `benchmark` /
  `slice` / `runtime` / `model` axes, the evidence JSONL path under
  `results/evidence/`, adapter/harness versions, and any caveats or
  interpretation labels (`adapter_smoke`, `benchmark_native_claim`, …).

Example layout:

```text
results/manifests/
  20260618T150500Z-tb-claude-code-haiku/
    smoke-5.txt                       # the slice manifest used (copy of config/manifests/terminal-bench-smoke-5.txt)
    run.json                          # run_id, axes, versions, evidence path, caveats
```

## Gitignore policy (the pattern this file documents)

Live-run registries are **machine-local and never committed**. This mirrors the
existing `results/raw/*`, `results/evidence/*`, `results/bundles/*` policy in
[`.gitignore`](../../.gitignore):

```gitignore
results/manifests/*
!results/manifests/README.md
```

Only this `README.md` is tracked, so the directory exists in a fresh clone as a
documented placeholder. Put real registry entries under a dated subdir (or flat
files); they will be ignored automatically.

## Why local-only

- Live evidence references provider credentials, private bundles, and host paths
  that are not portable across machines.
- The committed source of truth for **which tasks a slice contains** is
  [`config/manifests/`](../../config/manifests) (e.g.
  `terminal-bench-smoke-5.txt`). This directory records **what was actually run,
  when, and against what versions** — a run audit trail, not a slice definition.
- To share a run externally, use the redacted bundle path instead:
  `bencheval export-run --redaction public` (see
  [`docs/context/production-v1-pilot.md`](../../docs/context/production-v1-pilot.md)
  and the [production readiness tiers](../../docs/context/production-readiness.md)).

## Relationship to the readiness tiers

A populated `results/manifests/` entry with a complete, non-fake `EvidenceRecord`
is exactly the **Tier 1 (Phase B live evidence)** proof defined in
[`docs/context/production-readiness.md`](../../docs/context/production-readiness.md).
For the Terminal-Bench adapter the canonical single-instance anchor is the
`fix-git` task in `config/manifests/terminal-bench-smoke-5.txt`.
