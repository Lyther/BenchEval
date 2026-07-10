# Config Resolution

What this shows: how BenchEval finds the control-plane config tree for editable checkout, wheel install, and optional override.

```mermaid
flowchart TD
    Call["paths.repo_root()"]

    Call --> Env{"BENCHEVAL_HOME set<br/>and validate_config_bundle OK?"}
    Env -->|yes| Home["Use BENCHEVAL_HOME<br/>operator custom bundle"]
    Env -->|no| Cwd{"Walk up from cwd<br/>find config/benchmarks.yaml?"}
    Cwd -->|yes| Checkout["Editable checkout root<br/>live config/"]
    Cwd -->|no| Wheel{"importlib.resources<br/>bencheval/_bundled<br/>has marker?"}
    Wheel -->|yes| Bundled["Wheel package data<br/>one-click uv tool install"]
    Wheel -->|no| Fail["BenchEvalError<br/>no config bundle"]

    Home --> Need["Required: benchmarks.yaml,<br/>runtimes/, slices/, manifests/"]
    Checkout --> Need
    Bundled --> Need
```

Notes: Implemented in [`src/bencheval/paths.py`](../../src/bencheval/paths.py). Wheel contents mirror `scripts/export-config-bundle.sh` subset via hatch `force-include` in [`pyproject.toml`](../../pyproject.toml). `config/pricing/` and `config/selftest/` stay editable-checkout only. First-touch: `uv tool install bencheval` → `bencheval benchmark list` with no `BENCHEVAL_HOME`.
