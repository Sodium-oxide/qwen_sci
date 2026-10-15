# Optional computational experiments

The science workflow remains `Survey → Idea → ExperimentDesign → Author`. ExperimentDesign can start an independent computational branch B alongside the existing design branch A. A keeps its `DESIGN_ONLY` contract. B plans and optionally executes computations, retains versioned evidence, and hands verified results to Author.

## Modes and commands

`off` is the default and preserves existing runs. `plan` produces scientific protocols without issuing execution authorization or running generated programs. `run` authorizes the configured, bounded container execution and iteration loop.

```bash
uv run qwensci science --topic "YOUR ORIGINAL TOPIC" --computation-mode plan --until exp_design
uv run qwensci science --topic "YOUR ORIGINAL TOPIC" --computation-mode run --until author
uv run qwensci science --resume workspace/science-runs/RUN
uv run qwensci computation status --run-dir workspace/science-runs/RUN
uv run qwensci computation cancel --run-dir workspace/science-runs/RUN
uv run qwensci computation resume --run-dir workspace/science-runs/RUN
```

`--computation-model MODEL` selects B's LLM. Modes and model selection are immutable for a science run; resume without changing them. Old runs without computation options resolve to `off`. Explicit computational resume retries recoverable environment or controller failures using the original branch authorization. A completed A stage is reused. Completed Author output requires `--restart-from author --force` to consume a newly available B handoff.

`--until exp_design` joins both branches within B's budget. Author starts after joining B. Missing or failed B execution can leave A and the main workflow completed; inspect B's separate status to assess computational completion. Invalid computational handoffs are recorded as failed and excluded from Author.

## Runtime setup

Generated programs execute only in Linux Docker containers. Install and start a Docker daemon, then build the supplied image:

```bash
docker build -t qwensci-computation:py312-v1 -f src/agents/computational_experiment_agent/execution/Dockerfile .
```

On Windows, the runtime selects the available host `docker` command, otherwise `wsl.exe -d Ubuntu-24.04 -u root -- docker`. For that fallback, install Docker in `Ubuntu-24.04` and ensure its daemon is running. Build the image using that daemon. A missing daemon or image yields `ENVIRONMENT_UNAVAILABLE`; no ordinary host execution fallback is used.

The bundled image uses Python 3.12.12 with NumPy, SciPy, PySCF, JSON Schema and SymPy. Its installed dependencies are captured in `/opt/environment.lock`. Each execution resolves the configured image to an immutable image ID and records that identity and actual dependency lock. Additional Python dependencies must already be available in the configured image; generated programs do not install dependencies during the run.

## Configuration and bounds

The defaults in `src/config/default.yaml` are:

```yaml
computational_experiments:
  mode: off
  failure_policy: continue_main
  author_join: wait_within_budget
  planning:
    max_experiments: 2
    prioritize_primary_gaps: true
  iteration:
    max_code_repairs: 3
    max_protocol_revisions: 1
    max_total_executions: 12
  runtime:
    backend: docker
    max_parallel_experiments: 1
    max_wall_seconds: 3600
    max_execution_seconds: 900
    cpu_cores: 4
    memory_mb: 4096
    network_enabled: true
    environment_id: qwensci-computation:py312-v1
  backends:
    enabled: [mathir, python_project, pyscf]
```

Use the science CLI mode flag to enable the branch. The CLI choice is persisted with the run. The first implementation uses the fixed `continue_main` failure and `wait_within_budget` join behavior, Docker execution, and one active experiment per branch. A and B run concurrently; B's experiments run sequentially.

The total deadline includes planning, code generation, execution, validation and analysis. Failed executions also consume the execution count. Zero execution count or zero execution time prevents execution; zero branch time prevents planning. Each execution receives at most the remaining branch deadline. Container termination and cleanup may add a short bounded cleanup interval after a deadline.

Network is enabled by default as requested. To disable it, set `network_enabled: false` before creating the run. Project and declared inputs are read-only, output is bounded, and generated programs receive neither repository/home mounts nor control-process API credentials. Network access permits access to publicly reachable services; datasets used to support claims should remain explicitly declared and fingerprinted inputs.

