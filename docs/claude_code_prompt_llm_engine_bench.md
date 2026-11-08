# Project: LLM Serving Engine Benchmark (`engine-bench`)

You are the lead engineer building this tool with me. I've attached a PDF of our architecture and implementation plan. Read all of it before doing anything else. It is the source of truth for **what** we're building. This prompt adds the engineering rules and the order of work.

## 1. The goal

Build a reproducible Python CLI tool that:

1. Deploys the **same model** on different LLM serving engines (vLLM and SGLang first, TensorRT-LLM later).
2. Replays realistic traffic against each engine with **NVIDIA AIPerf** and records performance.
3. Optionally uses **NVIDIA AISimulate** (open-source, part of the Dynamo project, successor to AIConfigurator) to predict performance on CPU and shortlist configurations *before* using GPU time. This only works if AISimulate has a profile for our model, GPU and engine.
4. Recommends an engine and configuration for each workload and load level. Every recommendation must be traceable to raw measurements.

The tool measures **serving performance only**: latency, throughput, capacity, errors and GPU resource use. It does **not** grade answer quality, execute generated code, or judge whether an agent solved a task.

## 2. Things not decided yet: ask, don't guess

- **Target model ID and revision:** not chosen yet. Use the placeholders `EXACT_MODEL_ID` and `EXACT_COMMIT` in configs.
- **GPU type and count:** not chosen yet. Use `GPU_SYSTEM` and `GPU_UUID` placeholders.
- **Hourly cost rate:** operator-supplied, so keep it a config field.
- **SLO values:** the PDF's values (P95 TTFT ≤ 1,500 ms, error rate ≤ 1%, 60 s request deadline) are **starting proposals**. They must be configurable, never hard-coded.

If you hit another decision that changes the design, stop and ask me. Don't invent an answer.

## 3. Verify the tools first: don't code from memory

AIPerf and AISimulate change quickly, and their CLIs and export formats differ between versions. Before writing any integration code:

1. Install the tools in a virtual environment (`pip install aiperf`, `pip install aisimulate`) and **pin the exact versions** you tested.
2. Read their `--help` output and official docs: https://github.com/ai-dynamo/aiperf and https://github.com/ai-dynamo/aisimulate
3. Write down in `docs/tool-versions.md` the exact commands, flags and export file formats you confirmed.
4. Keep each tool's interface in **one module** (`benchmarks/` for AIPerf, `simulation/` for AISimulate), so a version upgrade only touches one place.
5. Save real export samples as test fixtures, and write **contract tests** that fail loudly if a field we depend on disappears or changes.

Known AISimulate facts to confirm yourself:

- The support check is currently `aiconfigurator cli support --model-path <MODEL> --system <SYSTEM> [--backend <vllm|sglang|trtllm> --backend-version <VER>]`. This compatibility command is targeted for removal in AISimulate 0.14.0, so check what the pinned version provides.
- An exit code of 0 only means the query ran. **Parse the actual YES/NO result.**
- A supported profile does not mean accurate predictions. AISimulate is experimental and not meant for capacity planning.

## 4. Architecture (summary of the PDF)

- **Control plane separate from benchmark traffic.** The Python controller plans and supervises runs but never sits in the request path. AIPerf sends requests **directly** to the engine's OpenAI-compatible endpoint, with no proxy.
- **Two execution modes:**
  - **Managed mode (preferred):** the runner starts one engine container, measures it, stops it, and verifies the GPU is released before the next engine starts.
  - **Endpoint mode:** benchmarks an existing endpoint. If hardware, engine or model metadata is missing, the result is marked an **unverified comparison**, never a recommendation.
- **Engine adapter contract.** Every engine implements the same interface:
  ```
  check_support(model, hardware, requirements) -> CapabilityReport
  render_launch(resolved_config)               -> LaunchSpec
  start(launch_spec)                           -> DeploymentHandle
  wait_ready(handle, deadline)                 -> ReadinessRecord
  describe(handle)                             -> EnvironmentManifest
  stop(handle)                                 -> CleanupRecord
  ```
  A `LaunchSpec` holds a pinned image **digest** (not a tag), an argument **array** (never shell string interpolation), GPU UUIDs, mounts, and env-var **names** for secrets. Secret values must never appear in manifests, logs or reports.
- **Simulation pre-screen (AISimulate):** runs the support check for **each** engine. If supported, it predicts metrics and shortlists configs. If not, it skips simulation and runs the full measured sweep. **Fairness rule:** use the shortlist only when **every** compared engine has a profile. Otherwise all engines get the same full sweep. Store predictions as artifacts. The report shows predicted vs measured error. Predictions are **never** evidence for a recommendation.
- **Experiment cell lifecycle.** A cell is one engine config × workload × cache regime × output mode × load point × repetition, with a stable ID hashed from its resolved config and manifests. States:
  `PLANNED → VALIDATED → RESOURCE_LOCKED → STARTING → READY → WARMING → MEASURING → DRAINING → EXPORTING → CLEANING → COMPLETED`
  - A cell can also end `UNSUPPORTED`, `FAILED`, `CANCELLED` or `INVALID`.
  - Persist every transition and its reason in SQLite.
  - Failures still go through cleanup.
  - Resume only reruns incomplete cells with matching hashes, and never appends to a partial timing window.
