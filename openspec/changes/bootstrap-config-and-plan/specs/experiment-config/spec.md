# Spec Delta

## Purpose

Defines the experiment configuration that drives every engine-bench run: one versioned YAML file that is fair across engines by construction, holds undecided values as explicit placeholders, and can be fully validated offline before any GPU time is spent.

## ADDED Requirements

### Requirement: Experiment config file format
An experiment SHALL be defined by a single YAML file. Loading SHALL reject unknown keys, duplicate keys at any nesting level, and values of the wrong type. Each rejection SHALL report the offending key path and, where available, the line number.

#### Scenario: Unknown key is rejected
- **WHEN** the config contains a key that the schema does not define (for example `slo.ttft_p59_ms`)
- **THEN** validation fails and the report names the key path `slo.ttft_p59_ms`

#### Scenario: Duplicate key is rejected
- **WHEN** the same key appears twice in one mapping
- **THEN** validation fails instead of silently keeping either value, and the report names the key and its line

### Requirement: Shared fairness block
Everything that must be identical across engines SHALL be declared exactly once, in a shared block that applies to every engine config: model ID, model revision, tokenizer, chat template, precision, maximum context length, generation settings, GPU system, GPU count and GPU UUIDs, client location, random seeds, workload selection, and the timing policy. Engine configs SHALL NOT be able to override any of these.

#### Scenario: Engine config tries to override a shared field
- **WHEN** an engine config sets an engine argument that the engine's fairness map ties to a shared field (for example a maximum-context-length or precision flag)
- **THEN** validation fails, naming the engine config, the argument, and the shared field it would override

#### Scenario: Fairness map entry is unverified
- **WHEN** an engine's fairness map entries have not yet been verified against the pinned engine image
- **THEN** validation still applies them and reports a warning saying the map is unverified for that engine

### Requirement: Engine configurations
Each engine config SHALL name an engine kind (`vllm`, `sglang` or `trtllm`), a role (`baseline` or `tuned`), a container image pinned by digest, and engine arguments given as a mapping from argument name to scalar value, never as a shell string. Each engine kind in the experiment SHALL have exactly one baseline config. Every engine kind SHALL declare the same number of tuned configs, and that number SHALL NOT exceed the declared per-engine tuning budget.

#### Scenario: Image given by tag
- **WHEN** an engine config's image is `vllm/vllm-openai:latest` or any reference without a `@sha256:` digest
- **THEN** validation fails and says that images must be pinned by digest

#### Scenario: Unequal tuning budget
- **WHEN** `vllm` declares two tuned configs and `sglang` declares one
- **THEN** validation fails, reporting the tuned-config count per engine kind

#### Scenario: Missing baseline
- **WHEN** an engine kind has no config with role `baseline`
- **THEN** validation fails, naming the engine kind

### Requirement: Named placeholders for undecided values
Fields whose values are not decided yet SHALL accept a named placeholder instead of a real value: `EXACT_MODEL_ID` (model ID), `EXACT_COMMIT` (model revision), `EXACT_DATASET_COMMIT` (dataset revisions), `GPU_SYSTEM` (GPU system), `GPU_UUID` (each GPU UUID), `EXACT_IMAGE_DIGEST` (image digest) and `EXACT_AIPERF_VERSION` (load-generator version). Each field SHALL accept only its own placeholder. Validation SHALL list every unresolved placeholder with its key path.

#### Scenario: Config with placeholders validates with warnings
- **WHEN** a config is otherwise valid but uses `EXACT_MODEL_ID` and `GPU_SYSTEM`
- **THEN** validation succeeds and lists both placeholders as unresolved, with their key paths

#### Scenario: Strict mode rejects placeholders
- **WHEN** the same config is validated in strict mode
- **THEN** validation fails because placeholders are unresolved

#### Scenario: Wrong placeholder in a field
- **WHEN** the model revision field contains `GPU_SYSTEM`
- **THEN** validation fails because that field accepts only `EXACT_COMMIT` or a real revision

### Requirement: Pinned revisions
Model and dataset revisions SHALL be full 40-character hexadecimal commit hashes, or their placeholder. Branch names, tags and short hashes SHALL be rejected.

