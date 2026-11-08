# Spec Delta

## Purpose

Turns a validated experiment config into a deterministic, offline plan: the deployments and cells to run, their stable content-hash IDs, the adaptive capacity-frontier search that decides which load points to measure, compatibility issues, and a GPU-time and cost budget with explicit assumptions. It also defines the versioned prior-results contract that later re-planning will consume.

## ADDED Requirements

### Requirement: Terminology
The plan SHALL use these units:
- A **deployment** is one engine config × one repetition. Each deployment runs on a fresh engine instance.
- A **series** is one engine config × workload × cache regime, across all repetitions. The output mode is part of the workload declaration, so each series has exactly one output mode.
- A **cell** is one series × repetition × load point, where a load point is either a closed-loop concurrency or an open-loop request rate. Every cell belongs to exactly one deployment.

#### Scenario: Cell membership
- **WHEN** the plan contains a cell for engine config `vllm_baseline`, repetition 1, workload `general` (output mode `fixed_length`), cache regime `unique_prefix` and concurrency 10
- **THEN** that cell is listed under the deployment for `vllm_baseline` repetition 1

### Requirement: Deployment order with engine rotation
The plan SHALL order deployments by repetition first. Within repetition `r`, engine kinds SHALL appear in the declared order rotated left by `r mod n`, where `n` is the number of engine kinds. Within one engine kind, the baseline config SHALL come first, followed by tuned configs in declared order.

#### Scenario: Two engines, three repetitions
- **WHEN** engine kinds are declared as `[vllm, sglang]`, each with only a baseline, and repetitions is 3
- **THEN** the deployment order is: vllm r0, sglang r0, sglang r1, vllm r1, vllm r2, sglang r2

### Requirement: Stable content-hash identifiers
Deployments, series and cells SHALL have IDs derived from a SHA-256 hash of the canonical form of every resolved input that affects the measurement: the shared fairness block, the engine config (kind, image digest, arguments), the workload identity hash, the workload's output mode, cache regime, load point, timing policy, cache-reset method, the load-generator version and, for deployments and cells, the repetition index. IDs SHALL NOT depend on YAML key order, formatting, comments, the experiment name, SLO limits, the search policy, required load, validity thresholds or cost rate. A hash-scheme version SHALL be part of the hashed content.

#### Scenario: Reordering keys keeps IDs
- **WHEN** two configs differ only in key order and comments
- **THEN** every deployment, series and cell ID in their plans is identical

#### Scenario: SLO change keeps IDs
- **WHEN** two configs differ only in `ttft_p95_ms`
- **THEN** every cell ID is identical, so existing measurements can be re-scored without re-running

#### Scenario: Measurement-affecting change alters IDs
- **WHEN** two configs differ in the engine image digest of `sglang_baseline`
- **THEN** every deployment and cell ID for `sglang_baseline` differs, and all other IDs are unchanged

### Requirement: Adaptive capacity-frontier search
For each series, the plan SHALL use a deterministic search policy that, given the ordered pass/fail/invalid observations of the series' discovery repetition (repetition 0), returns either the next load point to measure or a final search result. The policy SHALL:
1. Measure the coarse concurrency grid in ascending order.
2. If the first grid point fails, stop with result `no_feasible_load`.
3. If every grid point passes, extend upward by multiplying the last point by the extension factor, rounding up, capped at the concurrency cap. If the cap passes, stop extending with the frontier marked `capped`.
4. After the first failure, bisect between the highest passing and lowest failing concurrency until their gap is at most `max(1, ceil(passing × resolution))` or the refinement-step limit is reached.
5. Confirm with open-loop rates equal to the achieved request rate at the highest passing concurrency multiplied by each confirmation fraction in descending order, rounded to 2 decimal places, stopping at the first passing rate. If none passes, the frontier rate is `unconfirmed`.
6. If any observation is `invalid` (for example a saturated client), stop with result `blocked`, naming the invalid load point.

The policy SHALL never propose a load point above the cap, and SHALL never return a frontier above the highest measured passing load.

