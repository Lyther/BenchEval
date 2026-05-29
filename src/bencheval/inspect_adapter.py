"""Inspect AI execution adapter for BenchEval Core-8 E0/E1 tasks."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from bencheval.backends import INSPECT_BACKEND
from bencheval.doctor import inspect_ai_version, require_doctor_ok, run_doctor
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.task_contract import ExecutionProfile

MOCKLLM_MODEL_ID = "mockllm/model"

INSPECT_E0_TASKS: frozenset[str] = frozenset(
    {
        "be-core-t1-single-structured-call",
        "be-core-t2-multi-tool-join",
    },
)
INSPECT_E1_TASKS: frozenset[str] = frozenset(
    {
        "be-core-c1-small-logic-patch",
    },
)
INSPECT_SUPPORTED_TASKS: frozenset[str] = INSPECT_E0_TASKS | INSPECT_E1_TASKS


class InspectAdapterConfig(BaseModel):
    task_id: str
    model_id: str
    execution_profile: ExecutionProfile
    workspace: Path
    reference_artifact_name: str
    artifacts_dir: Path
    sandbox_docker: bool = Field(default=False)


@dataclass(frozen=True, slots=True)
class InspectInvokeResult:
    candidate_path: Path
    cost_usd: float
    latency_sec: float
    adapter_metadata: dict[str, str]


class InspectInvoker(Protocol):
    def __call__(self, config: InspectAdapterConfig) -> InspectInvokeResult: ...


def execution_profile_for_task(task_id: str) -> ExecutionProfile:
    if task_id in INSPECT_E0_TASKS:
        return "E0"
    if task_id in INSPECT_E1_TASKS:
        return "E1"
    raise BenchEvalError(
        f"task {task_id} is not supported for Inspect backend; "
        f"supported: {sorted(INSPECT_SUPPORTED_TASKS)}",
    )


def mockllm_e0_skips_inspect_doctor(*, model_id: str, execution_profile: ExecutionProfile) -> bool:
    return model_id == MOCKLLM_MODEL_ID and execution_profile == "E0"


def _find_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _extract_json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
    if fence_match:
        inner = fence_match.group(1).strip()
        balanced = _find_balanced_json_object(inner)
        stripped = balanced if balanced is not None else inner
    else:
        balanced = _find_balanced_json_object(stripped)
        if balanced is not None:
            stripped = balanced
        elif stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise AdapterFailureError(
            f"model output is not valid JSON: {e}",
            failure_label="model_output_invalid",
        ) from e
    if not isinstance(payload, dict):
        raise AdapterFailureError(
            "model output must be a JSON object",
            failure_label="model_output_invalid",
        )
    return payload


def _build_t1_prompt(workspace: Path) -> str:
    prompt = json.loads((workspace / "prompt.json").read_text(encoding="utf-8"))
    catalog = json.loads((workspace / "tool_catalog.json").read_text(encoding="utf-8"))
    return (
        "Respond with ONLY a JSON object of the form "
        '{"tool": "<tool_name>", "arguments": {...}} with no markdown.\n\n'
        f"User request:\n{prompt['user_request']}\n\n"
        f"Tool catalog:\n{json.dumps(catalog['tools'], indent=2)}"
    )


def _build_t2_prompt(workspace: Path) -> str:
    prompt = json.loads((workspace / "prompt.json").read_text(encoding="utf-8"))
    catalog = json.loads((workspace / "tool_catalog.json").read_text(encoding="utf-8"))
    return (
        "Respond with ONLY a JSON object of the form "
        '{"tool_calls": [{"tool": "<name>", "arguments": {...}}, ...], '
        '"result": "<final string>"} with no markdown.\n\n'
        f"User request:\n{prompt['user_request']}\n\n"
        f"Tool catalog:\n{json.dumps(catalog['tools'], indent=2)}"
    )


def _build_c1_prompt(workspace: Path) -> str:
    prompt = json.loads((workspace / "prompt.json").read_text(encoding="utf-8"))
    source_path = workspace / "repo" / "src" / "counter.py"
    source = source_path.read_text(encoding="utf-8")
    return (
        "Respond with ONLY a JSON patch object of the form "
        '{"files": {"repo/src/counter.py": "<full file contents>"}} with no markdown.\n'
        "Do not modify tests.\n\n"
        f"Bug description:\n{prompt['bug_description']}\n\n"
        f"Current source ({prompt['source_module']}):\n{source}"
    )


def _prompt_for_task(task_id: str, workspace: Path) -> str:
    if task_id == "be-core-t1-single-structured-call":
        return _build_t1_prompt(workspace)
    if task_id == "be-core-t2-multi-tool-join":
        return _build_t2_prompt(workspace)
    if task_id == "be-core-c1-small-logic-patch":
        return _build_c1_prompt(workspace)
    raise BenchEvalError(f"no Inspect prompt builder for task {task_id}")


def _candidate_filename(task_id: str, reference_artifact_name: str) -> str:
    if reference_artifact_name.endswith(".json"):
        return reference_artifact_name
    return f"{task_id}-candidate.json"


async def _generate_text(model_id: str, prompt: str) -> tuple[str, float, float]:
    from inspect_ai.model import ChatMessageUser, get_model

    model = get_model(model_id)
    started = time.perf_counter()
    output = await model.generate([ChatMessageUser(content=prompt)])
    latency = time.perf_counter() - started
    message = output.message
    text = message.text
    if text is None:
        text = json.dumps(message.content) if message.content is not None else ""
    usage = output.usage
    cost = 0.0
    if usage is not None and usage.total_cost is not None:
        cost = float(usage.total_cost)
    return text, cost, latency


def _mockllm_e0_invoke(config: InspectAdapterConfig) -> InspectInvokeResult:
    reference = config.workspace / config.reference_artifact_name
    if not reference.is_file():
        raise BenchEvalError(f"reference missing for mockllm E0 run: {reference}")
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)
    candidate_name = _candidate_filename(config.task_id, config.reference_artifact_name)
    candidate_path = config.artifacts_dir / candidate_name
    candidate_path.write_text(reference.read_text(encoding="utf-8"), encoding="utf-8")
    metadata = {
        "inspect_ai_version": "not_required",
        "invocation_mode": "mockllm_deterministic",
    }
    return InspectInvokeResult(
        candidate_path=candidate_path,
        cost_usd=0.0,
        latency_sec=0.0,
        adapter_metadata=metadata,
    )


def default_inspect_invoke(config: InspectAdapterConfig) -> InspectInvokeResult:
    if config.model_id == MOCKLLM_MODEL_ID and config.execution_profile == "E0":
        return _mockllm_e0_invoke(config)
    report = run_doctor(
        INSPECT_BACKEND,
        model_id=config.model_id,
        execution_profile=config.execution_profile,
    )
    require_doctor_ok(report)
    prompt = _prompt_for_task(config.task_id, config.workspace)
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)
    try:
        text, cost_usd, latency_sec = asyncio.run(_generate_text(config.model_id, prompt))
    except BenchEvalError:
        raise
    except Exception as e:
        raise AdapterFailureError(
            f"Inspect model invocation failed: {e}",
            failure_label="adapter_error",
        ) from e
    try:
        payload = _extract_json_object(text)
    except AdapterFailureError as e:
        raise AdapterFailureError(
            str(e),
            failure_label=e.failure_label,
            cost_usd=cost_usd,
            latency_sec=latency_sec,
            adapter_metadata={"inspect_ai_version": inspect_ai_version() or "unknown"},
        ) from e
    candidate_name = _candidate_filename(config.task_id, config.reference_artifact_name)
    candidate_path = config.artifacts_dir / candidate_name
    candidate_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    metadata = {"inspect_ai_version": inspect_ai_version() or "unknown"}
    if config.sandbox_docker:
        metadata["sandbox"] = "docker"
    return InspectInvokeResult(
        candidate_path=candidate_path,
        cost_usd=cost_usd,
        latency_sec=latency_sec,
        adapter_metadata=metadata,
    )


def run_inspect_adapter(
    config: InspectAdapterConfig,
    *,
    invoke: InspectInvoker | None = None,
) -> InspectInvokeResult:
    if config.task_id not in INSPECT_SUPPORTED_TASKS:
        raise BenchEvalError(
            f"Inspect backend does not support task {config.task_id!r}; "
            f"supported: {sorted(INSPECT_SUPPORTED_TASKS)}",
        )
    expected = execution_profile_for_task(config.task_id)
    if config.execution_profile != expected:
        raise BenchEvalError(
            f"task {config.task_id} requires Inspect profile {expected!r}, "
            f"got {config.execution_profile!r}",
        )
    if config.execution_profile == "E1" and not config.sandbox_docker:
        raise BenchEvalError(
            "E1 Inspect runs require sandbox_docker=True for be-core-c1-small-logic-patch",
        )
    invoker = invoke or default_inspect_invoke
    return invoker(config)


def assert_model_id(*, requested: str, reported: str | None) -> None:
    if reported is not None and reported != requested:
        raise BenchEvalError(
            f"adapter attempted to spoof model_id: requested {requested!r}, got {reported!r}",
        )
