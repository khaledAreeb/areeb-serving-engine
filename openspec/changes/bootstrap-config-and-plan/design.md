# Design

## Context

The repository is greenfield. It holds only the architecture deck and the engineering prompt (`docs/`). The development machine is CPU-only (no `nvidia-smi`), with Python 3.13 and `uv` available. This change must therefore be entirely offline and CPU-only. Several facts it touches are still unverified: engine CLI flags, flush endpoints, AIPerf loader names, and WildChat field names. The prompt forbids coding these from memory, so the design keeps each one as data marked `verified: false`, never as hard-coded truth. Requirements are in `specs/`; motivation is in `proposal.md`.

## Goals / Non-Goals

**Goals:**
- Make the config fair by construction: shared fields cannot be expressed per engine.
- Make IDs safe for reuse: a stale measurement must never be reused for a changed configuration.
- Write the search policy once as a pure function, so the runner (change 3) and delta planning (change 4) can share it.
- Fix the module boundaries and data contracts that later changes depend on.

**Non-Goals:**
- Real tokenizers, dataset downloads, and AIPerf input-format translation. The translation lives in `benchmarks/` (change 2), so `workloads/` stays independent of AIPerf.
- A persistent run index (change 3).
- Delta planning and `plan --prior` (change 4). This change ships only the prior-results contract and its reader.

## Decisions

### D1. Module layout follows the prompt; only this change's packages are created

```
src/engine_bench/
  cli.py            Typer app: validate, plan, workloads build
  logging.py        structlog setup (JSON or console)
  hashing.py        canonical JSON + SHA-256, hash-scheme version
  config/
    schema.py       Pydantic models (raw + resolved), defaults
    loader.py       YAML -> raw model, duplicate keys, line numbers
    rules.py        cross-field + fairness validation -> Issues
    capabilities.yaml   per-engine capability + fairness map (verified flags)
    identity.py     deployment / series / cell identity projections
    expand.py       deployments, rotation, cells, mirror reps
    search.py       pure frontier-search policy
    budget.py       time / GPU-hour / cost estimates
    prior.py        prior-results contract v1 model + reader checks
  workloads/
    spec.py         declared identity
    session.py      canonical session record
    tokens.py       TokenCounter protocol + approximate counter
    sampling.py     stratified, seeded session sampling
    wildchat.py     local-file importer + field mapping (versioned)
    builtin.py      declared manifests for AIPerf loaders
    manifest.py     manifest model + builder
```

Planning code lives in `config/` because the prompt's layout assigns "expand cells, estimate time/budget" there. The other seven packages are created by the changes that fill them, not as empty stubs.

### D2. Two model layers: raw and resolved
`RawExperiment` mirrors the YAML exactly (`extra="forbid"`, every default optional). `ResolvedExperiment` has every default filled in, is frozen, and is the only type the rest of the code sees. Defaults are defined in exactly one place (the resolver), and `validate --json` prints the resolved model, so users always see the values actually in effect.
*Alternative:* a single model with Pydantic defaults. Rejected because it cannot tell "user wrote 1500" from "default 1500", and that difference matters for warnings and for documenting defaults.

### D3. YAML loading with ruamel.yaml (round-trip loader)
The round-trip loader rejects duplicate keys and keeps line and column information for error messages. It builds plain mappings and scalars only, never arbitrary objects. The behaviour is confirmed in a test at implementation time.
*Alternative:* PyYAML `safe_load`. Rejected because it silently keeps the last duplicate key, which is a reproducibility hazard for experiment definitions.

### D4. Identity hashing uses a denylist over a per-entity projection
For each entity, the hash input is a projection of the resolved config:
- **Deployment:** the shared block, its own engine config and the repetition index.
- **Series:** the shared block, its own engine config, the workload declaration (identity hash plus output mode) and the cache regime.
- **Cell:** the series fields plus the load point and the repetition index.

All three also include the load-generator version and a `hash_scheme: 1` field. Inside each projection, every field is part of the identity except an explicit denylist of fields that only affect evaluation: `name`, `slo`, `search`, `required_load`, `validity`, `cost`, `estimates`.

A test walks the full schema and asserts that every leaf field is classified as either identity or evaluation-only, so adding a field forces a decision.
*Alternative:* an allowlist of identity fields. Rejected because forgetting a new measurement-affecting field would cause silent wrong reuse. Forgetting a new evaluation-only field under the denylist only causes an unnecessary rerun, the safe failure.

The canonical form is JSON with sorted keys, compact separators and UTF-8, and rejects NaN and Infinity. Integer and float types are fixed per field by the resolved model, so `1` and `1.0` never collide or diverge. Full SHA-256 values go in JSON; a 12-hex prefix is used for display.

### D5. The search policy is a pure function of observations

