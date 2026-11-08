# Tasks

## 1. Project setup

- [x] 1.1 Run `git init` at the project root and commit the existing `docs/` and `openspec/` as the initial commit; verify that `git log --oneline` shows one commit and `git status` lists no tracked changes
- [x] 1.2 Create `pyproject.toml` (package `engine-bench`, src layout, `requires-python = ">=3.11"`, console script `engine-bench`), add runtime deps (pydantic v2, typer, ruamel.yaml, structlog) and dev deps (pytest, ruff, mypy), then run `uv lock` and `uv sync`; verify that `uv run engine-bench --help` prints the command list
- [x] 1.3 Configure ruff (target `py311`), mypy (strict, `python_version = "3.11"`) and pytest in `pyproject.toml`; verify that `uv run ruff check`, `uv run mypy src` and `uv run pytest` all run cleanly on the empty package
- [x] 1.4 Add `.gitignore` covering `.venv/`, `data/`, `artifacts/`, caches and `*.plan.json` outputs; verify that `git check-ignore data/x artifacts/x .venv/x` matches all three
- [x] 1.5 Create `src/engine_bench/__init__.py`, `cli.py` (Typer app with explicit exit-code mapping 0/1/2) and `logging.py` (structlog: JSON when not a TTY, console otherwise); verify with tests that a usage error exits 2 and that logging emits JSON under a captured non-TTY stream
- [x] 1.6 Create `docs/tool-versions.md` listing every unverified external fact this change depends on (engine fairness flags, flush endpoints, fixed-length output method, AIPerf loader names and loader parameters, WildChat field names), each marked TODO-verify with the change that will verify it; verify that the file exists and that every item in design D7, D10 and D12 appears in it
- [x] 1.7 Commit group 1 ("project setup"); verify that `git status` is clean and `git log -1` shows the commit

## 2. Canonical hashing

- [x] 2.1 Implement `hashing.py`: canonical JSON (sorted keys, compact separators, UTF-8, NaN/Infinity rejected), SHA-256, a `hash_scheme: 1` field, and a 12-hex display prefix; verify with unit tests for key-order independence, NaN rejection, non-ASCII stability and golden digests for fixed inputs
- [x] 2.2 Commit group 2 ("canonical hashing") once its tests pass; verify that `git status` is clean

## 3. Config schema and loading

- [x] 3.1 Implement `config/loader.py` on the ruamel.yaml round-trip loader, returning plain data plus a key-path→line map; verify with tests that duplicate keys at top level and nested levels raise errors with the key and line, and that YAML tags cannot construct objects
- [x] 3.2 Implement `RawExperiment` models in `config/schema.py` (`extra="forbid"`) for:
  - the shared fairness block (including the load-generator version);
  - engine configs;
  - workloads, with declared identity fields, built-in loader name and loader parameters, and a **required** `output_mode` with no default;
  - cache regimes, timing, SLO (per-request and distribution), search policy, required load, validity limits, cache-reset method, cost, and the `estimates` block.

  Verify with tests that:
  - an unknown key such as `slo.ttft_p59_ms` is rejected with its key path and line;
  - a workload without `output_mode` fails, naming the workload;
  - `output_mode: streaming` fails, listing the allowed values.
- [x] 3.3 Implement the resolver that produces a frozen `ResolvedExperiment`, with all defaults defined in one place, and that records the provenance (`default` or `config`) of every timing and estimate value. The defaults are:
  - SLO: 1500 / 60000 / 1500 / 0.01.
  - Timing: 60 s warm-up, 180 s target, 50 minimum completed requests, 900 s maximum; request timeout = deadline; drain timeout = request timeout.
  - Search: grid `[1,5,10,20]`, factor 2, cap 256, 3 refinement steps, resolution 0.10, fractions `[1.0,0.9,0.8]`, achieved ratio 0.95.
  - Validity and dimensions: CPU limit 85%, repetitions 3, both cache regimes, reset `auto`.
  - Estimates: start 600 s, stop 60 s, flush 10 s, cell overhead 30 s.

  Verify with tests that:
  - a config with no optional sections resolves to exactly these values, all with provenance `default`;
  - overriding `estimates.deployment_start_s` and `timing.warmup_s` changes only those values, with provenance `config`.