#### Scenario: Branch name as revision
- **WHEN** the model revision is `main`
- **THEN** validation fails and says that revisions must be full commit hashes

### Requirement: Secrets by reference only
The config SHALL refer to secrets only by environment variable name (for example `hf_token_env: HF_TOKEN`). Validation SHALL reject any string value anywhere in the config that matches a known secret-token pattern, and SHALL NOT echo the matched value in its output.

#### Scenario: Token pasted into config
- **WHEN** a string value in the config looks like a Hugging Face access token
- **THEN** validation fails, names the key path, and shows the value redacted

### Requirement: Two kinds of SLO
The config SHALL define two separate SLO groups. Per-request limits (`ttft_ms`, `e2e_deadline_ms`) decide whether an individual request counts toward goodput and attainment. Distribution limits (`ttft_p95_ms`, `max_error_rate`) decide whether a cell passes or fails. When omitted, the defaults SHALL be `ttft_ms` 1500, `e2e_deadline_ms` 60000, `ttft_p95_ms` 1500 and `max_error_rate` 0.01. All four SHALL be overridable, and limits SHALL be positive, with `max_error_rate` in the range [0, 1).

#### Scenario: Defaults applied
- **WHEN** the config omits the SLO section
- **THEN** the resolved config contains `ttft_ms: 1500`, `e2e_deadline_ms: 60000`, `ttft_p95_ms: 1500` and `max_error_rate: 0.01`

#### Scenario: Invalid error budget
- **WHEN** `max_error_rate` is `1.5`
- **THEN** validation fails, naming the field and the allowed range

### Requirement: Timing policy
The shared timing policy SHALL define a warm-up period, a measurement window (target duration, minimum completed requests and maximum duration), a client request timeout, and a drain timeout. The request timeout SHALL be greater than or equal to the per-request `e2e_deadline_ms`, so that requests exceeding the deadline are observed rather than cut off early. When omitted, the defaults SHALL be:

| setting | default |
|---|---|
| warm-up | 60 s |
| measurement target | 180 s |
| minimum completed requests | 50 |
| maximum measurement duration | 900 s |
| request timeout | equal to `e2e_deadline_ms` |
| drain timeout | equal to the request timeout |

Every one of these values SHALL be overridable.

#### Scenario: Timing defaults applied
- **WHEN** the config omits the timing section and keeps the default deadline
- **THEN** the resolved timing is: 60 s warm-up, 180 s target, at least 50 completed requests, 900 s maximum, and 60000 ms for both the request timeout and the drain timeout

#### Scenario: Timeout shorter than deadline
- **WHEN** the request timeout is 30000 ms and `e2e_deadline_ms` is 60000
- **THEN** validation fails and says that the timeout must be at least the deadline

### Requirement: Load-search policy
The config SHALL define the adaptive capacity-frontier search. Its parameters are: a coarse concurrency grid (default `[1, 5, 10, 20]`), an upward extension factor (default 2), a concurrency cap (default 256), a maximum number of refinement steps (default 3), a refinement resolution as a fraction of the passing load (default 0.10), open-loop confirmation rate fractions (default `[1.0, 0.9, 0.8]`), and a minimum ratio of achieved to offered rate for an open-loop point to pass (default 0.95). The grid SHALL be strictly increasing positive integers no larger than the cap. Rate fractions SHALL be in (0, 1] and strictly decreasing.

#### Scenario: Grid not increasing
- **WHEN** the coarse grid is `[1, 10, 5]`
- **THEN** validation fails, naming the grid

#### Scenario: Grid exceeds cap
- **WHEN** the coarse grid contains 512 and the cap is 256
- **THEN** validation fails, naming both values

### Requirement: Optional required load
Each workload MAY declare a `required_load`, given as either a concurrency or a request rate. It SHALL be optional and empty by default. When a required concurrency exceeds the search cap, validation SHALL warn that the target cannot be reached by the search.

#### Scenario: Required load above the cap
- **WHEN** a workload's `required_load` is concurrency 400 and the cap is 256
- **THEN** validation succeeds with a warning that this target is above the highest load the search can test

