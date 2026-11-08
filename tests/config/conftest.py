"""Shared config fixtures.

``MINIMAL_YAML`` contains only the fields that have no default. Its line
numbers are relied on by tests, so append new sections at the end.
"""

from collections.abc import Callable

import pytest

from engine_bench.config.loader import load_yaml_text
from engine_bench.config.schema import RawExperiment, parse_raw

MINIMAL_YAML = """\
name: baseline-comparison
shared:
  model:
    id: EXACT_MODEL_ID
    revision: EXACT_COMMIT
  precision: bfloat16
  max_context_tokens: 8192
  generation:
    max_output_tokens: 1024
  hardware:
    gpu_system: GPU_SYSTEM
    gpu_count: 1
    gpu_uuids: [GPU_UUID]
  load_generator:
    aiperf_version: EXACT_AIPERF_VERSION
engines:
  - name: vllm_baseline
    engine: vllm
    role: baseline
    image: vllm/vllm-openai@EXACT_IMAGE_DIGEST
workloads:
  - name: general
    profile: general
    output_mode: fixed_length
    source:
      kind: local_import
      importer: wildchat
      dataset_id: allenai/WildChat-1M
      revision: EXACT_DATASET_COMMIT
      path: wildchat/sample.jsonl
    sampling:
      sample_size: 200
      seed: 7
  - name: coding
    profile: coding
    output_mode: fixed_length
    source:
      kind: aiperf_builtin
      loader: instructcoder
      dataset_id: instructcoder
      revision: EXACT_DATASET_COMMIT
    sampling:
      sample_size: 100
      seed: 7
"""

# 1-based line of the second workload's `- name: coding` entry in MINIMAL_YAML.
CODING_WORKLOAD_LINE = MINIMAL_YAML.splitlines().index("  - name: coding") + 1


@pytest.fixture
def minimal_yaml() -> str:
    return MINIMAL_YAML


@pytest.fixture
def coding_workload_line() -> int:
    return CODING_WORKLOAD_LINE


@pytest.fixture
def parse_text() -> Callable[[str], RawExperiment]:
    def parse(text: str) -> RawExperiment:
        return parse_raw(load_yaml_text(text))

    return parse
