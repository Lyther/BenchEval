"""CyberMetric-500 model-only adapter (roadmap SEC1.2; ``docs/context/cybermetric-spec.md``).

Pinned data below is reviewed identity (SEC1.1). The evaluation protocol is the
pinned upstream evaluator's prompt, parser and first-parseable-of-five attempt
rule, reimplemented verbatim -- never a fork of that script, never a native
verifier claim. The adapter makes the chat-completion requests itself: one
stdlib JSON POST per attempt to the confirmed endpoint, behind an injectable
``CybermetricRequestRunner`` at exactly that boundary.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Protocol

from bencheval.access_evidence import EffectiveAccessEvidence, model_only_access
from bencheval.benchmark_registry import HfDatasetSnapshotIdentity, load_benchmark_catalog
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.identity_strings import combined_data_sha256
from bencheval.model_binding import require_snapshot_endpoint
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.provider_registry import OpenAICompatibleLaunch, resolve_openai_compatible_launch
from bencheval.run_isolation import (
    dir_identity_error,
    open_owned_dir_fd,
    write_bytes_at_exclusive,
    write_text_at_exclusive,
)

CYBERMETRIC_ADAPTER_ID = "cybermetric"
CYBERMETRIC_BENCHMARK_ID = "cybermetric-500"
CYBERMETRIC_HARNESS_KIND = "cybermetric-native"
CYBERMETRIC_SLICE_ID = "cybermetric-500-v1"

# --- the population of record: the first author's Apache-2.0 snapshot -----------------
DATASET_REPO = "tihanyin/CyberMetric"
DATASET_REVISION = "32759c2fa90274706219e1cf946cadff93da52e3"
DATASET_FILE = "CyberMetric-500-v1.json"
DATASET_SHA256 = "sha256:036747c989da9f38f39a6b33fa2d5ab14147c928df0274217bbecab20be88faa"
DATASET_PIN = HfDatasetSnapshotIdentity(
    kind="hf-dataset-snapshot",
    repo=DATASET_REPO,
    revision=DATASET_REVISION,
    files={DATASET_FILE: DATASET_SHA256},
)
# Retained next to every run's evidence so redistribution carries its terms.
DATASET_CARD_FILE = "README.md"
LICENSE_FILE = "LICENSE-2.0.txt"
ATTRIBUTION_PINS: Mapping[str, str] = {
    DATASET_CARD_FILE: "sha256:a63f0b572f5355f88950153b1ffe6052f67ac32314e4cdfbb19c54880d964539",
    LICENSE_FILE: "sha256:cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
}

# --- the evaluation protocol: the pinned executable upstream evaluator ----------------
PROTOCOL_ID = "cybermetric-evaluator-v1"
EVALUATOR_SOURCE_REPO = "https://github.com/cybermetric/CyberMetric"
EVALUATOR_SOURCE_COMMIT = "294662b03be73a9c7c73918f687882c1ba637c47"
EVALUATOR_FILE = "CyberMetric_evaluator.py"
EVALUATOR_SHA256 = "sha256:d73642a3684c2a59a4fe45982e971c4043b3ae4d468334203b929ea2987d8597"
SYSTEM_PROMPT = "You are a security expert who answers questions."
USER_PROMPT = (
    "Question: {question}\nOptions: {options}\n\n"
    "Choose the correct answer (A, B, C, or D) only. Always return in this format: 'ANSWER: X' "
)
OPTION_JOIN = ", "
ANSWER_PATTERN = re.compile(r"ANSWER:?\s*([A-D])", re.IGNORECASE)
MAX_ATTEMPTS = 5
CHOICES: tuple[str, ...] = ("A", "B", "C", "D")

INSTANCE_ID_PREFIX = "cybermetric-"
INSTANCE_ID_HEX = 16

# Outcome classes. The first two keep the row in the denominator; the last two never do.
WRONG_ANSWER_LABEL: FailureLabel = "model_wrong_solution"
INVALID_OUTPUT_LABEL: FailureLabel = "model_output_invalid"
TRANSPORT_FAILURE_LABEL: FailureLabel = "remote_infra_failure"
# The confirmed wall envelope ended the question (the same label the aggregate
# harnesses stamp when their deadline fires), never the far end.
BUDGET_FAILURE_LABEL: FailureLabel = "runtime_budget_exceeded"

CACHE_ROOT_ENV = "BENCHEVAL_CYBERMETRIC_CACHE"

# Run-relative retention: ``cybermetric/attempts/<id>.json`` plus the two attribution files.
ARTIFACT_DIR = "cybermetric"
ATTEMPTS_DIR = "attempts"
# The OpenAI-compatible chat endpoint under the launch's ``<base_url>`` (already ``/v1``).
WIRE_PATH = "/chat/completions"
_SHORT_HEX = 16
_TOKEN_KEYS: tuple[str, ...] = ("prompt_tokens", "completion_tokens", "total_tokens")


@dataclass(frozen=True, slots=True)
class CybermetricQuestion:
    instance_id: str
    question: str
    answers: Mapping[str, str]
    solution: str


@dataclass(frozen=True, slots=True)
class CybermetricDataset:
    path: Path
    sha256: str
    identity: HfDatasetSnapshotIdentity
    questions: tuple[CybermetricQuestion, ...]


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """One chat-completion request, exactly as sent: the protocol sends no parameters."""

    model: str
    messages: tuple[Mapping[str, str], ...]
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatResponse:
    content: str | None
    served_model: str | None
    usage: Mapping[str, int]
    latency_sec: float
    raw: Mapping[str, object]


class CybermetricTransportError(BenchEvalError):
    """A request never produced a model answer: HTTP, network, timeout, or bad envelope."""


class CybermetricDeadlineError(CybermetricTransportError):
    """The request did not complete inside the allowance it was given: the confirmed
    wall envelope ended it, not the far end."""


class CybermetricRequestRunner(Protocol):
    def __call__(
        self,
        request: ChatRequest,
        *,
        launch: OpenAICompatibleLaunch,
        timeout_sec: float,
    ) -> ChatResponse: ...


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_number: int
    request_sha256: str
    response_content: str | None
    parsed_answer: str | None
    served_model: str | None
    usage: Mapping[str, int]
    latency_sec: float
    transport_error: str | None = None


@dataclass(frozen=True, slots=True)
class CybermetricInstanceOutcome:
    instance_id: str
    attempts: tuple[AttemptRecord, ...]
    final_answer: str | None
    primary_pass: bool
    failure_class: FailureLabel | None
    token_usage: Mapping[str, int]
    latency_sec: float
    cost_usd: float
    native_score: Mapping[str, object]
    adapter_metadata: Mapping[str, str]
    counts_toward_pass_at_k: bool
    artifact_paths: tuple[str, ...] = ()
    access_evidence: EffectiveAccessEvidence = field(default_factory=model_only_access)


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


# --- identity ----------------------------------------------------------------------------


def cybermetric_instance_id(question: str, answers: Mapping[str, str], solution: str) -> str:
    """Content-derived id: the record is its own identity, its position is not."""
    payload = json.dumps(
        {
            "question": question,
            "answers": {key: answers[key] for key in sorted(answers)},
            "solution": solution,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return INSTANCE_ID_PREFIX + digest[:INSTANCE_ID_HEX]


def cybermetric_cache_dir(
    *, cache_root: Path, identity: HfDatasetSnapshotIdentity = DATASET_PIN
) -> Path:
    return Path(cache_root) / identity.revision


def cybermetric_cache_root(environ: Mapping[str, str] | None = None) -> Path:
    """The host cache named by ``BENCHEVAL_CYBERMETRIC_CACHE``; unset fails closed."""
    source = os.environ if environ is None else environ
    raw = source.get(CACHE_ROOT_ENV, "").strip()
    if not raw:
        raise BenchEvalError(
            f"{CACHE_ROOT_ENV} is not set; it must name the cache holding the pinned "
            f"{DATASET_REPO} snapshot (revision directory with {DATASET_FILE}, "
            f"{DATASET_CARD_FILE} and {LICENSE_FILE})",
        )
    return Path(raw).expanduser()


def _record_error(index: int, message: str) -> BenchEvalError:
    return BenchEvalError(f"{DATASET_FILE} record {index}: {message}")


def _parse_records(raw: bytes) -> tuple[CybermetricQuestion, ...]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise BenchEvalError(f"{DATASET_FILE}: not a UTF-8 JSON document: {e}") from e
    records = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        raise BenchEvalError(f"{DATASET_FILE}: expected a non-empty 'questions' list")
    questions: list[CybermetricQuestion] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != {"question", "answers", "solution"}:
            raise _record_error(index, "not the pinned question/answers/solution schema")
        question, answers, solution = record["question"], record["answers"], record["solution"]
        if not isinstance(question, str) or not question.strip():
            raise _record_error(index, "empty question text")
        if (
            not isinstance(answers, dict)
            or tuple(sorted(answers)) != CHOICES
            or any(not isinstance(value, str) for value in answers.values())
        ):
            raise _record_error(index, "options must be exactly A, B, C and D with text values")
        if solution not in CHOICES:
            raise _record_error(index, f"solution {solution!r} is outside the choices")
        if question in seen:
            raise _record_error(index, "duplicate question text")
        seen.add(question)
        questions.append(
            CybermetricQuestion(
                instance_id=cybermetric_instance_id(question, answers, solution),
                question=question,
                answers={key: answers[key] for key in CHOICES},
                solution=solution,
            )
        )
    return tuple(questions)


def verify_cybermetric_dataset(
    path: Path, *, identity: HfDatasetSnapshotIdentity = DATASET_PIN
) -> CybermetricDataset:
    """Digest-verify the pinned file, then bind every record to its content id."""
    path = Path(path)
    expected = identity.files.get(path.name)
    if expected is None:
        raise BenchEvalError(
            f"{path.name} is not a pinned file of {identity.repo}@{identity.revision[:_SHORT_HEX]}",
        )
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise BenchEvalError(f"cannot read the pinned dataset {path}: {e}") from e
    digest = _sha256(raw)
    if digest != expected:
        raise BenchEvalError(
            f"{path.name}: sha256 {digest} does not match the pinned {expected}; "
            "no record is read from unverified bytes",
        )
    return CybermetricDataset(
        path=path, sha256=digest, identity=identity, questions=_parse_records(raw)
    )


def verify_attribution_files(
    cache_dir: Path, *, pins: Mapping[str, str] = ATTRIBUTION_PINS
) -> Mapping[str, Path]:
    found: dict[str, Path] = {}
    for name, pin in pins.items():
        candidate = Path(cache_dir) / name
        if not candidate.is_file():
            raise BenchEvalError(f"{name}: attribution file missing from {cache_dir}")
        try:
            digest = _sha256(candidate.read_bytes())
        except OSError as e:
            raise BenchEvalError(f"{name}: cannot read attribution file {candidate}: {e}") from e
        if digest != pin:
            raise BenchEvalError(f"{name}: sha256 {digest} does not match the pinned {pin}")
        found[name] = candidate
    return found


def cybermetric_identity_for(
    benchmark_id: str = CYBERMETRIC_BENCHMARK_ID,
) -> HfDatasetSnapshotIdentity:
    """The catalog row's pinned identity -- the bundle in force, never the module constant."""
    entry = load_benchmark_catalog().by_id_or_alias(benchmark_id)
    identity = entry.identity
    if not isinstance(identity, HfDatasetSnapshotIdentity):
        raise BenchEvalError(f"benchmark {entry.id!r} carries no hf-dataset-snapshot identity pin")
    if DATASET_FILE not in identity.files:
        raise BenchEvalError(f"benchmark {entry.id!r} identity does not pin {DATASET_FILE}")
    return identity


