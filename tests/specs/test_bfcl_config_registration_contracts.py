"""CF1.2 contracts: BFCL registration generated from configuration, staged in a run-owned copy.

Architecture §23.4 / roadmap CF1.2. The registration text is a human-locked
example derived from the pinned ``ModelConfig`` signature and the existing
``openbmb/MiniCPM-SALA-FC`` entry shape; nothing here is copied from output.

SUBSTITUTE_JUSTIFICATION
- substitute: a disposable ``bfcl_eval``-shaped package (`_substitute_package`
  from the materializer contracts) extended with a pinned-shaped
  ``constants/model_config.py`` and a placeholder ``OpenAICompletionsHandler``
  class, a `BfclPackageSource` bound to it, and a stub ``process_runner`` that
  records the launch and writes official-shaped result/score files
- replaces: the installed pinned bfcl-eval distribution, the reviewed registry
  pin, and the charged official generate/evaluate subprocesses
- necessity: prefix-bound registration, collision, pin drift, tampering, and
  retention must be forced deterministically without a provider call or any
  site-packages mutation
- real-option: none locally (bfcl_eval is not installed on the Mac); the real
  route is the CF1.3 dev-box plumbing pair through the official CLI
- proof-limit: proves BenchEval-side staging, binding, retention, and
  fail-closed behavior; the staged copy is imported by a real interpreter, but
  the substitute proves nothing about upstream generation or scoring
- real-proof: CF1.3 (pending)
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import BfclPackageDataIdentity
from bencheval.bfcl_native_adapter import (
    BfclCliResult,
    bfcl_pinned_harness_version,
    run_bfcl_instance,
)
from bencheval.bfcl_package import (
    REGISTRATION_FILE,
    REGISTRATION_MANIFEST_FILE,
    REGISTRATION_SCHEMA,
    BfclPackageSource,
    RegistrationSpec,
    effective_harness_version,
    parse_registration_manifest,
    registration_sha256,
    registration_spec_for,
    render_registration,
    render_registration_manifest,
    stage_bfcl_package,
    upstream_registry_keys,
    verify_staged_package,
)
from bencheval.bfcl_study import tree_digests
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_report import write_proof_backed_exposure_report
from bencheval.model_binding import resolve_model_binding
from tests.specs.test_bfcl_study_contracts import _substitute_package
from tests.specs.test_config_model_binding_contracts import (
    _QWEN_API,
    _QWEN_ENTRY,
    _QWEN_ID,
    _providers,
    _registry,
)
from tests.specs.test_exposure_pair_contracts import _rows as _pair_rows
from tests.specs.test_exposure_pair_contracts import _study_and_selection, _variant
from tests.specs.test_exposure_report_contracts import _benchmark_version, _proof_from_rows

_BASE_VERSION = "2026.3.23"
_UPSTREAM_KEY = "gpt-5.2-2025-12-11-FC"
_LABEL = re.compile(r"^bfcl-eval@2026\.3\.23\+registration-[0-9a-f]{64}$")

# Pinned-shaped registry file: the ModelConfig fields are those of bfcl-eval
# 2026.3.23; the mapping ends exactly like upstream (mapping, then comments).
_REGISTRY_TEXT = """from dataclasses import dataclass
from typing import Optional

from bfcl_eval.model_handler.api_inference.openai_completion import OpenAICompletionsHandler


@dataclass
class ModelConfig:
    model_name: str
    display_name: str
    url: str
    org: str
    license: str
    model_handler: str
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    is_fc_model: bool = True
    underscore_to_dot: bool = False


api_inference_model_map = {
    "gpt-5.2-2025-12-11-FC": ModelConfig(
        model_name="gpt-5.2-2025-12-11",
        display_name="GPT-5.2 (FC)",
        url="https://openai.com",
        org="OpenAI",
        license="Proprietary",
        model_handler=OpenAICompletionsHandler,
        input_price=None,
        output_price=None,
        is_fc_model=True,
        underscore_to_dot=False,
    ),
}


