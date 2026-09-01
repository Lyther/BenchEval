"""Composition and startup for the optional local operator console."""

from __future__ import annotations

import secrets
from pathlib import Path

from bencheval.exceptions import BenchEvalError


def run_console(*, port: int = 8090, open_browser: bool = True) -> None:
    """Run the private console on IPv4 loopback only."""
    if not 1024 <= port <= 65535:
        raise BenchEvalError("UI port must be between 1024 and 65535")
    try:
        from nicegui import app, ui
    except ImportError as exc:
        raise BenchEvalError(
            "operator console requires the UI extra; run `uv sync --extra ui`",
        ) from exc

    from bencheval.ui.pages import (
        catalog_page,
        compare_page,
        environment_page,
        overview_page,
        proofs_page,
        readiness_page,
        reports_page,
        run_builder_page,
        runs_page,
    )
    from bencheval.ui.security import LoopbackCapabilityMiddleware

    capability = secrets.token_urlsafe(32)
    app.add_middleware(LoopbackCapabilityMiddleware, capability=capability, port=port)
    css = Path(__file__).with_name("assets") / "console.css"
    ui.add_css(css.read_text(encoding="utf-8"), shared=True)
    ui.page("/")(overview_page)
    ui.page("/catalog")(catalog_page)
    ui.page("/run")(run_builder_page)
    ui.page("/runs")(runs_page)
    ui.page("/compare")(compare_page)
    ui.page("/reports")(reports_page)
    ui.page("/proofs")(proofs_page)
    ui.page("/readiness")(readiness_page)
    ui.page("/environment")(environment_page)
    launch_url = f"http://127.0.0.1:{port}/?cap={capability}"
    print(f"BenchEval operator console: {launch_url}")
    if not open_browser:
        print("Local capability URL is single-process and expires when this process stops.")
    ui.run(
        host="127.0.0.1",
        port=port,
        title="BenchEval Operator Console",
        show=f"/?cap={capability}" if open_browser else False,
        reload=False,
        fastapi_docs=False,
        endpoint_documentation="none",
        show_welcome_message=False,
        dark=True,
    )


__all__ = ["run_console"]