#### Scenario: Break inside the coarse grid
- **WHEN** concurrency 1, 5 and 10 pass and 20 fails, with resolution 0.10 and 3 refinement steps
- **THEN** the policy proposes 15, then bisects within (10, 20) based on each outcome until the gap is at most 1 or 3 steps are used, then proposes open-loop confirmation rates

#### Scenario: Everything passes
- **WHEN** the grid `[1, 5, 10, 20]` all passes with factor 2 and cap 256
- **THEN** the policy proposes 40, 80, 160 and then 256, and if 256 passes the frontier is marked `capped`

#### Scenario: Lowest load fails
- **WHEN** concurrency 1 fails
- **THEN** the search stops with `no_feasible_load` and proposes no further points

#### Scenario: Open-loop confirmation
- **WHEN** the highest passing concurrency is 14 with an achieved rate of 3.456 req/s, and the fractions are `[1.0, 0.9, 0.8]`
- **THEN** the policy proposes 3.46 req/s; if that fails, 3.11 req/s; if that fails, 2.76 req/s; and if all fail, the frontier rate is `unconfirmed`

#### Scenario: Client saturation blocks the search
- **WHEN** the observation at concurrency 80 is `invalid`
- **THEN** the search stops with `blocked`, naming concurrency 80

### Requirement: Repetitions mirror the discovery repetition
Repetitions after the discovery repetition SHALL measure exactly the load points the discovery repetition measured, in the same order, including failing points and open-loop rates, so that every measured load point has the same number of repetitions. Until discovery for a series completes, the plan SHALL list that series' later repetitions as pending discovery, not as concrete cells.

#### Scenario: Plan before any measurement
- **WHEN** a plan is made with no prior results
- **THEN** repetition 0 lists the coarse-grid cells as conditional (each runs only if the search reaches it), and repetitions 1 and above are listed as pending discovery

### Requirement: Compatibility issues
The plan SHALL list compatibility issues from a versioned engine-capability table that records, per engine kind:
- whether an adapter is available in the MVP;
- whether the prefix-cache flush endpoint is verified;
- whether the fixed-length output method is verified.

Rules:
- Deployments of an engine kind with no MVP adapter SHALL be listed as `UNSUPPORTED` and never silently dropped.
- When the cache-reset method is `auto` and the flush endpoint is unverified, the plan SHALL assume a restart between cells and say so.
- For every engine kind whose fixed-length output method is unverified, while at least one workload declares `fixed_length`, the plan SHALL list a compatibility issue naming the engine kind and the affected workloads.

#### Scenario: TensorRT-LLM in the MVP
- **WHEN** the config includes a `trtllm` engine config
- **THEN** its deployments appear in the plan marked `UNSUPPORTED`, with the reason

#### Scenario: Unverified flush endpoint
- **WHEN** the reset method is `auto` and the capability table marks `sglang` flush as unverified
- **THEN** the plan reports that `sglang` deployments restart between cells, and the budget includes those restarts

#### Scenario: Fixed-length output unverified
- **WHEN** workloads `general` and `coding` declare `fixed_length`, workload `agentic` declares `natural`, and fixed-length output is unverified for `vllm`
- **THEN** the plan lists a compatibility issue for `vllm` naming `general` and `coding`, and not `agentic`

### Requirement: Budget estimate
The plan SHALL estimate wall-clock time and GPU-hours as two figures:
- **Coarse-grid estimate**: the coarse grid plus one confirmation rate per series, at the target measurement duration.
- **Worst case**: every extension up to the cap, every refinement step and every confirmation rate, at the maximum measurement duration plus the drain timeout.

GPU-hours SHALL be wall-clock hours multiplied by the GPU count. Cost SHALL equal GPU-hours multiplied by the hourly rate when one is configured, and SHALL otherwise be reported as unavailable.

#### Scenario: Budget without a cost rate
- **WHEN** a plan is made for a config without a cost rate
- **THEN** both GPU-hour figures are reported and cost is reported as unavailable

