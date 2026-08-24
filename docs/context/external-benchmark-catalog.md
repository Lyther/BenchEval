# External benchmark catalog

> **Status:** Research only (updated 2026-07-14). **Not** the product catalog.
> **Live product YAML:** [`config/benchmarks.yaml`](../../config/benchmarks.yaml) has **8** catalog rows and **4** Tier-0 executable rows (`terminal-bench`, `gpqa-diamond`, `hle`, `bfcl-v4` — BFCL admitted 2026-08-24 on the diagnostic-labeled dev-box lifecycle demonstration `run-20260824-040631-228703-4756f857` plus the registered `passed` run `run-20260824-045622-854659-a46ae44d`). `swe-bench-verified` is demoted until official evaluation is wired. `swe-bench-pro`, `cybergym`, and `exploitgym` remain `adapter_pending`. Rows below that are not yet admitted remain a planning shortlist.
> **Do not** treat entries here as runnable via BenchEval CLI.

Third-party suites popular in coding-agent, tool-use, and security evaluation. Prefer official harnesses when a future adapter is designed.

## Coding & repository repair

| Benchmark | Scale | Focus | Notes / source |
|-----------|------:|-------|----------------|
| **SWE-bench Verified** | 500 | Real GitHub issues → patch | Human-filtered subset; de facto agent coding standard. [swebench.com](https://www.swebench.com/verified.html) |
| **SWE-bench Full** | 2,294 | Full issue set | Superset; costly. [swebench.com](https://www.swebench.com/) |
| **SWE-bench Lite** | 300 | Cost-reduced subset | Same family, lighter runs. [swebench.com/lite.html](https://www.swebench.com/lite.html) |
| **SWE-bench Multilingual** | 300 | 9 languages | Cross-language repo repair. [swebench.com/multilingual-leaderboard.html](https://www.swebench.com/multilingual-leaderboard.html) |
| **SWE-bench Multimodal** | 517 | Issues with visuals | UI/screenshot-bearing tasks. [swebench.com/multimodal.html](https://www.swebench.com/multimodal.html) |
| **SWE-bench Pro** | 1,865 | Harder proprietary-style | Scale AI; longer-horizon SWE. [swebench.com](https://www.swebench.com/) / Scale leaderboard |
| **SWE-bench Verified Mini** | 50 | Fast regression slice | Princeton HAL mini subset for cheap tracking. |
| **HumanEval** | 164 | Single-function synthesis | Classic code generation; fast but saturated. |
| **HumanEval+** | 164+ | Augmented tests | Stricter than HumanEval. |
| **MBPP** | 974 | Basic Python problems | Entry-level codegen. |
| **BigCodeBench** | 1,140 | Practical programming | Diverse libs/APIs; harder than HumanEval. |
| **LiveCodeBench** | rolling | Contamination-resistant | Time-stamped competitive programming. |
| **Aider Polyglot** | 225 | Multi-language edit | Edit-in-repo benchmark used in Aider leaderboard. |
| **DevEval** | 1,825 | Real-world dev tasks | Project-level completion. |
| **CodeClash** | varies | Goal-oriented SWE | SWE-bench team's newer goal-driven eval (2025). [codeclash.ai](https://codeclash.ai) |

## Agentic coding & terminal

| Benchmark | Scale | Focus | Notes |
|-----------|------:|-------|-------|
| **Terminal-Bench** | 89 (v2.0) | Shell/CLI agents | Terminal execution in Harbor-native format; v2.0 = 89 tasks (v1.0 = 80); official harness is Harbor (Claude Code, OpenHands, Codex CLI). [tbench.ai](https://www.tbench.ai/) |
| **SWE-smith** | generated | Trainable SWE tasks | Synthetic/issue-mining pipeline from SWE-bench team. [swesmith.com](https://swesmith.com) |
| **RepoBench** | varies | Cross-file context | Long-context repository understanding + completion. |
| **DS-1000** | 1,000 | Data-science code | Pandas/NumPy/Sklearn snippets. |

## Tool use & function calling

| Benchmark | Scale | Focus | Notes |
|-----------|------:|-------|-------|
| **BFCL (Berkeley Function Calling Leaderboard)** | multi-suite | Tool/API invocation | Gorilla project; AST + executable eval; current registry entry tracks V4. [gorilla.cs.berkeley.edu](https://gorilla.cs.berkeley.edu/leaderboard.html) |
| **τ-bench (tau-bench)** | retail/airline | Stateful tool agents | Sierra; multi-turn customer-service sim. [github.com/sierra-research/tau-bench](https://github.com/sierra-research/tau-bench) |
| **API-Bank** | 73 APIs | Tool planning | Early comprehensive tool-use benchmark. |

## Web & general agents

| Benchmark | Scale | Focus | Notes |
|-----------|------:|-------|-------|
| **WebArena** | 812 | Realistic web tasks | Self-hosted sites; high realism. |
| **VisualWebArena** | 910 | Multimodal web | Screenshots + DOM. |
| **GAIA** | 466 | General assistant | Multi-step reasoning + tools; HuggingFace leaderboard. |
| **AgentBench** | 8 envs | Multi-domain agents | OS, DB, KG, web games, etc. |
| **LiveBench** | rolling | Contamination-free QA | General capability; monthly refresh. [livebench.ai](https://livebench.ai/) |

## Cybersecurity & defensive

| Benchmark | Scale | Focus | Notes / source |
|-----------|------:|-------|----------------|
| **Cybench** | 40 CTF | Professional CTF tasks | Inspect-eval packaged; UK AISI standard. [cybench.github.io](https://cybench.github.io/) |
| **CyberGym** | 1,507 vulns / 188 projects | Vulnerability **reproduction** (PoC vs pre-patch code) | UC Berkeley; arXiv 2506.02548 (v3 2026-03); ~7.5× larger than prior cyber agent benches; used in Claude-Sonnet-4.5 system card; agents found 34 zero-days + 18 incomplete patches during eval. [rdi.berkeley.edu/blog/cybergym](https://rdi.berkeley.edu/blog/cybergym/) |
| **ExploitGym** | 869 / 3 domains | Full **exploit generation** (userspace, browser, Linux kernel) | Berkeley RDI; Stretch cybersecurity evaluation workload; never Core-weighted; host/harness policy applies. [cybergym.io](https://www.cybergym.io/) |
| **CyberGym-E2E** | pending | End-to-end vulnerability lifecycle | Berkeley RDI; paper 2026, full release pending — not yet a runnable public task set. [cybergym.io](https://www.cybergym.io/) |
| **BountyBench** | 25 systems / 40 bounties ($10–$30,485) | Detect / Exploit / Patch; 9-of-10 OWASP Top 10 | Stanford CRFM; arXiv 2505.15216; uses Detect + Patch in normal lanes, Exploit tasks are Stretch-gated. [bountybench.github.io](https://bountybench.github.io/) |
| **SECURE** | varies | Secure code generation | Security-aware codegen eval. |

## Naming note: DeepSWE

As of 2026-06-17, "DeepSWE" (e.g. `DeepSWE-32B`) is an **RL-trained agent/model** built by All Hands on top of SWE-bench-style tasks, not a verified standalone public benchmark with a canonical task set. It is **research only; not admitted** in product `config/benchmarks.yaml`. If a canonical DeepSWE task source appears (verified arXiv ID + public dataset + runnable harness), admit it deliberately with source URL, slice, adapter, and live proof.

## Naming note: DeepBench

**DeepBench** most often refers to **Baidu's HPC deep-learning kernel benchmark** (GEMM/conv), not LLM agents. In LLM eval discourse, users may mean **deep reasoning benches** (e.g., LiveBench hard subsets, GPQA, MATH) — clarify intent before adapter work.

## Recommended research shortlist (not admitted)

Priority for **future** adapter design only. None of these become product until YAML + adapter + live proof land:

1. SWE-bench Verified Mini or Lite — cheap SWE regression research; current catalog row is non-executable
2. Cybench (5–10 task smoke) — security appendix — **research only; not admitted**
3. τ-bench — stateful tool patterns — **research only; not admitted**
4. BFCL v4 official `generate` + `evaluate` lifecycle — wired and admitted (executable since 2026-08-24)
5. Terminal-Bench larger slices — smoke is Tier-0 executable via Harbor; live proof remains separate

## Integration posture (research only)

- Design against the **official** harness for each suite (Harbor, Gorilla BFCL, upstream SWE runners). Do not invent BenchEval-owned Docker planes.
- Historical Inspect/`--backend` / `--manifest --mode single` CLI shapes are **removed** from the product spine; do not recommend them as operator commands.
- Admission path: add executable entry + adapter dispatch + slice + `make check-production-v1` + recorded live proof. Until then, label candidates **research only; not admitted**.

## References

- SWE-bench family: <https://www.swebench.com/>
- SWE-rebench (NeurIPS 2025): <https://arxiv.org/abs/2505.20411>
- Cybench (ICLR 2025): <https://arxiv.org/abs/2408.08926>
- CyberGym (arXiv 2506.02548): <https://arxiv.org/abs/2506.02548> and Berkeley RDI blog: <https://rdi.berkeley.edu/blog/cybergym/>
- ExploitGym / CyberGym-E2E (Berkeley RDI observatory): <https://www.cybergym.io/>
- BountyBench (arXiv 2505.15216, Stanford CRFM): <https://arxiv.org/abs/2505.15216>
- Terminal-Bench 2.0 (89 tasks, Harbor-native): <https://www.tbench.ai/> and repo <https://github.com/laude-institute/terminal-bench-2>
- Harbor (official TB 2.0 harness, Apache-2.0): <https://github.com/harbor-framework/harbor>
- Agent benchmark survey: industry leaderboards (HAL, LiveBench, BFCL, GAIA)