- **Initial deployment:** one Linux GPU host with Docker and NVIDIA support, a local artifact directory, SQLite for the run index, and a local OS lock on the GPU set. No Kubernetes, distributed queue or web backend in the MVP.

## 5. Repository layout

```
src/engine_bench/
  config/       # YAML schema validation, pin revisions, expand cells, estimate time/budget
  workloads/    # WildChat, InstructCoder, TraceLab importers; sampling; hashed manifests
  simulation/   # AISimulate bridge: support check, predict, shortlist
  engines/      # base adapter + vllm, sglang (tensorrt_llm later)
  runner/       # GPU lock, lifecycle state machine, deadlines, cancel, resume, cleanup
  benchmarks/   # pinned AIPerf launcher + export compatibility layer
  metrics/      # collect AIPerf exports + nvidia-smi telemetry; normalize units
  analysis/     # comparability checks, repetition aggregation, SLO scoring, selection
  reports/      # Jinja2 + Plotly self-contained HTML, plus CSV and decision JSON
configs/  manifests/  tests/  docs/  .github/workflows/
```

CLI commands to implement:

```
engine-bench validate configs/experiment.yaml
engine-bench simulate configs/experiment.yaml   # AISimulate support check + predictions, no GPU
engine-bench plan     configs/experiment.yaml   # expanded cells, compatibility issues, budget; no GPU
engine-bench run      configs/experiment.yaml
engine-bench resume   EXPERIMENT_ID
engine-bench report   EXPERIMENT_ID
```

## 6. Fairness rules (non-negotiable)

- Keep these identical across engines: model weights and revision, tokenizer, chat template, precision, max context, generation settings, GPU type and count, client location, dataset selection, seeds, request histories and deadlines.
- Record actual output token counts. **Silent truncation invalidates the cell.**
- Keep startup, model loading and warmup **out** of serving metrics. Report them separately.
- Test cache regimes explicitly (unique prefix vs warm shared prefix), and reset between repetitions and between engines.
- Never feed an engine's generated answers into later turns. Replay the fixed recorded history.
- Report baseline and tuned results separately. Tuning gets an equal, predeclared budget per engine.
- Record unsupported combinations as `UNSUPPORTED`, never as a score of zero.

## 7. Metrics and decision logic

- **Metrics:**
  - P50/P95 TTFT and P95 end-to-end latency.
  - TPOT / generation rate.
  - Output throughput.
  - Goodput: requests per second meeting **all** SLO limits at once, checked jointly per request.
  - Errors, counted against all attempted requests, never dropped.
  - VRAM, utilization, clocks and power.
  - A metric that's missing is reported as `unavailable`, never as 0.
- **Decision:**
  1. Reject incomparable cells.
  2. Filter by the SLOs.
  3. Compare at the required load, without extrapolating past the tested range.
  4. Aggregate at least 3 repetitions, with confidence intervals from session- or trial-level resampling.
- **Outcomes:**
  - **Winner:** only when the benefit is stable and above the predeclared threshold (default 5%).
  - **Inconclusive:** with the next load points or repetitions needed.
  - **No feasible configuration:** when nothing meets the SLOs.

## 8. How to work

1. **Start in plan mode.** Read the PDF, then give me:
   - a short summary of your understanding
   - your open questions
   - a staged implementation plan with acceptance criteria for each stage
   
   Wait for my approval before writing code.
2. Build in stages that follow the PDF roadmap. Each stage must end with something runnable and tested:
   - **Stage 1:** project skeleton, config schema, `validate` and `plan`, workload manifests.
   - **Stage 2:** endpoint mode and the AIPerf wrapper, tested against a **fake OpenAI-compatible streaming server** you write (no GPU needed).
   - **Stage 3:** the `simulate` command and the AISimulate bridge with the support check and the fairness rule.
   - **Stage 4:** managed Docker mode for vLLM and SGLang: lifecycle, GPU lock, cleanup, resume.
   - **Stage 5:** analysis, SLO scoring and the HTML report, including predicted vs measured.
   - **Stage 6:** GitHub Actions (CPU checks on PRs, manual GPU workflow on a self-hosted runner), plus a README that another engineer can follow.
3. **Testing.** Use `pytest` with unit tests for every module. Cover:
   - streaming edge cases: empty chunks, multi-token chunks, partial streams, timeouts
   - lifecycle failures: slow start, OOM, readiness failure, cancellation; only owned containers are stopped and the GPU lock is always released
   - comparison rejection: mismatched precision, changed dataset hash, different timing policy
4. **Never invent benchmark results, model support or tool flags.** If you can't verify something, say so and leave a clearly marked TODO.
5. **Don't run anything that needs a GPU, downloads model weights, or pushes to a remote without asking me first.**
6. Use Python 3.11+, type hints, Pydantic for config models, structured logging, and small commits with clear messages.

Start now: read the PDF, then reply with your summary, your questions, and the staged plan.