MODEL_CONFIG_MAPPING = {
    **api_inference_model_map,
}

# Uncomment to get the supported_models.py file contents
# print(repr(list(MODEL_CONFIG_MAPPING.keys())))
"""
_HANDLER_TEXT = "class OpenAICompletionsHandler:\n    pass\n"

# Human-locked rendering for the §23.3 example (org/license unknown, url = endpoint).
_EXPECTED_REGISTRATION = """
# bencheval configured registration (bfcl-registration-v1); generated, do not edit.
MODEL_CONFIG_MAPPING["ollama-qwen3.5-397b-fc"] = ModelConfig(
    model_name="qwen3.5:397b",
    display_name="Qwen3.5 397B via Ollama Cloud (FC)",
    url="https://ollama.com/v1",
    org="unknown",
    license="unknown",
    model_handler=OpenAICompletionsHandler,
    input_price=None,
    output_price=None,
    is_fc_model=True,
    underscore_to_dot=True,
)
"""


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _package(root: Path) -> BfclPackageSource:
    """Substitute package with a pinned-shaped registry file and handler module."""
    identity = _substitute_package(root)
    pkg = root / "bfcl_eval"
    (pkg / "constants" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "model_handler" / "api_inference").mkdir(parents=True)
    (pkg / "model_handler" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "model_handler" / "api_inference" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "model_handler" / "api_inference" / "openai_completion.py").write_text(
        _HANDLER_TEXT, encoding="utf-8"
    )
    (pkg / REGISTRATION_FILE).write_text(_REGISTRY_TEXT, encoding="utf-8")
    assert isinstance(identity, BfclPackageDataIdentity)
    return BfclPackageSource(
        package_root=pkg,
        identity=identity,
        registry_sha256=_sha(_REGISTRY_TEXT.encode("utf-8")),
    )


def _spec(tmp_path: Path, **overrides: object) -> RegistrationSpec:
    entry = {**_QWEN_ENTRY, **overrides}
    binding = resolve_model_binding(
        str(entry["id"]), models=_registry(entry), providers=_providers(tmp_path)
    )
    return registration_spec_for(binding)


def _import_registration(pythonpath: Path, registry_id: str) -> list[object]:
    """Import the staged copy in a fresh interpreter, as the official CLI would."""
    code = (
        "import json, bfcl_eval.constants.model_config as m;"
        f"c = m.MODEL_CONFIG_MAPPING[{registry_id!r}];"
        "print(json.dumps([c.model_name, c.model_handler.__name__, c.is_fc_model,"
        " c.underscore_to_dot, len(m.MODEL_CONFIG_MAPPING)]))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(pythonpath), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --- rendering -------------------------------------------------------------------


def test_registration_renders_the_fixed_text_and_rejects_unsafe_values(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    assert spec.registry_id == _QWEN_ID
    assert spec.api_model == _QWEN_API
    assert spec.organization == "unknown" and spec.license == "unknown"
    assert spec.reference_url == "https://ollama.com/v1"
    assert render_registration(spec) == _EXPECTED_REGISTRATION
    assert render_registration(spec) == render_registration(_spec(tmp_path / "again"))
    assert registration_sha256(spec) != registration_sha256(
        _spec(tmp_path / "other", api_model="qwen3.5:397b-cloud")
    )
    # Values are validated primitives: no quoting, line, or escape tricks reach Python.
    unsafe = (
        {"api_model": 'qwen"3'},
        {"api_model": "qwen\n3"},
        {"api_model": "qwen\\3"},
        {"display_name": 'Qwen "x"'},
        {"id": "ollama qwen"},  # registry ids are identifiers: they name the launched model
    )
    for index, override in enumerate(unsafe):
        entry = {**_QWEN_ENTRY, **override}
        with pytest.raises(BenchEvalError):
            registration_spec_for(
                resolve_model_binding(
                    str(entry["id"]),
                    models=_registry(entry),
                    providers=_providers(tmp_path / f"p{index}"),
                )
            )
    # Provenance is fixed in the binding at plan time, never re-read at run time.
    provenance = _spec(
        tmp_path / "prov",
        reference_url="https://ollama.com/library/qwen3.5",
        organization="Alibaba",
        license="Apache-2.0",
    )
    assert (provenance.reference_url, provenance.organization, provenance.license) == (
        "https://ollama.com/library/qwen3.5",
        "Alibaba",
        "Apache-2.0",
    )
    assert registration_sha256(provenance) != registration_sha256(spec)


def test_upstream_keys_are_read_without_importing_the_registry() -> None:
    assert upstream_registry_keys(_REGISTRY_TEXT) == frozenset({_UPSTREAM_KEY})
    with pytest.raises(BenchEvalError):
        upstream_registry_keys("MODEL_CONFIG_MAPPING = build()\n")


def test_second_shipped_config_only_model_renders_without_code_changes(tmp_path: Path) -> None:
    binding = resolve_model_binding("ollama-gpt-oss-120b-fc")
    assert binding.api_model == "gpt-oss:120b" and binding.provider_id == "ollama-cloud"
    spec = registration_spec_for(binding)
    assert (spec.organization, spec.license, spec.reference_url) == (
        "OpenAI",
        "Apache-2.0",
        "https://ollama.com/library/gpt-oss",
    )
    text = render_registration(spec)
    assert 'MODEL_CONFIG_MAPPING["ollama-gpt-oss-120b-fc"]' in text
    assert 'model_name="gpt-oss:120b"' in text
    staged = stage_bfcl_package(
        source=_package(tmp_path / "site"), spec=spec, output_root=tmp_path / "overlay"
    )
    assert _import_registration(staged.pythonpath, "ollama-gpt-oss-120b-fc")[:2] == [
        "gpt-oss:120b",
        "OpenAICompletionsHandler",
    ]


def test_changed_endpoint_after_confirmation_fails_before_any_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _package(tmp_path / "site")
    plan = _configured_plan(tmp_path, diagnostic=True)  # snapshot: https://ollama.com/v1
    monkeypatch.setenv("OLLAMA_CLOUD_BASE_URL", "https://elsewhere.test/v1")
    envs: list[dict[str, str]] = []
    with pytest.raises(BenchEvalError, match="confirmed binding endpoint"):
        run_bfcl_instance(
            plan=plan,
            instance_id="multiple_19",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=_runner(envs),
            harness_version=bfcl_pinned_harness_version(),
            package_source=source,
        )
    assert envs == []


# --- staging ---------------------------------------------------------------------


def test_staged_copy_appends_exactly_one_registration_and_imports_like_the_cli(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "site")
    before = tree_digests(source.package_root)
    spec = _spec(tmp_path)
    staged = stage_bfcl_package(source=source, spec=spec, output_root=tmp_path / "run" / "overlay")
    assert staged.pythonpath == tmp_path / "run" / "overlay" / "pkg"
    assert staged.package_dir == staged.pythonpath / "bfcl_eval"
    registry = staged.package_dir / REGISTRATION_FILE
    data = registry.read_bytes()
    base = _REGISTRY_TEXT.encode("utf-8")
    assert data[: len(base)] == base and data[len(base) :] == _EXPECTED_REGISTRATION.encode()
    assert staged.base_registry_sha256 == source.registry_sha256
    assert staged.staged_registry_sha256 == _sha(data)
    assert staged.registration_sha256 == registration_sha256(spec)
    # Only the registry file differs; everything else is a byte-identical real copy.
    after = tree_digests(staged.package_dir)
    assert {rel for rel in after if after[rel] != before.get(rel)} == {REGISTRATION_FILE}
    assert set(after) == set(before)
    assert all(os.lstat(p).st_nlink == 1 for p in staged.package_dir.rglob("*") if p.is_file())
    assert tree_digests(source.package_root) == before
    # The real interpreter resolves the configured entry for generation/evaluation.
    assert _import_registration(staged.pythonpath, _QWEN_ID) == [
        _QWEN_API,
        "OpenAICompletionsHandler",
        True,
        True,
        2,
    ]
    verify_staged_package(staged, source=source)


def test_existing_upstream_key_cannot_be_replaced_or_relabelled(tmp_path: Path) -> None:
    source = _package(tmp_path / "site")
    spec = _spec(tmp_path, id=_UPSTREAM_KEY, api_model="gpt-5.2-2025-12-11")
    out = tmp_path / "run" / "overlay"
    with pytest.raises(BenchEvalError, match="existing"):
        stage_bfcl_package(source=source, spec=spec, output_root=out)
    assert not out.exists() or not any(out.iterdir())


def test_registry_pin_drift_fails_before_copying(tmp_path: Path) -> None:
    source = _package(tmp_path / "site")
    drifted = BfclPackageSource(
        package_root=source.package_root,
        identity=source.identity,
        registry_sha256="sha256:" + "0" * 64,
    )
    out = tmp_path / "run" / "overlay"
    with pytest.raises(BenchEvalError, match="registry"):
        stage_bfcl_package(source=drifted, spec=_spec(tmp_path), output_root=out)
    assert not out.exists() or not any(out.iterdir())


@pytest.mark.parametrize(
    ("label", "tamper", "declared"),
    [
        (
            "registration edited",
            lambda pkg: (pkg / REGISTRATION_FILE).write_text(
                (pkg / REGISTRATION_FILE).read_text().replace("qwen3.5:397b", "qwen3:8b")
            ),
            None,
        ),
        (
            "scorer changed",
            lambda pkg: (pkg / "eval_checker" / "eval_runner.py").write_text("def runner():\n"),
            None,
        ),
        (
            "undeclared data change",
            lambda pkg: (pkg / "data" / "BFCL_v4_multiple.json").write_text("{}\n"),
            None,
        ),
        (
            "declared data change with the wrong digest",
            lambda pkg: (pkg / "data" / "BFCL_v4_multiple.json").write_text("{}\n"),
            {"data/BFCL_v4_multiple.json": "sha256:" + "1" * 64},
        ),
    ],
)
def test_verify_rejects_every_undeclared_or_mismatched_change(
    tmp_path: Path, label: str, tamper, declared: dict[str, str] | None
) -> None:
    source = _package(tmp_path / "site")
    staged = stage_bfcl_package(
        source=source, spec=_spec(tmp_path), output_root=tmp_path / "run" / "overlay"
    )
    tamper(staged.package_dir)
    with pytest.raises(BenchEvalError):
        verify_staged_package(staged, source=source, declared_changes=declared)
    # A correctly declared data change (the variant's contract) is the only allowed extra.
    text = (staged.package_dir / "data" / "BFCL_v4_multiple.json").read_bytes()
    if label == "declared data change with the wrong digest":
        verify_staged_package(
            staged, source=source, declared_changes={"data/BFCL_v4_multiple.json": _sha(text)}
        )


def test_registration_manifest_round_trips_and_labels_the_effective_harness(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "site")
    spec = _spec(tmp_path)
    staged = stage_bfcl_package(source=source, spec=spec, output_root=tmp_path / "run" / "overlay")
    text = render_registration_manifest(staged, base_version=_BASE_VERSION)
    payload = json.loads(text)
    assert payload["schema_version"] == REGISTRATION_SCHEMA
    assert payload["base"]["bfcl_eval_version"] == _BASE_VERSION
    assert payload["base"]["registry_sha256"] == source.registry_sha256
    assert payload["staged"]["registry_sha256"] == staged.staged_registry_sha256
    assert payload["registration_sha256"] == staged.registration_sha256
    assert payload["registration"]["registry_id"] == _QWEN_ID
    assert payload["registration"]["api_model"] == _QWEN_API
    assert payload["registration"]["handler"] == "openai_completions_fc"
    label = effective_harness_version(_BASE_VERSION, staged.registration_sha256)
    assert _LABEL.fullmatch(label) and label.endswith(
        staged.registration_sha256.removeprefix("sha256:")
    )
    assert payload["harness_version"] == label
    parsed_spec, parsed = parse_registration_manifest(text)
    assert parsed_spec == spec and parsed == payload
    assert render_registration_manifest(staged, base_version=_BASE_VERSION) == text
    with pytest.raises(BenchEvalError):
        parse_registration_manifest(text.replace(_QWEN_API, "qwen3:8b"))


# --- adapter integration ---------------------------------------------------------


def _runner(envs: list[dict[str, str]]):
    def runner(command, *, cwd, timeout_sec, env) -> BfclCliResult:
        del cwd, timeout_sec
        command = tuple(command)
        envs.append(dict(env))
        model_dir = command[command.index("--model") + 1].replace("/", "_")
        project = Path(env["BFCL_PROJECT_ROOT"])
        ids = json.loads((project / "test_case_ids_to_generate.json").read_text())
        category, (instance_id,) = next(iter(ids.items()))
        if command[1] == "generate":
            result_root = Path(command[command.index("--result-dir") + 1])
            result = result_root / model_dir / "non_live" / f"BFCL_v4_{category}_result.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"id": instance_id, "result": [[]]}) + "\n")
        else:
            score_root = Path(command[command.index("--score-dir") + 1])
            score = score_root / model_dir / "non_live" / f"BFCL_v4_{category}_score.json"
            score.parent.mkdir(parents=True)
            score.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n"
            )
        return BfclCliResult(0, "", "", 0.1, command)

    return runner


def _configured_plan(tmp_path: Path, *, diagnostic: bool):
    return plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="tool-order-canonical-plumbing-2",
        runtime_id=None,
        model_id=_QWEN_ID,
        diagnostic=diagnostic,
        model_registry=_registry(_QWEN_ENTRY),
        provider_catalog=_providers(tmp_path),
    )


def test_configured_registration_requires_explicit_diagnostic_execution(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="diagnostic"):
        _configured_plan(tmp_path, diagnostic=False)
    plan = _configured_plan(tmp_path / "d", diagnostic=True)
    assert plan.diagnostic is True
    assert plan.comparison_validity == "diagnostic_only"
    assert plan.model_binding_snapshot is not None
    assert plan.model_binding_snapshot.bfcl is not None
    assert plan.model_binding_snapshot.bfcl.mode == "configured"


def test_configured_model_runs_through_the_staged_copy_and_retains_the_registration(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "site")
    before = tree_digests(source.package_root)
    plan = _configured_plan(tmp_path, diagnostic=True)
    envs: list[dict[str, str]] = []
    art = tmp_path / "art"
    outcome = run_bfcl_instance(
        plan=plan,
        instance_id="multiple_19",
        artifacts_dir=art,
        repo_root=tmp_path,
        process_runner=_runner(envs),
        harness_version=bfcl_pinned_harness_version(),
        package_source=source,
    )
    assert outcome.primary_pass is True
    label = outcome.adapter_metadata["harness_version"]
    assert _LABEL.fullmatch(label)
    assert outcome.adapter_metadata["base_harness_version"] == "bfcl-eval@2026.3.23"
    assert outcome.adapter_metadata["model_binding_sha256"] == plan.model_binding_snapshot.sha256
    assert outcome.adapter_metadata["bfcl_registry_id"] == _QWEN_ID
    assert outcome.adapter_metadata["api_model"] == _QWEN_API
    # Both official phases ran from the staged copy under the registry id.
    assert len(envs) == 2
    for env in envs:
        assert env["PYTHONPATH"] == str(art / "overlay" / "pkg")
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    for command in (e for e in envs):
        assert command is not None
    manifest = art / REGISTRATION_MANIFEST_FILE
    spec, payload = parse_registration_manifest(manifest.read_text(encoding="utf-8"))
    assert spec.registry_id == _QWEN_ID and spec.api_model == _QWEN_API
    assert payload["harness_version"] == label
    assert any(p.endswith(REGISTRATION_MANIFEST_FILE) for p in outcome.study_artifact_paths)
    assert (
        json.loads((art / "study" / "benchmark-identity.json").read_text())["harness_version"]
        == label
    )
    staged_registry = (art / "overlay" / "pkg" / "bfcl_eval" / REGISTRATION_FILE).read_bytes()
    assert staged_registry == _REGISTRY_TEXT.encode("utf-8") + _EXPECTED_REGISTRATION.encode()
    assert tree_digests(source.package_root) == before

    # A later instance reuses the same registration; a tampered copy fails closed.
    second = run_bfcl_instance(
        plan=plan,
        instance_id="parallel_multiple_125",
        artifacts_dir=art,
        repo_root=tmp_path,
        process_runner=_runner(envs),
        harness_version=bfcl_pinned_harness_version(),
        package_source=source,
    )
    assert second.adapter_metadata["harness_version"] == label
    (art / "overlay" / "pkg" / "bfcl_eval" / REGISTRATION_FILE).write_bytes(
        staged_registry.replace(b"qwen3.5:397b", b"qwen3:8b")
    )
    from bencheval.exceptions import AdapterFailureError

    with pytest.raises(AdapterFailureError) as excinfo:
        run_bfcl_instance(
            plan=plan,
            instance_id="multiple_19",
            artifacts_dir=art,
            repo_root=tmp_path,
            process_runner=_runner(envs),
            harness_version=bfcl_pinned_harness_version(),
            package_source=source,
        )
    assert excinfo.value.failure_label == "runtime_config_drift"
    assert len(envs) == 4


def test_configured_model_on_the_derived_benchmark_shares_one_copy(tmp_path: Path) -> None:
    """Registration and tool-order variant compose in one staged copy (CF1.3 derived arm)."""
    from bencheval.benchmark_registry import BfclDerivedDataRef, load_benchmark_catalog
    from bencheval.bfcl_study import DerivedSource, parse_variant_manifest
    from bencheval.exposure_selection import load_exposure_selection
    from bencheval.exposure_study import default_studies_dir, load_exposure_study

    source = _package(tmp_path / "site")
    ref = load_benchmark_catalog().by_id_or_alias("bfcl-v4-tool-order-v1").identity
    assert isinstance(ref, BfclDerivedDataRef)
    derived_source = DerivedSource(
        ref=ref,
        source_identity=source.identity,
        study=load_exposure_study(ref.study_id),
        selection=load_exposure_selection(default_studies_dir() / f"{ref.study_id}.selection.json"),
        package_root=source.package_root,
    )
    plan = plan_control_plane(
        benchmark_id="bfcl-v4-tool-order-v1",
        slice_id="tool-order-derived-plumbing-2",
        runtime_id=None,
        model_id=_QWEN_ID,
        diagnostic=True,
        model_registry=_registry(_QWEN_ENTRY),
        provider_catalog=_providers(tmp_path),
    )
    before = tree_digests(source.package_root)
    envs: list[dict[str, str]] = []
    art = tmp_path / "art"
    outcomes = [
        run_bfcl_instance(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=art,
            repo_root=tmp_path,
            process_runner=_runner(envs),
            harness_version=bfcl_pinned_harness_version(),
            derived_source=derived_source,
            package_source=source,
        )
        for instance_id in ("multiple_19", "parallel_multiple_125")
    ]
    assert all(o.primary_pass for o in outcomes)
    labels = {o.adapter_metadata["harness_version"] for o in outcomes}
    assert len(labels) == 1 and _LABEL.fullmatch(next(iter(labels)))
    assert {o.adapter_metadata["benchmark_version"] for o in outcomes} == {
        outcomes[0].adapter_metadata["benchmark_version"]
    }
    assert (
        outcomes[0]
        .adapter_metadata["benchmark_version"]
        .startswith("bfcl-v4-tool-order-v1@derived-")
    )
    package_dir = art / "overlay" / "pkg" / "bfcl_eval"
    after = tree_digests(package_dir)
    assert {rel for rel in after if after[rel] != before.get(rel)} == {
        REGISTRATION_FILE,
        "data/BFCL_v4_multiple.json",
        "data/BFCL_v4_parallel_multiple.json",
    }
    assert tree_digests(source.package_root) == before
    _identity, overlay = parse_variant_manifest(
        (art / "study" / "variant-manifest.json").read_text(encoding="utf-8"), artifacts_dir=art
    )
    assert set(overlay.registered_files) == {REGISTRATION_FILE}
    assert overlay.registered_files[REGISTRATION_FILE] == after[REGISTRATION_FILE]
    for env in envs:
        assert env["PYTHONPATH"] == str(art / "overlay" / "pkg")
    retained = set(outcomes[0].study_artifact_paths)
    assert any(p.endswith(REGISTRATION_MANIFEST_FILE) for p in retained)
    assert any(p.endswith("study/variant-manifest.json") for p in retained)
    assert any(p.endswith(f"overlay/pkg/bfcl_eval/{REGISTRATION_FILE}") for p in retained)


def test_real_pinned_package_stages_and_imports_the_configured_registration(
    tmp_path: Path,
) -> None:
    """Normal staging path over the installed bfcl-eval and the shipped registry pin."""
    pytest.importorskip("bfcl_eval")
    from bencheval.benchmark_registry import load_benchmark_catalog
    from bencheval.bfcl_native_adapter import _bfcl_package_root, bfcl_registry_pin

    identity = load_benchmark_catalog().by_id_or_alias("bfcl-v4").identity
    assert isinstance(identity, BfclPackageDataIdentity)
    source = BfclPackageSource(
        package_root=_bfcl_package_root(), identity=identity, registry_sha256=bfcl_registry_pin()
    )
    binding = resolve_model_binding(_QWEN_ID)
    spec = registration_spec_for(binding)
    assert spec.display_name == "Qwen3.5 397B via Ollama Cloud (FC)"
    staged = stage_bfcl_package(source=source, spec=spec, output_root=tmp_path / "overlay")
    api_model, handler, is_fc, u2d, _count = _import_registration(staged.pythonpath, _QWEN_ID)
    assert (api_model, handler, is_fc, u2d) == (_QWEN_API, "OpenAICompletionsHandler", True, True)
    # The upstream evaluate entry resolves the same registry from the copy.
    code = (
        "import bfcl_eval.constants.model_config as m, bfcl_eval.eval_checker.eval_runner as r;"
        "print(r.MODEL_CONFIG_MAPPING is m.MODEL_CONFIG_MAPPING, "
        f"{_QWEN_ID!r} in r.MODEL_CONFIG_MAPPING)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(staged.pythonpath), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "True True"
    verify_staged_package(staged, source=source)
    with pytest.raises(BenchEvalError, match="existing"):
        stage_bfcl_package(
            source=source,
            spec=RegistrationSpec(
                registry_id="gpt-5.2-2025-12-11-FC",
                api_model="gpt-5.2-2025-12-11",
                display_name="dup",
                handler="openai_completions_fc",
                underscore_to_dot=True,
                reference_url="https://example.test/v1",
                organization="unknown",
                license="unknown",
            ),
            output_root=tmp_path / "dup",
        )


# --- proof and report binding ------------------------------------------------------


def _registered_pair(tmp_path: Path, *, candidate_spec_override: dict[str, object] | None):
    study, selection = _study_and_selection()
    source = _package(tmp_path / "pkg-site")
    canonical_staged = stage_bfcl_package(
        source=source, spec=_spec(tmp_path / "a"), output_root=tmp_path / "ca" / "overlay"
    )
    candidate_staged = stage_bfcl_package(
        source=source,
        spec=_spec(tmp_path / "b", **(candidate_spec_override or {})),
        output_root=tmp_path / "cb" / "overlay",
    )
    label = effective_harness_version(_BASE_VERSION, canonical_staged.registration_sha256)
    candidate_label = effective_harness_version(_BASE_VERSION, candidate_staged.registration_sha256)
    files = _variant(tmp_path, study, selection)
    version = json.loads(files["study/variant-manifest.json"])["benchmark_version"]
    ids = list(selection.canonical.selected_ids)
    canonical = [
        r.model_copy(
            update={
                "harness_version": label,
                "artifact_paths": [*r.artifact_paths, REGISTRATION_MANIFEST_FILE],
            }
        )
        for r in _pair_rows(
            selection,
            "canonical",
            version=_benchmark_version("bfcl-v4"),
            passes=set(ids[:150]),
            run_id="run-canonical",
        )
    ]
    candidate = [
        r.model_copy(
            update={
                "harness_version": candidate_label,
                "artifact_paths": [*r.artifact_paths, REGISTRATION_MANIFEST_FILE],
            }
        )
        for r in _pair_rows(
            selection, "candidate", version=version, passes=set(ids[20:160]), run_id="run-candidate"
        )
    ]
    canonical_proof = _proof_from_rows(
        tmp_path / "canonical",
        canonical,
        extra_raw={
            REGISTRATION_MANIFEST_FILE: render_registration_manifest(
                canonical_staged, base_version=_BASE_VERSION
            )
        },
    )
    candidate_proof = _proof_from_rows(
        tmp_path / "candidate",
        candidate,
        extra_raw={
            **files,
            REGISTRATION_MANIFEST_FILE: render_registration_manifest(
                candidate_staged, base_version=_BASE_VERSION
            ),
        },
    )
    return study, selection, canonical_proof, candidate_proof, canonical_staged


def test_paired_report_binds_one_registration_shared_by_both_arms(tmp_path: Path) -> None:
    study, selection, canonical_proof, candidate_proof, staged = _registered_pair(
        tmp_path, candidate_spec_override=None
    )
    built = write_proof_backed_exposure_report(
        study,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="declared",
        output=tmp_path / "report.json",
        lock_output=tmp_path / "lock.json",
        fmt="json",
        selection=selection,
    )
    registration = built.report.payload["registration"]
    assert registration["registration_sha256"] == staged.registration_sha256
    assert registration["registry_id"] == _QWEN_ID
    assert registration["api_model"] == _QWEN_API
    assert built.lock_payload["registration_sha256"] == staged.registration_sha256


def test_paired_report_rejects_arms_with_different_registrations(tmp_path: Path) -> None:
    study, selection, canonical_proof, candidate_proof, _ = _registered_pair(
        tmp_path, candidate_spec_override={"api_model": "qwen3.5:397b-cloud"}
    )
    with pytest.raises(BenchEvalError, match="registration"):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="raw_only",
            output=tmp_path / "r.json",
            lock_output=tmp_path / "l.json",
            fmt="json",
            selection=selection,
        )
    assert not (tmp_path / "r.json").exists()


def test_registration_label_without_the_retained_manifest_is_rejected(tmp_path: Path) -> None:
    study, selection = _study_and_selection()
    label = effective_harness_version(_BASE_VERSION, "sha256:" + "a" * 64)
    files = _variant(tmp_path, study, selection)
    version = json.loads(files["study/variant-manifest.json"])["benchmark_version"]
    ids = list(selection.canonical.selected_ids)
    canonical = [
        r.model_copy(update={"harness_version": label})
        for r in _pair_rows(
            selection,
            "canonical",
            version=_benchmark_version("bfcl-v4"),
            passes=set(ids[:150]),
            run_id="run-canonical",
        )
    ]
    candidate = [
        r.model_copy(update={"harness_version": label})
        for r in _pair_rows(
            selection, "candidate", version=version, passes=set(ids[:150]), run_id="run-candidate"
        )
    ]
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate, extra_raw=files)
    with pytest.raises(BenchEvalError, match="registration"):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="raw_only",
            output=tmp_path / "r.json",
            lock_output=tmp_path / "l.json",
            fmt="json",
            selection=selection,
        )
