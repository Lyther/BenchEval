"""SEC1.2 RED contracts: the CyberMetric-500 model-only comparison lane.

SUBSTITUTE_JUSTIFICATION
- substitute: an eight-question dataset in the pinned CyberMetric record schema;
  a scripted ``CybermetricRequestRunner`` returning fixed response texts (or,
  stalled, nothing but its own deadline; or the text only after its allowance);
  and a loopback HTTP server on 127.0.0.1 speaking the chat-completions
  envelope, holding each reply for a scripted delay, splitting it from its
  headers, or trickling its body
- replaces: the Apache-2.0 CyberMetric-500 snapshot's 500 questions, and charged
  chat-completion calls to the two candidate models on the ByteLLM gateway
- necessity: the attempt loop's discriminating outcomes -- a wrong parseable
  answer, five unparseable answers, a transport failure on a given attempt, a
  reply that lands only after the confirmed wall envelope -- must be forced
  deterministically, one at a time, without a provider; the scoring,
  eligibility and one-row-per-question rules do not depend on which 500
  questions are asked; and the wire contract of the production transport
  (destination, payload, credential header, decoding, one request per failure,
  the deadline) is only observable from the far end of a socket this module owns
- real-option: none before SEC1.3. The dataset schema, the content-id rule, the
  pinned prompt/parser oracle, the provider launch resolver, the binding
  snapshot and its endpoint guard, the planner, the executor, the evidence
  model and the comparison validator are all the real ones; the two
  attribution files are the real pinned bytes
- proof-limit: proves protocol fidelity, eligibility classification, retention,
  binding to the confirmed API name and endpoint, the local transport boundary
  and comparison qualification only; it proves nothing about either model's
  security knowledge, ByteLLM's request compatibility, service availability or
  cost
- real-proof: SEC1.3's separately authorized live lifecycle on the pinned snapshot
- covered tests: every test in this module

Specification: ``docs/context/cybermetric-spec.md`` (written RED first; the
implementation and three review rounds that followed are recorded there).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import HfDatasetSnapshotIdentity, load_benchmark_catalog
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.cybermetric_adapter import (
    ANSWER_PATTERN,
    ATTRIBUTION_PINS,
    CACHE_ROOT_ENV,
    CYBERMETRIC_ADAPTER_ID,
    CYBERMETRIC_BENCHMARK_ID,
    CYBERMETRIC_HARNESS_KIND,
    CYBERMETRIC_SLICE_ID,
    DATASET_CARD_FILE,
    DATASET_FILE,
    DATASET_PIN,
    EVALUATOR_SHA256,
    INSTANCE_ID_PREFIX,
    LICENSE_FILE,
    MAX_ATTEMPTS,
    PROTOCOL_ID,
    ChatRequest,
    ChatResponse,
    CybermetricDataset,
    CybermetricDeadlineError,
    CybermetricQuestion,
    CybermetricTransportError,
    build_chat_request,
    cybermetric_benchmark_identity,
    cybermetric_cache_dir,
    cybermetric_harness_version,
    cybermetric_instance_id,
    default_request_runner,
    evaluate_question,
    parse_answer,
    run_cybermetric_slice,
    verify_attribution_files,
    verify_cybermetric_dataset,
)
from bencheval.doctor import run_plan_doctor
from bencheval.domain import RunPlan, RunPlanInstance
from bencheval.evidence import (
    INFRASTRUCTURE_FAILURE_CLASSES,
    EvidenceRecord,
    eligible_for_pass_at_k,
)
from bencheval.exceptions import BenchEvalError
from bencheval.model_compare import assess_model_comparison_validity, is_model_comparison_evidence
from bencheval.paths import repo_root, validate_config_bundle
from bencheval.provenance_gates import is_captured_harness_version, is_provisional_benchmark_version
from bencheval.provider_registry import OpenAICompatibleLaunch, resolve_openai_compatible_launch
from bencheval.slice_manifest import load_slice_manifest, slice_instance_ids, slices_for_benchmark

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cybermetric"
_BASELINE_MODEL = "gpt-5.2-2025-12-11"
_CANDIDATE_MODEL = "glm-5.2"
# A shipped registry row on the same route whose vendor API name is not its logical id:
# the one case where sending the id instead of the confirmed name is observable.
_FC_MODEL = "gpt-5.2-2025-12-11-FC"
_FC_API_MODEL = "gpt-5.2-2025-12-11"
_CREDENTIAL = "test-credential-placeholder"
# The bytellm profile's default public endpoint, and one it was never confirmed on.
_DEFAULT_ENDPOINT = "http://127.0.0.1:4000/v1"
_DRIFTED_ENDPOINT = "http://127.0.0.1:9/v1"
_FIXTURE_SLICE_ID = "cybermetric-fixture-8"
_SERVED_MODEL = "loopback/gpt-5.2"
_USAGE = {"prompt_tokens": 41, "completion_tokens": 4, "total_tokens": 45}

# Reviewed pins, written here independently of the module so a drifted constant fails.
_PINNED_REPO = "tihanyin/CyberMetric"
_PINNED_REVISION = "32759c2fa90274706219e1cf946cadff93da52e3"
_PINNED_DATASET_SHA256 = "sha256:036747c989da9f38f39a6b33fa2d5ab14147c928df0274217bbecab20be88faa"
_PINNED_EVALUATOR_SHA256 = "sha256:d73642a3684c2a59a4fe45982e971c4043b3ae4d468334203b929ea2987d8597"
# The pinned evaluator's own regex, copied verbatim from ``CyberMetric_evaluator.py``.
_UPSTREAM_ANSWER_RE = re.compile(r"ANSWER:?\s*([A-D])", re.IGNORECASE)

# Eight synthetic questions in the pinned schema. None is CyberMetric content.
_SYNTHETIC: tuple[dict[str, object], ...] = (
    {
        "question": "Which layer of the fictional Sentinel stack signs audit frames?",
        "answers": {"A": "Relay", "B": "Ledger", "C": "Portal", "D": "Cache"},
        "solution": "B",
    },
    {
        "question": "What does the Sentinel rotate-key command require first?",
        "answers": {"A": "A quorum token", "B": "A reboot", "C": "A DNS change", "D": "Nothing"},
        "solution": "A",
    },
    {
        "question": "Which Sentinel mode disables outbound relay traffic?",
        "answers": {"A": "Open", "B": "Mirror", "C": "Sealed", "D": "Drift"},
        "solution": "C",
    },
    {
        "question": "How many verifier nodes does a Sentinel cell need to attest?",
        "answers": {"A": "One", "B": "Two", "C": "Five", "D": "Three"},
        "solution": "D",
    },
    {
        "question": "Which Sentinel artifact records a revoked capability?",
        "answers": {
            "A": "The tombstone list",
            "B": "The relay log",
            "C": "The cache",
            "D": "Nothing",
        },
        "solution": "A",
    },
    {
        "question": "What is the Sentinel default for an unsigned frame?",
        "answers": {"A": "Accept", "B": "Drop", "C": "Queue", "D": "Mirror"},
        "solution": "B",
    },
    {
        "question": "Which Sentinel role may approve a ledger fork?",
        "answers": {"A": "Reader", "B": "Relay", "C": "Warden", "D": "Cache"},
        "solution": "C",
    },
    {
        "question": "When does a Sentinel session token expire by default?",
        "answers": {"A": "Never", "B": "At reboot", "C": "Hourly", "D": "At cell rotation"},
        "solution": "D",
    },
)


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class _Snapshot:
    """A synthetic dataset laid out exactly as the pinned cache directory is."""

    def __init__(self, cache_root: Path, records: Sequence[Mapping[str, object]] = _SYNTHETIC):
        self.cache_root = cache_root
        self.dir = cache_root / _PINNED_REVISION
        self.dir.mkdir(parents=True)
        self.dataset_path = self.dir / DATASET_FILE
        self.dataset_path.write_text(
            json.dumps({"questions": list(records)}, indent=2) + "\n", encoding="utf-8"
        )
        self.sha256 = _sha256(self.dataset_path.read_bytes())
        shutil.copy2(_FIXTURES / "README.md", self.dir / DATASET_CARD_FILE)
        shutil.copy2(_FIXTURES / "LICENSE-2.0.txt", self.dir / LICENSE_FILE)
        self.identity = HfDatasetSnapshotIdentity(
            kind="hf-dataset-snapshot",
            repo=_PINNED_REPO,
            revision=_PINNED_REVISION,
            files={DATASET_FILE: self.sha256},
        )

    def dataset(self) -> CybermetricDataset:
        return verify_cybermetric_dataset(self.dataset_path, identity=self.identity)

    def attribution(self) -> Mapping[str, Path]:
        return verify_attribution_files(self.dir)


class _ScriptedRunner:
    """Returns each question's scripted responses in order; records every request
    and the launch it was asked to use."""

    def __init__(self, scripts: Mapping[str, Sequence[str | Exception]] | None = None) -> None:
        self.scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self.requests: list[ChatRequest] = []
        self.launches: list[OpenAICompatibleLaunch] = []
        self.timeouts: list[float] = []
        self.default: list[str | Exception] = []

    def __call__(
        self, request: ChatRequest, *, launch: OpenAICompatibleLaunch, timeout_sec: float
    ) -> ChatResponse:
        self.requests.append(request)
        self.launches.append(launch)
        self.timeouts.append(timeout_sec)
        key = _question_key(request)
        queue = self.scripts.get(key, self.default)
        if not queue:
            raise AssertionError(f"no scripted response left for {key!r}: the loop over-asked")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResponse(
            content=item,
            served_model=request.model,
            usage={
                "prompt_tokens": 10 + len(item) % 7,
                "completion_tokens": 5,
                "total_tokens": 15 + len(item) % 7,
            },
            latency_sec=0.25,
            raw={"choices": [{"message": {"content": item}}], "model": request.model},
        )


class _LateRunner(_ScriptedRunner):
    """A far end whose scripted text arrives only after the allowance it was given."""

    def __call__(
        self, request: ChatRequest, *, launch: OpenAICompatibleLaunch, timeout_sec: float
    ) -> ChatResponse:
        time.sleep(timeout_sec + 0.05)
        return super().__call__(request, launch=launch, timeout_sec=timeout_sec)


class _StalledRunner(_ScriptedRunner):
    """A far end that never answers: only the transport's own deadline ever returns,
    and a real transport's deadline fires at or after its allowance, never before."""

    def __call__(
        self, request: ChatRequest, *, launch: OpenAICompatibleLaunch, timeout_sec: float
    ) -> ChatResponse:
        self.requests.append(request)
        self.launches.append(launch)
        self.timeouts.append(timeout_sec)
        time.sleep(timeout_sec + 0.05)
        raise CybermetricDeadlineError(f"no response within the {timeout_sec:.3f}s allowance")


