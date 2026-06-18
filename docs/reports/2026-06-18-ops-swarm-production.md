# Swarm Report — Production readiness (4 workers)

**Issue:** Close gap between Phase A software and honest "production v1" narrative.
**Constraint:** Do not edit `concept-hld.md` / `concept-zero.md`.

## Executive Decision

- **Status:** partial (software + ops layer complete; Phase B matrix still host-gated)
- **Answer:** Tier **Production v1 software** is met (`638` tests, `doctor --profile pilot`, evidence register, runbooks). Tier **live production proof** requires dev-box matrix exit `0` per `production-readiness.md`.
- **Next action:** `scripts/doctor-pilot.sh` on dev-box → `./scripts/run-live-pilot-matrix.sh` → `bencheval evidence register` per run.

## Packets

| ID | Role | Deliverable |
|----|------|-------------|
| P1 | docs/UX | `production-readiness.md`, README 5-min split, roadmap count, `results/manifests/README.md` |
| P2 | doctor | `bencheval doctor --profile pilot`, `tests/test_doctor.py` |
| P3 | registry | `live_run_manifest.py`, `bencheval evidence register`, tests |
| P4 | ops | `docs/ops/dev-box-pilot.md`, `doctor-pilot.sh` (aligned to native pilot profile) |

## Verification

- `make check-production-v1` → passed (`638` pytest)
- `shellcheck` includes `doctor-pilot.sh`

## Unresolved (human / dev-box)

- Full TB×2 + compare + BFCL live matrix
- Proxy/ops-server: document in dev-box-pilot §2; verify on host
