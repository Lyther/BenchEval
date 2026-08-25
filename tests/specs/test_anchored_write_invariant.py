"""Class-invariant tripwire: executor-reachable modules never write raw pathnames.

Rounds 5-8 fixed the same unchecked post-launch write site-by-site (HLE, GPQA,
external-agent, terminal-bench, codex config). This static guard ends the
recurrence for the spellings it knows: ``.write_text(`` / ``.write_bytes(``,
builtin ``open(`` / ``os.fdopen(`` with write/append/exclusive or ``+`` modes,
``os.write(``, ``shutil.copy(`` / ``shutil.copyfile(``, and ``os.replace(``.
Any hit in a scanned module fails unless it sits on the explicit allowlist
below with a one-line justification. Anchored writes go through
``run_isolation.write_*_at_exclusive`` on a descriptor pinned before
subprocess launch.

Honest scope: this is a tripwire, not a proof. Aliasing (``w = os.write``),
indirect calls (``getattr(os, "write")``), modes split across lines, and
writes spelled through other libraries evade it; it says nothing about reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "bencheval"

SCANNED_FILES: tuple[str, ...] = (
    "hle_adapter.py",
    "gpqa_adapter.py",
    "terminal_bench_harbor.py",
    "external_agent_adapter.py",
    "momo_agent_adapter.py",
    "control_plane_executor.py",
    "bfcl_native_adapter.py",
    "cybergym_adapter.py",
    "exploitgym_adapter.py",
    "swebench_adapter.py",
)

# Pending adapters are scanned before admission so their retained skeletons
# cannot carry a known path-ownership defect into the executor when promoted.
# bfcl_native_adapter.py joined the scan at BFCL admission (2026-08-24).
ALLOWED_SITES: dict[str, tuple[str, ...]] = {
    "terminal_bench_harbor.py": (
        # fd-based mkstemp proxy env file: the descriptor from mkstemp owns
        # the inode (no pathname lookup), and the file lives outside the
        # evidence tree by construction.
        'os.fdopen(fd, "w", encoding="utf-8")',
    ),
}

_WRITE_MODE = re.compile(r'["\'](?:[wax][b+]*|[^"\']*\+[^"\']*)["\']')
_WRITE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.write_text\("),
    re.compile(r"\.write_bytes\("),
    # Builtin open() / os.fdopen() with a write, append, exclusive, or +
    # mode on the same line (os.open(...) with O_* flags is a different
    # spelling and is not matched).
    re.compile(r"(?<![\w.])(?:os\.fdopen|open)\([^)]*" + _WRITE_MODE.pattern),
    re.compile(r"(?<![\w.])os\.write\("),
    re.compile(r"(?<![\w.])shutil\.copy(?:file)?\("),
    re.compile(r"(?<![\w.])os\.replace\("),
)


def find_violations(text: str, *, allowed: tuple[str, ...] = ()) -> list[str]:
    """Return one ``lineno: line`` entry per raw-write spelling not allowlisted."""
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not any(pattern.search(stripped) for pattern in _WRITE_PATTERNS):
            continue
        if any(token in stripped for token in allowed):
            continue
        violations.append(f"{lineno}: {stripped}")
    return violations


def test_no_raw_pathname_writes_in_executor_reachable_modules() -> None:
    violations: list[str] = []
    for name in SCANNED_FILES:
        allowed = ALLOWED_SITES.get(name, ())
        text = (SRC / name).read_text(encoding="utf-8")
        violations.extend(f"{name}:{entry}" for entry in find_violations(text, allowed=allowed))
    assert not violations, (
        "raw pathname writes outside the allowlist (anchor them to a pinned "
        "dirfd via run_isolation.write_*_at_exclusive, or justify an allowlist "
        "entry):\n" + "\n".join(violations)
    )


@pytest.mark.parametrize(
    "bad_line",
    [
        "path.write_text(content, encoding='utf-8')",
        "path.write_bytes(data)",
        'open(p, "w")',
        'open(p, "a")',
        'open(p, "x")',
        'open(p, "r+")',
        'open(p, "wb")',
        'os.fdopen(fd, "w", encoding="utf-8")',
        "os.write(fd, data)",
        "shutil.copy(src, dst)",
        "shutil.copyfile(src, dst)",
        "os.replace(src, dst)",
    ],
)
def test_scanner_flags_write_spellings(bad_line: str) -> None:
    assert find_violations(bad_line + "\n"), bad_line


@pytest.mark.parametrize(
    "ok_line",
    [
        "os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)",
        "open(p, encoding='utf-8')",
        'os.fdopen(fd, encoding="utf-8")',
        "handle.write(text)",
        'write_text_at_exclusive(artifacts_fd, "stdout.log", text)',
        "os.unlink(name, dir_fd=dir_fd)",
    ],
)
def test_scanner_ignores_read_fd_and_anchored_spellings(ok_line: str) -> None:
    assert not find_violations(ok_line + "\n"), ok_line