def load_pinned_cybermetric_dataset(
    identity: HfDatasetSnapshotIdentity = DATASET_PIN,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[CybermetricDataset, Mapping[str, Path]]:
    """The verified host snapshot and its verified attribution files, or a typed refusal."""
    cache_dir = cybermetric_cache_dir(cache_root=cybermetric_cache_root(environ), identity=identity)
    path = cache_dir / DATASET_FILE
    if not path.is_file():
        raise BenchEvalError(
            f"pinned dataset {DATASET_FILE} is not present under {cache_dir} "
            f"(revision {identity.revision[:_SHORT_HEX]}); place the licensed snapshot there",
        )
    return verify_cybermetric_dataset(path, identity=identity), verify_attribution_files(cache_dir)


def cybermetric_benchmark_identity(identity: HfDatasetSnapshotIdentity = DATASET_PIN) -> str:
    """``cybermetric-500@<short-revision>+data-<short-sha>``, the HLE/SWE shape."""
    return (
        f"{CYBERMETRIC_BENCHMARK_ID}@{identity.revision[:_SHORT_HEX]}"
        f"+data-{combined_data_sha256(identity.files)[:_SHORT_HEX]}"
    )


def cybermetric_harness_version() -> str:
    """``<protocol-id>@<short evaluator sha>``: a captured, source-owned revision."""
    return f"{PROTOCOL_ID}@{EVALUATOR_SHA256.removeprefix('sha256:')[:_SHORT_HEX]}"


# --- the protocol ------------------------------------------------------------------------


def build_chat_request(api_model: str, question: CybermetricQuestion) -> ChatRequest:
    options = OPTION_JOIN.join(f"{key}) {question.answers[key]}" for key in CHOICES)
    return ChatRequest(
        model=api_model,
        messages=(
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT.format(question=question.question, options=options),
            },
        ),
        parameters={},
    )


