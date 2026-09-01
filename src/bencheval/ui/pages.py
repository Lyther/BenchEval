"""NiceGUI pages for the local BenchEval operator console."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from bencheval.application import (
    OperatorOperations,
    PlanPreviewDTO,
    PlanRequestDTO,
    proof_inventory_counts,
)
from bencheval.exceptions import BenchEvalError
from bencheval.live_run_manifest import default_runs_manifest_path
from bencheval.proof_bundle import default_proofs_dir
from bencheval.redaction import env_secret_values, redact_string
from bencheval.ui.session import RUN_SESSION, RunSessionView

OPS = OperatorOperations()

NAVIGATION = (
    ("Overview", "/", "dashboard"),
    ("Catalog", "/catalog", "inventory_2"),
    ("Run Builder", "/run", "play_circle"),
    ("Runs & Evidence", "/runs", "fact_check"),
    ("Compare", "/compare", "compare_arrows"),
    ("Reports & Exports", "/reports", "download"),
    ("Proofs", "/proofs", "verified"),
    ("Readiness", "/readiness", "rule"),
    ("Environment", "/environment", "settings_ethernet"),
)


def _notify_error(exc: BaseException) -> None:
    message = redact_string(
        str(exc).splitlines()[0][:500],
        extra_secrets=env_secret_values(),
    )
    ui.notify(message, type="negative", close_button=True, timeout=0)


def _shell(title: str, subtitle: str) -> None:
    ui.add_body_html('<a class="skip-link" href="#main-content">Skip to content</a>')
    with ui.left_drawer(value=True).classes("be-nav p-4"):
        ui.label("BENCH / EVAL").classes("be-kicker")
        ui.label("Operator Console").classes("text-xl font-bold mb-5")
        for label, href, icon in NAVIGATION:
            with ui.row().classes("items-center gap-3 py-2"):
                ui.icon(icon).classes("text-teal-4")
                ui.link(label, href).classes("text-white no-underline")
        ui.separator().classes("my-5")
        session = RUN_SESSION.snapshot()
        ui.label("Run session").classes("be-kicker")
        ui.label(session.state.upper()).classes("be-status mt-2")
        ui.label(session.message).classes("be-muted text-xs mt-2")
    with ui.header().classes("bg-transparent border-b border-slate-700 px-8"):
        ui.label(title).classes("text-lg font-semibold")
        ui.space()
        ui.label("127.0.0.1 · private").classes("be-status be-mono")
    ui.element("span").props('id="main-content" tabindex="-1"')
    ui.label(title).classes("text-3xl font-bold")
    ui.label(subtitle).classes("be-muted mb-6")


def _metric(label: str, value: str, detail: str) -> None:
    with ui.card().classes("be-card p-5 min-w-52 grow"):
        ui.label(label).classes("be-kicker")
        ui.label(value).classes("text-3xl font-bold mt-2")
        ui.label(detail).classes("be-muted text-sm")


def _json_panel(title: str) -> tuple[ui.card, ui.code]:
    card = ui.card().classes("be-card w-full p-5")
    with card:
        ui.label(title).classes("be-kicker")
        code = ui.code("No result yet", language="json").classes("w-full be-mono")
    return card, code


def _set_json(code: ui.code, value: object) -> None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    code.set_content(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _session_payload(view: RunSessionView) -> dict[str, object]:
    result = view.result.model_dump(mode="json") if view.result is not None else None
    return {
        "state": view.state,
        "run_id": view.run_id,
        "started_at": view.started_at,
        "message": view.message,
        "result": result,
    }


def overview_page() -> None:
    _shell("Overview", "Truthful control-plane state at a glance")
    try:
        catalog = OPS.catalog()
        runs = OPS.runs()
        proofs = OPS.proofs()
    except BenchEvalError as exc:
        _notify_error(exc)
        return
    verified_proofs, corrupt_proofs = proof_inventory_counts(proofs)
    proof_detail = "verified local objects"
    if corrupt_proofs:
        proof_detail += f" · {corrupt_proofs} corrupt"
    with ui.row().classes("w-full gap-4 flex-wrap"):
        _metric("Catalog", str(catalog.benchmark_count), "benchmarks")
        _metric("Executable", str(catalog.executable_count), "admitted adapters")
        _metric("Live history", str(len(runs)), "validated current runs")
        _metric("Proof inventory", str(verified_proofs), proof_detail)
    with ui.row().classes("w-full gap-5 mt-5 items-start"):
        with ui.card().classes("be-card p-5 grow"):
            ui.label("Recent runs").classes("be-kicker")
            columns = [
                {"name": "run", "label": "Run", "field": "run", "align": "left"},
                {"name": "benchmark", "label": "Benchmark", "field": "benchmark"},
                {"name": "status", "label": "Registration", "field": "status"},
                {"name": "model", "label": "Model", "field": "model"},
            ]
            rows = [
                {
                    "run": row.run_id,
                    "benchmark": row.benchmark_id or "—",
                    "status": row.status,
                    "model": row.model_id,
                }
                for row in runs[:8]
            ]
            ui.table(columns=columns, rows=rows, row_key="run").classes("w-full")
        with ui.card().classes("be-card p-5 w-80"):
            ui.label("Readiness boundary").classes("be-kicker")
            ui.label("Tier-0 ≠ Tier-1 ≠ Tier-2").classes("text-xl font-bold mt-2")
            ui.label(
                "Software gates, registered live proof, and benchmark readiness remain separate.",
            ).classes("be-muted")
            ui.link("Open readiness ledger", "/readiness").classes("text-teal-4 mt-4")


def catalog_page() -> None:
    _shell("Catalog", "Benchmarks, models, runtimes, agents, and providers")
    search = (
        ui.input("Search catalog", placeholder="ID, name, or state")
        .props("outlined clearable")
        .classes("w-full mb-4")
    )
    tables: dict[str, ui.table] = {}

    def rows_for(kind: str, query: str = "") -> list[dict[str, str]]:
        page = OPS.catalog_page(kind=kind, query=query, limit=200)
        return [
            {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "detail": " · ".join(item.detail),
                "runnable": "yes" if item.runnable else "no",
            }
            for item in page.items
        ]

    with ui.tabs().classes("w-full") as tabs:
        selected = ui.tab("Benchmarks")
        for name in ("Models", "Runtimes", "Agents", "Providers"):
            ui.tab(name)
    with ui.tab_panels(tabs, value=selected).classes("w-full bg-transparent"):
        for tab_name, kind in (
            ("Benchmarks", "benchmark"),
            ("Models", "model"),
            ("Runtimes", "runtime"),
            ("Agents", "agent"),
            ("Providers", "provider"),
        ):
            with ui.tab_panel(tab_name):
                columns = [
                    {"name": "id", "label": "ID", "field": "id", "align": "left"},
                    {"name": "name", "label": "Name", "field": "name", "align": "left"},
                    {"name": "status", "label": "State", "field": "status"},
                    {"name": "detail", "label": "Contract", "field": "detail"},
                    {"name": "runnable", "label": "Runnable", "field": "runnable"},
                ]
                tables[kind] = ui.table(
                    columns=columns,
                    rows=rows_for(kind),
                    row_key="id",
                    pagination=25,
                ).classes("w-full")

    def filter_catalog() -> None:
        for kind, table in tables.items():
            table.rows = rows_for(kind, str(search.value or ""))
            table.update()

    search.on_value_change(lambda _: filter_catalog())


def run_builder_page() -> None:
    _shell("Run Builder", "Axes → plan → preflight → explicit launch")
    snapshot = OPS.catalog()
    values = {
        kind: [item.id for item in snapshot.items if item.kind == kind]
        for kind in {item.kind for item in snapshot.items}
    }
    preview: dict[str, PlanPreviewDTO] = {}
    preflight: dict[str, str] = {}
    default_slices = {
        item.id: item.default_slice
        for item in snapshot.items
        if item.kind == "benchmark" and item.default_slice is not None
    }
    initial_benchmark = next(
        (item.id for item in snapshot.items if item.kind == "benchmark" and item.runnable),
        None,
    )
    with (
        ui.card().classes("be-card w-full p-5"),
        ui.grid(columns=3).classes("w-full gap-4"),
    ):
        benchmark = ui.select(
            values.get("benchmark", []),
            label="Benchmark",
            value=initial_benchmark,
        ).props("outlined")
        slice_id = ui.input(
            "Slice",
            value=default_slices.get(initial_benchmark or "", ""),
        ).props("outlined")
        model = ui.select(values.get("model", []), label="Model").props("outlined")
        provider = ui.select(values.get("provider", []), label="Provider", value="bytellm").props(
            "outlined"
        )
        runtime = ui.select([None, *values.get("runtime", [])], label="Runtime (optional)").props(
            "outlined clearable"
        )
        agent = ui.select([None, *values.get("agent", [])], label="Agent (optional)").props(
            "outlined clearable"
        )
        output = ui.input("Evidence output (optional)").props("outlined")
        artifacts = ui.input("Artifacts directory (optional)").props("outlined")
        diagnostic = ui.checkbox("Diagnostic interpretation")
    benchmark.on_value_change(
        lambda event: slice_id.set_value(default_slices.get(str(event.value), "")),
    )
    _, result = _json_panel("Canonical plan")
    _, preflight_result = _json_panel("Preflight")

    def request() -> PlanRequestDTO:
        return PlanRequestDTO(
            benchmark_id=str(benchmark.value or ""),
            slice_id=str(slice_id.value or ""),
            model_id=str(model.value or ""),
            provider_id=str(provider.value or "bytellm"),
            runtime_id=str(runtime.value) if runtime.value else None,
            agent_id=str(agent.value) if agent.value else None,
            diagnostic=bool(diagnostic.value),
            output_path=str(output.value) if output.value else None,
            artifacts_dir=str(artifacts.value) if artifacts.value else None,
        )

    def plan_action() -> None:
        try:
            value = OPS.plan(request())
            preview["value"] = value
            preflight.clear()
            _set_json(result, value)
            ui.notify("Plan is valid", type="positive")
        except (BenchEvalError, ValueError) as exc:
            preview.clear()
            _notify_error(exc)

    def launch_now() -> None:
        value = preview.get("value")
        if value is None:
            _notify_error(BenchEvalError("build and review a valid plan first"))
            return
        confirmation.close()
        try:
            session = RUN_SESSION.start(request(), fingerprint=value.fingerprint)
            ui.notify(session.message, type="positive")
            ui.navigate.to("/runs")
        except BenchEvalError as exc:
            _notify_error(exc)

    def start_action() -> None:
        value = preview.get("value")
        if value is None:
            _notify_error(BenchEvalError("build and review a valid plan first"))
            return
        if preflight.get("fingerprint") != value.fingerprint:
            _notify_error(BenchEvalError("run a passing preflight for this exact plan first"))
            return
        confirmation_text.set_text(
            f"Launch {value.benchmark_version} for {value.instance_count} instances "
            f"with model {value.model_id}? The configured envelope is "
            f"${value.max_cost_usd:.2f} and {value.max_wall_clock_sec}s.",
        )
        confirmation.open()

    def preflight_action() -> None:
        value = preview.get("value")
        if value is None:
            _notify_error(BenchEvalError("build a valid plan before preflight"))
            return
        try:
            report = OPS.doctor(
                backend=value.backend,
                profile=value.execution_profile,
                model_id=value.model_id,
            )
            _set_json(preflight_result, report)
            if report.ok:
                preflight["fingerprint"] = value.fingerprint
            else:
                preflight.clear()
            ui.notify(
                "Preflight passed" if report.ok else "Preflight has blockers",
                type="positive" if report.ok else "warning",
            )
        except (BenchEvalError, ValueError) as exc:
            preflight.clear()
            _notify_error(exc)

    with ui.dialog() as confirmation, ui.card().classes("be-card p-6 max-w-xl"):
        ui.label("Confirm charged run").classes("text-xl font-bold")
        confirmation_text = ui.label().classes("be-muted")
        ui.label("BenchEval will not retry automatically.").classes("be-kicker")
        with ui.row().classes("justify-end gap-3 w-full"):
            ui.button("Back", on_click=confirmation.close).props("flat")
            ui.button("Launch once", icon="play_arrow", on_click=launch_now).props("color=red")

    with ui.row().classes("gap-3 mt-4"):
        ui.button("Build plan", icon="description", on_click=plan_action).props("color=teal")
        ui.button("Run preflight", icon="health_and_safety", on_click=preflight_action).props(
            "outline color=teal"
        )
        ui.button("Start confirmed run", icon="play_arrow", on_click=start_action).props(
            "color=red"
        )
        ui.label("Start may incur provider cost; it never retries automatically.").classes(
            "be-muted self-center"
        )


def runs_page() -> None:
    _shell("Runs & Evidence", "Validated current projection and the one active session")
    session_card, session_code = _json_panel("Active run session")
    initial_session = RUN_SESSION.snapshot()

    def refresh_session() -> None:
        _set_json(session_code, _session_payload(RUN_SESSION.snapshot()))

    _set_json(session_code, _session_payload(initial_session))
    ui.timer(2.0, refresh_session)
    with session_card:
        cancel_button = ui.button(
            "Cancel active run",
            icon="stop",
            on_click=lambda: _set_json(session_code, _session_payload(RUN_SESSION.cancel())),
        ).props("outline color=red")
        if initial_session.state != "running":
            cancel_button.disable()
    runs = OPS.runs()
    rows = [row.model_dump(mode="json") for row in runs]
    columns = [
        {"name": "run_id", "label": "Run ID", "field": "run_id", "align": "left"},
        {"name": "benchmark_id", "label": "Benchmark", "field": "benchmark_id"},
        {"name": "status", "label": "Registration", "field": "status"},
        {"name": "model_id", "label": "Model", "field": "model_id"},
        {"name": "runtime_id", "label": "Runtime", "field": "runtime_id"},
        {"name": "last_generated_at", "label": "Updated", "field": "last_generated_at"},
    ]
    ui.table(columns=columns, rows=rows, row_key="run_id", pagination=25).classes("w-full mt-5")
    with ui.expansion("Run, evidence, artifact, and qualification detail", icon="search").classes(
        "be-card w-full mt-5 p-2"
    ):
        detail_run_id = ui.input("Run ID", placeholder="run-…").classes("w-full")
        _, detail_result = _json_panel("Validated run detail")

        def detail_action() -> None:
            try:
                _set_json(detail_result, OPS.run_detail(str(detail_run_id.value or "")))
            except (BenchEvalError, OSError, ValueError) as exc:
                _notify_error(exc)

        ui.button("Load validated detail", icon="manage_search", on_click=detail_action).props(
            "color=teal"
        )
    with ui.expansion("Append legal lifecycle event", icon="edit_note").classes(
        "be-card w-full mt-5 p-2"
    ):
        with ui.grid(columns=3).classes("w-full gap-3"):
            run_id = ui.input("Run ID")
            model_id = ui.input("Model ID")
            status = ui.select(
                ["registered", "running", "completed", "passed", "failed", "archived"],
                label="Status",
            )
            benchmark = ui.input("Benchmark")
            slice_id = ui.input("Slice")
            runtime = ui.input("Runtime")
            evidence = ui.input("Evidence path")
            report = ui.input("Report path")
            bundle = ui.input("Bundle path")
            notes = ui.input("Notes")
        _, qualification_result = _json_panel("Evidence qualification")

        def qualify_action() -> None:
            if not evidence.value:
                _notify_error(BenchEvalError("evidence path is required for qualification"))
                return
            try:
                _set_json(qualification_result, OPS.qualify(Path(str(evidence.value))))
            except (BenchEvalError, OSError, ValueError) as exc:
                _notify_error(exc)

        def register_action() -> None:
            try:
                value = OPS.register(
                    run_id=str(run_id.value or ""),
                    model_id=str(model_id.value or ""),
                    status=status.value,
                    benchmark_id=str(benchmark.value) if benchmark.value else None,
                    slice_id=str(slice_id.value) if slice_id.value else None,
                    runtime_id=str(runtime.value) if runtime.value else None,
                    evidence_path=Path(str(evidence.value)) if evidence.value else None,
                    report_path=Path(str(report.value)) if report.value else None,
                    bundle_path=Path(str(bundle.value)) if bundle.value else None,
                    notes=str(notes.value or ""),
                )
                ui.notify(f"Registered {value.status}", type="positive")
            except (BenchEvalError, ValueError) as exc:
                _notify_error(exc)

        with ui.row().classes("gap-3"):
            ui.button("Qualify evidence", on_click=qualify_action).props("outline color=teal")
            ui.button("Append event", on_click=register_action).props("color=teal")


def compare_page() -> None:
    _shell("Compare", "Validity precedes every headline")
    with ui.card().classes("be-card w-full p-5"):
        baseline = ui.input("Baseline evidence JSONL").classes("w-full")
        current = ui.input("Current evidence JSONL").classes("w-full")
        output = ui.input("Exclusive output path").classes("w-full")
        fmt = ui.select(["markdown", "json"], value="markdown", label="Format")
        _, result = _json_panel("Comparison artifact")

        def action() -> None:
            try:
                value = OPS.compare(
                    Path(str(baseline.value)),
                    Path(str(current.value)),
                    Path(str(output.value)),
                    output_format=fmt.value,
                )
                _set_json(result, value)
            except (BenchEvalError, OSError, ValueError) as exc:
                _notify_error(exc)

        ui.button("Compare", icon="compare_arrows", on_click=action).props("color=teal")


def reports_page() -> None:
    _shell("Reports & Exports", "Derived artifacts; canonical evidence remains unchanged")
    evidence = ui.input("Evidence JSONL").classes("w-full")
    output = ui.input("Exclusive output path or directory").classes("w-full")
    raw = ui.input("Raw artifacts directory (bundle only)").classes("w-full")
    _, result = _json_panel("Generated artifact")

    def invoke(callback: Callable[[], object]) -> None:
        try:
            _set_json(result, callback())
            ui.notify("Artifact created", type="positive")
        except (BenchEvalError, OSError, ValueError) as exc:
            _notify_error(exc)

    with ui.row().classes("gap-3 flex-wrap"):
        ui.button(
            "Markdown report",
            on_click=lambda: invoke(
                lambda: OPS.report(Path(str(evidence.value)), Path(str(output.value)))
            ),
        )
        ui.button(
            "Parquet export",
            on_click=lambda: invoke(
                lambda: OPS.warehouse(
                    Path(str(evidence.value)), Path(str(output.value)), fmt="parquet"
                )
            ),
        )
        ui.button(
            "DuckDB export",
            on_click=lambda: invoke(
                lambda: OPS.warehouse(
                    Path(str(evidence.value)), Path(str(output.value)), fmt="duckdb"
                )
            ),
        )
        ui.button(
            "Public bundle",
            on_click=lambda: invoke(
                lambda: OPS.bundle(
                    Path(str(evidence.value)),
                    Path(str(output.value)),
                    raw_dir=Path(str(raw.value)) if raw.value else None,
                    redaction="public",
                )
            ),
        )
        ui.button(
            "Private bundle",
            on_click=lambda: invoke(
                lambda: OPS.bundle(
                    Path(str(evidence.value)),
                    Path(str(output.value)),
                    raw_dir=Path(str(raw.value)) if raw.value else None,
                    redaction="private",
                )
            ),
        ).props("color=orange")


def proofs_page() -> None:
    _shell("Proofs", "Permanent, local, content-addressed private proof inventory")
    try:
        proofs = OPS.proofs()
    except (BenchEvalError, OSError, ValueError) as exc:
        _notify_error(exc)
        proofs = ()
    rows = [row.model_dump(mode="json") for row in proofs]
    columns = [
        {"name": "proof_id", "label": "Proof ID", "field": "proof_id", "align": "left"},
        {"name": "run_id", "label": "Run", "field": "run_id"},
        {"name": "benchmark_id", "label": "Benchmark", "field": "benchmark_id"},
        {"name": "classification", "label": "Classification", "field": "classification"},
        {"name": "verified", "label": "Integrity", "field": "verified"},
    ]
    ui.table(columns=columns, rows=rows, row_key="proof_id", pagination=20).classes("w-full")
    with ui.expansion("Verify or import proof", icon="verified_user").classes(
        "be-card w-full mt-5 p-2"
    ):
        source = ui.input("Proof directory or archive").classes("w-full")
        expected = ui.input("Expected sha256 proof ID (optional)").classes("w-full")
        store = ui.input("Store root (optional)", value=str(default_proofs_dir())).classes("w-full")
        _, result = _json_panel("Proof operation")

        def verify_action() -> None:
            try:
                _set_json(
                    result,
                    OPS.proof_verify(
                        Path(str(source.value)), str(expected.value) if expected.value else None
                    ),
                )
            except (BenchEvalError, OSError, ValueError) as exc:
                _notify_error(exc)

        def import_action() -> None:
            try:
                _set_json(result, OPS.proof_import(Path(str(source.value)), Path(str(store.value))))
            except (BenchEvalError, OSError, ValueError) as exc:
                _notify_error(exc)

        with ui.row().classes("gap-3"):
            ui.button("Verify", on_click=verify_action).props("color=teal")
            ui.button("Import permanent proof", on_click=import_action).props("color=orange")
        ui.label(
            "Verification proves inventory/content integrity, not creator authenticity. "
            "No delete action exists."
        ).classes("be-muted")
    with ui.expansion("Export private_proof_v1", icon="archive").classes("be-card w-full mt-5 p-2"):
        export_run_id = ui.input("Run ID")
        export_evidence = ui.input("Evidence JSONL")
        export_artifacts = ui.input("Artifacts directory")
        export_manifest = ui.input("Run manifest", value=str(default_runs_manifest_path()))
        export_output = ui.input("Exclusive proof output directory")
        capture = ui.input("Capture directory (optional)")

        def export_action() -> None:
            try:
                value = OPS.proof_export(
                    run_id=str(export_run_id.value),
                    evidence_path=Path(str(export_evidence.value)),
                    artifacts_dir=Path(str(export_artifacts.value)),
                    manifest_path=Path(str(export_manifest.value)),
                    output_dir=Path(str(export_output.value)),
                    capture_dir=Path(str(capture.value)) if capture.value else None,
                )
                ui.notify(value.proof_id, type="positive", close_button=True, timeout=0)
            except (BenchEvalError, OSError, ValueError) as exc:
                _notify_error(exc)

        ui.button("Export proof", on_click=export_action).props("color=teal")


def readiness_page() -> None:
    _shell("Readiness", "Software, live proof, and benchmark readiness are independent")
    try:
        rows = [row.model_dump(mode="json") for row in OPS.readiness()]
    except (BenchEvalError, OSError, ValueError) as exc:
        _notify_error(exc)
        rows = []
    columns = [
        {"name": "benchmark_id", "label": "Benchmark", "field": "benchmark_id", "align": "left"},
        {"name": "software_state", "label": "Software", "field": "software_state"},
        {"name": "tier1_state", "label": "Tier-1", "field": "tier1_state"},
        {"name": "tier2_state", "label": "Tier-2", "field": "tier2_state"},
        {"name": "blockers", "label": "Blockers", "field": "blockers"},
    ]
    for row in rows:
        row["blockers"] = " · ".join(row["blockers"])
    ui.table(columns=columns, rows=rows, row_key="benchmark_id", pagination=20).classes("w-full")


def environment_page() -> None:
    _shell("Environment", "Presence and capability only; credential values never cross")
    with ui.card().classes("be-card w-full p-5"):
        backend = ui.select(["inspect", "harbor"], value="inspect", label="Backend")
        profile = ui.select(
            [None, "E0", "E1", "E2", "E3", "E4", "pilot"], label="Profile", clearable=True
        )
        model = ui.select(
            [item.id for item in OPS.catalog().items if item.kind == "model"],
            label="Model",
            clearable=True,
        )
        _, result = _json_panel("Doctor report")

        def action() -> None:
            try:
                value = OPS.doctor(
                    backend=backend.value, profile=profile.value, model_id=model.value
                )
                _set_json(result, value)
            except (BenchEvalError, ValueError) as exc:
                _notify_error(exc)

        ui.button("Run doctor", icon="health_and_safety", on_click=action).props("color=teal")
        ui.label("The console never displays credential values or edits .env.").classes("be-muted")
