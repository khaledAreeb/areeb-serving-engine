from collections.abc import Callable

import pytest

from engine_bench.config.issues import ConfigError, Issue
from engine_bench.config.schema import BuiltinSource, LocalImportSource, RawExperiment

Parse = Callable[[str], RawExperiment]


def _issues(parse: Parse, text: str) -> list[Issue]:
    with pytest.raises(ConfigError) as info:
        parse(text)
    return list(info.value.issues)


def _only(parse: Parse, text: str) -> Issue:
    issues = _issues(parse, text)
    assert len(issues) == 1, [i.format() for i in issues]
    return issues[0]


def test_minimal_config_parses(parse_text: Parse, minimal_yaml: str) -> None:
    raw = parse_text(minimal_yaml)
    assert raw.name == "baseline-comparison"
    assert [w.name for w in raw.workloads] == ["general", "coding"]
    assert isinstance(raw.workloads[0].source, LocalImportSource)
    assert isinstance(raw.workloads[1].source, BuiltinSource)
    assert raw.slo is None  # not written, so the resolver will fill defaults


# --- unknown keys -------------------------------------------------------------------


def test_unknown_key_is_reported_with_path_and_line(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml + "slo:\n  ttft_p59_ms: 1500\n"
    issue = _only(parse_text, text)
    assert issue.code == "unknown_key"
    assert issue.path == "slo.ttft_p59_ms"
    assert issue.line == len(minimal_yaml.splitlines()) + 2
    assert "ttft_p59_ms" in issue.message


def test_unknown_nested_key_inside_a_list_item(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace("    role: baseline\n", "    role: baseline\n    gpu: 2\n")
    issue = _only(parse_text, text)
    assert (issue.code, issue.path) == ("unknown_key", "engines[0].gpu")
    assert issue.message.startswith("engine 'vllm_baseline': ")


# --- output mode -------------------------------------------------------------------------


def test_workload_without_output_mode_is_rejected_naming_it(
    parse_text: Parse, minimal_yaml: str, coding_workload_line: int
) -> None:
    text = minimal_yaml.replace(
        "  - name: coding\n    profile: coding\n    output_mode: fixed_length\n",
        "  - name: coding\n    profile: coding\n",
    )
    issue = _only(parse_text, text)
    assert issue.code == "missing_key"
    assert issue.path == "workloads[1].output_mode"
    assert issue.message == "workload 'coding': 'output_mode' is required"
    assert issue.line == coding_workload_line


def test_unknown_output_mode_lists_allowed_values(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace("output_mode: fixed_length", "output_mode: streaming", 1)
    issue = _only(parse_text, text)
    assert issue.path == "workloads[0].output_mode"
    assert "'streaming'" in issue.message
    assert "'fixed_length'" in issue.message
    assert "'natural'" in issue.message


# --- union sources -------------------------------------------------------------------------


def test_missing_field_in_a_union_source_has_a_clean_path(
    parse_text: Parse, minimal_yaml: str
) -> None:
    text = minimal_yaml.replace("      path: wildchat/sample.jsonl\n", "")
    issue = _only(parse_text, text)
    assert issue.path == "workloads[0].source.path"
    assert issue.code == "missing_key"


def test_unknown_source_kind_lists_allowed_kinds(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace("kind: aiperf_builtin", "kind: http_download")
    issue = _only(parse_text, text)
    assert issue.path == "workloads[1].source"
    assert "'local_import'" in issue.message
    assert "'aiperf_builtin'" in issue.message


def test_strata_are_rejected_for_builtin_sources(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace(  # strata on the coding (builtin) workload
        "      sample_size: 100\n      seed: 7\n",
        "      sample_size: 100\n      seed: 7\n      strata:\n        turn_edges: [1, 2]\n",
    )
    issue = _only(parse_text, text)
    assert issue.path == "workloads[1]"
    assert "local_import" in issue.message


def test_strata_edges_must_increase(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace(
        "      sample_size: 200\n      seed: 7\n",
        "      sample_size: 200\n      seed: 7\n      strata:\n        turn_edges: [1, 4, 2]\n",
    )
    issue = _only(parse_text, text)
    assert issue.path == "workloads[0].sampling.strata.turn_edges"
    assert "strictly increasing" in issue.message


# --- strict types ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snippet", "path"),
    [
        ("repetitions: true\n", "repetitions"),
        ("repetitions: '3'\n", "repetitions"),
        ("slo:\n  per_request:\n    ttft_ms: '1500'\n", "slo.per_request.ttft_ms"),
        ("estimates:\n  deployment_start_s: .nan\n", "estimates.deployment_start_s"),
        ("estimates:\n  deployment_start_s: 0\n", "estimates.deployment_start_s"),
    ],
)
def test_strict_types_and_ranges(
    parse_text: Parse, minimal_yaml: str, snippet: str, path: str
) -> None:
    issue = _only(parse_text, minimal_yaml + snippet)
    assert issue.path == path
    assert issue.code == "invalid_value"


def test_error_rate_range_is_enforced(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml + "slo:\n  distribution:\n    max_error_rate: 1.5\n"
    issue = _only(parse_text, text)
    assert issue.path == "slo.distribution.max_error_rate"
    assert "less than 1" in issue.message


def test_engine_args_must_be_flag_names_with_scalar_values(
    parse_text: Parse, minimal_yaml: str
) -> None:
    text = minimal_yaml.replace(
        "    role: baseline\n", "    role: baseline\n    args:\n      max_num_seqs: 256\n"
    )
    issue = _only(parse_text, text)
    assert issue.path == "engines[0].args.max_num_seqs"


def test_engine_arg_values_cannot_be_lists(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace(
        "    role: baseline\n", "    role: baseline\n    args:\n      --max-num-seqs: [1, 2]\n"
    )
    issues = _issues(parse_text, text)
    assert {issue.path for issue in issues} == {"engines[0].args.--max-num-seqs"}


# --- uniqueness and required load ----------------------------------------------------------


def test_duplicate_workload_names_are_rejected(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace("  - name: coding\n", "  - name: general\n")
    issue = _only(parse_text, text)
    assert issue.path == "workloads"
    assert "general" in issue.message


def test_required_load_needs_exactly_one_unit(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace(
        "      seed: 7\n  - name: coding",
        "      seed: 7\n    required_load:\n      concurrency: 30\n      request_rate: 2.5\n"
        "  - name: coding",
    )
    issue = _only(parse_text, text)
    assert issue.path == "workloads[0].required_load"
    assert "exactly one" in issue.message


def test_all_problems_are_reported_together(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml + "repetitions: 0\nmystery: 1\n"
    paths = [issue.path for issue in _issues(parse_text, text)]
    assert paths == ["repetitions", "mystery"]