```
next_step(policy, observations: list[Observation]) -> Measure(load_point) | Done(result)

Observation = (load_point, outcome: pass|fail|invalid, achieved_rps: float | None)
Result      = frontier(concurrency, rate | "unconfirmed", capped: bool)
            | no_feasible_load | blocked(load_point)
```

State is rebuilt from the observation list on every call, with no hidden state. This makes the policy resumable after a crash, usable identically online by the runner and offline by delta planning in change 4, and exhaustively testable with table-driven cases. The phases (coarse → extend → refine → confirm) are derived from the observations, not stored.

```
  coarse grid      extend (x2, cap)        refine (bisect)       confirm (open loop)
  1  5  10  20 --> 40  80  160  256        pass=P  fail=F        R0 = rps@P
  P  P  P   P      P   P   F               mid=(P+F)//2          try R0*1.0, *0.9, *0.8
                           |               until gap<=max(1,     first pass = frontier
                           +-------------> ceil(P*res)) or steps rate
```

### D6. Repetition 0 discovers; later repetitions mirror it
Repetition 0 of each series runs the adaptive search. Repetitions 1 and above measure exactly the load points repetition 0 measured, including failing points and the open-loop rates. Because rotation finishes all of repetition 0 before repetition 1 starts, the mirrored points are always known when they are needed. Change 4 treats disagreement at the boundary between repetitions as "Inconclusive", and its delta planning then schedules the follow-up.
*Alternatives:* (a) an independent search per repetition. Rejected because load points would end up with different repetition counts, so aggregation at a fixed load becomes impossible. (b) A separate discovery pass that does not count as a repetition. Rejected because it costs a fourth deployment per engine config. Discovery data is real measurement under the same protocol.

### D7. Engine capability table as versioned data
`config/capabilities.yaml` records, per engine kind:
- `adapter`: `mvp` or `later`
- `flush_endpoint`: endpoint and a `verified` flag
- `fixed_length_output`: method and a `verified` flag
- `fairness_map`: engine flag mapped to the shared field it controls, each with a `verified` flag

Every entry starts with `verified: false` and a TODO marker. Rules and the planner read this table; change 3 verifies entries against the pinned images and flips the flags. Unverified data still drives behaviour, conservatively: fairness-map entries are enforced (with a warning), and an unverified flush makes `auto` plan a restart.

### D8. Budget model

```
per cell       = warmup + measure_window + cell_overhead           (coarse: target window,
                                                                    worst: max window + drain)
per boundary   = flush            if reset resolves to flush
               = stop + start     if reset resolves to restart
per deployment = start + sum(cells) + (cells - 1) * boundary + stop
wall           = sum(deployments)        GPU-hours = wall_h * gpu_count
cost           = GPU-hours * rate        or "unavailable"
```

Coarse point count per series: the coarse grid plus 1 confirmation rate. Worst case: the coarse grid, every extension to the cap, the maximum refinement steps and every confirmation fraction. All repetitions are included in both.

The proposed defaults are below. Every value is overridable in the config (`estimates.*` and `timing.*`). Each value the budget uses is printed in the plan's **Assumptions** section with its source (`default` or `config`), and the same list appears in the plan JSON.

| setting | value |
|---|---|
| `deployment_start_s` | 600 |
| `deployment_stop_s` | 60 |
| `cache_flush_s` | 10 |
| `cell_overhead_s` | 30 |
| warm-up | 60 s |
| measurement target | 180 s |
| min completed requests | 50 |
| measurement max | 900 s |
| drain timeout | 60 s (= request timeout) |

### D9. Prior-results contract v1

```json
{
  "contract": "engine-bench/prior-results",
  "version": 1,
  "config_hash": "<sha256 of resolved identity-relevant config>",
  "completed_cells": ["<cell_id>", "..."],
  "observations": [
    {"cell_id": "<cell_id>", "outcome": "pass", "achieved_rps": 3.456}
  ],
  "follow_up": [
    {"series_id": "<series_id>", "add_repetitions": 2,
     "add_load_points": [{"kind": "concurrency", "value": 15}]}
  ]
}
```

Observations reference cells by ID only. The reader maps each ID back to its series, repetition and load point through the current expansion, so the file cannot contradict the config.

This change ships only the model and the reader, both tested against hand-written fixtures. Delta planning and the `plan --prior` option move to change 4, where they are tested against the analysis layer's real output. Until then, `plan` has no `--prior` option, so Typer rejects it as an unknown option with exit 2. If change 4 needs more fields, it bumps the version and keeps a reader for v1.