def _question_key(request: ChatRequest) -> str:
    """The question text is the only stable handle a runner has on a request."""
    user = next(m["content"] for m in request.messages if m["role"] == "user")
    return user.split("\nOptions:", 1)[0].removeprefix("Question: ")


def _launch() -> OpenAICompatibleLaunch:
    return resolve_openai_compatible_launch("bytellm", environ={"BYTELLM_API_KEY": _CREDENTIAL})


def _q(index: int, dataset: CybermetricDataset) -> CybermetricQuestion:
    return dataset.questions[index]


# --- a loopback chat-completions endpoint: the far end of the production transport --------


@dataclass(frozen=True, slots=True)
class _Reply:
    status: int
    body: bytes
    stall: threading.Event | None = None
    delay_sec: float = 0.0  # before the status line
    body_delay_sec: float = 0.0  # between the headers and the body
    chunk_delay_sec: float = 0.0  # before every ``chunk_size`` bytes of the body
    chunk_size: int = 0
    close_delimited: bool = False  # no Content-Length: the body ends with the connection


def _completion(content: str, *, served_model: str = _SERVED_MODEL) -> _Reply:
    payload = {
        "id": "chatcmpl-loopback",
        "object": "chat.completion",
        "model": served_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": dict(_USAGE),
    }
    return _Reply(HTTPStatus.OK, json.dumps(payload).encode("utf-8"))


class _ChatServer(ThreadingHTTPServer):
    """Records every exchange and when it arrived; answers from a scripted queue first,
    then from the fixture's answer key -- after ``misses_before_answer`` unparseable
    replies per question, each reply held for ``delay_sec``. It never retries anything
    on the caller's behalf."""

    def __init__(
        self,
        answers: Mapping[str, str] | None = None,
        *,
        misses_before_answer: int = 0,
        delay_sec: float = 0.0,
        reply_shape: Mapping[str, float | int] | None = None,
    ) -> None:
        super().__init__(("127.0.0.1", 0), _ChatHandler)
        self.answers = dict(answers or {})
        self.misses_before_answer = misses_before_answer
        self.delay_sec = delay_sec
        self.reply_shape = dict(reply_shape or {})
        self.replies: list[_Reply] = []
        self.requests: list[tuple[str, dict[str, str], bytes]] = []
        self.request_times: list[float] = []
        self.asked: dict[str, int] = {}
        self.lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/v1"

    def exchange(self, path: str, headers: dict[str, str], body: bytes) -> _Reply:
        with self.lock:
            self.requests.append((path, headers, body))
            self.request_times.append(time.monotonic())
            if self.replies:
                return self.replies.pop(0)
        try:
            sent = json.loads(body)
            user = next(m["content"] for m in sent["messages"] if m["role"] == "user")
        except (ValueError, KeyError, TypeError, StopIteration):
            return _Reply(HTTPStatus.BAD_REQUEST, b'{"error":"not a chat request"}')
        key = user.split("\nOptions:", 1)[0].removeprefix("Question: ")
        letter = self.answers.get(key)
        if letter is None:
            return _Reply(HTTPStatus.BAD_REQUEST, b'{"error":"unknown question"}')
        with self.lock:
            self.asked[key] = asked = self.asked.get(key, 0) + 1
        content = "ANSWER: X" if asked <= self.misses_before_answer else f"ANSWER: {letter}"
        return replace(_completion(content), delay_sec=self.delay_sec, **self.reply_shape)


class _ChatHandler(BaseHTTPRequestHandler):
    server: _ChatServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length", "0")))
        headers = {key.lower(): value for key, value in self.headers.items()}
        reply = self.server.exchange(self.path, headers, body)
        if reply.delay_sec:
            time.sleep(reply.delay_sec)
        if reply.stall is not None:
            reply.stall.wait(timeout=10)
        try:
            self.send_response(reply.status)
            self.send_header("content-type", "application/json")
            if not reply.close_delimited:
                self.send_header("content-length", str(len(reply.body)))
            self.end_headers()
            if reply.body_delay_sec:
                time.sleep(reply.body_delay_sec)
            if reply.chunk_delay_sec and reply.chunk_size:
                for offset in range(0, len(reply.body), reply.chunk_size):
                    time.sleep(reply.chunk_delay_sec)
                    self.wfile.write(reply.body[offset : offset + reply.chunk_size])
                    self.wfile.flush()
            else:
                self.wfile.write(reply.body)
        except OSError:
            return  # the client gave up first: the deadline case


@contextmanager
def _serving(server: _ChatServer) -> Iterator[_ChatServer]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _loopback_launch(server: _ChatServer) -> OpenAICompatibleLaunch:
    return resolve_openai_compatible_launch(
        "bytellm", environ={"BYTELLM_API_KEY": _CREDENTIAL, "BYTELLM_BASE_URL": server.endpoint}
    )


def _wire_request() -> ChatRequest:
    """One request in the pinned shape, built by hand: only the transport is under test."""
    return ChatRequest(
        model=_FC_API_MODEL,
        messages=(
            {"role": "system", "content": "You are a security expert who answers questions."},
            {
                "role": "user",
                "content": (
                    "Question: Which Sentinel mode disables outbound relay traffic?\n"
                    "Options: A) Open, B) Mirror, C) Sealed, D) Drift\n\n"
                    "Choose the correct answer (A, B, C, or D) only. "
                    "Always return in this format: 'ANSWER: X' "
                ),
            },
        ),
    )