### Requirement: Measurement validity limits
The config SHALL define client-saturation limits: a maximum client CPU utilization (default 85%) and an optional maximum client network utilization. Repetitions SHALL default to 3 and SHALL be at least 1. When repetitions are fewer than 3, validation SHALL warn that the experiment cannot produce a Winner outcome.

#### Scenario: Default saturation limit
- **WHEN** the config omits client-saturation limits
- **THEN** the resolved config has a client CPU limit of 85% and no network limit

#### Scenario: Too few repetitions
- **WHEN** repetitions is 2
- **THEN** validation succeeds with a warning that fewer than 3 repetitions cannot yield a Winner

### Requirement: Experiment dimensions
The config SHALL declare the cache regimes to test, from `unique_prefix` and `warm_shared_prefix`, and they SHALL default to both. The cache-reset method SHALL be one of `auto` (flush if the engine's flush endpoint is verified, otherwise restart), `flush` or `restart`, and SHALL default to `auto`.

#### Scenario: Default cache regimes
- **WHEN** the config omits cache regimes
- **THEN** the resolved config contains both `unique_prefix` and `warm_shared_prefix`

### Requirement: Explicit output mode per workload
Every workload SHALL declare its `output_mode` explicitly, as either `fixed_length` (output length forced to the recorded target) or `natural` (stop at end of sequence, capped by the maximum output tokens). There SHALL be no default: a workload without `output_mode` is a validation error. When any workload declares `fixed_length` while the capability table marks the fixed-length output method as unverified for an engine kind in the experiment, validation SHALL report a compatibility warning that names each such engine kind and the affected workloads.

#### Scenario: Output mode missing
- **WHEN** a workload has no `output_mode`
- **THEN** validation fails, naming the workload and saying that `output_mode` is required

#### Scenario: Unknown output mode
- **WHEN** a workload's `output_mode` is `streaming`
- **THEN** validation fails and lists the allowed values

#### Scenario: Fixed-length on an unverified engine
- **WHEN** workload `coding` declares `fixed_length` and the capability table marks fixed-length output as unverified for `sglang`, which is in the experiment
- **THEN** validation succeeds with a compatibility warning that names `sglang` and the workload `coding`

#### Scenario: Natural output needs no verification
- **WHEN** every workload declares `natural`
- **THEN** validation reports no fixed-length compatibility warning

### Requirement: Overridable planning estimates
The config SHALL have an `estimates` block for durations the planner cannot know in advance. Its defaults SHALL be: `deployment_start_s` 600, `deployment_stop_s` 60, `cache_flush_s` 10 and `cell_overhead_s` 30. Every value SHALL be overridable and SHALL be a positive number. The estimates SHALL NOT affect any deployment, series or cell ID.

#### Scenario: Override deployment start
- **WHEN** the config sets `estimates.deployment_start_s: 300`
- **THEN** the resolved config uses 300 for the deployment start estimate and keeps the other estimate defaults

### Requirement: Optional cost rate
The config MAY declare an operator-supplied hourly cost rate per GPU and a currency code. When it is absent, every cost figure derived from the config SHALL be reported as unavailable, never as zero.

#### Scenario: No cost rate
- **WHEN** the config has no cost rate
- **THEN** the resolved config records cost as unavailable

### Requirement: Validate command
`engine-bench validate CONFIG` SHALL check the config against every rule in this capability without network or GPU access. It SHALL print errors and warnings, each with its key path, and SHALL exit 0 when there are no errors, 1 when there are errors (or, in `--strict` mode, any warnings or unresolved placeholders), and 2 on a usage error such as a missing file. With `--json` it SHALL print a machine-readable report that contains the resolved config (with defaults filled in), the errors, the warnings and the unresolved placeholders.

#### Scenario: Valid config
- **WHEN** a config has no errors and no warnings
- **THEN** the command exits 0 and reports that it is valid

#### Scenario: Missing file
- **WHEN** the config path does not exist
- **THEN** the command exits 2 with a message naming the path

#### Scenario: JSON report
- **WHEN** the command runs with `--json` on a config that has one warning
- **THEN** it prints a JSON object with the resolved config, an empty error list, one warning and the placeholder list, and exits 0