def parse_answer(text: str | None) -> str | None:
    if not text:
        return None
    match = ANSWER_PATTERN.search(text)
    return match.group(1).upper() if match else None


def _request_sha256(request: ChatRequest) -> str:
    payload = {
        "model": request.model,
        "messages": [dict(message) for message in request.messages],
        "parameters": dict(request.parameters),
    }
    return _sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def _token_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def evaluate_question(
    question: CybermetricQuestion,
    *,
    api_model: str,
    launch: OpenAICompatibleLaunch,
    runner: CybermetricRequestRunner,
    timeout_sec: float,
    run_deadline: float | None = None,
) -> CybermetricInstanceOutcome:
    """The pinned attempt loop: first parseable letter wins, five misses are invalid output.

    The named deviation from upstream: a transport failure ends the loop at once
    and classifies the row as infrastructure, never a silent retry.

    ``timeout_sec`` is the question's whole wall allowance -- one absolute deadline
    over all of its attempts, never reset per attempt -- capped by ``run_deadline``
    (an absolute ``time.monotonic()`` instant) when the run's envelope ends sooner.
    Each request is given only what remains; when nothing remains, no request is
    started and the row is a budget failure (review SEC12-IMPL-F001).
    """
    request = build_chat_request(api_model, question)
    request_sha256 = _request_sha256(request)
    started = time.monotonic()
    deadline = started + timeout_sec
    envelope = "per_instance"
    if run_deadline is not None and run_deadline < deadline:
        deadline, envelope = run_deadline, "run_total"
    attempts: list[AttemptRecord] = []
    usage = dict.fromkeys(_TOKEN_KEYS, 0)
    latency = 0.0
    final: str | None = None
    transport_error: str | None = None
    exhausted = False
    for number in range(1, MAX_ATTEMPTS + 1):
        allowance = deadline - time.monotonic()
        if allowance <= 0:
            exhausted = True
            break
        attempt_started = time.monotonic()
        try:
            response = runner(request, launch=launch, timeout_sec=allowance)
        except CybermetricTransportError as exc:
            elapsed = time.monotonic() - attempt_started
            latency += elapsed
            transport_error = str(exc)
            exhausted = isinstance(exc, CybermetricDeadlineError)
            attempts.append(
                AttemptRecord(
                    attempt_number=number,
                    request_sha256=request_sha256,
                    response_content=None,
                    parsed_answer=None,
                    served_model=None,
                    usage={},
                    latency_sec=elapsed,
                    transport_error=transport_error,
                )
            )
            break
        completed = time.monotonic()
        late = completed >= deadline
        parsed = parse_answer(response.content)
        for key in _TOKEN_KEYS:
            usage[key] += _token_count(response.usage.get(key))
        latency += float(response.latency_sec)
        attempts.append(
            AttemptRecord(
                attempt_number=number,
                request_sha256=request_sha256,
                response_content=response.content,
                parsed_answer=parsed,
                served_model=response.served_model,
                usage=dict(response.usage),
                latency_sec=float(response.latency_sec),
                transport_error=_late_message(completed - deadline) if late else None,
            )
        )
        if late:
            # Retained with its usage, never scored: a response that completed
            # after the envelope is budget evidence whatever letter it carries.
            transport_error = attempts[-1].transport_error
            exhausted = True
            break
        if parsed is not None:
            final = parsed
            break

    failure: FailureLabel | None
    if exhausted:
        failure, counts, passed = BUDGET_FAILURE_LABEL, False, False
    elif transport_error is not None:
        failure, counts, passed = TRANSPORT_FAILURE_LABEL, False, False
    elif final is None:
        failure, counts, passed = INVALID_OUTPUT_LABEL, True, False
    elif final == question.solution:
        failure, counts, passed = None, True, True
    else:
        failure, counts, passed = WRONG_ANSWER_LABEL, True, False
    served = next((a.served_model for a in reversed(attempts) if a.served_model), None)
    parsed_attempt = str(len(attempts)) if final is not None else "none"
    metadata = {
        "protocol_id": PROTOCOL_ID,
        "evaluator_sha256": EVALUATOR_SHA256,
        "harness_version": cybermetric_harness_version(),
        "attempts": str(len(attempts)),
        "parsed_attempt": parsed_attempt,
        "served_model": served or "unreported",
        "request_sha256": request_sha256,
        "request_parameters": json.dumps(dict(request.parameters), sort_keys=True),
        "reported_cost_usd": "unavailable",
        # The allowance this question actually had (the per-instance wall, or less
        # when the run's envelope ended sooner), and which envelope ended it, if any.
        "wall_allowance_sec": f"{deadline - started:.3f}",
        "wall_envelope_exhausted": envelope if exhausted else "none",
    }
    native: dict[str, object] = {
        "answer": final,
        "solution": question.solution,
        "correct": passed,
        "attempts": len(attempts),
        "transport_error": transport_error,
    }
    return CybermetricInstanceOutcome(
        instance_id=question.instance_id,
        attempts=tuple(attempts),
        final_answer=final,
        primary_pass=passed,
        failure_class=failure,
        token_usage=usage,
        latency_sec=latency,
        cost_usd=0.0,
        native_score=native,
        adapter_metadata=metadata,
        counts_toward_pass_at_k=counts,
    )