## Scientific capabilities

Method profiles are independent of discipline templates. For example, a `materials_chemical` study can choose `quantum_chemistry` with PySCF. The planner receives registered profiles, exact contracts and selected gap/evidence context. It cannot declare a new backend or mark its own result qualified.

| Method/backend | Current execution scope | Required diagnostics |
|---|---|---|
| Numerical modeling / `python_project` | Generated Python models using installed libraries | Finite outputs, independent reference or invariant, convergence, bound raw observations |
| Numerical modeling / `mathir` | Existing quantitative ODE/PDE execution IR and fixed solvers | Validated IR, reference/invariant and convergence diagnostics |
| Quantum chemistry / `pyscf` | Generated projects using installed PySCF APIs; optional legacy fixed single-point driver | Electronic state, reference SCF convergence, method sensitivity, raw endpoint binding and task-specific checks |
| Data analysis / `python_project` | Generated analyses of declared data | Data provenance, estimator validation, uncertainty and explicit diagnostic inputs |
| Molecular dynamics / `python_project` | Registered protocol profile with generated implementation | Equilibration, effective sample size, force-field sensitivity; required software must be in the image |
| Algorithm evaluation / `python_project` | Generated benchmarks with declared baselines and inputs | Repeats, baseline comparability, resource accounting and uncertainty |

New PySCF plans default to `method_spec.implementation_mode: generated`. The agent writes a Python project using the available PySCF API; task types, methods, properties, solvent models, periodic systems and comparison overrides are not restricted to the legacy driver. Endpoints use `observation_binding`, so the host derives each metric from raw condition records. Generated PySCF programs can enter the same bounded code-repair loop as generic Python projects.

The optional `implementation_mode: fixed` preserves the original gas-phase RHF/UHF/RKS/UKS single-point driver and its restrictions. Old sealed protocols without an implementation mode retain this fixed behavior. Generated implementations require the necessary installed software and actual task diagnostics. External optimizers and plugins are not automatically supplied by the bundled image; missing required software or data should be reported as `NEEDS_INPUT`.

Generated PySCF output includes an `electronic_states` record for each condition, with `charge`, `spin`, `nelectron` and actual reference `converged` status. Electronic checks follow declared condition-level charge/spin overrides. Geometry optimization requires `geometry_convergence`; frequency calculations require `frequency_analysis`; transition-state tasks require both. Generated methods explicitly classify `iterative_method`: iterated post-SCF methods declare `true` and must pass a separate `method_convergence` check, while noniterative methods declare `false` with `noniterative_justification`. Additional scientific checks are declared in `method_spec.required_checks`. Diagnostics must cover every applicable condition, including requirements introduced by condition-level task or method overrides. Their numerical evidence must use raw-bound diagnostic endpoints and predeclared thresholds; an unimplemented check cannot qualify a result.

`reference_scf_required` defaults to `true`. A genuinely non-SCF algorithm may declare `false`, explain that choice in `reference_scf_justification`, and supply its own algorithm diagnostics. Such generated protocols do not require SCF tolerances or SCF convergence, but still require electronic-state and scientific-quality checks. The fixed driver always requires SCF.

Declare dataset or structure files in the run's configuration before launch. Each `computational_experiments.inputs` entry contains an absolute `source_path`, a relative staged `path` and its expected `sha256`; optional descriptive fields can state the format and provenance. The controller checks that fingerprint before staging and on resume. `computational_experiments.constraints` carries additional user constraints into planning. Inputs are copied into the isolated `/inputs` volume and never supplied as host directory mounts.

Host qualification supports independent analytic expression evaluation, condition differences, repeat standard errors, explicit metric thresholds and fixed PySCF checks. An unimplemented diagnostic stays failed rather than accepting a program's `passed` flag. Domain-specific checks such as trajectory autocorrelation or dataset leakage still need explicit raw diagnostic inputs and scientifically appropriate, predeclared checks; the registry alone does not compute them.

## Code and observations

