"""X4.1 acceptance: the study journey in a real browser, driven from the keyboard.

The projection contracts prove what the operations return. This module proves the
operator can actually do the work: reach the added Compare controls by keyboard,
build a proof-backed report from retained proofs, reproduce a retained lock,
read the result out of the rendered table, and be told why a request was refused.

It runs the real console process, a real Chrome, real key events, and the
retained X2.4 FC plumbing proofs. It is skipped where the optional UI extra, the
Selenium driver, or a Chrome binary is absent:

    uv run --extra ui --with selenium pytest tests/specs/test_exposure_console_browser_acceptance.py

That command leaves ``pyproject.toml`` and ``uv.lock`` alone but does resync the
shared project environment for its duration, so do not start it beside a running
suite; restore the environment afterwards with ``uv sync --all-extras
--all-groups``.

A declared-population journey needs retained declared proofs, which are far too
large to vendor. Point ``BENCHEVAL_DECLARED_JOURNEY`` at a directory holding
``canonical/``, ``candidate/`` and ``lock.json`` copied from the operator host's
proof store to run it; it is skipped otherwise.

SUBSTITUTE_JUSTIFICATION
- substitute: none for the console, the browser, the input events, the proofs, or
  the operations; the declared journey reads copied proofs from a directory the
  operator supplies
- replaces: nothing — this module exists because dictionary-level projection
  tests cannot show that the page is operable
- necessity: a copied proof directory is the supported reproduction input, and
  the retained declared proofs are ~25 MB, so they are supplied rather than
  vendored
- real-option: this is the real option; the console is spawned as the operator
  spawns it and driven only through key events
- proof-limit: proves keyboard reachability, labeling, and the rendered result
  of the real journeys in headless Chrome; it does not prove screen-reader
  announcement, other browsers, or the scientific validity of any study
- real-proof: the retained X2.4 FC plumbing proofs and lock
  (``tests/fixtures/exposure/x24fc``) and, when supplied, the retained X2.4b
  declared Live proofs and lock from the dev-box store
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("nicegui", reason="operator console requires the UI extra")
pytest.importorskip("selenium", reason="browser acceptance requires selenium")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver

_MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
_CHROME = (
    shutil.which("google-chrome")
    or shutil.which("chromium")
    or (str(_MAC_CHROME) if _MAC_CHROME.exists() else None)
)
pytestmark = pytest.mark.skipif(_CHROME is None, reason="browser acceptance requires Chrome")

_REPO = Path(__file__).resolve().parents[2]
_X24FC = _REPO / "tests" / "fixtures" / "exposure" / "x24fc"
_RETAINED_LOCK = _X24FC / "x24fc-exposure-report.lock.json"
_RETAINED_REPORT = _X24FC / "x24fc-exposure-report.json"
_DECLARED = os.environ.get("BENCHEVAL_DECLARED_JOURNEY")
_STUDY_FIELDS = (
    "Study id or manifest path",
    "Canonical evidence JSONL",
    "Candidate evidence JSONL",
    "Canonical proof directory",
    "Candidate proof directory",
    "Lock path (report writes it, reproduce reads it)",
    "Population selection record (optional)",
    "Exclusive report output",
    "Analysis",
)
_STUDY_BUTTONS = ("VALIDATE STUDY", "BUILD REPORT", "REPRODUCE LOCK")
_FOCUS_JS = """
const el = document.activeElement;
if (!el) return null;
return {
  tag: el.tagName,
  aria: el.getAttribute('aria-label'),
  text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
};
"""
_ROWS_JS = """
return Array.from(document.querySelectorAll('.be-table tbody tr')).map(
  tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim()));
"""
_RESULT_JS = """
const panels = Array.from(document.querySelectorAll('.be-mono'));
const last = panels[panels.length - 1];
return last ? last.innerText.replace(/\\ncontent_copy\\s*$/, '') : null;
"""
_FIELDS_JS = """
return Array.from(document.querySelectorAll('input[aria-label]')).map(
  i => [i.getAttribute('aria-label'), i.value]).filter(pair => pair[1]);
"""
_NOTIFY_JS = """
return Array.from(document.querySelectorAll('.q-notification')).map(
  n => n.innerText.replace(/\\s+/g, ' ').trim());