- [x] 3.4 Implement placeholder types (each field accepts only its own placeholder), 40-hex revision checks and `@sha256:` digest checks; verify with tests for a placeholder in the wrong field, `main` as a revision, and a tag-only image
- [x] 3.5 Commit group 3 ("config schema and loading") once its tests pass; verify that `git status` is clean

## 4. Validation rules and `validate` command

- [ ] 4.1 Create `config/capabilities.yaml` (vllm and sglang `adapter: mvp`, trtllm `adapter: later`; flush endpoint, fixed-length method and fairness-map entries all `verified: false` with TODO markers) and a typed loader for it; verify with a test that the file loads and that every entry has an explicit `verified` flag
- [ ] 4.2 Implement `config/rules.py`, returning structured issues (severity, key path, line, message), with these rules:
  - fairness-map override rejection, plus an unverified-map warning;
  - exactly one baseline per engine kind, and equal tuned counts within the budget;
  - request timeout ≥ deadline, and SLO ranges;
  - search-policy constraints, and a warning when required load is above the cap;
  - a warning when repetitions are below 3.

  Verify with one passing and one failing test per rule, matching the spec scenarios.
- [ ] 4.3 Implement the fixed-length compatibility rule: for each engine kind in the experiment whose capability entry marks fixed-length output as unverified, while any workload declares `fixed_length`, emit one compatibility warning naming the engine kind and the affected workloads. Verify with tests that:
  - `coding` on `fixed_length` with sglang unverified warns, naming `sglang` and `coding`;
  - all-`natural` workloads produce no such warning;
  - marking the method verified in a test capability table removes the warning.
- [ ] 4.4 Implement secret detection over all string values, with redacted output; verify with a test that a Hugging Face-style token fails validation and that the raw value appears nowhere in text or JSON output
- [ ] 4.5 Wire `engine-bench validate CONFIG [--strict] [--json]`, with exit codes 0/1/2, an unresolved-placeholder listing and compatibility warnings. Verify with CLI tests for:
  - a valid config (0);
  - a config with placeholders (0, then 1 under `--strict`);
  - a config with only a fixed-length compatibility warning (0, then 1 under `--strict`);
  - an invalid config (1);
  - a missing file (2);
  - the shape of the `--json` report.
- [ ] 4.6 Add `configs/experiment.example.yaml` (vllm and sglang baselines; three workloads, each with an explicit `output_mode`; all undecided values as placeholders) and `docs/config-reference.md` (every field, its default or "required", and its rule). Verify with tests that:
  - the example validates with only placeholder and compatibility warnings;
  - every schema field is mentioned in the reference doc.
- [ ] 4.7 Commit group 4 ("validation rules and validate command") once its tests pass; verify that `git status` is clean

## 5. Workload identity and session format

- [ ] 5.1 Implement `workloads/spec.py` with the declared workload identity hash:
  - Local imports: source, dataset ID, revision, sampling, sample size, seed, token-counter ID and importer version.
  - Built-in loaders: additionally the pinned AIPerf version, the loader name and every loader parameter (sampling, seed, sizes).
  - `output_mode` is excluded.

  Verify with tests that:
  - the hash is computable without data;
  - changing only the seed changes it;
  - changing only the AIPerf version changes the InstructCoder and TraceLab identities and leaves the WildChat identity unchanged;
  - changing only a TraceLab size parameter changes the TraceLab identity;
  - changing only `output_mode` leaves the identity unchanged.
- [ ] 5.2 Implement `workloads/session.py` (canonical session record: session ID, ordered turns with user message, recorded assistant response, recorded output tokens, input tokens and optional delay; JSONL read/write); verify with a round-trip test on a three-turn session that preserves order and all fields
- [ ] 5.3 Implement `workloads/tokens.py` (a `TokenCounter` protocol and the `approx-utf8-bytes-div4/v1` counter, with an identity string and an `is_provisional` property that is true for this counter); verify with tests for deterministic counts on ASCII and multi-byte text, and that the counter reports provisional
- [ ] 5.4 Commit group 5 ("workload identity and session format") once its tests pass; verify that `git status` is clean

