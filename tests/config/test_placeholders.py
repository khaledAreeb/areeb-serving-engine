from collections.abc import Callable

import pytest

from engine_bench.config.issues import ConfigError, Issue
from engine_bench.config.placeholders import KNOWN_PLACEHOLDERS, Placeholder, placeholder_in
from engine_bench.config.schema import RawExperiment

Parse = Callable[[str], RawExperiment]

COMMIT = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "sha256:" + "ab" * 32


def _only(parse: Parse, text: str) -> Issue:
    with pytest.raises(ConfigError) as info:
        parse(text)
    assert len(info.value.issues) == 1, [i.format() for i in info.value.issues]
    return info.value.issues[0]


def test_all_named_placeholders_exist() -> None:
    assert {
        "EXACT_MODEL_ID",
        "EXACT_COMMIT",
        "EXACT_DATASET_COMMIT",
        "GPU_SYSTEM",
        "GPU_UUID",
        "EXACT_IMAGE_DIGEST",
        "EXACT_AIPERF_VERSION",
    } == KNOWN_PLACEHOLDERS


def test_each_field_accepts_its_own_placeholder(parse_text: Parse, minimal_yaml: str) -> None:
    raw = parse_text(minimal_yaml)  # MINIMAL_YAML uses every placeholder in its own field
    assert raw.shared.model.id == "EXACT_MODEL_ID"
    assert raw.shared.model.revision == "EXACT_COMMIT"
    assert raw.shared.hardware.gpu_system == "GPU_SYSTEM"
    assert raw.shared.hardware.gpu_uuids == ["GPU_UUID"]
    assert raw.shared.load_generator.aiperf_version == "EXACT_AIPERF_VERSION"
    assert raw.engines[0].image == "vllm/vllm-openai@EXACT_IMAGE_DIGEST"
    assert raw.workloads[0].source.revision == "EXACT_DATASET_COMMIT"


def test_real_values_are_accepted(parse_text: Parse, minimal_yaml: str) -> None:
    text = (
        minimal_yaml.replace("id: EXACT_MODEL_ID", "id: org/model-7b")
        .replace("revision: EXACT_COMMIT", f"revision: {COMMIT}")
        .replace("gpu_system: GPU_SYSTEM", "gpu_system: h100_sxm")
        .replace("[GPU_UUID]", "[GPU-6a7c0f2e-1b3d-4e5f-8a9b-0c1d2e3f4a5b]")
        .replace("aiperf_version: EXACT_AIPERF_VERSION", "aiperf_version: 0.3.0")
        .replace("@EXACT_IMAGE_DIGEST", f":v0.9.0@{DIGEST}")
        .replace("revision: EXACT_DATASET_COMMIT", f"revision: {COMMIT}")
    )
    raw = parse_text(text)
    assert raw.shared.model.revision == COMMIT
    assert raw.engines[0].image == f"vllm/vllm-openai:v0.9.0@{DIGEST}"


# --- a placeholder in the wrong field -------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "path", "accepted"),
    [
        ("revision: EXACT_COMMIT", "revision: GPU_SYSTEM", "shared.model.revision", "EXACT_COMMIT"),
        ("id: EXACT_MODEL_ID", "id: GPU_SYSTEM", "shared.model.id", "EXACT_MODEL_ID"),
        (
            "gpu_system: GPU_SYSTEM",
            "gpu_system: EXACT_MODEL_ID",
            "shared.hardware.gpu_system",
            "GPU_SYSTEM",
        ),
        ("[GPU_UUID]", "[GPU_SYSTEM]", "shared.hardware.gpu_uuids[0]", "GPU_UUID"),
        (
            "aiperf_version: EXACT_AIPERF_VERSION",
            "aiperf_version: EXACT_COMMIT",
            "shared.load_generator.aiperf_version",
            "EXACT_AIPERF_VERSION",
        ),
        (
            "revision: EXACT_DATASET_COMMIT",
            "revision: EXACT_COMMIT",
            "workloads[0].source.revision",
            "EXACT_DATASET_COMMIT",
        ),
    ],
)
def test_placeholder_in_the_wrong_field_is_rejected(
    parse_text: Parse, minimal_yaml: str, old: str, new: str, path: str, accepted: str
) -> None:
    issue = _only(parse_text, minimal_yaml.replace(old, new, 1))
    assert issue.path == path
    assert accepted in issue.message