"""


# --- the console under test ---------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _accepts(port: int, *, deadline: float) -> bool:
    """The launch URL is printed before uvicorn binds; wait for the real listener."""
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def console(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The real operator console, launched the way the operator launches it."""
    port = _free_port()
    log = tmp_path_factory.mktemp("console") / "console.log"
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [sys.executable, "-m", "bencheval.cli", "ui", "--port", str(port), "--no-open"],
            cwd=_REPO,
            stdout=handle,
            stderr=subprocess.STDOUT,
            # The console is launched as the operator launches it. NiceGUI reads
            # PYTEST_CURRENT_TEST to switch itself into its own screen-test mode,
            # so that marker must not leak into a real console process.
            env={
                key: value
                for key, value in {**os.environ, "PYTHONUNBUFFERED": "1"}.items()
                if key != "PYTEST_CURRENT_TEST"
            },
        )
        try:
            deadline = time.monotonic() + 90
            capability = ""
            while time.monotonic() < deadline and not capability:
                if process.poll() is not None:
                    raise AssertionError(f"console exited:\n{log.read_text(errors='ignore')}")
                for line in log.read_text(errors="ignore").splitlines():
                    if "cap=" in line:
                        capability = line.split("cap=")[1].strip()
                        break
                time.sleep(0.2)
            assert capability, f"console never printed its URL:\n{log.read_text(errors='ignore')}"
            assert _accepts(port, deadline=deadline), "the console never accepted a connection"
            yield f"http://127.0.0.1:{port}", capability
        finally:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - teardown safety
                process.kill()


@pytest.fixture(scope="module")
def browser() -> Iterator[WebDriver]:
    options = Options()
    options.binary_location = str(_CHROME)
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,2000")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    try:
        yield driver
    finally:
        driver.quit()


@pytest.fixture
def compare(console: tuple[str, str], browser: WebDriver) -> WebDriver:
    """A freshly loaded Compare page with the console's capability cookie held."""
    base, capability = console
    browser.get(f"{base}/?cap={capability}")
    _wait_until(browser, lambda d: d.execute_script("return !!(window.socket)"))
    browser.get(f"{base}/compare")
    _wait_until(
        browser,
        lambda d: d.execute_script(
            "return !!document.querySelector('.be-table') && !!(window.socket "
            "&& window.socket.connected)"
        ),
    )
    return browser


# --- keyboard driving ---------------------------------------------------------------


def _wait_until(driver: WebDriver, predicate, *, timeout: float = 30.0) -> object:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        last = predicate(driver)
        if last:
            return last
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for the page; last value: {last!r}")


def _press(driver: WebDriver, *keys: str) -> None:
    chain = ActionChains(driver)
    for key in keys:
        chain.send_keys(key)
    chain.perform()


def _focus(driver: WebDriver) -> dict[str, str]:
    return driver.execute_script(_FOCUS_JS) or {}


def _is(focus: dict[str, str], name: str) -> bool:
    """Inputs are identified by their accessible name, controls by their label.

    Matching anything else against ``innerText`` would match ``<body>``, whose
    text contains every label on the page.
    """
    if focus.get("aria") == name:
        return True
    return focus.get("tag") in {"BUTTON", "A"} and name in focus.get("text", "")


def _tab_to(driver: WebDriver, name: str, *, limit: int = 60) -> int:
    """Tab until ``name`` holds focus, and report how many presses it took."""
    for pressed in range(1, limit + 1):
        _press(driver, Keys.TAB)
        if _is(_focus(driver), name):
            return pressed
    raise AssertionError(f"{name!r} is not reachable by keyboard within {limit} presses")


def _type(driver: WebDriver, field: str, value: str) -> None:
    """Move focus to ``field`` by keyboard and replace its contents."""
    _tab_to(driver, field)
    select_all = Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL
    ActionChains(driver).key_down(select_all).send_keys("a").key_up(select_all).perform()
    _press(driver, Keys.DELETE)
    if value:
        _press(driver, value)
    # Quasar commits an input on blur; the operator's next Tab does the same.
    _press(driver, Keys.TAB)


def _choose_analysis(driver: WebDriver, value: str) -> None:
    _tab_to(driver, "Analysis")
    _press(driver, Keys.ENTER)
    _wait_until(driver, lambda d: d.execute_script("return !!document.querySelector('.q-menu')"))
    for _ in range(4):
        if driver.execute_script(
            "return (document.querySelector('.q-menu .q-item--active "
            ".q-item__label')||{}).innerText === arguments[0];",
            value,
        ):
            break
        _press(driver, Keys.ARROW_DOWN)
    _press(driver, Keys.ENTER)
    _wait_until(
        driver,
        lambda d: (
            value
            in d.execute_script(
                "return (document.querySelector('[aria-label=\"Analysis\"]')"
                ".closest('.q-field').innerText || '');"
            )
        ),
    )


def _activate(driver: WebDriver, button: str) -> None:
    _tab_to(driver, button)
    _press(driver, Keys.ENTER)