# --- the transport -----------------------------------------------------------------------


class _Watchdog:
    """The absolute deadline over one exchange. When it expires the socket is shut
    down, so whatever the exchange is blocked on -- connect, send, headers, a body
    still arriving -- fails at once instead of being renewed by each byte of
    progress (review SEC12-IMPL-F001, second round)."""

    def __init__(self, deadline: float) -> None:
        self._sock: socket.socket | None = None
        self.expired = threading.Event()
        self._timer = threading.Timer(max(0.0, deadline - time.monotonic()), self._expire)
        self._timer.daemon = True

    def arm(self, sock: socket.socket | None) -> None:
        # Hold the socket itself: ``http.client`` drops ``conn.sock`` as soon as a
        # will-close response begins, while the response keeps reading from it.
        self._sock = sock

    def _expire(self) -> None:
        self.expired.set()
        sock = self._sock
        if sock is not None:
            try:
                # ``shutdown`` wakes a blocked receive at once (EOF); ``close`` would not.
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # the exchange already closed it

    def __enter__(self) -> _Watchdog:
        self._timer.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._timer.cancel()


def _connection(url: str, *, timeout_sec: float) -> tuple[http.client.HTTPConnection, str]:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            host, parts.port, timeout=timeout_sec, context=ssl.create_default_context()
        )
    elif parts.scheme == "http":
        conn = http.client.HTTPConnection(host, parts.port, timeout=timeout_sec)
    else:
        raise BenchEvalError(f"confirmed endpoint {url!r} is not an http(s) URL")
    return conn, parts.path + (f"?{parts.query}" if parts.query else "")