def test_wrong_placeholder_in_the_image_digest_is_rejected(
    parse_text: Parse, minimal_yaml: str
) -> None:
    text = minimal_yaml.replace("@EXACT_IMAGE_DIGEST", "@EXACT_COMMIT")
    issue = _only(parse_text, text)
    assert issue.path == "engines[0].image"
    assert "EXACT_IMAGE_DIGEST" in issue.message


# --- revisions -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "revision", ["main", "v1.0", COMMIT[:7], COMMIT.upper(), COMMIT + "0", "refs/pr/1"]
)
def test_revisions_must_be_full_lowercase_commit_hashes(
    parse_text: Parse, minimal_yaml: str, revision: str
) -> None:
    text = minimal_yaml.replace("revision: EXACT_COMMIT", f"revision: '{revision}'")
    issue = _only(parse_text, text)
    assert issue.path == "shared.model.revision"
    assert "full 40-character" in issue.message


def test_unquoted_numeric_revision_gets_a_quoting_hint(
    parse_text: Parse, minimal_yaml: str
) -> None:
    text = minimal_yaml.replace("revision: EXACT_COMMIT", "revision: 0123456")
    issue = _only(parse_text, text)
    assert issue.path == "shared.model.revision"
    assert "quote it" in issue.message


def test_dataset_revision_branch_name_is_rejected(parse_text: Parse, minimal_yaml: str) -> None:
    text = minimal_yaml.replace("revision: EXACT_DATASET_COMMIT", "revision: main", 1)
    issue = _only(parse_text, text)
    assert issue.path == "workloads[0].source.revision"
    assert "EXACT_DATASET_COMMIT" in issue.message


# --- images -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "image", ["vllm/vllm-openai:latest", "vllm/vllm-openai", "lmsysorg/sglang:v0.4.0"]
)
def test_tag_only_images_are_rejected(parse_text: Parse, minimal_yaml: str, image: str) -> None:
    text = minimal_yaml.replace("vllm/vllm-openai@EXACT_IMAGE_DIGEST", image)
    issue = _only(parse_text, text)
    assert issue.path == "engines[0].image"
    assert "pinned by digest" in issue.message


@pytest.mark.parametrize(
    "digest", ["sha256:abc", "sha256:" + "AB" * 32, "md5:" + "ab" * 16, "latest"]
)
def test_malformed_digests_are_rejected(parse_text: Parse, minimal_yaml: str, digest: str) -> None:
    text = minimal_yaml.replace("@EXACT_IMAGE_DIGEST", f"@{digest}")
    issue = _only(parse_text, text)
    assert issue.path == "engines[0].image"
    assert "sha256" in issue.message


def test_bare_placeholder_image_points_to_the_repository_form(
    parse_text: Parse, minimal_yaml: str
) -> None:
    text = minimal_yaml.replace("vllm/vllm-openai@EXACT_IMAGE_DIGEST", "EXACT_IMAGE_DIGEST")
    issue = _only(parse_text, text)
    assert "<repository>@EXACT_IMAGE_DIGEST" in issue.message


# --- versions and free-text fields ---------------------------------------------------


@pytest.mark.parametrize("version", ["latest", ">=0.3", "v0.3.0", "0.3.*"])
def test_load_generator_version_must_be_exact(
    parse_text: Parse, minimal_yaml: str, version: str
) -> None:
    text = minimal_yaml.replace("EXACT_AIPERF_VERSION", f"'{version}'")
    issue = _only(parse_text, text)
    assert issue.path == "shared.load_generator.aiperf_version"


@pytest.mark.parametrize("version", ["0.3.0", "1.2", "1.2.0rc1", "0.3.0.post1", "1.0.0+cu124"])
def test_exact_versions_are_accepted(parse_text: Parse, minimal_yaml: str, version: str) -> None:
    raw = parse_text(minimal_yaml.replace("EXACT_AIPERF_VERSION", f"'{version}'"))
    assert raw.shared.load_generator.aiperf_version == version


def test_model_id_cannot_contain_whitespace(parse_text: Parse, minimal_yaml: str) -> None:
    issue = _only(parse_text, minimal_yaml.replace("id: EXACT_MODEL_ID", "id: 'my model'"))
    assert issue.path == "shared.model.id"


# --- placeholder lookup ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("EXACT_COMMIT", Placeholder.COMMIT),
        ("vllm/vllm-openai@EXACT_IMAGE_DIGEST", Placeholder.IMAGE_DIGEST),
        (f"vllm/vllm-openai@{DIGEST}", None),
        ("org/model-7b", None),
    ],
)
def test_placeholder_in(value: str, expected: Placeholder | None) -> None:
    assert placeholder_in(value) is expected
