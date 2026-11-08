# Tool versions and unverified facts

This file is the single list of external facts that engine-bench depends on. Each one is either pinned and confirmed, or marked **TODO-verify** with the change that will confirm it. Never code against an unverified fact as if it were true. Keep it as data marked `verified: false` (see `src/engine_bench/config/capabilities.yaml`, added in change 1 group 4) until it has been checked against the pinned version.

Status legend:

- **pinned**: exact version recorded and in use.
- **TODO-verify (change N)**: not yet confirmed; change N confirms it and updates this file.
- **observed**: seen in upstream docs, but not yet checked against an installed, pinned version.

## Python toolchain

| Item | Status | Notes |
|---|---|---|
| Python | pinned floor `>=3.11` | Developed on CPython 3.13.13; ruff and mypy target py311. CI covers 3.11 in change 6. |
| Runtime and dev dependencies | pinned | Exact versions are locked in `uv.lock` (pydantic, typer, ruamel.yaml, structlog, pytest, ruff, mypy). |
| typer 0.28 | pinned | Vendors click privately as `typer._click`. engine-bench uses only Typer's public exceptions (`typer.Exit`, `typer.Abort`, `typer.exceptions.TyperException`). |

## AIPerf (load generator)

| Fact | Used by | Status | Notes |
|---|---|---|---|
| AIPerf version | config `EXACT_AIPERF_VERSION`, built-in workload identity, cell IDs | TODO-verify (change 2) | Pin the exact version after installing it in a venv. |
| CLI command and flags for one profiling run | `benchmarks/` | TODO-verify (change 2) | Confirm them from `aiperf --help` of the pinned version. |
| Export file names and formats | `benchmarks/`, `metrics/` | observed, TODO-verify (change 2) | The README mentions `profile_export_aiperf.json` and `profile_export_aiperf.csv` under `artifacts/<run-name>/`. Save real samples as contract-test fixtures. |
| Goodput semantics (per-request SLO thresholds) | `analysis/` | TODO-verify (change 2) | Use AIPerf goodput only where it matches our per-request limits (`ttft_ms`, `e2e_deadline_ms`). |
| Built-in loader names: InstructCoder, TraceLab | `workloads/builtin.py`, workload identity | observed, TODO-verify (change 2) | Both are listed as public datasets in the AIPerf README. |
| Built-in loader parameters (sampling, seed, sample size, length/size settings) | workload identity | TODO-verify (change 2) | Every parameter that changes content must enter the identity hash. |
| Observing the inputs AIPerf actually sent | workload content hash for built-ins | TODO-verify (change 2) | The README mentions `inputs.json` replay. Until this is confirmed, built-in content hashes stay `unavailable`. |
| Multi-turn input format | `benchmarks/` translation of canonical sessions | TODO-verify (change 2) | The README mentions `multi_turn` inline datasets. |
| GPU telemetry via DCGM | `metrics/` | observed, TODO-verify (change 3) | |

## AISimulate (CPU-only pre-screen)

| Fact | Used by | Status | Notes |
|---|---|---|---|
| AISimulate version | `simulation/` | TODO-verify (change 5) | NVIDIA Dynamo docs pinned `aisimulate==0.12.0` for the compatibility command when last checked. Re-check at implementation time. |
| Support-check command | `simulation/` | observed, TODO-verify (change 5) | `aiconfigurator cli support --model-path <MODEL> --system <SYSTEM> [--backend <vllm\|sglang\|trtllm> --backend-version <VER>]`. Planned for removal in 0.14.0. |
| Support-check result parsing | `simulation/` | TODO-verify (change 5) | Exit code 0 only means the query ran. Parse the actual YES/NO result. |
| Support matrix coverage for our model, GPU and engines | fairness rule for shortlisting | TODO-verify (change 5) | Docs describe silicon-validated data for TensorRT-LLM and SGLang on H100, H200 and B200, and vLLM on select platforms. |

## Serving engines (design D7)

All entries below live in `config/capabilities.yaml` with `verified: false` until change 3 checks them against the pinned images.

| Fact | Engines | Status | Notes |
|---|---|---|---|
| Container image digests | vLLM, SGLang | TODO-verify (change 3) | Config placeholder `EXACT_IMAGE_DIGEST`; images are always pinned by `@sha256:` digest. |
| Adapter availability in the MVP | vLLM, SGLang (mvp); TensorRT-LLM (later) | decided | TensorRT-LLM deployments are planned as `UNSUPPORTED` until its adapter exists. |
| Fairness map: engine flags that control shared fields (model and revision, tokenizer, chat template, precision/quantization, max context length, seed) | vLLM, SGLang | TODO-verify (change 3) | Confirm the flag names from each pinned image's `--help`. Until then, `validate` enforces the map and warns that it is unverified. |
| Prefix-cache flush endpoint | vLLM, SGLang | TODO-verify (change 3) | Until verified, cache reset `auto` plans a restart between cells. Confirm the endpoint name and any server flag it requires. |
| Fixed-length output method (forcing output to the recorded length) | vLLM, SGLang | TODO-verify (change 3) | Until verified, `validate` warns and `plan` lists a compatibility issue for every workload with `output_mode: fixed_length`. |

## Datasets (design D12)

| Fact | Used by | Status | Notes |
|---|---|---|---|
| WildChat dataset ID and variant | config | TODO-verify (user confirmation) | Decided when the user confirms the download. The dataset is gated on Hugging Face; the token comes from an environment variable (`HF_TOKEN`), never from the config. |
| WildChat revision (40-hex commit) | config `EXACT_DATASET_COMMIT` | TODO-verify (user confirmation) | |
| WildChat field names (conversation turns, role, content, language, turn count) | `workloads/wildchat.py` (`FIELD_MAP_VERSION`) | TODO-verify (before first real import) | The test fixture is synthetic and mimics the documented schema. Confirm against the dataset card at the pinned revision. |
| Stratification bucket edges | config | proposal | Input tokens 0/512/2048/8192/∞, turns 1/2/4/∞. Configurable. |

## Model and hardware

| Fact | Status | Notes |
|---|---|---|
| Model ID and revision | undecided | Placeholders `EXACT_MODEL_ID`, `EXACT_COMMIT`. |
| Real tokenizer for token counting | undecided | Added once the model is chosen. Until then, `approx-utf8-bytes-div4/v1` is used and every manifest is provisional. |
| GPU system, count and UUIDs | undecided | Placeholders `GPU_SYSTEM`, `GPU_UUID`. |
| Target traffic (`required_load`) | undecided | Optional per workload; empty for now. |