def wire_payload(request: ChatRequest) -> dict[str, object]:
    """Exactly the request: ``model``, ``messages`` and whatever parameters it carries (none)."""
    return {
        "model": request.model,
        "messages": [dict(message) for message in request.messages],
        **dict(request.parameters),
    }


def _envelope_content(data: object, url: str) -> str | None:
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and "content" in message:
                content = message["content"]
                if content is None or isinstance(content, str):
                    return content
    raise CybermetricTransportError(f"response from {url} is not a chat-completion envelope")


def _deadline_message(url: str, timeout_sec: float) -> str:
    return f"no complete response from {url} within the {max(0.0, timeout_sec):.3f}s allowance"


def _late_message(overrun_sec: float) -> str:
    return f"response completed {overrun_sec:.3f}s after the allowance; retained, not scored"


def _exchange(url: str, body: bytes, headers: Mapping[str, str], *, deadline: float) -> bytes:
    """One POST whose whole exchange is bounded by ``deadline``: the socket's own
    timeout bounds each wait, the watchdog ends the exchange at the deadline however
    much progress it is making. Direct ``http.client``: no proxy resolution and no
    redirect following exist on this path, so nothing stands between BenchEval and
    the confirmed endpoint and nothing can resend the credential elsewhere; any
    status but 200 is a transport failure."""
    allowance = deadline - time.monotonic()
    if allowance <= 0:
        raise CybermetricDeadlineError(_deadline_message(url, allowance))
    conn, path = _connection(url, timeout_sec=allowance)
    try:
        with _Watchdog(deadline) as watchdog:
            try:
                conn.connect()
                watchdog.arm(conn.sock)
                if watchdog.expired.is_set():
                    raise CybermetricDeadlineError(_deadline_message(url, allowance))
                conn.request("POST", path, body=body, headers=dict(headers))
                response = conn.getresponse()
                raw = response.read()
                # A close-delimited body (no Content-Length, no chunking) ends in a
                # normal EOF when the watchdog shuts the socket down: the deadline,
                # not the far end, truncated it (review round 3).
                if watchdog.expired.is_set():
                    raise CybermetricDeadlineError(_deadline_message(url, allowance))
            except (http.client.HTTPException, OSError) as exc:
                if watchdog.expired.is_set() or isinstance(exc, TimeoutError):
                    raise CybermetricDeadlineError(_deadline_message(url, allowance)) from exc
                raise CybermetricTransportError(
                    f"transport failure against {url}: {type(exc).__name__}"
                ) from exc
    finally:
        conn.close()
    if response.status != 200:
        raise CybermetricTransportError(f"HTTP {response.status} from {url}")
    return raw


