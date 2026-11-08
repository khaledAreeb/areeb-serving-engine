"""Experiment config models (design D2).

Two layers:

* ``Raw*`` models mirror the YAML exactly. Fields that have a default are
  optional, and ``None`` means "not written by the user". Unknown keys are
  forbidden and types are strict (no ``"1500"`` -> 1500, no ``true`` -> 1).
* ``Resolved*`` models have every default filled in by
  ``engine_bench.config.resolver`` (the single place where defaults live), are
  frozen, and are the only config types the rest of engine-bench uses.

Leaf models without defaults (sources, engine configs, required load, cost) are
shared by both layers. Cross-field rules (fairness, budgets, grid order, ...)
live in ``engine_bench.config.rules``, not here.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from itertools import pairwise
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from engine_bench.config.issues import ConfigError, Issue, Severity
from engine_bench.config.loader import LoadedYaml, join_index, join_key
from engine_bench.config.placeholders import (
    AiperfVersion,
    DatasetRevision,
    GpuSystem,
    GpuUuid,
    ImageRef,
    ModelId,
    ModelRevision,
)

_STRICT = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

# --- shared field types -------------------------------------------------------------

Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Token = Annotated[str, StringConstraints(pattern=r"^\S+$")]
EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]*$")]
ArgName = Annotated[str, StringConstraints(pattern=r"^--[A-Za-z0-9][A-Za-z0-9._-]*$")]
ParamName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")]
ArgValue = str | bool | int | float | None
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Fraction = Annotated[float, Field(gt=0, le=1)]
Percent = Annotated[float, Field(gt=0, le=100)]

EngineKind = Literal["vllm", "sglang", "trtllm"]
EngineRole = Literal["baseline", "tuned"]
Profile = Literal["general", "coding", "agentic"]
OutputMode = Literal["fixed_length", "natural"]
CacheRegime = Literal["unique_prefix", "warm_shared_prefix"]
CacheReset = Literal["auto", "flush", "restart"]
ClientLocation = Literal["same_host", "remote"]
TokenCounterId = Literal["approx-utf8-bytes-div4/v1"]
LocalImporter = Literal["wildchat"]


def _strictly_increasing(values: Sequence[int]) -> Sequence[int]:
    if any(b <= a for a, b in pairwise(values)):
        raise ValueError("bucket edges must be strictly increasing")
    return values


def _unique_names(items: Sequence[Any], kind: str) -> None:
    counts = Counter(item.name for item in items)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"{kind} names must be unique; duplicated: {', '.join(duplicates)}")


# --- leaf models shared by both layers -----------------------------------------------


class LoadGenerator(BaseModel):
    model_config = _STRICT
    aiperf_version: AiperfVersion


class EngineConfig(BaseModel):
    model_config = _STRICT
    name: Name
    engine: EngineKind
    role: EngineRole
    image: ImageRef
    args: dict[ArgName, ArgValue] = Field(default_factory=dict)


class LocalImportSource(BaseModel):
    model_config = _STRICT
    kind: Literal["local_import"]
    importer: LocalImporter
    dataset_id: Token
    revision: DatasetRevision
    path: Token


class BuiltinSource(BaseModel):
    model_config = _STRICT
    kind: Literal["aiperf_builtin"]
    loader: Token
    dataset_id: Token
    revision: DatasetRevision
    loader_params: dict[ParamName, ArgValue] = Field(default_factory=dict)


WorkloadSource = Annotated[LocalImportSource | BuiltinSource, Field(discriminator="kind")]


class RequiredLoad(BaseModel):
    model_config = _STRICT
    concurrency: PositiveInt | None = None
    request_rate: PositiveFloat | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> RequiredLoad:
        if (self.concurrency is None) == (self.request_rate is None):
            raise ValueError("give exactly one of 'concurrency' or 'request_rate'")
        return self


class Cost(BaseModel):
    model_config = _STRICT
    gpu_hour_rate: PositiveFloat
    currency: CurrencyCode


# --- raw layer (mirrors the YAML) -----------------------------------------------------


class RawTokenizer(BaseModel):
    model_config = _STRICT
    id: ModelId | None = None
    revision: ModelRevision | None = None


class RawModelSpec(BaseModel):
    model_config = _STRICT
    id: ModelId
    revision: ModelRevision
    tokenizer: RawTokenizer | None = None
    chat_template: Token | None = None


class RawGeneration(BaseModel):
    model_config = _STRICT
    max_output_tokens: PositiveInt
    temperature: Annotated[float, Field(ge=0)] | None = None
    top_p: Fraction | None = None


class RawHardware(BaseModel):
    model_config = _STRICT
    gpu_system: GpuSystem
    gpu_count: PositiveInt
    gpu_uuids: Annotated[list[GpuUuid], Field(min_length=1)]


class RawClient(BaseModel):
    model_config = _STRICT
    location: ClientLocation | None = None


class RawSeeds(BaseModel):
    model_config = _STRICT
    engine: NonNegativeInt | None = None
    client: NonNegativeInt | None = None


class RawShared(BaseModel):
    model_config = _STRICT
    model: RawModelSpec
    precision: Token
    max_context_tokens: PositiveInt
    generation: RawGeneration
    hardware: RawHardware
    client: RawClient | None = None
    seeds: RawSeeds | None = None
    load_generator: LoadGenerator


class RawStrata(BaseModel):
    model_config = _STRICT
    input_token_edges: Annotated[list[NonNegativeInt], Field(min_length=1)] | None = None
    turn_edges: Annotated[list[PositiveInt], Field(min_length=1)] | None = None

    @field_validator("input_token_edges", "turn_edges")
    @classmethod
    def _increasing(cls, value: list[int] | None) -> list[int] | None:
        return None if value is None else list(_strictly_increasing(value))


class RawSampling(BaseModel):
    model_config = _STRICT
    sample_size: PositiveInt
    seed: NonNegativeInt
    strata: RawStrata | None = None


class RawWorkload(BaseModel):
    model_config = _STRICT
    name: Name
    profile: Profile
    output_mode: OutputMode
    source: WorkloadSource
    sampling: RawSampling
    token_counter: TokenCounterId | None = None
    required_load: RequiredLoad | None = None

    @model_validator(mode="after")
    def _strata_only_for_local_imports(self) -> RawWorkload:
        if self.sampling.strata is not None and not isinstance(self.source, LocalImportSource):
            raise ValueError("sampling.strata applies only to local_import sources")
        return self


class RawPerRequestSlo(BaseModel):
    model_config = _STRICT
    ttft_ms: PositiveInt | None = None
    e2e_deadline_ms: PositiveInt | None = None


class RawDistributionSlo(BaseModel):
    model_config = _STRICT
    ttft_p95_ms: PositiveInt | None = None
    max_error_rate: Annotated[float, Field(ge=0, lt=1)] | None = None


class RawSlo(BaseModel):
    model_config = _STRICT
    per_request: RawPerRequestSlo | None = None
    distribution: RawDistributionSlo | None = None


class RawTiming(BaseModel):
    model_config = _STRICT
    warmup_s: NonNegativeInt | None = None
    measure_target_s: PositiveInt | None = None
    measure_min_requests: PositiveInt | None = None
    measure_max_s: PositiveInt | None = None
    request_timeout_ms: PositiveInt | None = None
    drain_timeout_ms: PositiveInt | None = None


class RawSearch(BaseModel):
    model_config = _STRICT
    coarse_grid: Annotated[list[PositiveInt], Field(min_length=1)] | None = None
    extension_factor: Annotated[float, Field(gt=1)] | None = None
    max_concurrency: PositiveInt | None = None
    refine_max_steps: NonNegativeInt | None = None
    refine_resolution: Fraction | None = None
    confirm_rate_fractions: Annotated[list[Fraction], Field(min_length=1)] | None = None
    min_achieved_ratio: Fraction | None = None


class RawValidity(BaseModel):
    model_config = _STRICT
    client_cpu_max_pct: Percent | None = None
    client_network_max_pct: Percent | None = None


class RawEstimates(BaseModel):
    model_config = _STRICT
    deployment_start_s: PositiveFloat | None = None
    deployment_stop_s: PositiveFloat | None = None
    cache_flush_s: PositiveFloat | None = None
    cell_overhead_s: PositiveFloat | None = None


class RawTuning(BaseModel):
    model_config = _STRICT
    max_configs_per_engine: NonNegativeInt | None = None


class RawData(BaseModel):
    model_config = _STRICT
    dir: Token | None = None
    hf_token_env: EnvVarName | None = None


class RawExperiment(BaseModel):
    model_config = _STRICT
    name: Name
    shared: RawShared
    engines: Annotated[list[EngineConfig], Field(min_length=1)]
    workloads: Annotated[list[RawWorkload], Field(min_length=1)]
    cache_regimes: Annotated[list[CacheRegime], Field(min_length=1)] | None = None
    cache_reset: CacheReset | None = None
    repetitions: PositiveInt | None = None
    timing: RawTiming | None = None
    slo: RawSlo | None = None
    search: RawSearch | None = None
    validity: RawValidity | None = None
    estimates: RawEstimates | None = None
    tuning: RawTuning | None = None
    cost: Cost | None = None
    data: RawData | None = None

    @field_validator("engines")
    @classmethod
    def _unique_engine_names(cls, value: list[EngineConfig]) -> list[EngineConfig]:
        _unique_names(value, "engine config")
        return value

    @field_validator("workloads")
    @classmethod
    def _unique_workload_names(cls, value: list[RawWorkload]) -> list[RawWorkload]:
        _unique_names(value, "workload")
        return value

    @field_validator("cache_regimes")
    @classmethod
    def _unique_regimes(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("cache regimes must not repeat")
        return value


# --- resolved layer (defaults filled in, frozen) ----------------------------------------


class Tokenizer(BaseModel):
    model_config = _STRICT
    id: ModelId
    revision: ModelRevision


class ModelSpec(BaseModel):
    model_config = _STRICT
    id: ModelId
    revision: ModelRevision
    tokenizer: Tokenizer
    chat_template: str


class Generation(BaseModel):
    model_config = _STRICT
    max_output_tokens: int
    temperature: float
    top_p: float


class Hardware(BaseModel):
    model_config = _STRICT
    gpu_system: GpuSystem
    gpu_count: int
    gpu_uuids: tuple[GpuUuid, ...]


class Client(BaseModel):
    model_config = _STRICT
    location: ClientLocation


class Seeds(BaseModel):
    model_config = _STRICT
    engine: int
    client: int


class Shared(BaseModel):
    model_config = _STRICT
    model: ModelSpec
    precision: str
    max_context_tokens: int
    generation: Generation
    hardware: Hardware
    client: Client
    seeds: Seeds
    load_generator: LoadGenerator


class Strata(BaseModel):
    model_config = _STRICT
    input_token_edges: tuple[int, ...]
    turn_edges: tuple[int, ...]


class Sampling(BaseModel):
    model_config = _STRICT
    sample_size: int
    seed: int
    strata: Strata | None


class Workload(BaseModel):
    model_config = _STRICT
    name: str
    profile: Profile
    output_mode: OutputMode
    source: WorkloadSource
    sampling: Sampling
    token_counter: TokenCounterId
    required_load: RequiredLoad | None


class PerRequestSlo(BaseModel):
    model_config = _STRICT
    ttft_ms: int
    e2e_deadline_ms: int


class DistributionSlo(BaseModel):
    model_config = _STRICT
    ttft_p95_ms: int
    max_error_rate: float


class Slo(BaseModel):
    model_config = _STRICT
    per_request: PerRequestSlo
    distribution: DistributionSlo


class Timing(BaseModel):
    model_config = _STRICT
    warmup_s: int
    measure_target_s: int
    measure_min_requests: int
    measure_max_s: int
    request_timeout_ms: int
    drain_timeout_ms: int


class Search(BaseModel):
    model_config = _STRICT
    coarse_grid: tuple[int, ...]
    extension_factor: float
    max_concurrency: int
    refine_max_steps: int
    refine_resolution: float
    confirm_rate_fractions: tuple[float, ...]
    min_achieved_ratio: float


class Validity(BaseModel):
    model_config = _STRICT
    client_cpu_max_pct: float
    client_network_max_pct: float | None


class Estimates(BaseModel):
    model_config = _STRICT
    deployment_start_s: float
    deployment_stop_s: float
    cache_flush_s: float
    cell_overhead_s: float


class Tuning(BaseModel):
    model_config = _STRICT
    max_configs_per_engine: int


class Data(BaseModel):
    model_config = _STRICT
    dir: str
    hf_token_env: str


class ResolvedExperiment(BaseModel):
    model_config = _STRICT
    name: str
    shared: Shared
    engines: tuple[EngineConfig, ...]
    workloads: tuple[Workload, ...]
    cache_regimes: tuple[CacheRegime, ...]
    cache_reset: CacheReset
    repetitions: int
    timing: Timing
    slo: Slo
    search: Search
    validity: Validity
    estimates: Estimates
    tuning: Tuning
    cost: Cost | None
    data: Data


# --- parsing raw data with located issues ----------------------------------------------


def _loc_to_path(loc: Sequence[int | str], data: Any) -> str:
    """Turn a pydantic error location into a config key path.

    Drops pydantic-internal segments: discriminated-union tags (``local_import``),
    union member labels (``str``, ``int``) and ``[key]`` markers.
    """
    path = ""
    current: Any = data
    for segment in loc:
        if isinstance(segment, int):
            path = join_index(path, segment)
            in_range = isinstance(current, list) and 0 <= segment < len(current)
            current = current[segment] if in_range else None
            continue
        if segment == "[key]":
            continue
        if isinstance(current, dict):
            if segment in current:
                path = join_key(path, segment)
                current = current[segment]
                continue
            if current.get("kind") == segment:
                continue  # discriminated-union tag
            path = join_key(path, segment)
            current = None
            continue
        if current is None:
            path = join_key(path, segment)
        # Otherwise ``current`` is a scalar or list and the segment is a union label.
    return path


def _entity_prefix(path: str, data: dict[str, Any]) -> str:
    for collection, label in (("engines", "engine"), ("workloads", "workload")):
        if path.startswith(f"{collection}["):
            index_text = path[len(collection) + 1 : path.index("]")]
            items = data.get(collection)
            if index_text.isdigit() and isinstance(items, list):
                index = int(index_text)
                item = items[index] if index < len(items) else None
                name = item.get("name") if isinstance(item, dict) else None
                if isinstance(name, str):
                    return f"{label} '{name}': "
    return ""


def _describe(error: Any, path: str) -> tuple[str, str]:
    kind: str = error["type"]
    ctx: dict[str, Any] = error.get("ctx") or {}
    key = path.rsplit(".", 1)[-1] if path else "<root>"
    if kind == "extra_forbidden":
        return "unknown_key", f"unknown key '{key}'"
    if kind == "missing":
        return "missing_key", f"'{key}' is required"
    if kind == "literal_error":
        allowed = ctx["expected"]
        return "invalid_value", f"invalid value {error['input']!r}; allowed values: {allowed}"
    if kind == "union_tag_invalid":
        field_name, tag, allowed = ctx["discriminator"], ctx["tag"], ctx["expected_tags"]
        return "invalid_value", f"invalid {field_name} {tag!r}; allowed values: {allowed}"
    message: str = error["msg"]
    if kind == "string_type" and isinstance(error.get("input"), bool | int | float):
        message += "; YAML read this as a number or boolean, so quote it to keep it as text"
    return "invalid_value", message.removeprefix("Value error, ")


_TYPE_PREFIX = "Input should be a valid "


def _merge(messages: list[str]) -> str:
    """Merge messages for one location (several union members can fail at once)."""
    unique = list(dict.fromkeys(messages))
    if len(unique) > 1 and all(m.startswith(_TYPE_PREFIX) for m in unique):
        kinds = [m.removeprefix(_TYPE_PREFIX) for m in unique]
        return f"{_TYPE_PREFIX}{', '.join(kinds[:-1])} or {kinds[-1]}"
    return "; ".join(unique)


def parse_raw(loaded: LoadedYaml) -> RawExperiment:
    """Validate loaded YAML against the raw schema, raising located issues."""
    try:
        return RawExperiment.model_validate(loaded.data)
    except ValidationError as exc:
        grouped: dict[tuple[str, str], list[str]] = {}
        for error in exc.errors(include_url=False):
            path = _loc_to_path(error["loc"], loaded.data)
            code, message = _describe(error, path)
            grouped.setdefault((path, code), []).append(message)
        issues = [
            Issue(
                Severity.ERROR,
                code,
                path,
                _entity_prefix(path, loaded.data) + _merge(messages),
                loaded.line_for(path),
            )
            for (path, code), messages in grouped.items()
        ]
        raise ConfigError(issues) from None