# --- the lane's plans: the unmodified planner over a fixture slice in a copied bundle ------


def _plan(model_id: str, *, diagnostic: bool = True) -> RunPlan:
    """The unmodified planner's plan for the lane over the bundle's fixture slice.

    Nothing about it is edited afterwards: the binding snapshot, the instances
    and every label are what a ``bencheval run`` of that slice would confirm.
    ``_bundle`` must have been applied first.
    """
    return plan_control_plane(
        benchmark_id=CYBERMETRIC_BENCHMARK_ID,
        slice_id=_FIXTURE_SLICE_ID,
        runtime_id=None,
        model_id=model_id,
        diagnostic=diagnostic,
    )


def _bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: _Snapshot,
    dataset: CybermetricDataset,
    *,
    executable: bool = False,
    instance_ids: Sequence[str] | None = None,
    wall_sec_per_instance: int = 60,
) -> Path:
    """A copied config bundle whose only deltas are this snapshot's digest, the
    admission flag, and a fixture slice naming the eight content ids (or the given
    subset) under the given per-instance wall."""
    ids = (
        list(instance_ids)
        if instance_ids is not None
        else [q.instance_id for q in dataset.questions]
    )
    bundle = tmp_path / "bundle"
    shutil.copytree(repo_root() / "config", bundle / "config")
    catalog_path = bundle / "config" / "benchmarks.yaml"
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    rows = [b for b in raw["benchmarks"] if b["id"] == CYBERMETRIC_BENCHMARK_ID]
    assert rows, f"catalog has no {CYBERMETRIC_BENCHMARK_ID!r} row yet"
    rows[0]["identity"]["files"] = {DATASET_FILE: snapshot.sha256}
    rows[0]["executable"] = executable
    catalog_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    fixture_slice = {
        "schema_version": "0.1",
        "slice": {
            "id": _FIXTURE_SLICE_ID,
            "benchmark_id": CYBERMETRIC_BENCHMARK_ID,
            "purpose": "model_comparison",
            "selection_policy": "fixed_instance_ids",
            "instances": ids,
            "valid_for": ["model_comparison"],
            "invalid_for": ["benchmark_native_claim"],
        },
        "budget": {
            "max_instances": len(ids),
            "max_wall_clock_sec_per_instance": wall_sec_per_instance,
            "max_total_cost_usd": 1,
        },
        "labels": {"contamination_warning": False, "public_benchmark": True},
    }
    (bundle / "config" / "slices" / f"{_FIXTURE_SLICE_ID}.yaml").write_text(
        yaml.safe_dump(fixture_slice, sort_keys=False), encoding="utf-8"
    )
    validate_config_bundle(bundle)
    monkeypatch.setenv("BENCHEVAL_HOME", str(bundle))
    monkeypatch.setenv(CACHE_ROOT_ENV, str(snapshot.cache_root))
    monkeypatch.setenv("BYTELLM_API_KEY", _CREDENTIAL)
    # The confirmed endpoint is the profile default unless a contract overrides it.
    monkeypatch.delenv("BYTELLM_BASE_URL", raising=False)
    return bundle


def _rows(path: Path) -> list[EvidenceRecord]:
    return [
        EvidenceRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _execute(
    tmp_path: Path, plan: RunPlan, runner: _ScriptedRunner, *, name: str
) -> tuple[list[EvidenceRecord], Path]:
    evidence = tmp_path / f"{name}.jsonl"
    artifacts = tmp_path / f"{name}-artifacts"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=artifacts,
        cybermetric_request_runner=runner,
        run_id=f"run-{name}",
    )
    return _rows(evidence), artifacts


def _all_correct(dataset: CybermetricDataset) -> _ScriptedRunner:
    return _ScriptedRunner({q.question: [f"ANSWER: {q.solution}"] for q in dataset.questions})


# --- identity pins: guards over reviewed data (expected GREEN) --------------------------


def test_the_pins_are_the_reviewed_licensed_snapshot_and_evaluator() -> None:
    """SEC1.1's reviewed identity, restated here so a drifted constant is caught."""
    assert DATASET_PIN.repo == _PINNED_REPO
    assert DATASET_PIN.revision == _PINNED_REVISION
    assert DATASET_PIN.files == {DATASET_FILE: _PINNED_DATASET_SHA256}
    assert EVALUATOR_SHA256 == _PINNED_EVALUATOR_SHA256
    assert PROTOCOL_ID == "cybermetric-evaluator-v1"
    assert MAX_ATTEMPTS == 5
    assert ANSWER_PATTERN.pattern == _UPSTREAM_ANSWER_RE.pattern
    assert ANSWER_PATTERN.flags & re.IGNORECASE


def test_the_attribution_fixtures_are_the_pinned_bytes() -> None:
    """The retained card and license are the real files, not stand-ins."""
    for name, pin in ATTRIBUTION_PINS.items():
        assert _sha256((_FIXTURES / name).read_bytes()) == pin
    assert (
        (_FIXTURES / LICENSE_FILE)
        .read_text(encoding="utf-8")
        .lstrip()
        .startswith("Apache License\n")
    )


# --- 1. dataset identity and content-derived ids -----------------------------------------


def test_verify_dataset_accepts_pinned_bytes_and_binds_content_ids(tmp_path: Path) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    assert dataset.sha256 == snap.sha256
    assert dataset.identity == snap.identity
    assert len(dataset.questions) == len(_SYNTHETIC)
    ids = [q.instance_id for q in dataset.questions]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(rf"{INSTANCE_ID_PREFIX}[0-9a-f]{{16}}", i) for i in ids)
    again = snap.dataset()
    assert [q.instance_id for q in again.questions] == ids


def test_verify_dataset_refuses_a_digest_mismatch_before_reading_records(tmp_path: Path) -> None:
    snap = _Snapshot(tmp_path / "cache")
    raw = snap.dataset_path.read_bytes()
    snap.dataset_path.write_bytes(raw.replace(b'"solution": "B"', b'"solution": "C"', 1))
    with pytest.raises(BenchEvalError, match="sha256"):
        snap.dataset()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.pop("solution"),
        lambda r: r["answers"].pop("D"),
        lambda r: r.__setitem__("solution", "E"),
        lambda r: r["answers"].__setitem__("E", "A fifth option"),
    ],
    ids=["no-solution", "three-options", "solution-outside-choices", "five-options"],
)
def test_verify_dataset_refuses_a_record_outside_the_pinned_schema(tmp_path: Path, mutate) -> None:
    records = [json.loads(json.dumps(r)) for r in _SYNTHETIC]
    mutate(records[3])
    snap = _Snapshot(tmp_path / "cache", records)
    with pytest.raises(BenchEvalError):
        snap.dataset()


def test_verify_dataset_refuses_duplicate_question_text(tmp_path: Path) -> None:
    records = [json.loads(json.dumps(r)) for r in _SYNTHETIC]
    records[5]["question"] = records[2]["question"]
    snap = _Snapshot(tmp_path / "cache", records)
    with pytest.raises(BenchEvalError, match="duplicate"):
        snap.dataset()


def test_instance_id_is_the_record_content_not_its_position(tmp_path: Path) -> None:
    """Reordering the file keeps every id; editing one option changes exactly one."""
    forward = _Snapshot(tmp_path / "f").dataset()
    reversed_records = list(reversed(_SYNTHETIC))
    backward = _Snapshot(tmp_path / "b", reversed_records).dataset()
    assert {q.instance_id for q in forward.questions} == {q.instance_id for q in backward.questions}
    assert [q.instance_id for q in forward.questions] != [q.instance_id for q in backward.questions]

    edited = [json.loads(json.dumps(r)) for r in _SYNTHETIC]
    edited[4]["answers"]["C"] = "The relay log (rotated)"
    changed = _Snapshot(tmp_path / "c", edited).dataset()
    before = [q.instance_id for q in forward.questions]
    after = [q.instance_id for q in changed.questions]
    assert sum(a != b for a, b in zip(before, after, strict=True)) == 1
    assert before[4] != after[4]

    r = _SYNTHETIC[0]
    direct = cybermetric_instance_id(str(r["question"]), r["answers"], str(r["solution"]))  # type: ignore[arg-type]
    assert direct == before[0]