def default_request_runner(
    request: ChatRequest, *, launch: OpenAICompatibleLaunch, timeout_sec: float
) -> ChatResponse:
    """One stdlib JSON POST to ``<base_url>/chat/completions``: bearer credential from
    the launch, the API model and the messages, nothing else. Any failure -- HTTP
    status, network, deadline, non-chat envelope -- is one ``CybermetricTransportError``
    after that one request; there is no client-side retry, and the credential is
    never logged, retained or echoed in an error. ``timeout_sec`` is the allowance
    the caller has left and bounds the complete exchange, not each wait in it; its
    expiry is the ``CybermetricDeadlineError`` subtype so the loop can tell the
    envelope from the far end."""
    credential = launch.environment.get("OPENAI_API_KEY", "").strip()
    if not credential:
        raise BenchEvalError(
            f"provider {launch.provider_id!r}: the launch carries no credential; "
            "the transport refuses to run without one",
        )
    url = launch.base_url.rstrip("/") + WIRE_PATH
    body = json.dumps(wire_payload(request), ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {credential}",
    }
    started = time.monotonic()
    raw = _exchange(url, body, headers, deadline=started + timeout_sec)
    latency = time.monotonic() - started
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CybermetricTransportError(f"response from {url} is not JSON") from exc
    content = _envelope_content(data, url)
    served = data.get("model")
    reported = data.get("usage")
    usage = (
        {key: value for key, value in reported.items() if _token_count(value) or value == 0}
        if isinstance(reported, dict)
        else {}
    )
    return ChatResponse(
        content=content,
        served_model=served if isinstance(served, str) and served else None,
        usage={key: int(value) for key, value in usage.items() if isinstance(value, int)},
        latency_sec=latency,
        raw=data,
    )