### D10. Workload identity and content are separate hashes
The identity hash covers the fields that determine content, and it is computable without data:
- **Local imports:** source, dataset ID, revision, sampling, sample size, seed, token-counter ID and importer version.
- **AIPerf built-in loaders** (InstructCoder, TraceLab): the content is produced inside AIPerf, so the identity also includes the pinned AIPerf version, the loader name and every loader parameter (sampling, seed, sizes).

Upgrading AIPerf therefore changes the built-in workload identities, but not the identity of a local import such as WildChat. The output mode is part of the workload declaration but not of the identity hash; it enters the series and cell projections directly (D4).

The content hash covers the canonical session file. It is computed when the data is present, or observed from AIPerf later for built-in loaders. Change 2 or 3 will check that all engines in a comparison saw the same content hash. This lets `plan` work before any download, while still catching any drift in the actual content.

### D11. The approximate token counter always yields provisional manifests
`approx-utf8-bytes-div4/v1` (`ceil(len(text.encode()) / 4)`) is deterministic and dependency-free, and it is the only counter in this change. The `provisional` flag is set from the counter ID alone: it is true for every manifest built with this counter, whether or not the model is resolved. The counter ID is part of the workload identity, so adding the real-tokenizer counter (once the model is chosen) changes the identity and the cell IDs on purpose. The rule binding later changes is that any component producing a comparison outcome rejects cells with provisional manifests as `provisional_workload_manifest`. Such cells may still be measured, but only as exploratory results.

### D14. Output mode is a required per-workload choice
`output_mode` lives on each workload and has no default. Choosing between fixed-length and natural output changes what is measured, so it must be a deliberate decision. A workload that needs both modes is declared twice. The fixed-length method is unverified for every engine at first (D7), so `validate` emits a compatibility warning, and `plan` lists a compatibility issue, for each engine kind with an unverified method while any workload uses `fixed_length`.

### D15. Git workflow
The project root becomes a Git repository at the start of implementation. The existing `docs/` and `openspec/` are committed first. After that, each task group ends with one commit, once that group's tests pass, so history stays small and bisectable.

### D12. WildChat field mapping isolated and versioned; synthetic fixture
All knowledge of WildChat field names lives in `wildchat.py` behind a `FIELD_MAP_VERSION`. The test fixture is a small hand-written JSONL file of synthetic conversations that mimics the documented schema. It contains no real dataset text, so nothing gated is committed. Field names are confirmed against the dataset card at the pinned revision before the first real import. The fixture includes:
- multi-turn sessions
- several languages
- a session with a missing assistant turn
- an over-long session
- **canary strings**, which the no-raw-text tests search for in manifests and captured logs

Proposed default buckets (configurable):

| bucket | edges |
|---|---|
| input tokens | 0, 512, 2048, 8192, ∞ |
| turns | 1, 2, 4, ∞ |

### D13. CLI and tooling
- **CLI:** Typer, which gives type-hinted commands on top of Click. Exit codes 0, 1 and 2 are mapped explicitly, never left to the framework's defaults.
- **Environment:** `uv` manages the venv and `uv.lock`. `requires-python = ">=3.11"`, and ruff and mypy target `py311`, so 3.12+ syntax is caught locally even on 3.13. The CI matrix in change 6 adds a real 3.11 run.
- **Logging:** structlog, with JSON output when not on a TTY.
- **Secret detection:** a best-effort regex set (Hugging Face `hf_…` and `sk-…` style tokens). Matches are redacted to `hf_****` in every output.

## Risks / Trade-offs

- [A hash-scheme bug causes wrong reuse] → denylist design (D4), the schema-classification test, golden-ID tests over a fixed config, and `hash_scheme` versioning so a fix invalidates old IDs cleanly.
- [Unverified fairness-map flags wrongly reject or allow an argument] → every entry carries `verified: false` and `validate` warns. Change 3 verifies against pinned images before any GPU run.
- [The approximate token counter misplaces sessions in buckets] → manifests are always provisional, the identity changes on the switch, and provisional data is barred from final comparisons.
- [Repetition 0 is an outlier and steers the load points] → mirrored repetitions expose the disagreement, and the decision layer turns it into "Inconclusive" with follow-up points instead of silently trusting repetition 0.
- [Prior contract v1 doesn't fit what change 4 produces] → it is versioned with an explicit version check, and the reader is kept small.
- [Budget defaults are guesses] → they are always printed as assumptions. Change 3 records real start and flush times so they can be calibrated.
- [Python 3.13 locally but 3.11 floor] → ruff and mypy target py311 now, and CI covers 3.11 later.

## Migration Plan

Greenfield, so nothing to migrate. Rollback means reverting the change.

## Open Questions

- Default stratification bucket edges (D12) and timing defaults (D8) are proposals. They are config values and can be tuned without changing specs or tasks.
- Which WildChat variant and revision to use is a config value, decided when the user confirms the download.
