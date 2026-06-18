"""API contract tests: Protocol conformance, CLI exit codes, JSON output shapes.

These tests freeze the v0.3 control-plane boundaries defined in
``docs/api/internal-contracts.md``. They assert structure, not implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval import (
    load_benchmark_catalog,
    load_runtime_profile,
)
from bencheval.contracts import (
    AdapterDispatcher,
    BenchmarkCatalogSource,
    RunPlanner,
    RuntimeCatalogSource,
    SliceManifestSource,
)
from bencheval.runtime_registry import load_runtime_catalog as _load_runtime_catalog
from bencheval.slice_manifest import load_slice_manifest as _load_slice_manifest

# ---------------------------------------------------------------------------
# Protocol structural conformance (duck-typing, no runtime isinstance)
# ---------------------------------------------------------------------------
# A module/function satisfies a Protocol if it has the named methods with
# compatible signatures. We check callability + signature presence, not isinstance
# (Protocol classes with non-method members require runtime_checkable for isinstance).


class TestProtocolConformance:
    def test_benchmark_registry_satisfies_catalog_source(self) -> None:
        # load_benchmark_catalog(path=None) -> BenchmarkCatalog
        cat = load_benchmark_catalog(Path("config/benchmarks.yaml"))
        assert cat is not None
        # The function is the source; Protocol.load(path) matches the call shape.
        assert callable(load_benchmark_catalog)

    def test_runtime_registry_satisfies_catalog_source(self) -> None:
        # load_catalog(dir_path=None) and load_profile(path) match RuntimeCatalogSource.
        _load_runtime_catalog()
        assert hasattr(_load_runtime_catalog, "__call__")
        assert callable(load_runtime_profile)

    def test_slice_manifest_satisfies_source(self) -> None:
        m = _load_slice_manifest(Path("config/slices/swe-bench-verified-smoke-10.yaml"))
        assert m is not None
        # load(path) and instance_ids(manifest, path) match SliceManifestSource.
        from bencheval.slice_manifest import slice_instance_ids

        assert callable(slice_instance_ids)

    def test_protocols_are_distinct_types(self) -> None:
        # Anti-spaghetti: each boundary is a distinct Protocol, not a catch-all.
        assert BenchmarkCatalogSource is not RuntimeCatalogSource
        assert RuntimeCatalogSource is not SliceManifestSource
        assert RunPlanner is not AdapterDispatcher

    def test_runtime_catalog_source_has_two_methods(self) -> None:
        # load_catalog + load_profile (both required by the Protocol).
        members = {n for n in dir(RuntimeCatalogSource) if not n.startswith("_")}
        assert "load_catalog" in members
        assert "load_profile" in members


# ---------------------------------------------------------------------------
# Exit-code contract (frozen: 0 success, 1 business, 2 usage)
# ---------------------------------------------------------------------------


class TestExitCodes:
    def _run_cli(self, argv: list[str]) -> int:
        """Invoke the CLI, capturing argparse's SystemExit(2) as exit code 2."""
        from bencheval.cli import main

        try:
            return main(argv)
        except SystemExit as e:
            # argparse calls parser.exit(2) for invalid choices / missing required args.
            code = e.code
            return code if isinstance(code, int) else 2

    def test_success_returns_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = self._run_cli(["benchmark", "list", "--format", "json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "benchmarks" in payload

    def test_unknown_command_returns_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = self._run_cli(["not-a-command"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "error" in err.lower() or "invalid choice" in err.lower()

    def test_partial_four_axis_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = self._run_cli(
            [
                "run",
                "--dry-run",
                "--benchmark",
                "terminal-bench",
                "--slice",
                "smoke-5",
                "--model",
                "runtime-default",
            ],
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "error" in err.lower()

    def test_conflicting_selection_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        # --task and --suite together -> usage error -> exit 2 (dry-run path).
        rc = self._run_cli(["run", "--dry-run", "--task", "t1", "--suite", "smoke", "--model", "m"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "error" in err.lower()

    def test_missing_output_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        # non-dry-run without --output -> exit 2.
        rc = self._run_cli(
            ["run", "--task", "be-core-t1-single-structured-call", "--model", "local/harness"],
        )
        assert rc == 2

    def test_business_failure_returns_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        # local backend with a non-harness model -> nonzero (model mismatch or preflight).
        rc = self._run_cli(
            [
                "run",
                "--task",
                "be-core-t1-single-structured-call",
                "--model",
                "openai/gpt-bogus",
                "--backend",
                "local",
                "--output",
                "/tmp/bencheval-contract-test.jsonl",
            ],
        )
        assert rc != 0


# ---------------------------------------------------------------------------
# JSON output contract (stable stdout shapes)
# ---------------------------------------------------------------------------


class TestJsonOutputShapes:
    def test_benchmark_list_json_has_benchmarks_key(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from bencheval.cli import main

        rc = main(["benchmark", "list", "--format", "json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload["benchmarks"], list)
        assert len(payload["benchmarks"]) > 0

    def test_benchmark_show_json_is_entry_dict(self, capsys: pytest.CaptureFixture[str]) -> None:
        from bencheval.cli import main

        rc = main(["benchmark", "show", "terminal-bench", "--format", "json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == "terminal-bench"

    def test_runtime_list_json_has_runtimes_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        from bencheval.cli import main

        rc = main(["runtime", "list", "--format", "json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload["runtimes"], list)
        assert len(payload["runtimes"]) > 0


# ---------------------------------------------------------------------------
# Secret-leak guard (env var names only, never values)
# ---------------------------------------------------------------------------


class TestNoSecretLeak:
    def test_runtime_profile_yaml_has_no_secret_values(self) -> None:
        # Seed runtime profiles must reference env var NAMES only.
        for p in sorted(Path("config/runtimes").glob("*.yaml")):
            text = p.read_text(encoding="utf-8")
            # Heuristic: no line should look like a key assignment with a real value.
            for line in text.splitlines():
                low = line.lower()
                if "api_key" in low and ":" in line:
                    # env_vars_required lists NAMES (e.g. ANTHROPIC_API_KEY), not values.
                    assert "sk-" not in low
                    assert "key-" not in low

    def test_doctor_env_check_does_not_echo_values(self) -> None:
        from bencheval.doctor import env_var_present

        # env_var_present returns a bool; it must not return the value.
        assert isinstance(env_var_present("DEFINITELY_NOT_SET_VAR_XYZ"), bool)
        assert env_var_present("DEFINITELY_NOT_SET_VAR_XYZ") is False