# --- the slice run -----------------------------------------------------------------------


def require_planned_instances(plan: RunPlan, dataset: CybermetricDataset) -> None:
    """Every planned instance must be a record of the verified dataset."""
    known = {question.instance_id for question in dataset.questions}
    missing = [
        validate_control_plane_instance_id(inst.instance_id)
        for inst in plan.instances
        if inst.instance_id not in known
    ]
    if missing:
        raise BenchEvalError(
            f"planned instances are not in the verified dataset {dataset.path.name} "
            f"({dataset.sha256}): {missing}",
        )


def resolve_confirmed_launch(
    plan: RunPlan, *, require_api_key: bool
) -> tuple[OpenAICompatibleLaunch, str]:
    """The launch for the plan's provider on the confirmed endpoint, and the API name
    every request must carry: the snapshot's, never the logical id (CF1)."""
    launch = resolve_openai_compatible_launch(plan.provider_id, require_api_key=require_api_key)
    require_snapshot_endpoint(plan.model_binding_snapshot, base_url=launch.base_url)
    snapshot = plan.model_binding_snapshot
    return launch, (snapshot.api_model if snapshot is not None else plan.model_id)


def run_cybermetric_slice(
    *,
    plan: RunPlan,
    artifacts_dir: Path,
    dataset: CybermetricDataset,
    attribution: Mapping[str, Path],
    request_runner: CybermetricRequestRunner | None = None,
    timeout_sec: float,
    run_wall_sec: float | None = None,
) -> tuple[CybermetricInstanceOutcome, ...]:
    """One outcome per planned instance; attempts and attribution retained under the run.

    Binding happens before anything is sent or written: the launch is resolved
    for the plan's provider, the confirmed endpoint is enforced by the existing
    snapshot guard, and every request carries the snapshot's vendor API name.

    ``timeout_sec`` is each question's absolute wall allowance over its attempts;
    ``run_wall_sec`` is the whole run's, counted from here. A question the run's
    envelope has no room left for is recorded as a budget failure with no request
    (review SEC12-IMPL-F001). Neither wall is derived from the other.
    """
    if plan.adapter_id != CYBERMETRIC_ADAPTER_ID:
        raise BenchEvalError(f"cybermetric adapter cannot run adapter_id={plan.adapter_id!r}")
    require_planned_instances(plan, dataset)
    by_id = {question.instance_id: question for question in dataset.questions}
    launch, api_model = resolve_confirmed_launch(plan, require_api_key=request_runner is None)
    snapshot = plan.model_binding_snapshot
    runner: CybermetricRequestRunner = (
        request_runner if request_runner is not None else default_request_runner
    )
    run_started = time.monotonic()
    run_deadline = None if run_wall_sec is None else run_started + run_wall_sec
    run_metadata = {
        "benchmark_version": cybermetric_benchmark_identity(dataset.identity),
        "dataset_sha256": dataset.sha256,
        "api_model": api_model,
        "provider_base_url": launch.base_url,
        "max_wall_clock_sec_per_instance": f"{timeout_sec:g}",
    }
    if run_wall_sec is not None:
        run_metadata["max_wall_clock_sec"] = f"{run_wall_sec:g}"
    if snapshot is not None:
        run_metadata["model_binding_sha256"] = snapshot.sha256

    root = Path(artifacts_dir) / ARTIFACT_DIR
    attempts_dir = root / ATTEMPTS_DIR
    root_fd = open_owned_dir_fd(root, role="cybermetric artifacts directory")
    attempts_fd: int | None = None
    try:
        attempts_fd = open_owned_dir_fd(attempts_dir, role="cybermetric attempts directory")
        shared: list[str] = []
        for name, source in attribution.items():
            write_bytes_at_exclusive(root_fd, name, Path(source).read_bytes())
            shared.append(f"{ARTIFACT_DIR}/{name}")
        outcomes: list[CybermetricInstanceOutcome] = []
        for inst in plan.instances:
            question = by_id[inst.instance_id]
            outcome = evaluate_question(
                question,
                api_model=api_model,
                launch=launch,
                runner=runner,
                timeout_sec=timeout_sec,
                run_deadline=run_deadline,
            )
            name = f"{question.instance_id}.json"
            write_text_at_exclusive(
                attempts_fd,
                name,
                json.dumps([asdict(attempt) for attempt in outcome.attempts], indent=2) + "\n",
            )
            outcomes.append(
                replace(
                    outcome,
                    adapter_metadata={**outcome.adapter_metadata, **run_metadata},
                    artifact_paths=(f"{ARTIFACT_DIR}/{ATTEMPTS_DIR}/{name}", *shared),
                )
            )
        for fd, path, role in (
            (root_fd, root, "cybermetric artifacts directory"),
            (attempts_fd, attempts_dir, "cybermetric attempts directory"),
        ):
            identity_error = dir_identity_error(fd, path, role=role)
            if identity_error is not None:
                raise AdapterFailureError(identity_error, failure_label="evidence_corrupt")
        return tuple(outcomes)
    finally:
        if attempts_fd is not None:
            os.close(attempts_fd)
        os.close(root_fd)


