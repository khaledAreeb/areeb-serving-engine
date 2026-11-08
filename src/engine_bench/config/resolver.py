"""Resolve a raw config into a frozen ResolvedExperiment (design D2).

This module is the single place where config defaults live:

* ``DEFAULTS`` maps a key path to its static default. ``workloads[]`` stands
  for every workload.
* ``DERIVED_DEFAULTS`` maps a key path to the key path whose resolved value it
  copies when the user leaves it unset.

Resolution records the provenance (``default`` or ``config``) of every field
that has a default, so the plan can show where each assumption came from.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, TypeVar

from engine_bench.config.loader import LoadedYaml, load_yaml_file
from engine_bench.config.schema import (
    Client,
    Data,
    DistributionSlo,
    Estimates,
    Generation,
    Hardware,
    LocalImportSource,
    ModelSpec,
    PerRequestSlo,
    RawClient,
    RawData,
    RawDistributionSlo,
    RawEstimates,
    RawExperiment,
    RawPerRequestSlo,
    RawSearch,
    RawSeeds,
    RawSlo,
    RawStrata,
    RawTiming,
    RawTokenizer,
    RawTuning,
    RawValidity,
    RawWorkload,
    ResolvedExperiment,
    Sampling,
    Search,
    Seeds,
    Shared,
    Slo,
    Strata,
    Timing,
    Tokenizer,
    Tuning,
    Validity,
    Workload,
    parse_raw,
)

Source = Literal["default", "config"]
T = TypeVar("T")

DEFAULTS: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "shared.model.chat_template": "model_default",
        "shared.generation.temperature": 0.0,
        "shared.generation.top_p": 1.0,
        "shared.client.location": "same_host",
        "shared.seeds.engine": 0,
        "shared.seeds.client": 0,
        "workloads[].token_counter": "approx-utf8-bytes-div4/v1",
        "workloads[].sampling.strata.input_token_edges": (0, 512, 2048, 8192),
        "workloads[].sampling.strata.turn_edges": (1, 2, 4),
        "cache_regimes": ("unique_prefix", "warm_shared_prefix"),
        "cache_reset": "auto",
        "repetitions": 3,
        "timing.warmup_s": 60,
        "timing.measure_target_s": 180,
        "timing.measure_min_requests": 50,
        "timing.measure_max_s": 900,
        "slo.per_request.ttft_ms": 1500,
        "slo.per_request.e2e_deadline_ms": 60000,
        "slo.distribution.ttft_p95_ms": 1500,
        "slo.distribution.max_error_rate": 0.01,
        "search.coarse_grid": (1, 5, 10, 20),
        "search.extension_factor": 2.0,
        "search.max_concurrency": 256,
        "search.refine_max_steps": 3,
        "search.refine_resolution": 0.10,
        "search.confirm_rate_fractions": (1.0, 0.9, 0.8),
        "search.min_achieved_ratio": 0.95,
        "validity.client_cpu_max_pct": 85.0,
        "validity.client_network_max_pct": None,
        "estimates.deployment_start_s": 600.0,
        "estimates.deployment_stop_s": 60.0,
        "estimates.cache_flush_s": 10.0,
        "estimates.cell_overhead_s": 30.0,
        "tuning.max_configs_per_engine": 0,
        "data.dir": "data",
        "data.hf_token_env": "HF_TOKEN",
    }
)

DERIVED_DEFAULTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "shared.model.tokenizer.id": "shared.model.id",
        "shared.model.tokenizer.revision": "shared.model.revision",
        "timing.request_timeout_ms": "slo.per_request.e2e_deadline_ms",
        "timing.drain_timeout_ms": "timing.request_timeout_ms",
    }
)


@dataclass(frozen=True)
class ResolvedConfig:
    """A resolved experiment plus where each defaultable value came from."""

    experiment: ResolvedExperiment
    provenance: Mapping[str, Source]
    source: str = "<string>"

    def source_of(self, path: str) -> Source:
        return self.provenance[path]


class _Resolver:
    def __init__(self) -> None:
        self.provenance: dict[str, Source] = {}

    def pick(self, path: str, given: T | None, default_key: str | None = None) -> T:
        if given is not None:
            self.provenance[path] = "config"
            return given
        self.provenance[path] = "default"
        value: T = DEFAULTS[default_key or path]
        return value

    def derive(self, path: str, given: T | None, fallback: T) -> T:
        self.provenance[path] = "default" if given is None else "config"
        return fallback if given is None else given

    def shared(self, raw: RawExperiment) -> Shared:
        s = raw.shared
        tokenizer = s.model.tokenizer or RawTokenizer()
        generation = s.generation
        client = s.client or RawClient()
        seeds = s.seeds or RawSeeds()
        return Shared(
            model=ModelSpec(
                id=s.model.id,
                revision=s.model.revision,
                tokenizer=Tokenizer(
                    id=self.derive("shared.model.tokenizer.id", tokenizer.id, s.model.id),
                    revision=self.derive(
                        "shared.model.tokenizer.revision", tokenizer.revision, s.model.revision
                    ),
                ),
                chat_template=self.pick("shared.model.chat_template", s.model.chat_template),
            ),
            precision=s.precision,
            max_context_tokens=s.max_context_tokens,
            generation=Generation(
                max_output_tokens=generation.max_output_tokens,
                temperature=self.pick("shared.generation.temperature", generation.temperature),
                top_p=self.pick("shared.generation.top_p", generation.top_p),
            ),
            hardware=Hardware(
                gpu_system=s.hardware.gpu_system,
                gpu_count=s.hardware.gpu_count,
                gpu_uuids=tuple(s.hardware.gpu_uuids),
            ),
            client=Client(location=self.pick("shared.client.location", client.location)),
            seeds=Seeds(
                engine=self.pick("shared.seeds.engine", seeds.engine),
                client=self.pick("shared.seeds.client", seeds.client),
            ),
            load_generator=s.load_generator,
        )

    def workload(self, index: int, w: RawWorkload) -> Workload:
        prefix = f"workloads[{index}]"
        strata: Strata | None = None
        if isinstance(w.source, LocalImportSource):
            raw_strata = w.sampling.strata or RawStrata()
            strata = Strata(
                input_token_edges=tuple(
                    self.pick(
                        f"{prefix}.sampling.strata.input_token_edges",
                        raw_strata.input_token_edges,
                        "workloads[].sampling.strata.input_token_edges",
                    )
                ),
                turn_edges=tuple(
                    self.pick(
                        f"{prefix}.sampling.strata.turn_edges",
                        raw_strata.turn_edges,
                        "workloads[].sampling.strata.turn_edges",
                    )
                ),
            )
        return Workload(
            name=w.name,
            profile=w.profile,
            output_mode=w.output_mode,
            source=w.source,
            sampling=Sampling(
                sample_size=w.sampling.sample_size, seed=w.sampling.seed, strata=strata
            ),
            token_counter=self.pick(
                f"{prefix}.token_counter", w.token_counter, "workloads[].token_counter"
            ),
            required_load=w.required_load,
        )

    def resolve(self, raw: RawExperiment) -> ResolvedExperiment:
        raw_slo = raw.slo or RawSlo()
        pr = raw_slo.per_request or RawPerRequestSlo()
        dist = raw_slo.distribution or RawDistributionSlo()
        slo = Slo(
            per_request=PerRequestSlo(
                ttft_ms=self.pick("slo.per_request.ttft_ms", pr.ttft_ms),
                e2e_deadline_ms=self.pick("slo.per_request.e2e_deadline_ms", pr.e2e_deadline_ms),
            ),
            distribution=DistributionSlo(
                ttft_p95_ms=self.pick("slo.distribution.ttft_p95_ms", dist.ttft_p95_ms),
                max_error_rate=self.pick("slo.distribution.max_error_rate", dist.max_error_rate),
            ),
        )

        t = raw.timing or RawTiming()
        request_timeout = self.derive(
            "timing.request_timeout_ms", t.request_timeout_ms, slo.per_request.e2e_deadline_ms
        )
        timing = Timing(
            warmup_s=self.pick("timing.warmup_s", t.warmup_s),
            measure_target_s=self.pick("timing.measure_target_s", t.measure_target_s),
            measure_min_requests=self.pick("timing.measure_min_requests", t.measure_min_requests),
            measure_max_s=self.pick("timing.measure_max_s", t.measure_max_s),
            request_timeout_ms=request_timeout,
            drain_timeout_ms=self.derive(
                "timing.drain_timeout_ms", t.drain_timeout_ms, request_timeout
            ),
        )

        s = raw.search or RawSearch()
        search = Search(
            coarse_grid=tuple(self.pick("search.coarse_grid", s.coarse_grid)),
            extension_factor=self.pick("search.extension_factor", s.extension_factor),
            max_concurrency=self.pick("search.max_concurrency", s.max_concurrency),
            refine_max_steps=self.pick("search.refine_max_steps", s.refine_max_steps),
            refine_resolution=self.pick("search.refine_resolution", s.refine_resolution),
            confirm_rate_fractions=tuple(
                self.pick("search.confirm_rate_fractions", s.confirm_rate_fractions)
            ),
            min_achieved_ratio=self.pick("search.min_achieved_ratio", s.min_achieved_ratio),
        )

        v = raw.validity or RawValidity()
        validity = Validity(
            client_cpu_max_pct=self.pick("validity.client_cpu_max_pct", v.client_cpu_max_pct),
            client_network_max_pct=self.pick(
                "validity.client_network_max_pct", v.client_network_max_pct
            ),
        )

        e = raw.estimates or RawEstimates()
        estimates = Estimates(
            deployment_start_s=self.pick("estimates.deployment_start_s", e.deployment_start_s),
            deployment_stop_s=self.pick("estimates.deployment_stop_s", e.deployment_stop_s),
            cache_flush_s=self.pick("estimates.cache_flush_s", e.cache_flush_s),
            cell_overhead_s=self.pick("estimates.cell_overhead_s", e.cell_overhead_s),
        )

        tuning = raw.tuning or RawTuning()
        data = raw.data or RawData()
        return ResolvedExperiment(
            name=raw.name,
            shared=self.shared(raw),
            engines=tuple(raw.engines),
            workloads=tuple(self.workload(i, w) for i, w in enumerate(raw.workloads)),
            cache_regimes=tuple(self.pick("cache_regimes", raw.cache_regimes)),
            cache_reset=self.pick("cache_reset", raw.cache_reset),
            repetitions=self.pick("repetitions", raw.repetitions),
            timing=timing,
            slo=slo,
            search=search,
            validity=validity,
            estimates=estimates,
            tuning=Tuning(
                max_configs_per_engine=self.pick(
                    "tuning.max_configs_per_engine", tuning.max_configs_per_engine
                )
            ),
            cost=raw.cost,
            data=Data(
                dir=self.pick("data.dir", data.dir),
                hf_token_env=self.pick("data.hf_token_env", data.hf_token_env),
            ),
        )


def resolve(raw: RawExperiment, *, source: str = "<string>") -> ResolvedConfig:
    """Fill every default and record each defaultable field's provenance."""
    resolver = _Resolver()
    experiment = resolver.resolve(raw)
    return ResolvedConfig(
        experiment=experiment,
        provenance=MappingProxyType(dict(sorted(resolver.provenance.items()))),
        source=source,
    )


def resolve_loaded(loaded: LoadedYaml) -> ResolvedConfig:
    """Parse and resolve already-loaded YAML (raises ConfigError on schema problems)."""
    return resolve(parse_raw(loaded), source=loaded.source)


def load_config(path: Path) -> ResolvedConfig:
    """Load, parse and resolve an experiment file.

    Raises ``OSError`` for unreadable files and ``ConfigError`` for invalid content.
    Cross-field rules are checked separately by ``engine_bench.config.rules``.
    """
    return resolve_loaded(load_yaml_file(path))
