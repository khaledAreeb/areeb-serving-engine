# Proposal

## Why

`engine-bench` will spend scarce GPU-hours deploying the same model on several serving engines to find each engine's capacity frontier. Every later stage therefore depends on an experiment definition that is unambiguous, fair by construction, and cheap to check before any GPU is touched. This first change (Stage 1 of 6) builds that foundation: a validated config, a deterministic plan with stable cell IDs and a budget, and hashed workload manifests, all runnable on a CPU-only machine.

## What Changes

- **Project skeleton**:
  - Python 3.11+ package `engine_bench` (src layout), with `pyproject.toml`, pytest/ruff/mypy setup and structured logging.
  - A new Git repository, committed in small steps (one commit per task group), with a `.gitignore` that keeps datasets and artifacts out of Git.
  - A `docs/tool-versions.md` stub that lists every external fact still unverified.
- **Experiment config schema** (Pydantic, YAML):
  - **Shared fairness block**: model, revision, tokenizer, chat template, precision, max context, generation settings, GPU, seeds and timing.
  - **Engine configs**, which may carry only engine-tuning knobs.
  - **Workloads**, each of which must declare its `output_mode` explicitly. There is no default.
  - **Run settings**: cache regimes, repetitions, the adaptive load-search policy, two kinds of SLO, client-saturation limits and an optional per-workload `required_load`.
  - **Optional cost and estimates**: an operator cost rate, and a planning-estimates block whose time defaults can be overridden.
  - **Placeholders**: undecided values stay as named placeholders (`EXACT_MODEL_ID`, `EXACT_COMMIT`, `GPU_SYSTEM`, `GPU_UUID`, `EXACT_IMAGE_DIGEST`, `EXACT_AIPERF_VERSION`).
- **`engine-bench validate CONFIG`**: schema and fairness checks, a placeholder report, and `--strict` and `--json` modes with defined exit codes. It warns when a workload uses `fixed_length` output on an engine whose fixed-length method is not yet verified.
- **`engine-bench plan CONFIG`**:
  - Expands deployments (engine × config × repetition, engine order rotated per repetition) and their initial cells, and assigns stable hash IDs.
  - Lists compatibility issues, including unverified fixed-length output.
  - Estimates GPU time and cost (coarse estimate and worst case), with every time value the estimate uses printed under **Assumptions**.
  - Runs with no GPU and no network.
- **Adaptive capacity-frontier search policy** as a pure, testable function:
  - A coarse concurrency grid (default 1, 5, 10, 20), extended upward while the SLO passes.
  - Bisection around the break point, then open-loop rate confirmation.
  - Later repetitions mirror the load points of the discovery repetition.
- **Prior-results contract v1**: the data model and a validating reader (contract name and version check, observations resolved through the current expansion, warnings for unknown cell IDs and a config-hash mismatch). Delta planning that consumes it is not part of this change (see Non-goals).
- **Workload manifests**:
  - Declared workload identity hashes, computable offline. For AIPerf built-in loaders (InstructCoder, TraceLab), the identity includes the pinned AIPerf version, the loader name and the loader parameters.
  - A WildChat importer that reads a local file only, built and tested against a small synthetic fixture.
  - Manifests built with the approximate token counter are always provisional, and provisional manifests may never support a final comparison.
  - New CLI subcommand `engine-bench workloads build CONFIG`, which is an addition to the command surface in the architecture deck.

## Capabilities

### New Capabilities
- `experiment-config`: the experiment YAML schema, its fairness and safety rules, placeholders, defaults (SLOs, search policy, saturation threshold, timing and planning estimates), the required per-workload output mode, and the `validate` command.
- `experiment-planning`: deployment and cell expansion, stable IDs, engine-order rotation, the adaptive frontier-search policy and repetition mirroring, compatibility issues, budget estimation with printed assumptions, the prior-results contract v1 reader, and the `plan` command.
- `workload-manifests`: declared workload identity (including the pinned load-generator version for built-in loaders), importers and sampling, the canonical session format, hashed manifests, the provisional rule, data-handling rules, and the `workloads build` command.

### Modified Capabilities
(none — no specs exist yet)

## Non-goals

- Delta planning from prior results and the `plan --prior` option. Both move to change 4, so they are tested against real outputs from the analysis layer. Until then, `plan` does not accept prior results.
- A real-tokenizer token counter. It is added once the model is chosen. Until then, only the approximate counter exists, and every manifest it produces is provisional.
- Sending any request, running AIPerf, starting containers, or touching a GPU (changes 2–3).
- The SQLite run index, lifecycle state machine, resume and cleanup (change 3).
- Computing pass/fail, aggregates or decisions (change 4).
- AISimulate (change 5) and CI (change 6).
- Downloading WildChat, model weights or any dataset. The importer reads local files only. Downloading needs the user's explicit confirmation and is a later, separate step.

## Impact

- **New repository**: `git init` at the project root. The existing `docs/` and `openspec/` are committed first, then one commit per task group.
- **New code**:
  - `src/engine_bench/{cli.py, logging.py, hashing.py}`
  - `src/engine_bench/config/` and `src/engine_bench/workloads/`
  - `configs/experiment.example.yaml`, `tests/` and `docs/tool-versions.md`
- **New dependencies**:
  - Runtime: pydantic v2, typer, ruamel.yaml and structlog.
  - Dev: pytest, ruff and mypy.
  - Exact versions are pinned at implementation time.
- **Contracts other changes depend on**:
  - The cell/deployment ID scheme.
  - The canonical session format and the workload manifest schema (including the `provisional` flag and the rule that bars provisional manifests from final comparisons).
  - The search-policy function.
  - The prior-results contract v1.
- **Systems**: none. Everything runs on CPU, offline.
