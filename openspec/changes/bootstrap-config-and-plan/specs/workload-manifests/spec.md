# Spec Delta

## Purpose

Defines how benchmark workloads are declared, imported, sampled and fingerprinted, so that every engine replays exactly the same sessions and any difference in workload content is detectable from hashed manifests. Raw dataset content never leaves the local data directory.

## ADDED Requirements

### Requirement: Declared workload identity
Each workload in the experiment config SHALL declare its name, profile (`general`, `coding` or `agentic`), source (a local import with a named importer, or a load-generator built-in dataset with a named loader), dataset ID, dataset revision, sampling parameters, sample size, seed, token-counter identity and output mode. The system SHALL compute a workload identity hash from the fields that determine the workload's content, without needing the dataset itself:
- For local imports: source, dataset ID, revision, sampling parameters, sample size, seed, token-counter identity and importer version.
- For built-in loaders: see "Built-in load-generator datasets".

The output mode is not part of the workload identity hash, because it does not change the content. It enters cell IDs directly. Cell IDs depend on the workload identity hash.

#### Scenario: Identity without data
- **WHEN** a workload is declared but its dataset file is not present locally
- **THEN** its identity hash can still be computed, and `plan` can still produce cell IDs

#### Scenario: Seed change alters identity
- **WHEN** two declarations differ only in the sampling seed
- **THEN** their identity hashes differ

### Requirement: Canonical session format
Imported workloads SHALL be written as canonical session records, one session per line. A record holds a session ID and its ordered turns, and each turn holds the user message, the recorded assistant response, the recorded output token count, the input token count, and an optional recorded delay before the turn. Recorded assistant responses SHALL be kept so that later turns can replay fixed history instead of engine-generated output.

#### Scenario: Multi-turn session preserved
- **WHEN** a three-turn conversation is imported
- **THEN** its record contains all three turns in order, each with the recorded assistant response and recorded output token count

### Requirement: WildChat importer
The WildChat importer SHALL read only from a local file path. It SHALL sample whole sessions, stratified by language, input-size bucket and turn-count bucket using configured bucket edges, so that the result is identical for the same input file, parameters and seed. It SHALL exclude, and count by reason, sessions that have a turn without a recorded assistant response and sessions whose longest prompt plus target output would exceed the shared maximum context length. When the local source is missing, it SHALL fail with an error naming the expected path and stating that downloads are not performed automatically.

#### Scenario: Deterministic sampling
- **WHEN** the importer runs twice on the same local file with the same parameters and seed
- **THEN** both runs produce byte-identical session files and manifests

#### Scenario: Whole sessions only
- **WHEN** a sampled session has five turns
- **THEN** all five turns are in the output, never a subset

#### Scenario: Over-long session excluded
- **WHEN** a session's final prompt plus its target output exceeds the shared maximum context length
- **THEN** the session is excluded and counted under the reason `exceeds_max_context` in the manifest

#### Scenario: Source missing
- **WHEN** the configured local WildChat file does not exist
- **THEN** the importer fails with an error naming the path and saying that nothing was downloaded

### Requirement: Built-in load-generator datasets
Workloads that use a load-generator built-in loader (InstructCoder, TraceLab) produce their content inside the load generator. Their identity hash SHALL therefore include:
- the pinned load-generator version (or its placeholder);
- the loader name;
- every loader parameter: sampling parameters, seed, sample size and any size or length settings;
- the dataset ID, dataset revision and token-counter identity.

Their manifest SHALL record the same fields. Its content hash SHALL be reported as `unavailable` until the inputs the load generator actually sends can be observed, and SHALL never be filled with a placeholder value. The identity of a local-import workload SHALL NOT depend on the load-generator version.

#### Scenario: TraceLab manifest before any run
- **WHEN** manifests are built for a TraceLab workload
- **THEN** the manifest records the load-generator version, the loader name and parameters, and its content hash is `unavailable`

#### Scenario: Load-generator version change alters built-in identity
- **WHEN** two configs differ only in the pinned load-generator version
- **THEN** the identity hashes of the InstructCoder and TraceLab workloads differ, and the identity hash of the WildChat workload is unchanged

#### Scenario: Loader parameter change alters built-in identity
- **WHEN** two configs differ only in a TraceLab loader size parameter
- **THEN** the TraceLab workload identity hashes differ

### Requirement: Workload manifest
Every workload SHALL have a manifest that contains: the identity hash; the content hash of the canonical session file, or `unavailable`; session and turn counts; per-stratum counts; input and output token statistics (minimum, median, 95th percentile, maximum); turns-per-session statistics; exclusion counts by reason; the token-counter identity; and a `provisional` flag. Manifests SHALL contain no raw prompt or response text, and SHALL be byte-identical for identical inputs.

#### Scenario: No raw text in manifest
- **WHEN** a manifest is built from sessions containing user text
- **THEN** the manifest file contains only hashes, counts and statistics, and none of the session text

### Requirement: Provisional token counts
This version SHALL provide one token counter, `approx-utf8-bytes-div4/v1`, which is deterministic and needs no model files. A counter based on the model's real tokenizer is added once the model is chosen. Every manifest built with `approx-utf8-bytes-div4/v1` SHALL be marked `provisional: true`, whether or not the model ID is resolved. The token-counter identity is part of the workload identity hash, so switching counters changes the workload identity and every dependent cell ID.

#### Scenario: Approximate counter with a placeholder model
- **WHEN** manifests are built with `approx-utf8-bytes-div4/v1` while the model ID is `EXACT_MODEL_ID`
- **THEN** every manifest is marked `provisional: true` and names the approximate counter

#### Scenario: Approximate counter with a resolved model
- **WHEN** manifests are built with `approx-utf8-bytes-div4/v1` and a real model ID and revision
- **THEN** every manifest is still marked `provisional: true`

### Requirement: Provisional manifests are never final evidence
A provisional workload manifest SHALL NOT support a final comparison. Any component that produces a comparison outcome (Winner, Inconclusive or No feasible configuration) SHALL reject as incomparable every cell whose workload manifest is provisional, with the reason `provisional_workload_manifest`. Results from cells with provisional manifests SHALL be labelled exploratory wherever they are reported.

#### Scenario: Comparison with a provisional manifest
- **WHEN** a comparison includes a cell whose workload manifest has `provisional: true`
- **THEN** that cell is rejected as incomparable with reason `provisional_workload_manifest` and contributes nothing to the outcome

### Requirement: Data handling
Workload tooling SHALL NOT access the network. Dataset files and canonical session files SHALL be stored under the configured data directory, which the repository ignores. Logs SHALL NOT contain raw prompt or response text. Credentials for gated datasets SHALL be referred to only by environment variable name.

#### Scenario: Logging during import
- **WHEN** the importer logs progress or errors
- **THEN** log entries contain session IDs, counts and hashes, never message text

### Requirement: Workloads build command
`engine-bench workloads build CONFIG` SHALL build the canonical session file and manifest for every local-import workload and the declared manifest for every built-in workload, writing them under the data directory, and SHALL print each workload's identity hash, content hash (or `unavailable`) and provisional status. It SHALL exit 0 on success, 1 when any workload fails to build, and 2 on usage errors.

#### Scenario: Build with one missing source
- **WHEN** the config declares a WildChat workload whose local file is missing and a TraceLab workload
- **THEN** the TraceLab manifest is written, the WildChat failure is reported with its path, and the command exits 1