## 6. Identities and expansion

- [ ] 6.1 Implement `config/identity.py` projections for deployments, series and cells, with the evaluation-only denylist (design D4) and the workload's `output_mode` included in the series and cell projections. Verify with tests that:
  - key reordering and SLO-only changes keep IDs identical;
  - an image-digest change alters only that engine's IDs;
  - an `output_mode` change alters that workload's series and cell IDs;
  - estimate-only changes keep IDs identical;
  - a schema walk classifies every leaf field as identity or evaluation-only.
- [ ] 6.2 Implement deployment expansion with rotation (repetition-major, engine kinds rotated left by `r mod n`, baseline first); verify with the two-engine, three-repetition spec scenario and a three-engine case
- [ ] 6.3 Implement cell expansion: repetition 0 lists coarse-grid cells as `conditional`, later repetitions as `pending_discovery`, and engine kinds with `adapter: later` as `UNSUPPORTED` with a reason; verify with tests on the example config, including a trtllm entry
- [ ] 6.4 Commit group 6 ("identities and expansion") once its tests pass; verify that `git status` is clean

## 7. Frontier search policy

- [ ] 7.1 Implement `config/search.py` `next_step(policy, observations)` as a pure function covering coarse, extend, refine, confirm, `no_feasible_load`, `capped`, `blocked` and `unconfirmed`, with rates rounded to 2 decimals. Verify with:
  - table-driven tests for every spec scenario: break at 20, all pass to the cap, concurrency 1 fails, confirmation rates 3.46/3.11/2.76, invalid at 80;
  - property tests that it never exceeds the cap, never returns a frontier above the highest passing load, and always terminates.
- [ ] 7.2 Implement mirroring: given a completed discovery observation list, return the ordered load points every later repetition must measure; verify with a test that the mirrored list equals discovery's measured points, including failing points and open-loop rates
- [ ] 7.3 Commit group 7 ("frontier search policy") once its tests pass; verify that `git status` is clean

## 8. Budget, compatibility and required load

- [ ] 8.1 Implement `config/budget.py` using the design D8 formulas: coarse and worst-case wall time, GPU-hours = wall × GPU count, cost or `unavailable`, and an assumptions list of every time value used, with its value and provenance. Restart replaces flush when the reset method resolves to restart, including `auto` with an unverified flush. Verify with:
  - hand-computed expected values for the example config under `flush`, `restart` and `auto`, with and without a cost rate;
  - a test that with `deployment_start_s: 300` and `warmup_s: 30` the assumptions list shows those two as `config`, every other value as `default`, and the budget uses 300 and 30.
- [ ] 8.2 Implement compatibility-issue and required-load reachability reporting, including the fixed-length issue per unverified engine kind with its affected workloads. Verify with tests for:
  - an unverified sglang flush under `auto`;
  - a trtllm deployment;
  - `general` and `coding` on `fixed_length` with `agentic` on `natural`: the vllm issue names `general` and `coding` only;
  - a reachable required concurrency of 30;
  - a required rate reported as "judged after measurement".
- [ ] 8.3 Commit group 8 ("budget, compatibility and required load") once its tests pass; verify that `git status` is clean

## 9. Prior-results contract

- [ ] 9.1 Implement `config/prior.py`: the contract v1 model and a reader that checks the contract name and version, resolves observations through the current expansion, and warns about unknown cell IDs and a config-hash mismatch. Verify with tests for:
  - a version-2 rejection that names version 1;
  - 3 ignored unknown IDs, warned with the count 3;
  - the hash-mismatch warning with the count of matching completed cells.
- [ ] 9.2 Add hand-written prior-results fixtures under `tests/fixtures/prior/` for the 9.1 tests. Write `docs/planning.md` covering terminology, IDs, search, mirroring, budget and Assumptions, and prior contract v1, and state that delta planning and `plan --prior` arrive in change 4. Verify that the fixtures are used by the 9.1 tests and that the doc's JSON example parses as a valid v1 contract in a test.
- [ ] 9.3 Commit group 9 ("prior-results contract") once its tests pass; verify that `git status` is clean