#### Scenario: Restart raises the budget
- **WHEN** the reset method changes from `flush` to `restart`
- **THEN** in both time estimates, each between-cell flush inside a deployment is replaced by one deployment stop plus one deployment start

### Requirement: Assumptions section
The plan output SHALL contain a section titled **Assumptions**. For every time value the budget uses, it SHALL show the name, the value and its source (`default` or `config`). These values are the deployment start and stop estimates, the cache-flush estimate, the per-cell overhead, the warm-up, the measurement target and maximum, and the drain timeout. The same list SHALL appear in the plan JSON.

#### Scenario: Defaults shown as assumptions
- **WHEN** a plan is made for a config that sets no timing values and no estimates
- **THEN** the Assumptions section lists every time value with source `default`, including `deployment_start_s 600 (default)`

#### Scenario: Overridden estimate is shown with its source
- **WHEN** the config sets `estimates.deployment_start_s: 300` and `timing.warmup_s: 30`
- **THEN** the Assumptions section lists `deployment_start_s 300 (config)` and `warmup_s 30 (config)`, every other time value with source `default`, and the budget figures use 300 and 30

### Requirement: Required-load reachability
For every workload with a `required_load` given as a concurrency, the plan SHALL report whether the search can reach that concurrency under the cap. For a `required_load` given as a request rate, the plan SHALL report that reachability can only be judged after measurement.

#### Scenario: Required concurrency within reach
- **WHEN** a workload requires concurrency 30 and the cap is 256
- **THEN** the plan reports that the target is reachable by the search

### Requirement: Prior-results contract
The system SHALL define a prior-results contract with name `engine-bench/prior-results` and version 1. A v1 document contains:
- the hash of the config that produced it;
- the IDs of completed cells;
- per-cell observations: cell ID, outcome `pass`/`fail`/`invalid`, and achieved request rate;
- follow-up requests per series: additional repetitions and/or additional load points.

The system SHALL provide a reader that checks a document against a current config's expansion, with these rules:
- It SHALL reject an unknown contract name or version, naming the supported version.
- It SHALL resolve each observation to its series, repetition and load point through the current expansion, never trusting those values from the file.
- It SHALL ignore observations for cell IDs that are not in the current expansion, with a warning that counts them.
- It SHALL warn when the document's config hash differs from the current config, and report how many completed cells still match.

The `plan` command SHALL NOT accept prior results in this version.

#### Scenario: Unsupported contract version
- **WHEN** a prior-results document declares contract version 2
- **THEN** the reader rejects it and names version 1 as the supported version

#### Scenario: Unknown cell IDs
- **WHEN** a v1 document has 3 observations whose cell IDs are not in the current expansion
- **THEN** the reader ignores those 3 observations and warns with the count 3

#### Scenario: Config hash mismatch
- **WHEN** a v1 document's config hash differs from the current config, and 10 of its completed cell IDs are in the current expansion
- **THEN** the reader warns about the mismatch and reports 10 matching completed cells

### Requirement: Deterministic offline plan output
`engine-bench plan CONFIG` SHALL validate the config first and refuse to plan when there are errors. Unresolved placeholders SHALL be allowed and shown in the plan. The command SHALL NOT access the network, a GPU or a container runtime.

Output:
- It SHALL print a human-readable summary: deployments, cells, compatibility issues, budget, and the Assumptions section.
- With `--json` it SHALL print the plan as JSON, and with `--out FILE` it SHALL write that JSON to a file.
- The JSON SHALL carry a plan-format version, SHALL contain no timestamps or host-specific values, and SHALL be byte-identical for an identical config.

Exit codes SHALL be 0 on success, 1 on an invalid config, and 2 on usage errors.

#### Scenario: Same inputs, same bytes
- **WHEN** `plan --json` runs twice on the same config
- **THEN** both outputs are byte-identical

#### Scenario: Invalid config
- **WHEN** the config has a validation error
- **THEN** `plan` prints the validation errors, writes no plan, and exits 1
