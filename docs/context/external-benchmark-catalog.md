# External benchmark catalog

> **Status:** Research (2026-06-17). For Calibration/Stretch adapter planning — **not** Core-weighted tasks.
> **BenchEval Core today:** 8 admitted (core-8) + 8 in review (core-16) native task contracts.

Third-party suites popular in coding-agent, tool-use, and security evaluation. Prefer Inspect/Harbor-packaged variants where available (`inspect-evals`, Harbor datasets).

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
| **Terminal-Bench** | 80+ | Shell/CLI agents | Terminal execution in container; popular 2025–2026 agent leaderboard staple. |
| **SWE-smith** | generated | Trainable SWE tasks | Synthetic/issue-mining pipeline from SWE-bench team. [swesmith.com](https://swesmith.com) |
| **RepoBench** | varies | Cross-file context | Long-context repository understanding + completion. |
| **DS-1000** | 1,000 | Data-science code | Pandas/NumPy/Sklearn snippets. |

## Tool use & function calling

| Benchmark | Scale | Focus | Notes |
|-----------|------:|-------|-------|
| **BFCL (Berkeley Function Calling Leaderboard)** | multi-suite | Tool/API invocation | Gorilla project; AST + executable eval. [gorilla.cs.berkeley.edu](https://gorilla.cs.berkeley.edu/leaderboard.html) |
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

| Benchmark | Scale | Focus | Notes |
|-----------|------:|-------|-------|
| **Cybench** | 40 CTF | Professional CTF tasks | Inspect-eval packaged; UK AISI standard. [cybench.github.io](https://cybench.github.io/) |
| **CyberGym** | 1,507 vulns | Exploit generation / patching | Berkeley RDI; agentic cyber gym. [rdi.berkeley.edu/blog/cybergym](https://rdi.berkeley.edu/blog/cybergym/) |
| **BountyBench** | real bounties | Vuln find/exploit/patch | Cybench team's dollar-impact successor. [bountybench.github.io](https://bountybench.github.io/) |
| **SECURE** | varies | Secure code generation | Security-aware codegen eval. |

## Naming note: DeepBench

**DeepBench** most often refers to **Baidu's HPC deep-learning kernel benchmark** (GEMM/conv), not LLM agents. In LLM eval discourse, users may mean **deep reasoning benches** (e.g., LiveBench hard subsets, GPQA, MATH) — clarify intent before adapter work.

## Recommended Calibration/Stretch shortlist (first adapters)

Priority order for BenchEval Stretch (non–Core-weighted), credential-gated:

1. SWE-bench Verified Mini or Lite — cheap SWE regression
2. Cybench (5–10 task smoke) — security appendix
3. τ-bench — stateful tool E0/E1 pattern alignment
4. BFCL v3 slice — tool-calling regression
5. Terminal-Bench smoke — Harbor/Inspect terminal profile POC

## Inspect / Harbor integration hints

- `inspect-evals` ships SWE-bench, Cybench, and other tasks — align with `bencheval doctor --backend inspect`.
- Harbor datasets (e.g., SWE-bench Pro packaging) align with `harbor_adapter.py` S4 slice pattern.
- All external suites should land as **E3 Calibration** or **E4 Stretch** per concept-zero §18 — never mixed into Core weighted totals without explicit migration.

## References

- SWE-bench family: https://www.swebench.com/
- Cybench (ICLR 2025): https://arxiv.org/abs/2408.08926
- CyberGym: Berkeley RDI blog (2025)
- Agent benchmark survey: industry leaderboards (HAL, LiveBench, BFCL, GAIA)