## 10. `plan` command

- [ ] 10.1 Wire `engine-bench plan CONFIG [--json] [--out FILE]`, with no `--prior` option. It must:
  - validate first and refuse on errors;
  - print a human summary with sections for deployments, cells, compatibility issues, budget, and **Assumptions** (each time value with its value and source);
  - emit the versioned plan JSON (`plan_format: 1`, sorted keys, an `assumptions` list, no timestamps or host-specific values).

  Verify with CLI tests that:
  - an invalid config exits 1 and writes no file;
  - all summary sections are present, including Assumptions with sources;
  - `--out` writes bytes identical to `--json` stdout;
  - `--prior x` is rejected as an unknown option with exit 2.
- [ ] 10.2 Verify plan determinism: run `plan --json` twice on the example config and assert byte-identical output, in a test that also runs under a different working directory and a different `TZ`
- [ ] 10.3 Verify the offline guarantee: a test that runs `validate`, `plan` and `workloads build` with socket creation and subprocess spawning patched to raise, and asserts that all three succeed
- [ ] 10.4 Commit group 10 ("plan command") once its tests pass; verify that `git status` is clean

## 11. WildChat importer and manifests

- [ ] 11.1 Create the synthetic fixture `tests/fixtures/wildchat/sample.jsonl` (no real dataset text) with multi-turn sessions, three or more languages, a session missing an assistant turn, an over-long session and canary strings; verify that the fixture loads and that the canaries are present
- [ ] 11.2 Implement `workloads/wildchat.py` and `workloads/sampling.py`:
  - `wildchat.py`: local file only, field map behind `FIELD_MAP_VERSION`, and a missing-file error that names the path and says nothing was downloaded.
  - `sampling.py`: seeded stratified sampling over language × input bucket × turn bucket, whole sessions only, with exclusions `missing_assistant_turn` and `exceeds_max_context`.

  Verify with tests for byte-identical output across two runs, whole-session retention, both exclusion reasons and the missing-file error.
- [ ] 11.3 Implement `workloads/builtin.py` and `workloads/manifest.py`:
  - `builtin.py`: declared manifests for InstructCoder and TraceLab, recording the AIPerf version, loader name and loader parameters, with content hash `unavailable`.
  - `manifest.py`: identity hash, content hash, counts, strata, token stats (min/p50/p95/max), turns per session, exclusions, counter ID, and a `provisional` flag derived from the counter.

  Verify with tests that:
  - the TraceLab manifest records the AIPerf version and has content hash `unavailable`;
  - manifests built with `approx-utf8-bytes-div4/v1` are `provisional: true` both with `EXACT_MODEL_ID` and with a resolved model ID;
  - manifests are byte-identical across runs.
- [ ] 11.4 Add no-raw-text tests: build manifests from the canary fixture with logs captured, and assert that no canary string appears in any manifest file or log record
- [ ] 11.5 Wire `engine-bench workloads build CONFIG`: write under the data directory; print the identity hash, the content hash (or `unavailable`) and the provisional status; use exit codes 0/1/2. Document the command in `docs/workloads.md`, together with the canonical session format, the data-handling rules, and the rule that provisional manifests can never support a final comparison. Verify with CLI tests for:
  - the fixture-backed success, where provisional is shown as true;
  - the "missing WildChat file plus TraceLab" case: TraceLab is written and the command exits 1.
- [ ] 11.6 Commit group 11 ("WildChat importer and manifests") once its tests pass; verify that `git status` is clean

## 12. Integration check

- [ ] 12.1 Run the end-to-end flow on the example config pointed at the fixture: `validate` → `workloads build` → `plan --json`. Verify that each step's exit code and key outputs match the specs, including the compatibility warnings and the Assumptions section. Then run `uv run ruff check`, `uv run mypy src`, `uv run pytest` and `openspec validate bootstrap-config-and-plan --strict`, and confirm that all pass.
- [ ] 12.2 Commit any integration fixes ("integration check"); verify that `git status` is clean and `git log --oneline` shows one commit per task group after the initial commit
