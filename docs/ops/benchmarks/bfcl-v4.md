# bfcl-v4

Executable model-only benchmark. The adapter implements `bfcl generate` **and** `bfcl evaluate` as one bounded lifecycle, with the official score JSONL as its only verdict authority.

```bash
uv run bencheval run bfcl-v4/smoke-5 --model gpt-5.2-2025-12-11 --provider bytellm --dry-run
```

- **Status:** `executable: true` in `config/benchmarks.yaml` (admitted 2026-08-24).
- **Lifecycle:** bounded generate → evaluate; the pinned `bfcl-eval` package and official score parser are enforced before launch.
- **Identity boundary:** the bare package version is harness identity (`harness_version`). The catalog `identity:` block pins the benchmark identity separately: `bfcl_eval_version` `2026.3.23`, upstream gorilla commit `6ea57973…`, and sha256 digests of the nine package data files behind the five smoke categories — question + `possible_answer/` for simple_python, parallel, multiple, and parallel_multiple, plus question-only for irrelevance (v4 has no `possible_answer/BFCL_v4_irrelevance.json` by design: it scores on "no function called"). Before launch the adapter verifies those files inside the installed `bfcl_eval` package and captures `benchmark_version` as `bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b`; drift fails closed, no launch.
- **Admission record:** met 2026-08-24 by live dev-box run `run-20260824-040631-228703-4756f857` (dev-box-cpu, `gpt-5.2-2025-12-11` via ByteLLM): all 5 smoke categories completed the real generate → evaluate lifecycle and produced official `BFCL_v4_<category>_score.json` artifacts (irrelevance passed 1.0; 4 categories scored real `model_wrong_solution` 0.0 — verified as model behavior, not an interface defect). Evidence: `results/evidence/run-20260824-040631-228703-4756f857.jsonl`; raw artifacts: `results/raw/run-20260824-040631-228703-4756f857/`. Launches stay gated on `config/bfcl-v4-supported-models.yaml` and the identity pin. `--diagnostic` is refused now that the row is executable; diagnostic-labeled evidence can never register `passed`.