__all__ = [
    "ANSWER_PATTERN",
    "ARTIFACT_DIR",
    "ATTEMPTS_DIR",
    "ATTRIBUTION_PINS",
    "BUDGET_FAILURE_LABEL",
    "CACHE_ROOT_ENV",
    "CHOICES",
    "CYBERMETRIC_ADAPTER_ID",
    "CYBERMETRIC_BENCHMARK_ID",
    "CYBERMETRIC_HARNESS_KIND",
    "CYBERMETRIC_SLICE_ID",
    "DATASET_CARD_FILE",
    "DATASET_FILE",
    "DATASET_PIN",
    "DATASET_REPO",
    "DATASET_REVISION",
    "DATASET_SHA256",
    "EVALUATOR_FILE",
    "EVALUATOR_SHA256",
    "EVALUATOR_SOURCE_COMMIT",
    "EVALUATOR_SOURCE_REPO",
    "INSTANCE_ID_HEX",
    "INSTANCE_ID_PREFIX",
    "INVALID_OUTPUT_LABEL",
    "LICENSE_FILE",
    "MAX_ATTEMPTS",
    "OPTION_JOIN",
    "PROTOCOL_ID",
    "SYSTEM_PROMPT",
    "TRANSPORT_FAILURE_LABEL",
    "USER_PROMPT",
    "WIRE_PATH",
    "WRONG_ANSWER_LABEL",
    "AttemptRecord",
    "ChatRequest",
    "ChatResponse",
    "CybermetricDataset",
    "CybermetricDeadlineError",
    "CybermetricInstanceOutcome",
    "CybermetricQuestion",
    "CybermetricRequestRunner",
    "CybermetricTransportError",
    "build_chat_request",
    "cybermetric_benchmark_identity",
    "cybermetric_cache_dir",
    "cybermetric_cache_root",
    "cybermetric_harness_version",
    "cybermetric_identity_for",
    "cybermetric_instance_id",
    "default_request_runner",
    "evaluate_question",
    "load_pinned_cybermetric_dataset",
    "parse_answer",
    "require_planned_instances",
    "resolve_confirmed_launch",
    "run_cybermetric_slice",
    "verify_attribution_files",
    "verify_cybermetric_dataset",
    "wire_payload",
]