B creates an immutable project per implementation version, including source files, host-owned experiment/smoke configuration, a README, dependency requests and a file manifest. A generated project reads `configs/experiment.json` and declared `/inputs`, then writes `/output/observations.json`. It cannot overwrite host configuration. Source files must parse and remain inside their declared project.

Generated Python and PySCF endpoints declare how the host extracts their numeric value from raw condition records:

```json
{
  "metric_id": "final_concentration",
  "description": "Concentration at the declared final time",
  "unit": "dimensionless",
  "estimator": "final_concentration",
  "primary": true,
  "observation_binding": {
    "source_key": "traces",
    "value_key": "values",
    "statistic": "final_value"
  }
}
```

Corresponding observations contain raw records and their reported metrics:

```json
{
  "traces": [{"condition_id": "fine", "times": [0, 1], "values": [1, 0.36787944117144233]}],
  "metrics": [{"metric_id": "final_concentration", "condition_id": "fine", "value": 0.36787944117144233, "unit": "dimensionless"}]
}
```

Bindings support a scalar value, final value, mean, minimum, maximum and trapezoidal integral. Each record identifies its condition and optionally its state. The host recomputes the endpoint and rejects a conflicting reported value. For MathIR, it extracts endpoints from raw solver records; for fixed PySCF, from raw energies; for generated PySCF, from the declared raw property bindings. Reference checks must cover all specified conditions, finite ordered traces and any declared time span. Units and condition/endpoint coverage are checked independently.

Qualification verifies the declared numerical checks; it does not establish that an assumed model represents the real system. Model assumptions, input provenance and conclusion scope remain visible in the protocol and report.

## Iteration and evidence

Engineering failures create a new implementation version within the repair cap. Numerical or method refinements create a new protocol version within the revision cap and preserve earlier evidence. The original hypothesis, endpoints, decision thresholds and comparison identities remain fixed. A qualified result that refutes the hypothesis is accepted immediately. The loop does not revise such a result to seek support.

Host-computed metrics, errors, uncertainty and qualification are deterministic. Optional LLM discussion refers to metric IDs and cannot introduce numeric literals or replace trusted statuses. Simulation discussion cannot claim physical experimental observations. The host renders the numeric tables directly.

B stores its own `context.json`, `branch_state.json`, `events.jsonl`, `controller.log`, `supervisor.log`, authorization and final manifest under `RUN/computation`. Each experiment has separate protocol, implementation and execution versions. Execution records retain actual status, image identity, output, logs and lineage. Qualified handoffs seal and revalidate the protocol, source files, raw observations and recomputed numeric results.

An independent supervisor enforces B's wall deadline and cancellation while A is running or B is blocked in an LLM call. It verifies worker process identity, stops the worker process tree and containers, and preserves available evidence. Interrupted completed executions are processed without resubmission. Resume verifies upstream source identity and experiment/protocol/implementation bindings before reusing evidence.

Author consumes B through a separate `computational_experiment_evidence` section. It includes methods, actual computational qualification, metrics, errors, conclusion scope and unresolved items. Numeric evidence is regenerated from the verified capsule after prose-quality editing. Existing quantitative evidence keeps its separate adapter and authorization workflow. A's methods and expected outcomes retain their proposal status.

## Verification

Local regression tests cover contracts, path restrictions, raw-metric consistency, repair bounds, missing inputs, missing software, budgets, cancellation, recovery, dual-branch scheduling and Author evidence integrity:

```bash
python -m pytest -q tests/test_computational_experiments.py tests/test_science_workflow.py tests/test_science_cli.py
```

Real acceptance tests require the built Docker image. In PowerShell:

```powershell
$env:QWENSCI_REAL_COMPUTATION_TESTS = '1'
python -m pytest -q tests/test_computational_experiments.py -k 'real_reference or real_runtime'
```

They execute generated Python and MathIR scalar relaxation with an analytic reference and convergence checks, fixed and generated PySCF hydrogen calculations with two bases (including MP2 and dipole properties), runtime cancellation/timeout, rejection of symlink outputs, and rejection of forged completion markers. These tests use deterministic protocol/code fixtures; a full production LLM-driven research run requires separately configured upstream evidence and model credentials.