def test_cache_dir_is_keyed_by_the_pinned_revision(tmp_path: Path) -> None:
    assert cybermetric_cache_dir(cache_root=tmp_path) == tmp_path / DATASET_PIN.revision


def test_attribution_files_are_verified_by_digest(tmp_path: Path) -> None:
    snap = _Snapshot(tmp_path / "cache")
    found = snap.attribution()
    assert set(found) == {DATASET_CARD_FILE, LICENSE_FILE}
    (snap.dir / LICENSE_FILE).write_text("MIT License\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match=LICENSE_FILE):
        snap.attribution()


def test_identity_strings_are_captured_not_provisional() -> None:
    benchmark_version = cybermetric_benchmark_identity()
    assert benchmark_version == (
        f"{CYBERMETRIC_BENCHMARK_ID}@{_PINNED_REVISION[:16]}"
        f"+data-{_PINNED_DATASET_SHA256.removeprefix('sha256:')[:16]}"
    )
    assert not is_provisional_benchmark_version(benchmark_version)
    harness_version = cybermetric_harness_version()
    assert (
        harness_version == f"{PROTOCOL_ID}@{_PINNED_EVALUATOR_SHA256.removeprefix('sha256:')[:16]}"
    )
    assert is_captured_harness_version(harness_version)


# --- 2. protocol fidelity: the pinned evaluator is the oracle -----------------------------


def test_chat_request_is_the_pinned_evaluator_prompt_verbatim(tmp_path: Path) -> None:
    """Both strings are copied from ``CyberMetric_evaluator.py`` at the pinned digest,
    including the trailing space after ``'ANSWER: X'``."""
    q = _q(0, _Snapshot(tmp_path / "cache").dataset())
    request = build_chat_request("gpt-5.2-2025-12-11", q)
    assert request.model == "gpt-5.2-2025-12-11"
    assert request.parameters == {}
    assert request.messages == (
        {"role": "system", "content": "You are a security expert who answers questions."},
        {
            "role": "user",
            "content": (
                "Question: Which layer of the fictional Sentinel stack signs audit frames?\n"
                "Options: A) Relay, B) Ledger, C) Portal, D) Cache\n\n"
                "Choose the correct answer (A, B, C, or D) only. "
                "Always return in this format: 'ANSWER: X' "
            ),
        },
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ANSWER: B", "B"),
        ("answer: c", "C"),
        ("ANSWER:D", "D"),
        ("Sure.\n\nANSWER:   a\n", "A"),
        ("ANSWER: A ... on reflection ANSWER: B", "A"),
        ("The ANSWER is D", None),
        ("ANSWER: E", None),
        ("B", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_answer_is_the_pinned_regex(text: str | None, expected: str | None) -> None:
    assert parse_answer(text) == expected
    if text:
        match = _UPSTREAM_ANSWER_RE.search(text)
        assert (match.group(1).upper() if match else None) == expected


# --- 3. the attempt loop: first parseable wins, misses stay in the denominator ------------


def test_a_correct_first_answer_uses_exactly_one_attempt(tmp_path: Path) -> None:
    dataset = _Snapshot(tmp_path / "cache").dataset()
    q = _q(0, dataset)
    runner = _ScriptedRunner({q.question: ["ANSWER: B", "ANSWER: A"]})
    out = evaluate_question(q, api_model="m", launch=_launch(), runner=runner, timeout_sec=30)
    assert out.instance_id == q.instance_id
    assert len(out.attempts) == 1 and len(runner.requests) == 1
    assert out.final_answer == "B" and out.primary_pass is True
    assert out.failure_class is None and out.counts_toward_pass_at_k is True


def test_the_first_parseable_answer_ends_the_attempts_even_when_wrong(tmp_path: Path) -> None:
    """The upstream loop returns the first *parseable* letter, correct or not.
    A third scripted response -- the correct one -- must never be requested."""
    dataset = _Snapshot(tmp_path / "cache").dataset()
    q = _q(1, dataset)  # solution A
    runner = _ScriptedRunner({q.question: ["Let me think.", "ANSWER: C", "ANSWER: A"]})
    out = evaluate_question(q, api_model="m", launch=_launch(), runner=runner, timeout_sec=30)
    assert len(out.attempts) == 2 and len(runner.requests) == 2
    assert [a.parsed_answer for a in out.attempts] == [None, "C"]
    assert out.final_answer == "C" and out.primary_pass is False
    assert out.failure_class == "model_wrong_solution"
    assert out.counts_toward_pass_at_k is True


def test_five_unparseable_responses_are_an_eligible_invalid_output(tmp_path: Path) -> None:
    dataset = _Snapshot(tmp_path / "cache").dataset()
    q = _q(2, dataset)
    runner = _ScriptedRunner({q.question: ["no letter"] * 5 + ["ANSWER: C"]})
    out = evaluate_question(q, api_model="m", launch=_launch(), runner=runner, timeout_sec=30)
    assert len(out.attempts) == 5 and len(runner.requests) == 5
    assert out.final_answer is None and out.primary_pass is False
    assert out.failure_class == "model_output_invalid"
    assert out.counts_toward_pass_at_k is True
    assert out.failure_class not in INFRASTRUCTURE_FAILURE_CLASSES


def test_a_transport_failure_is_ineligible_and_never_silently_retried(tmp_path: Path) -> None:
    """The upstream loop swallows exceptions inside its five-attempt budget; the
    named deviation is that BenchEval classifies them and stops."""
    dataset = _Snapshot(tmp_path / "cache").dataset()
    q = _q(3, dataset)
    runner = _ScriptedRunner(
        {q.question: ["not a letter", CybermetricTransportError("HTTP 502"), "ANSWER: D"]}
    )
    out = evaluate_question(q, api_model="m", launch=_launch(), runner=runner, timeout_sec=30)
    assert len(runner.requests) == 2
    assert len(out.attempts) == 2
    assert out.attempts[1].transport_error is not None and "502" in out.attempts[1].transport_error
    assert out.final_answer is None and out.primary_pass is False
    assert out.failure_class == "remote_infra_failure"
    assert out.counts_toward_pass_at_k is False


def test_a_response_completed_after_the_allowance_is_retained_but_never_scored(
    tmp_path: Path,
) -> None:
    """Review SEC12-IMPL-F001, second round: whatever letter a late response carries, it
    is budget evidence -- retained with its usage in the attempt record, never the
    question's answer, never eligible."""
    dataset = _Snapshot(tmp_path / "cache").dataset()
    question = _q(0, dataset)
    runner = _LateRunner({question.question: [f"ANSWER: {question.solution}"]})
    outcome = evaluate_question(
        question, api_model=_BASELINE_MODEL, launch=_launch(), runner=runner, timeout_sec=0.3
    )
    assert outcome.failure_class == "runtime_budget_exceeded"
    assert outcome.primary_pass is False and outcome.counts_toward_pass_at_k is False
    assert outcome.final_answer is None and outcome.native_score["answer"] is None
    assert len(outcome.attempts) == 1 and len(runner.requests) == 1
    (attempt,) = outcome.attempts
    assert attempt.response_content == f"ANSWER: {question.solution}"
    assert attempt.parsed_answer == question.solution
    assert attempt.transport_error and "after the allowance" in attempt.transport_error
    assert outcome.token_usage["total_tokens"] == attempt.usage["total_tokens"] > 0
    assert outcome.adapter_metadata["parsed_attempt"] == "none"
    assert outcome.adapter_metadata["wall_envelope_exhausted"] == "per_instance"


def test_usage_and_latency_are_summed_over_every_attempt(tmp_path: Path) -> None:
    dataset = _Snapshot(tmp_path / "cache").dataset()
    q = _q(4, dataset)
    runner = _ScriptedRunner({q.question: ["x", "y", "ANSWER: A"]})
    out = evaluate_question(q, api_model="m", launch=_launch(), runner=runner, timeout_sec=30)
    expected_prompt = sum(a.usage["prompt_tokens"] for a in out.attempts)
    assert len(out.attempts) == 3
    assert out.token_usage["prompt_tokens"] == expected_prompt
    assert out.token_usage["completion_tokens"] == 15
    assert out.token_usage["total_tokens"] == expected_prompt + 15
    assert out.latency_sec == pytest.approx(0.75)
    assert out.cost_usd == 0.0
    assert out.adapter_metadata["reported_cost_usd"] == "unavailable"


def test_every_attempt_resends_the_same_parameterless_request(tmp_path: Path) -> None:
    dataset = _Snapshot(tmp_path / "cache").dataset()
    q = _q(5, dataset)
    runner = _ScriptedRunner({q.question: ["?", "??", "ANSWER: B"]})
    evaluate_question(q, api_model="m", launch=_launch(), runner=runner, timeout_sec=30)
    assert len({json.dumps(r.messages, sort_keys=True) for r in runner.requests}) == 1
    assert all(r.parameters == {} for r in runner.requests)
    assert all(r.model == "m" for r in runner.requests)


def test_the_served_model_is_retained_on_every_attempt(tmp_path: Path) -> None:
    dataset = _Snapshot(tmp_path / "cache").dataset()
    q = _q(6, dataset)
    runner = _ScriptedRunner({q.question: ["...", "ANSWER: C"]})
    out = evaluate_question(q, api_model="m", launch=_launch(), runner=runner, timeout_sec=30)
    assert [a.served_model for a in out.attempts] == ["m", "m"]
    assert out.adapter_metadata["served_model"] == "m"
    assert out.adapter_metadata["attempts"] == "2"
    assert out.adapter_metadata["protocol_id"] == PROTOCOL_ID
    assert out.adapter_metadata["evaluator_sha256"] == _PINNED_EVALUATOR_SHA256


# --- 4. the transport: the production runner against a loopback endpoint -----------------


def test_default_transport_decodes_a_close_delimited_reply_inside_the_allowance() -> None:
    """The within-budget control for the close-delimited cutoff contract: a body that
    ends with the connection, not a Content-Length, decodes normally."""
    with _serving(_ChatServer()) as server:
        server.replies.append(replace(_completion("ANSWER: C"), close_delimited=True))
        response = default_request_runner(
            _wire_request(), launch=_loopback_launch(server), timeout_sec=5
        )
    assert response.content == "ANSWER: C" and response.served_model == _SERVED_MODEL
    assert len(server.requests) == 1


def test_default_transport_posts_the_exact_request_to_the_confirmed_endpoint() -> None:
    """One JSON POST to ``<base_url>/chat/completions`` carrying the bearer credential,
    the API model and the messages -- nothing else -- and the envelope decoded as sent,
    the served model read from the response rather than echoed from the request."""
    request = _wire_request()
    with _serving(_ChatServer()) as server:
        server.replies.append(_completion("ANSWER: C", served_model="gateway/gpt-5.2"))
        response = default_request_runner(request, launch=_loopback_launch(server), timeout_sec=5)
    ((path, headers, body),) = server.requests
    assert path == "/v1/chat/completions"
    assert headers["authorization"] == f"Bearer {_CREDENTIAL}"
    assert headers["content-type"].split(";")[0].strip() == "application/json"
    assert json.loads(body) == {
        "model": _FC_API_MODEL,
        "messages": [dict(m) for m in request.messages],
    }
    assert response.content == "ANSWER: C"
    assert response.served_model == "gateway/gpt-5.2"
    assert dict(response.usage) == _USAGE
    assert response.latency_sec > 0
    assert response.raw["choices"][0]["message"]["content"] == "ANSWER: C"
    assert _CREDENTIAL not in json.dumps(response.raw)


@pytest.mark.parametrize("mode", ["http-502", "bad-envelope", "timeout"])
def test_default_transport_turns_one_failed_exchange_into_a_transport_error(mode: str) -> None:
    """A failed exchange is one typed error after exactly one request -- no hidden
    retry -- and the credential never appears in the error text."""
    stall = threading.Event()
    reply = {
        "http-502": _Reply(HTTPStatus.BAD_GATEWAY, b'{"error":"bad gateway"}'),
        "bad-envelope": _Reply(HTTPStatus.OK, b'{"object":"list","data":[]}'),
        # A *valid* envelope, delayed past the deadline (review SEC12-N001): a transport
        # that ignored the deadline would return it and fail the expected-error assertion.
        "timeout": _Reply(HTTPStatus.OK, _completion("ANSWER: C").body, stall=stall),
    }[mode]
    with _serving(_ChatServer()) as server:
        server.replies.append(reply)
        try:
            with pytest.raises(CybermetricTransportError) as caught:
                default_request_runner(
                    _wire_request(), launch=_loopback_launch(server), timeout_sec=1
                )
        finally:
            stall.set()
    assert len(server.requests) == 1
    if mode == "http-502":
        assert "502" in str(caught.value)
    if mode == "timeout":
        # The envelope ended the exchange, not the far end: the typed subtype the
        # attempt loop turns into a budget failure (review SEC12-IMPL-F001).
        assert isinstance(caught.value, CybermetricDeadlineError)
    assert _CREDENTIAL not in str(caught.value)


# --- 5. the slice run: one outcome per planned instance, bound to the confirmed route -----


def test_run_slice_yields_one_outcome_per_planned_instance_in_plan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    runner = _all_correct(dataset)
    runner.scripts[dataset.questions[1].question] = ["hmm", "hmm", "ANSWER: A"]
    outcomes = run_cybermetric_slice(
        plan=plan,
        artifacts_dir=tmp_path / "run",
        dataset=dataset,
        attribution=snap.attribution(),
        request_runner=runner,
        timeout_sec=30,
    )
    assert [o.instance_id for o in outcomes] == [i.instance_id for i in plan.instances]
    assert len(runner.requests) == len(plan.instances) + 2
    assert sum(len(o.attempts) for o in outcomes) == len(plan.instances) + 2


def test_run_slice_retains_attempts_and_attribution_under_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    runner = _all_correct(dataset)
    runner.scripts[dataset.questions[2].question] = ["nope", "ANSWER: C"]
    run_dir = tmp_path / "run"
    outcomes = run_cybermetric_slice(
        plan=plan,
        artifacts_dir=run_dir,
        dataset=dataset,
        attribution=snap.attribution(),
        request_runner=runner,
        timeout_sec=30,
    )
    for outcome in outcomes:
        attempts_file = run_dir / "cybermetric" / "attempts" / f"{outcome.instance_id}.json"
        assert attempts_file.is_file()
        retained = json.loads(attempts_file.read_text(encoding="utf-8"))
        assert [a["attempt_number"] for a in retained] == list(range(1, len(outcome.attempts) + 1))
        assert [a["response_content"] for a in retained] == [
            a.response_content for a in outcome.attempts
        ]
        assert f"cybermetric/attempts/{outcome.instance_id}.json" in outcome.artifact_paths
    for name, pin in ATTRIBUTION_PINS.items():
        assert _sha256((run_dir / "cybermetric" / name).read_bytes()) == pin
        assert all(f"cybermetric/{name}" in o.artifact_paths for o in outcomes)


def test_run_slice_refuses_a_plan_whose_instances_are_not_the_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    foreign = plan.model_copy(
        update={
            "instances": (
                *plan.instances[:-1],
                RunPlanInstance(instance_id="cybermetric-0000000000000000"),
            )
        }
    )
    with pytest.raises(BenchEvalError, match="cybermetric-0000000000000000"):
        run_cybermetric_slice(
            plan=foreign,
            artifacts_dir=tmp_path / "run",
            dataset=dataset,
            attribution=snap.attribution(),
            request_runner=_all_correct(dataset),
            timeout_sec=30,
        )


def test_run_slice_sends_the_confirmed_api_model_to_the_confirmed_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The logical id names the row; every request carries the snapshot's vendor API
    name and the launch it is handed is the snapshot's route. A run that discarded the
    snapshot would send the logical id."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_FC_MODEL)
    snapshot = plan.model_binding_snapshot
    assert snapshot is not None
    assert snapshot.api_model == _FC_API_MODEL != plan.model_id
    runner = _all_correct(dataset)
    run_cybermetric_slice(
        plan=plan,
        artifacts_dir=tmp_path / "run",
        dataset=dataset,
        attribution=snap.attribution(),
        request_runner=runner,
        timeout_sec=30,
    )
    assert len(runner.requests) == len(dataset.questions)
    assert {r.model for r in runner.requests} == {_FC_API_MODEL}
    assert {(launch.provider_id, launch.base_url) for launch in runner.launches} == {
        ("bytellm", snapshot.base_url)
    }


def test_run_slice_refuses_an_endpoint_changed_after_planning_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The snapshot froze the public endpoint at confirmation; an override that changed
    since is a silent substitution, refused by the existing binding guard with nothing
    sent and nothing written."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    assert plan.model_binding_snapshot is not None
    assert plan.model_binding_snapshot.base_url == _DEFAULT_ENDPOINT
    monkeypatch.setenv("BYTELLM_BASE_URL", _DRIFTED_ENDPOINT)
    runner = _all_correct(dataset)
    with pytest.raises(BenchEvalError, match="re-plan before launching"):
        run_cybermetric_slice(
            plan=plan,
            artifacts_dir=tmp_path / "run",
            dataset=dataset,
            attribution=snap.attribution(),
            request_runner=runner,
            timeout_sec=30,
        )
    assert runner.requests == [] and runner.launches == []
    assert not (tmp_path / "run").exists()


def test_run_slice_stops_launching_when_the_run_envelope_is_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review SEC12-IMPL-F001. The run-total wall is one absolute deadline over the whole
    slice: a question that starts inside it is given only what remains, and a question
    it has no room left for is a budget failure with no request at all -- the far end
    never answers here, so only the deadline ever returns."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    questions = dataset.questions[:3]
    _bundle(
        tmp_path,
        monkeypatch,
        snap,
        dataset,
        instance_ids=[q.instance_id for q in questions],
        wall_sec_per_instance=1,
    )
    plan = _plan(_BASELINE_MODEL)
    runner = _StalledRunner()
    outcomes = run_cybermetric_slice(
        plan=plan,
        artifacts_dir=tmp_path / "run",
        dataset=dataset,
        attribution=snap.attribution(),
        request_runner=runner,
        timeout_sec=plan.max_wall_clock_sec_per_instance,
        run_wall_sec=1.5,
    )
    assert [o.instance_id for o in outcomes] == [q.instance_id for q in questions]
    assert [o.failure_class for o in outcomes] == ["runtime_budget_exceeded"] * 3
    assert not any(o.primary_pass or o.counts_toward_pass_at_k for o in outcomes)
    assert len(runner.requests) == 2  # the third question was never asked
    first, second, third = outcomes
    assert [o.adapter_metadata["attempts"] for o in outcomes] == ["1", "1", "0"]
    assert first.adapter_metadata["wall_envelope_exhausted"] == "per_instance"
    assert second.adapter_metadata["wall_envelope_exhausted"] == "run_total"
    assert third.adapter_metadata["wall_envelope_exhausted"] == "run_total"
    assert runner.timeouts[0] == pytest.approx(1.0, abs=0.01)  # the whole per-question wall
    assert 0 < runner.timeouts[1] < 1.0  # only what the run had left
    assert first.attempts[0].transport_error and "allowance" in first.attempts[0].transport_error
    assert third.attempts == () and third.latency_sec == 0.0 and third.final_answer is None
    attempts_dir = tmp_path / "run" / "cybermetric" / "attempts"
    assert json.loads((attempts_dir / f"{third.instance_id}.json").read_text()) == []
    assert {o.adapter_metadata["max_wall_clock_sec"] for o in outcomes} == {"1.5"}
    assert {o.adapter_metadata["max_wall_clock_sec_per_instance"] for o in outcomes} == {"1"}


# --- 6. catalog, slice, planner and doctor registration ------------------------------------


def test_catalog_row_is_a_pinned_non_executable_cybersecurity_benchmark() -> None:
    entry = load_benchmark_catalog().by_id_or_alias(CYBERMETRIC_BENCHMARK_ID)
    assert entry.id == CYBERMETRIC_BENCHMARK_ID
    assert entry.adapter_id == CYBERMETRIC_ADAPTER_ID
    assert entry.executable is False
    assert entry.category == "cybersecurity"
    assert entry.task_count == 500
    assert entry.public_indexed is True
    assert entry.identity == DATASET_PIN
    assert entry.default_slice == CYBERMETRIC_SLICE_ID


def test_slice_pins_all_500_content_ids_for_model_comparison() -> None:
    manifests = slices_for_benchmark(CYBERMETRIC_BENCHMARK_ID)
    by_id = {m.slice.id: m for m in manifests}
    assert CYBERMETRIC_SLICE_ID in by_id
    manifest = by_id[CYBERMETRIC_SLICE_ID]
    assert manifest.slice.selection_policy == "fixed_instance_ids"
    assert manifest.slice.purpose == "model_comparison"
    assert "model_comparison" in manifest.slice.valid_for
    assert "benchmark_native_claim" in manifest.slice.invalid_for
    path = next(
        p for p in _slice_paths() if load_slice_manifest(p).slice.id == CYBERMETRIC_SLICE_ID
    )
    ids = slice_instance_ids(manifest, path)
    assert len(ids) == 500 and len(set(ids)) == 500
    assert all(re.fullmatch(rf"{INSTANCE_ID_PREFIX}[0-9a-f]{{16}}", i) for i in ids)


def _slice_paths() -> list[Path]:
    from bencheval.slice_manifest import default_slices_dir, list_slice_manifest_paths

    return list(list_slice_manifest_paths(str(default_slices_dir())))


def test_slice_ids_are_derived_from_the_pinned_dataset_when_it_is_on_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host-asset case: runs where the licensed snapshot has been fetched into the cache."""
    import os

    cache_root = os.environ.get(CACHE_ROOT_ENV)
    dataset_path = (
        cybermetric_cache_dir(cache_root=Path(cache_root)) / DATASET_FILE if cache_root else None
    )
    if dataset_path is None or not dataset_path.is_file():
        pytest.skip(f"pinned CyberMetric-500 snapshot not present under {CACHE_ROOT_ENV}")
    dataset = verify_cybermetric_dataset(dataset_path)
    manifest = next(
        m
        for m in slices_for_benchmark(CYBERMETRIC_BENCHMARK_ID)
        if m.slice.id == CYBERMETRIC_SLICE_ID
    )
    path = next(
        p for p in _slice_paths() if load_slice_manifest(p).slice.id == CYBERMETRIC_SLICE_ID
    )
    assert set(slice_instance_ids(manifest, path)) == {q.instance_id for q in dataset.questions}


def test_the_real_planner_produces_the_lane_model_only() -> None:
    plan = plan_control_plane(
        benchmark_id=CYBERMETRIC_BENCHMARK_ID,
        slice_id=CYBERMETRIC_SLICE_ID,
        runtime_id=None,
        model_id=_BASELINE_MODEL,
        diagnostic=True,
    )
    assert plan.adapter_id == CYBERMETRIC_ADAPTER_ID
    assert plan.harness_kind == CYBERMETRIC_HARNESS_KIND
    assert plan.runtime_id is None and plan.agent_id is None
    assert plan.comparison_validity == "model_comparison"
    assert len(plan.instances) == 500
    assert plan.model_binding_snapshot is not None
    assert plan.model_binding_snapshot.provider_id == "bytellm"


@pytest.mark.parametrize("scaffold", [{"runtime_id": "claude-code"}, {"agent_id": "terminus-2"}])
def test_the_planner_refuses_a_runtime_or_agent_for_the_model_only_lane(scaffold) -> None:
    """Refused *because* the lane is model-only -- an unknown-benchmark refusal is not this."""
    with pytest.raises(BenchEvalError, match=r"model-only|does not support harness"):
        plan_control_plane(
            benchmark_id=CYBERMETRIC_BENCHMARK_ID,
            slice_id=CYBERMETRIC_SLICE_ID,
            runtime_id=scaffold.get("runtime_id"),
            agent_id=scaffold.get("agent_id"),
            model_id=_BASELINE_MODEL,
            diagnostic=True,
        )


def test_plan_doctor_fails_closed_without_the_pinned_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    assert run_plan_doctor(plan).ok is True

    monkeypatch.setenv(CACHE_ROOT_ENV, str(tmp_path / "empty-cache"))
    report = run_plan_doctor(plan)
    assert report.ok is False
    failed = {c.name for c in report.checks if c.status == "fail"}
    assert "cybermetric_dataset" in failed

    monkeypatch.setenv(CACHE_ROOT_ENV, str(snap.cache_root))
    monkeypatch.delenv("BYTELLM_API_KEY")
    report = run_plan_doctor(plan)
    assert report.ok is False
    assert "provider_credentials" in {c.name for c in report.checks if c.status == "fail"}


# --- 7. executor: one row per question, honest labels, comparison qualification --------


def test_execute_writes_one_scored_row_per_question_with_honest_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    runner = _all_correct(dataset)
    runner.scripts[dataset.questions[0].question] = ["no", "no", "no", "no", "no"]
    runner.scripts[dataset.questions[1].question] = ["ANSWER: D"]  # solution A: wrong
    runner.scripts[dataset.questions[2].question] = ["?", "ANSWER: C"]
    rows, artifacts = _execute(tmp_path, plan, runner, name="baseline")

    assert len(rows) == len(dataset.questions)
    assert [r.task_id for r in rows] == [q.instance_id for q in dataset.questions]
    assert (
        sum(
            len(
                json.loads(
                    (artifacts / "cybermetric" / "attempts" / f"{r.task_id}.json").read_text()
                )
            )
            for r in rows
        )
        == len(rows) + 5
    )
    by_id = {r.task_id: r for r in rows}
    invalid = by_id[dataset.questions[0].instance_id]
    wrong = by_id[dataset.questions[1].instance_id]
    late = by_id[dataset.questions[2].instance_id]
    assert invalid.primary_pass is False and invalid.failure_class == "model_output_invalid"
    assert eligible_for_pass_at_k(invalid) is True
    assert wrong.primary_pass is False and wrong.failure_class == "model_wrong_solution"
    assert late.primary_pass is True and late.failure_class is None
    assert sum(r.primary_pass for r in rows) == len(rows) - 2

    for row in rows:
        assert row.adapter_id == CYBERMETRIC_ADAPTER_ID
        assert row.harness_kind == CYBERMETRIC_HARNESS_KIND
        assert row.harness_version == cybermetric_harness_version()
        assert row.benchmark_version == cybermetric_benchmark_identity(snap.identity)
        assert row.interpretation_label == "diagnostic"
        assert row.verifier_integrity_label != "native" and row.verifier_log_path is None
        assert row.cost_usd == 0.0 and row.adapter_metadata["reported_cost_usd"] == "unavailable"
        assert row.token_usage is not None and row.token_usage["total_tokens"] > 0
        assert row.provider_id == "bytellm" and row.provider_config_hash
        assert row.runtime_id is None and row.agent_id is None
        assert f"cybermetric/attempts/{row.task_id}.json" in row.artifact_paths
        assert f"cybermetric/{LICENSE_FILE}" in row.artifact_paths
        assert f"cybermetric/{DATASET_CARD_FILE}" in row.artifact_paths


def test_execute_marks_a_transport_failure_ineligible_without_retrying_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    runner = _all_correct(dataset)
    victim = dataset.questions[3].question
    runner.scripts[victim] = [CybermetricTransportError("connection reset"), "ANSWER: D"]
    rows, _ = _execute(tmp_path, plan, runner, name="infra")
    row = next(r for r in rows if r.task_id == dataset.questions[3].instance_id)
    assert row.failure_class == "remote_infra_failure"
    assert eligible_for_pass_at_k(row) is False
    assert len(runner.scripts[victim]) == 1  # the correct answer was never requested
    assert len(rows) == len(dataset.questions)


def test_execute_sends_the_confirmed_api_model_and_rows_carry_the_logical_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the executor: requests carry the snapshot's API name on the snapshot's
    route, rows carry the logical id and the binding digest that confirmed them."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_FC_MODEL)
    snapshot = plan.model_binding_snapshot
    assert snapshot is not None
    assert snapshot.api_model == _FC_API_MODEL != plan.model_id
    runner = _all_correct(dataset)
    rows, _ = _execute(tmp_path, plan, runner, name="fc")
    assert {r.model for r in runner.requests} == {_FC_API_MODEL}
    assert {(launch.provider_id, launch.base_url) for launch in runner.launches} == {
        (plan.provider_id, snapshot.base_url)
    }
    assert {r.model_id for r in rows} == {_FC_MODEL}
    assert {r.adapter_metadata["model_binding_sha256"] for r in rows} == {snapshot.sha256}


def test_execute_refuses_an_endpoint_changed_after_planning_without_reserving_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The existing endpoint guard runs before any output is reserved: no request, no
    evidence file, no artifacts tree."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL)
    assert plan.model_binding_snapshot is not None
    assert plan.model_binding_snapshot.base_url == _DEFAULT_ENDPOINT
    monkeypatch.setenv("BYTELLM_BASE_URL", _DRIFTED_ENDPOINT)
    runner = _all_correct(dataset)
    evidence = tmp_path / "drift.jsonl"
    artifacts = tmp_path / "drift-artifacts"
    with pytest.raises(BenchEvalError, match="re-plan before launching"):
        execute_control_plane_run(
            plan=plan,
            output_path=evidence,
            artifacts_dir=artifacts,
            cybermetric_request_runner=runner,
        )
    assert runner.requests == [] and runner.launches == []
    assert not evidence.exists() and not artifacts.exists()


def test_execute_without_an_injected_runner_uses_the_production_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no runner injected, every question reaches the confirmed loopback endpoint
    as one bearer-authenticated JSON POST of model and messages, the rows are scored
    from the server's answers, the served identity is retained as the server named it,
    and no retained byte -- evidence, plan, attempts -- carries the credential."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    with _serving(_ChatServer({q.question: q.solution for q in dataset.questions})) as server:
        monkeypatch.setenv("BYTELLM_BASE_URL", server.endpoint)
        plan = _plan(_BASELINE_MODEL)
        assert plan.model_binding_snapshot is not None
        assert plan.model_binding_snapshot.base_url == server.endpoint
        server.replies.append(_completion("ANSWER: X"))  # one unparseable first reply
        evidence = tmp_path / "wire.jsonl"
        artifacts = tmp_path / "wire-artifacts"
        execute_control_plane_run(
            plan=plan, output_path=evidence, artifacts_dir=artifacts, run_id="run-wire"
        )
    rows = _rows(evidence)
    assert len(rows) == len(dataset.questions)
    assert len(server.requests) == len(dataset.questions) + 1
    assert {path for path, _, _ in server.requests} == {"/v1/chat/completions"}
    assert {headers["authorization"] for _, headers, _ in server.requests} == {
        f"Bearer {_CREDENTIAL}"
    }
    assert all(set(json.loads(body)) == {"model", "messages"} for _, _, body in server.requests)
    assert {json.loads(body)["model"] for _, _, body in server.requests} == {_BASELINE_MODEL}
    assert all(r.primary_pass for r in rows)
    assert {r.adapter_metadata["served_model"] for r in rows} == {_SERVED_MODEL}
    retained = [evidence, *(p for p in artifacts.rglob("*") if p.is_file())]
    assert all(_CREDENTIAL.encode("utf-8") not in p.read_bytes() for p in retained)


def test_execute_enforces_the_confirmed_wall_envelope_through_the_production_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review SEC12-IMPL-F001, through the real planner, doctor, executor and transport:
    the plan's per-instance wall is one absolute deadline over a question's attempts
    and its run-total wall one over the run. A far end whose fifth reply -- the answer
    -- could only land after the envelope yields ineligible budget rows, never passes,
    every request starts inside the run's deadline, and the run ends with it."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    questions = dataset.questions[:2]
    _bundle(
        tmp_path,
        monkeypatch,
        snap,
        dataset,
        instance_ids=[q.instance_id for q in questions],
        wall_sec_per_instance=1,
    )
    # Four misses and then the answer, each held 0.6 s: the answer needs 3 s per question.
    server = _ChatServer(
        {q.question: q.solution for q in questions},
        misses_before_answer=MAX_ATTEMPTS - 1,
        delay_sec=0.6,
    )
    with _serving(server):
        monkeypatch.setenv("BYTELLM_BASE_URL", server.endpoint)
        plan = _plan(_BASELINE_MODEL)
        assert (plan.max_wall_clock_sec_per_instance, plan.max_wall_clock_sec) == (1, 2)
        evidence = tmp_path / "wall.jsonl"
        artifacts = tmp_path / "wall-artifacts"
        started = time.monotonic()
        summary = execute_control_plane_run(
            plan=plan, output_path=evidence, artifacts_dir=artifacts, run_id="run-wall"
        )
        elapsed = time.monotonic() - started
    rows = _rows(evidence)
    assert [r.task_id for r in rows] == [q.instance_id for q in questions]
    assert summary.passed_count == 0 and not any(r.primary_pass for r in rows)
    assert {r.failure_class for r in rows} == {"runtime_budget_exceeded"}
    assert all(eligible_for_pass_at_k(r) is False for r in rows)
    assert all(t - started <= plan.max_wall_clock_sec for t in server.request_times)
    assert elapsed < plan.max_wall_clock_sec + 1.0
    assert all(1 <= int(r.adapter_metadata["attempts"]) < MAX_ATTEMPTS for r in rows)
    assert {r.adapter_metadata["wall_envelope_exhausted"] for r in rows} <= {
        "per_instance",
        "run_total",
    }
    assert {r.adapter_metadata["max_wall_clock_sec"] for r in rows} == {"2"}
    for row in rows:
        attempts = json.loads(
            (artifacts / "cybermetric" / "attempts" / f"{row.task_id}.json").read_text()
        )
        assert len(attempts) == int(row.adapter_metadata["attempts"])
        assert attempts[-1]["transport_error"] and "allowance" in attempts[-1]["transport_error"]
        assert _CREDENTIAL not in json.dumps(attempts)


@pytest.mark.parametrize(
    ("shape", "delay_sec"),
    [
        # Status line after 0.6 s, body 0.9 s later: every wait is inside the wall,
        # the exchange is not.
        pytest.param({"body_delay_sec": 0.9}, 0.6, id="split-response"),
        # A valid body delivered 16 bytes every 0.4 s: progress on every wait.
        pytest.param({"chunk_delay_sec": 0.4, "chunk_size": 16}, 0.0, id="trickled-body"),
        # No Content-Length: the cutoff is a normal EOF, not an exception (round 3).
        pytest.param(
            {"body_delay_sec": 0.9, "close_delimited": True}, 0.6, id="close-delimited-body"
        ),
    ],
)
def test_execute_bounds_the_whole_exchange_by_the_confirmed_wall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: dict[str, float | int], delay_sec: float
) -> None:
    """Review SEC12-IMPL-F001, second round, through the real planner, doctor, executor
    and transport: the wall bounds the complete exchange, not each wait in it. A far
    end that keeps making progress past the deadline is cut off at the deadline, the
    run ends with it, and the correct answer it was sending never becomes a pass."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    question = dataset.questions[0]
    _bundle(
        tmp_path,
        monkeypatch,
        snap,
        dataset,
        instance_ids=[question.instance_id],
        wall_sec_per_instance=1,
    )
    server = _ChatServer(
        {question.question: question.solution}, delay_sec=delay_sec, reply_shape=shape
    )
    with _serving(server):
        monkeypatch.setenv("BYTELLM_BASE_URL", server.endpoint)
        plan = _plan(_BASELINE_MODEL)
        assert (plan.max_wall_clock_sec_per_instance, plan.max_wall_clock_sec) == (1, 1)
        evidence = tmp_path / "exchange.jsonl"
        artifacts = tmp_path / "exchange-artifacts"
        started = time.monotonic()
        summary = execute_control_plane_run(
            plan=plan, output_path=evidence, artifacts_dir=artifacts, run_id="run-exchange"
        )
        elapsed = time.monotonic() - started
    (row,) = _rows(evidence)
    assert summary.passed_count == 0 and row.primary_pass is False
    assert row.failure_class == "runtime_budget_exceeded"
    assert eligible_for_pass_at_k(row) is False
    assert row.adapter_metadata["wall_envelope_exhausted"] != "none"
    assert elapsed < plan.max_wall_clock_sec + 0.4
    assert len(server.requests) == 1 and row.adapter_metadata["attempts"] == "1"
    (attempt,) = json.loads(
        (artifacts / "cybermetric" / "attempts" / f"{row.task_id}.json").read_text()
    )
    assert attempt["response_content"] is None and attempt["parsed_answer"] is None
    assert attempt["transport_error"] and "allowance" in attempt["transport_error"]


def test_execute_refuses_an_agent_for_the_model_only_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    plan = _plan(_BASELINE_MODEL).model_copy(update={"agent_id": "terminus-2"})
    with pytest.raises(BenchEvalError, match="model-only"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "agent.jsonl",
            artifacts_dir=tmp_path / "agent-artifacts",
            cybermetric_request_runner=_all_correct(dataset),
        )


def test_execute_refuses_a_non_diagnostic_run_while_the_row_is_not_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset, executable=False)
    plan = _plan(_BASELINE_MODEL, diagnostic=False)
    with pytest.raises(BenchEvalError, match="diagnostic"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "plain.jsonl",
            artifacts_dir=tmp_path / "plain-artifacts",
            cybermetric_request_runner=_all_correct(dataset),
        )


def test_diagnostic_rows_never_qualify_as_a_model_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ranking comes out of a non-admitted lane, however clean the two runs are."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset)
    baseline, _ = _execute(tmp_path, _plan(_BASELINE_MODEL), _all_correct(dataset), name="a")
    current, _ = _execute(tmp_path, _plan(_CANDIDATE_MODEL), _all_correct(dataset), name="b")
    verdict = assess_model_comparison_validity(baseline, current)
    assert verdict.valid is False
    assert any("interpretation_label" in reason for reason in verdict.reasons)


def test_admitted_runs_on_one_route_qualify_as_a_model_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bundle's only further delta is ``executable: true`` -- the post-admission path."""
    snap = _Snapshot(tmp_path / "cache")
    dataset = snap.dataset()
    _bundle(tmp_path, monkeypatch, snap, dataset, executable=True)
    baseline, _ = _execute(
        tmp_path, _plan(_BASELINE_MODEL, diagnostic=False), _all_correct(dataset), name="a"
    )
    runner = _all_correct(dataset)
    runner.scripts[dataset.questions[7].question] = ["ANSWER: A"]  # solution D: one miss
    current, _ = _execute(tmp_path, _plan(_CANDIDATE_MODEL, diagnostic=False), runner, name="b")
    assert is_model_comparison_evidence(baseline, current) is True
    verdict = assess_model_comparison_validity(baseline, current)
    assert verdict.valid is True, verdict.reasons
    assert (verdict.baseline_model_id, verdict.current_model_id) == (
        _BASELINE_MODEL,
        _CANDIDATE_MODEL,
    )
    assert {r.provider_config_hash for r in baseline + current} != {None}
    assert len({r.provider_config_hash for r in baseline + current}) == 1
