"""External benchmark catalog loader."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root

BenchmarkCategory = Literal[
    "agentic_terminal",
    "coding",
    "cybersecurity",
    "data_science",
    "general_agent",
    "long_context",
    "ml_research",
    "multimodal",
    "os_desktop",
    "reasoning",
    "safety",
    "tool_use",
    "web_agent",
]

BenchmarkTier = Literal["calibration", "stretch", "reference_only"]
BenchmarkAdapterStatus = Literal[
    "adapter_pending",
    "cataloged",
    "manifest_available",
    "unverified",
]
BenchmarkBackend = Literal["inspect", "harbor", "external"]
BenchmarkProfile = Literal["E3", "E4"]
ContaminationRisk = Literal["low", "medium", "high", "unknown"]
SafetyReview = Literal["standard", "dual_use", "offensive_restricted"]

_KEY_SEPARATOR_RE = re.compile(r"[\s_-]+")


class BenchmarkEntry(BaseModel):
    """Catalog metadata for one public benchmark family."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    category: BenchmarkCategory
    tier: BenchmarkTier
    adapter_status: BenchmarkAdapterStatus
    recommended_backend: BenchmarkBackend
    recommended_profile: BenchmarkProfile
    task_count: int | None = Field(default=None, ge=1)
    public_indexed: bool
    contamination_risk: ContaminationRisk
    single_mode_required: bool
    safety_review: SafetyReview
    source_url: str | None = Field(default=None, min_length=1)
    notes: str = Field(min_length=1)


class BenchmarkCatalog(BaseModel):
    """Validated catalog of external benchmark support metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(ge=1)
    benchmarks: tuple[BenchmarkEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids_and_aliases(self) -> Self:
        ids: dict[str, str] = {}
        aliases: dict[str, str] = {}
        for benchmark in self.benchmarks:
            folded_id = _fold_key(benchmark.id)
            if folded_id in ids:
                raise ValueError(f"duplicate benchmark id: {benchmark.id}")
            ids[folded_id] = benchmark.id
        for benchmark in self.benchmarks:
            for alias in benchmark.aliases:
                folded_alias = _fold_key(alias)
                id_owner = ids.get(folded_alias)
                if id_owner is not None and id_owner != benchmark.id:
                    message = (
                        f"benchmark alias {alias!r} for {benchmark.id} conflicts with id {id_owner}"
                    )
                    raise ValueError(
                        message,
                    )
                owner = aliases.get(folded_alias)
                if owner is not None and owner != benchmark.id:
                    raise ValueError(
                        f"duplicate benchmark alias {alias!r}: {owner} and {benchmark.id}",
                    )
                aliases[folded_alias] = benchmark.id
        return self

    def by_id_or_alias(self, key: str) -> BenchmarkEntry:
        folded = _fold_key(key)
        for benchmark in self.benchmarks:
            if _fold_key(benchmark.id) == folded:
                return benchmark
            if any(_fold_key(alias) == folded for alias in benchmark.aliases):
                return benchmark
        raise BenchEvalError(f"benchmark not found: {key}")


ExecutionSupport = Literal["executable_adapter", "manifest_only", "metadata_only"]


@dataclass(frozen=True, slots=True)
class BenchmarkFilter:
    category: BenchmarkCategory | None = None
    tier: BenchmarkTier | None = None
    adapter_status: BenchmarkAdapterStatus | None = None
    safety_review: SafetyReview | None = None
    execution_support: ExecutionSupport | None = None


def default_benchmarks_path() -> Path:
    return _repo_root() / "config" / "benchmarks.yaml"


def _fold_key(value: str) -> str:
    return _KEY_SEPARATOR_RE.sub("-", value.strip().lower()).strip("-")


@lru_cache(maxsize=4)
def _load_benchmark_catalog_cached(catalog_path_str: str) -> BenchmarkCatalog:
    catalog_path = Path(catalog_path_str)
    try:
        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as e:
        raise BenchEvalError(f"cannot decode benchmark catalog {catalog_path} as UTF-8: {e}") from e
    except OSError as e:
        raise BenchEvalError(f"cannot read benchmark catalog {catalog_path}: {e}") from e
    except yaml.YAMLError as e:
        raise BenchEvalError(f"{catalog_path.name}: invalid YAML: {e}") from e
    try:
        return BenchmarkCatalog.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{catalog_path.name}: {e}") from e


def clear_benchmark_catalog_cache() -> None:
    _load_benchmark_catalog_cached.cache_clear()


def load_benchmark_catalog(path: Path | None = None) -> BenchmarkCatalog:
    catalog_path = (path or default_benchmarks_path()).resolve()
    return _load_benchmark_catalog_cached(str(catalog_path))


_EXECUTABLE_BENCHMARK_IDS = frozenset(
    {
        "terminal-bench",
        "swe-bench-verified",
        "bfcl-v4",
    },
)


def execution_support_label(entry: BenchmarkEntry) -> str:
    """Whether catalog metadata implies a runnable control-plane adapter."""
    if entry.id in _EXECUTABLE_BENCHMARK_IDS:
        return "executable_adapter"
    if entry.adapter_status == "manifest_available":
        return "manifest_only"
    return "metadata_only"


def filter_benchmarks(
    catalog: BenchmarkCatalog,
    filters: BenchmarkFilter,
) -> tuple[BenchmarkEntry, ...]:
    entries = catalog.benchmarks
    if filters.category is not None:
        entries = tuple(b for b in entries if b.category == filters.category)
    if filters.tier is not None:
        entries = tuple(b for b in entries if b.tier == filters.tier)
    if filters.adapter_status is not None:
        entries = tuple(b for b in entries if b.adapter_status == filters.adapter_status)
    if filters.safety_review is not None:
        entries = tuple(b for b in entries if b.safety_review == filters.safety_review)
    if filters.execution_support is not None:
        entries = tuple(
            b for b in entries if execution_support_label(b) == filters.execution_support
        )
    return tuple(sorted(entries, key=lambda b: b.id))