def _rows(driver: WebDriver) -> dict[str, str]:
    rendered = driver.execute_script(_ROWS_JS) or []
    assert all(len(row) == 2 for row in rendered), rendered
    keys = [row[0] for row in rendered]
    assert len(keys) == len(set(keys)), f"the table renders a duplicate row key: {keys}"
    return {row[0]: row[1] for row in rendered}


def _await_rows(driver: WebDriver, key: str) -> dict[str, str]:
    """Wait for the table to hold the result of the action just taken.

    ``key`` is a row the new result must carry, so a table still showing the
    previous action cannot be read as this one's answer.
    """
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        rows = _rows(driver)
        if key in rows:
            return rows
        notified = driver.execute_script(_NOTIFY_JS)
        assert not notified, (
            f"the journey was refused instead of rendered: {notified}; "
            f"fields: {driver.execute_script(_FIELDS_JS)}"
        )
        time.sleep(0.1)
    raise AssertionError(f"no study result with a {key!r} row reached the table")


def _result(driver: WebDriver) -> dict[str, object]:
    text = _wait_until(
        driver,
        lambda d: (d.execute_script(_RESULT_JS) or "").strip().startswith("{") or None,
    )
    assert text
    return json.loads(driver.execute_script(_RESULT_JS))


def _dismiss_notifications(driver: WebDriver) -> None:
    driver.execute_script("document.querySelectorAll('.q-notification').forEach(n => n.remove());")


# --- the journeys -------------------------------------------------------------------


def test_the_study_controls_are_keyboard_reachable_and_labeled(compare: WebDriver) -> None:
    """Every added control is reachable in order, after the page's own controls."""
    order: list[str] = []
    for _ in range(40):
        _press(compare, Keys.TAB)
        focus = _focus(compare)
        name = focus.get("aria") or focus.get("text", "")
        if focus.get("tag") == "BODY":
            break
        order.append(name)

    # The Compare page keeps its original controls, unchanged and first.
    assert "Baseline evidence JSONL" in order
    assert order.index("Baseline evidence JSONL") < order.index("Study id or manifest path")
    # Then the study controls, in the order the card lays them out.
    positions = [order.index(field) for field in _STUDY_FIELDS]
    assert positions == sorted(positions), order
    # Every input announces itself; none is a bare box.
    assert all(
        compare.execute_script(
            "return !!document.querySelector(arguments[0]);",
            f'[aria-label="{field}"]',
        )
        for field in _STUDY_FIELDS
    )
    # The three actions follow the fields and are reachable without a mouse.
    for button in _STUDY_BUTTONS:
        match = next(name for name in order if button in name)
        assert order.index(match) > positions[-1]


def test_a_study_validates_from_the_keyboard(compare: WebDriver) -> None:
    _type(compare, "Study id or manifest path", "bfcl-v4-live-vs-non-live")
    _activate(compare, "VALIDATE STUDY")

    rows = _await_rows(compare, "digest")
    assert rows["study"] == "bfcl-v4-live-vs-non-live"
    assert rows["digest"].startswith("sha256:")
    assert rows["relation"] and rows["comparison mode"]


def test_a_proof_backed_report_is_built_and_read_from_the_table(
    compare: WebDriver, tmp_path: Path
) -> None:
    """The retained FC plumbing proofs rebuild their report through the page."""
    report = tmp_path / "report.json"
    lock = tmp_path / "lock.json"
    _type(compare, "Study id or manifest path", "bfcl-v4-live-vs-non-live")
    _type(compare, "Canonical proof directory", str(_X24FC / "canonical"))
    _type(compare, "Candidate proof directory", str(_X24FC / "candidate"))
    _type(compare, "Lock path (report writes it, reproduce reads it)", str(lock))
    _type(compare, "Exclusive report output", str(report))
    _activate(compare, "BUILD REPORT")

    rows = _await_rows(compare, "permitted interpretation")
    retained = json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))
    # The page rebuilt the retained report byte for byte, and says so.
    assert report.read_bytes() == _RETAINED_REPORT.read_bytes()
    result = _result(compare)
    assert result["report_sha256"] == json.loads(_RETAINED_LOCK.read_text())["report_sha256"]
    assert result["lock_sha256"] and lock.is_file()
    # The operator reads the population, both native scores, and the limits.
    assert rows["study"] == retained["study_id"]
    assert rows["analysis mode"] == retained["analysis_mode"] == "plumbing_only"
    assert retained["canonical"]["benchmark_id"] in rows["canonical"]
    assert retained["candidate"]["benchmark_id"] in rows["candidate"]
    assert rows["permitted interpretation"] == retained["permitted_interpretation"]
    assert rows["non-claims"]
    for claim in retained["forbidden_claims"]:
        assert claim in rows["non-claims"]
    assert rows["caveats"]


