import re
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine_bench.config.resolver import (
    DEFAULTS,
    DERIVED_DEFAULTS,
    ResolvedConfig,
    load_config,
    resolve,
)
from engine_bench.config.schema import RawExperiment
from engine_bench.hashing import canonical_json

Parse = Callable[[str], RawExperiment]

TIMING_AND_ESTIMATES = {
    "timing.warmup_s",
    "timing.measure_target_s",
    "timing.measure_min_requests",
    "timing.measure_max_s",
    "timing.request_timeout_ms",
    "timing.drain_timeout_ms",
    "estimates.deployment_start_s",
    "estimates.deployment_stop_s",
    "estimates.cache_flush_s",
    "estimates.cell_overhead_s",
}


@pytest.fixture
def resolved_minimal(parse_text: Parse, minimal_yaml: str) -> ResolvedConfig:
    return resolve(parse_text(minimal_yaml))


def test_minimal_config_resolves_to_the_specified_defaults(
    resolved_minimal: ResolvedConfig,
) -> None:
    e = resolved_minimal.experiment.model_dump(mode="json")
    assert e["slo"] == {
        "per_request": {"ttft_ms": 1500, "e2e_deadline_ms": 60000},
        "distribution": {"ttft_p95_ms": 1500, "max_error_rate": 0.01},
    }
    assert e["timing"] == {
        "warmup_s": 60,
        "measure_target_s": 180,
        "measure_min_requests": 50,
        "measure_max_s": 900,
        "request_timeout_ms": 60000,
        "drain_timeout_ms": 60000,
    }
    assert e["search"] == {
        "coarse_grid": [1, 5, 10, 20],
        "extension_factor": 2.0,
        "max_concurrency": 256,
        "refine_max_steps": 3,
        "refine_resolution": 0.10,
        "confirm_rate_fractions": [1.0, 0.9, 0.8],
        "min_achieved_ratio": 0.95,
    }
    assert e["validity"] == {"client_cpu_max_pct": 85.0, "client_network_max_pct": None}
    assert e["repetitions"] == 3
    assert e["cache_regimes"] == ["unique_prefix", "warm_shared_prefix"]
    assert e["cache_reset"] == "auto"
    assert e["estimates"] == {
        "deployment_start_s": 600.0,
        "deployment_stop_s": 60.0,
        "cache_flush_s": 10.0,
        "cell_overhead_s": 30.0,
    }
    assert e["tuning"] == {"max_configs_per_engine": 0}
    assert e["cost"] is None
    assert e["data"] == {"dir": "data", "hf_token_env": "HF_TOKEN"}


def test_every_timing_and_estimate_value_has_default_provenance(
    resolved_minimal: ResolvedConfig,
) -> None:
    for path in TIMING_AND_ESTIMATES:
        assert resolved_minimal.source_of(path) == "default", path


def test_overrides_change_only_their_own_values(parse_text: Parse, minimal_yaml: str) -> None:
    baseline = resolve(parse_text(minimal_yaml))
    text = minimal_yaml + "estimates:\n  deployment_start_s: 300\ntiming:\n  warmup_s: 30\n"
    overridden = resolve(parse_text(text))

    assert overridden.experiment.estimates.deployment_start_s == 300.0
    assert overridden.experiment.timing.warmup_s == 30
    assert overridden.source_of("estimates.deployment_start_s") == "config"
    assert overridden.source_of("timing.warmup_s") == "config"
    for path in TIMING_AND_ESTIMATES - {"estimates.deployment_start_s", "timing.warmup_s"}:
        assert overridden.source_of(path) == "default", path

    before = baseline.experiment.model_dump(mode="json")
    after = overridden.experiment.model_dump(mode="json")
    before["estimates"]["deployment_start_s"] = 300.0
    before["timing"]["warmup_s"] = 30
    assert before == after


def test_request_and_drain_timeouts_follow_the_deadline(
    parse_text: Parse, minimal_yaml: str
) -> None:
    text = minimal_yaml + "slo:\n  per_request:\n    e2e_deadline_ms: 90000\n"
    resolved = resolve(parse_text(text))
    assert resolved.experiment.timing.request_timeout_ms == 90000
    assert resolved.experiment.timing.drain_timeout_ms == 90000
    assert resolved.source_of("timing.request_timeout_ms") == "default"


def test_drain_timeout_follows_an_explicit_request_timeout(
    parse_text: Parse, minimal_yaml: str
) -> None:
    resolved = resolve(parse_text(minimal_yaml + "timing:\n  request_timeout_ms: 70000\n"))
    assert resolved.experiment.timing.request_timeout_ms == 70000
    assert resolved.experiment.timing.drain_timeout_ms == 70000
    assert resolved.source_of("timing.request_timeout_ms") == "config"
    assert resolved.source_of("timing.drain_timeout_ms") == "default"


def test_tokenizer_defaults_to_the_model(resolved_minimal: ResolvedConfig) -> None:
    model = resolved_minimal.experiment.shared.model
    assert (model.tokenizer.id, model.tokenizer.revision) == (model.id, model.revision)
    assert model.chat_template == "model_default"


def test_strata_defaults_apply_only_to_local_imports(resolved_minimal: ResolvedConfig) -> None:
    general, coding = resolved_minimal.experiment.workloads
    assert general.sampling.strata is not None
    assert general.sampling.strata.input_token_edges == (0, 512, 2048, 8192)
    assert general.sampling.strata.turn_edges == (1, 2, 4)
    assert coding.sampling.strata is None
    assert general.token_counter == coding.token_counter == "approx-utf8-bytes-div4/v1"


def test_partial_strata_keep_the_other_default(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace(
        "      sample_size: 200\n      seed: 7\n",
        "      sample_size: 200\n      seed: 7\n      strata:\n        turn_edges: [1, 3]\n",
    )
    resolved = resolve(parse_text(text))
    strata = resolved.experiment.workloads[0].sampling.strata
    assert strata is not None
    assert strata.turn_edges == (1, 3)
    assert strata.input_token_edges == (0, 512, 2048, 8192)
    assert resolved.source_of("workloads[0].sampling.strata.turn_edges") == "config"
    assert resolved.source_of("workloads[0].sampling.strata.input_token_edges") == "default"


def test_output_mode_has_no_default_and_is_kept(resolved_minimal: ResolvedConfig) -> None:
    assert not any("output_mode" in key for key in DEFAULTS)
    assert [w.output_mode for w in resolved_minimal.experiment.workloads] == [
        "fixed_length",
        "fixed_length",
    ]


def test_every_recorded_default_is_declared_in_one_place(
    resolved_minimal: ResolvedConfig,
) -> None:
    declared = set(DEFAULTS) | set(DERIVED_DEFAULTS)
    for path in resolved_minimal.provenance:
        assert re.sub(r"workloads\[\d+\]", "workloads[]", path) in declared, path


def test_resolved_experiment_is_frozen(resolved_minimal: ResolvedConfig) -> None:
    with pytest.raises(ValidationError, match="frozen"):
        resolved_minimal.experiment.repetitions = 5  # type: ignore[misc]


def test_resolved_experiment_is_canonically_hashable(resolved_minimal: ResolvedConfig) -> None:
    text = canonical_json(resolved_minimal.experiment.model_dump(mode="json"))
    assert '"repetitions":3' in text


def test_load_config_reads_a_file(tmp_path: Path, minimal_yaml: str) -> None:
    path = tmp_path / "experiment.yaml"
    path.write_text(minimal_yaml, encoding="utf-8")
    resolved = load_config(path)
    assert resolved.source == str(path)
    assert resolved.experiment.name == "baseline-comparison"
