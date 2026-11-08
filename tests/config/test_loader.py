from pathlib import Path

import pytest

from engine_bench.config.issues import ConfigError
from engine_bench.config.loader import load_yaml_file, load_yaml_text, parent_path


def _single_issue(text: str) -> tuple[str, str, int | None, str]:
    with pytest.raises(ConfigError) as info:
        load_yaml_text(text)
    assert len(info.value.issues) == 1
    issue = info.value.issues[0]
    return issue.code, issue.path, issue.line, issue.message


# --- plain data -------------------------------------------------------------------


def test_returns_json_native_types() -> None:
    loaded = load_yaml_text(
        "b: true\nanchored: &flag false\nn: null\ni: 3\nh: 0x1F\nf: 2.5\ns: text\ny: yes\n"
    )
    values = loaded.data
    assert values == {
        "b": True,
        "anchored": False,
        "n": None,
        "i": 3,
        "h": 31,
        "f": 2.5,
        "s": "text",
        "y": "yes",  # YAML 1.2: yes is a string, not a boolean
    }
    assert type(values["b"]) is bool
    assert type(values["anchored"]) is bool
    assert type(values["h"]) is int
    assert type(values["f"]) is float
    assert type(values["s"]) is str


def test_nested_structures_become_dicts_and_lists() -> None:
    loaded = load_yaml_text("engines:\n  - name: a\n    args: {--x: 1}\n")
    assert loaded.data == {"engines": [{"name": "a", "args": {"--x": 1}}]}
    assert type(loaded.data["engines"]) is list
    assert type(loaded.data["engines"][0]) is dict


# --- line map ---------------------------------------------------------------------


def test_line_map_covers_keys_and_list_items() -> None:
    text = (
        "name: x\n"  # 1
        "slo:\n"  # 2
        "  per_request:\n"  # 3
        "    ttft_ms: 1500\n"  # 4
        "engines:\n"  # 5
        "  - name: a\n"  # 6
        "  - name: b\n"  # 7
        "    image: img\n"  # 8
    )
    loaded = load_yaml_text(text)
    assert loaded.lines["name"] == 1
    assert loaded.lines["slo.per_request.ttft_ms"] == 4
    assert loaded.lines["engines[1]"] == 7
    assert loaded.lines["engines[1].image"] == 8


def test_line_for_falls_back_to_nearest_ancestor() -> None:
    loaded = load_yaml_text("slo:\n  per_request:\n    ttft_ms: 1500\n")
    assert loaded.line_for("slo.per_request.e2e_deadline_ms") == 2
    assert loaded.line_for("unknown") is None


def test_parent_path() -> None:
    assert parent_path("engines[1].image") == "engines[1]"
    assert parent_path("engines[1]") == "engines"
    assert parent_path("engines") == ""
    assert parent_path("") is None


# --- duplicate keys ---------------------------------------------------------------


def test_duplicate_top_level_key_is_rejected_with_key_and_line() -> None:
    code, path, line, message = _single_issue("name: a\nrepetitions: 3\nname: b\n")
    assert code == "duplicate_key"
    assert path == "name"
    assert line == 3
    assert "'name'" in message


def test_duplicate_nested_key_is_rejected_with_full_path_and_line() -> None:
    text = "slo:\n  per_request:\n    ttft_ms: 1500\n    ttft_ms: 900\n"
    code, path, line, message = _single_issue(text)
    assert code == "duplicate_key"
    assert path == "slo.per_request.ttft_ms"
    assert line == 4
    assert "'ttft_ms'" in message


def test_duplicate_key_inside_a_list_item_is_rejected() -> None:
    code, _, line, _ = _single_issue("engines:\n  - name: a\n    name: b\n")
    assert code == "duplicate_key"
    assert line == 3


# --- tags and unsupported values --------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "a: !!python/object/apply:os.system ['echo hi']\n",
        "a: !!python/object:builtins.dict {}\n",
        "a: !custom value\n",
        "a: !custom {x: 1}\n",
        "a: !!str 5\n",
    ],
)
def test_yaml_tags_are_rejected(text: str) -> None:
    code, path, line, message = _single_issue(text)
    assert code == "yaml_tag"
    assert path == "a"
    assert line == 1
    assert "tags are not allowed" in message


def test_dates_are_rejected_with_a_hint_to_quote() -> None:
    code, path, _, message = _single_issue("revision: 2024-01-01\n")
    assert (code, path) == ("unsupported_value", "revision")
    assert "quote" in message


def test_non_string_keys_are_rejected() -> None:
    code, _, line, _ = _single_issue("args:\n  1: x\n")
    assert code == "non_string_key"
    assert line == 2


def test_multiple_problems_are_all_reported() -> None:
    with pytest.raises(ConfigError) as info:
        load_yaml_text("a: !x 1\nb: 2024-01-01\n")
    assert [issue.code for issue in info.value.issues] == ["yaml_tag", "unsupported_value"]


# --- document-level errors --------------------------------------------------------


def test_syntax_error_reports_a_line() -> None:
    code, _, line, message = _single_issue("a: 1\nb: [1, 2\n")
    assert code == "yaml_syntax"
    assert line is not None
    assert message.startswith("YAML syntax error")


@pytest.mark.parametrize(
    ("text", "code"),
    [("", "empty_config"), ("# only a comment\n", "empty_config"), ("- a\n- b\n", "invalid_root")],
)
def test_root_must_be_a_mapping(text: str, code: str) -> None:
    assert _single_issue(text)[0] == code


def test_missing_file_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_yaml_file(tmp_path / "missing.yaml")


def test_file_source_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    path.write_text("name: x\n", encoding="utf-8")
    assert load_yaml_file(path).source == str(path)