def test_a_refused_request_says_why_and_leaves_no_stale_result(
    compare: WebDriver, tmp_path: Path
) -> None:
    """A half-supplied input pair is refused, and the table does not keep a result."""
    _type(compare, "Study id or manifest path", "bfcl-v4-live-vs-non-live")
    _type(compare, "Canonical proof directory", str(_X24FC / "canonical"))
    _type(compare, "Lock path (report writes it, reproduce reads it)", str(tmp_path / "lock.json"))
    _type(compare, "Exclusive report output", str(tmp_path / "report.json"))
    _dismiss_notifications(compare)
    _activate(compare, "BUILD REPORT")

    messages = _wait_until(compare, lambda d: d.execute_script(_NOTIFY_JS) or None)
    assert any("exactly one input pair" in message for message in messages)  # type: ignore[union-attr]
    assert _rows(compare) == {}
    assert not (tmp_path / "report.json").exists()
    assert not (tmp_path / "lock.json").exists()
    _dismiss_notifications(compare)


def test_a_retained_lock_reproduces_without_upgrading_its_claim(
    compare: WebDriver, tmp_path: Path
) -> None:
    reproduced = tmp_path / "reproduced.json"
    _type(compare, "Canonical proof directory", str(_X24FC / "canonical"))
    _type(compare, "Candidate proof directory", str(_X24FC / "candidate"))
    _type(compare, "Lock path (report writes it, reproduce reads it)", str(_RETAINED_LOCK))
    _type(compare, "Exclusive report output", str(reproduced))
    _activate(compare, "REPRODUCE LOCK")

    rows = _await_rows(compare, "reproduced")
    retained = json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))
    assert rows["reproduced"] == "yes"
    assert rows["report digest"] == json.loads(_RETAINED_LOCK.read_text())["report_sha256"]
    assert reproduced.read_bytes() == _RETAINED_REPORT.read_bytes()
    # A reproduction shows the locked report's own words: same permitted
    # interpretation, same non-claims, no new endorsement.
    assert rows["locked study"] == retained["study_id"]
    assert rows["permitted interpretation"] == retained["permitted_interpretation"]
    for claim in retained["forbidden_claims"]:
        assert claim in rows["non-claims"]


@pytest.mark.skipif(_DECLARED is None, reason="BENCHEVAL_DECLARED_JOURNEY not supplied")
def test_a_declared_population_journey_reports_and_reproduces(
    compare: WebDriver, tmp_path: Path
) -> None:
    """Declared analysis over retained declared proofs, then its lock reproduced."""
    from bencheval.exposure_report import _retained_selection
    from bencheval.exposure_selection import render_selection_record

    supplied = Path(str(_DECLARED))
    lock = json.loads((supplied / "lock.json").read_text(encoding="utf-8"))
    selection = tmp_path / "selection.json"
    retained_selection = _retained_selection(lock)
    assert retained_selection is not None, "the supplied lock retains no population selection"
    selection.write_text(render_selection_record(retained_selection), encoding="utf-8")
    report = tmp_path / "declared-report.json"

    _type(compare, "Study id or manifest path", lock["study_id"])
    _type(compare, "Canonical proof directory", str(supplied / "canonical"))
    _type(compare, "Candidate proof directory", str(supplied / "candidate"))
    _type(compare, "Lock path (report writes it, reproduce reads it)", str(tmp_path / "lock.json"))
    _type(compare, "Population selection record (optional)", str(selection))
    _type(compare, "Exclusive report output", str(report))
    _choose_analysis(compare, "declared")
    _activate(compare, "BUILD REPORT")

    rows = _await_rows(compare, "population binding")
    result = _result(compare)
    assert result["report_sha256"] == lock["report_sha256"]
    assert rows["analysis mode"] == "declared_population"
    assert rows["population binding"] and "raw-only" not in rows["population binding"]
    assert rows["non-claims"] and rows["caveats"]

    reproduced = tmp_path / "reproduced.json"
    _type(compare, "Lock path (report writes it, reproduce reads it)", str(supplied / "lock.json"))
    _type(compare, "Exclusive report output", str(reproduced))
    _activate(compare, "REPRODUCE LOCK")

    repeated = _await_rows(compare, "reproduced")
    assert repeated["reproduced"] == "yes"
    assert repeated["report digest"] == lock["report_sha256"]
    # Reproducing a declared lock reproduces its report; it does not restate the
    # comparison as a finding.
    assert (
        repeated["permitted interpretation"]
        == json.loads(reproduced.read_text(encoding="utf-8"))["permitted_interpretation"]
    )
