# Runnable adapter coverage gap (S0.4)

> Updated 2026-06-18. Machine-readable catalog: `config/benchmarks.yaml`.

| adapter_status | Count (approx.) | Meaning |
|---|---:|---|
| `cataloged` | majority | Metadata only; no typed slice + executor path |
| `adapter_pending` | some | Planned adapter; not `manifest_available` |
| `manifest_available` | 3 | `terminal-bench`, `swe-bench-verified`, `bfcl-v4` |
| `cataloged` (example) | `cybench` | Metadata only until adapter + typed slice |
| `unverified` | some | Reference-only entries |

## Planner-ready slices (typed YAML under `config/slices/`)

| benchmark_id | slice_id | instances | runtime smoke pairing |
|---|---|---:|---|
| `terminal-bench` | `smoke-5` | 5 | `claude-code`, `codex-cli` + Harbor |
| `swe-bench-verified` | `swe-bench-verified-smoke-10` | 10 | `mini-swe-agent` + `swebench` |
| `bfcl-v4` | `smoke-5` | 5 | `native-api` / `inspect-api` + `bfcl` |
| `swe-rebench` | `swe-rebench-smoke-10` | 10 | catalog only (`adapter_pending`) |

## Harness mapping (control-plane planner)

- `terminal-bench` → `terminal-bench-harbor` / `harbor`
- `swe-bench-verified` → `swebench` / `swebench-native`
- `bfcl-v4` → `bfcl` / `bfcl-native`
- Other catalog entries → `recommended_backend` heuristic until native adapter lands

## Live execution blockers

See `docs/roadmap.md` § Live blockers (Harbor CLI, Docker, `mini-swe-agent`, `bfcl-eval`, runtime auth).

Adapter-smoke uses injected process runners in CI; label runs via slice `purpose` / `interpretation_label`.
