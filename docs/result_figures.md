# Automatic experiment result figures

Q1/Q2 and computational experiments share `src/result_figures`. After saving and
qualifying an execution, the workflow renders fixed Matplotlib templates in an
independent process. Qualified results that refute a hypothesis receive the same
figure treatment as other qualified results. Plotting status is separate from
the scientific result status.

## Installation and configuration

Install the figure dependencies in the workflow's Python environment:

```bash
uv sync --group result-figures
```

Matplotlib, Pillow and PyMuPDF are locked in `uv.lock`; NumPy is a core dependency.
The experiment Docker image does not need these plotting dependencies. The
renderer uses the host Python runtime, `Agg`, fixed templates, a clean
environment, a wall deadline, resource limits where supported, and disabled
network access and child processes.

The resolved run configuration controls the service:

```yaml
result_figures:
  enabled: true
  qualified_only: true
  formats: [png, pdf]       # svg is also supported
  max_figures_per_execution: 6
  timeout_seconds_per_figure: 30
  max_total_seconds_per_execution: 120
  max_output_bytes: 52428800
  failure_policy: continue_with_warning
```

`max_output_bytes` limits each output file. The computational branch's remaining
wall budget can shorten the figure deadline. Missing dependencies, cancellation,
expired deadlines, invalid data and individual rendering errors are recorded;
completed numerical results are retained. Numerical qualification still decides
whether a result is accepted. A plotting failure does not launch another solve.

## Supported data and selection

| Saved data | Figures |
| --- | --- |
| Ordered time/state traces | Trajectories comparing the saved conditions, with different units separated |
| One-dimensional PDE fields | First/middle/last saved spatial profiles and full time-space heatmaps |
| Two-dimensional PDE fields | Final saved fields, with shared color limits across matching conditions |
| Scalar endpoints | Condition comparisons grouped by metric and unit |
| Raw sample arrays | Histograms and boxplots |
| Registered refinement results and reference errors | Log-log grid/time-step error curves |

All saved trace points are exported. Field selection, flattening convention,
units, conditions and shared color limits are recorded in `data_binding` and
captions. Three-dimensional fields require an explicitly declared slice and are
currently skipped. Monte Carlo summaries can be plotted as scalar endpoints;
distributions require saved samples. Error bars require unambiguously bound
uncertainty; the templates do not infer them from unrelated diagnostics.
Convergence plots require distinct positive steps and positive reference errors;
zero errors are recorded as a reason to skip the logarithmic curve. The
per-execution figure limit and omitted recipe IDs are recorded in the manifest.
Reference curves in the computational branch also separate parameter overrides,
fixed solver options and time domains; unrelated physical conditions and duplicate
resolutions cannot form a convergence curve.

## Saved convergence studies

The renderer never runs a refinement study. `prepare_pde_convergence_plans()`
creates plans requiring separate execution authorization. After those plans have
actually run and been qualified, register their saved evidence before qualifying
or finalizing the parent execution:

```python
from src.result_figures import register_saved_convergence_study

study_ref = register_saved_convergence_study(
    root=run_dir,
    version_dir=version_dir,
    records=records,
)
```

Each `records` entry has exactly these keys:

- `plan`, `result`, `execution`, `qualification`: run-relative `path` and
  `sha256` references to the saved artifacts.
- `scenario_id`, `state_id`, `unit`: the saved scenario and field identity.
- `axis`: `x`, `y`, `z`, or `time_step`.
- `error_path`: dictionary keys starting with `verification`, locating the
  already saved numeric reference error inside the scenario's solver result.
- `error_norm`, `reference_id`: the definition of the error and its reference.

Registration verifies each hash, plan/execution identity and recomputed
qualification. Child plans must match refinements reconstructed from the parent
plan; changes to physics, scenarios or parameters are rejected. Time-step
studies are grouped by fixed grid; grid studies are grouped by fixed solver
options. Different scenarios, references and error definitions form separate
curves. Duplicate resolutions are rejected. The resulting
`convergence/result_study.json` is immutable, is read automatically by the parent
figure adapter, and becomes part of its sealed dependencies.

## Artifacts, retries and delivery

Each execution owns a `figures/figures_manifest.json` pointer and immutable
generation/attempt directories. Successful figures include PNG/PDF/SVG outputs,
`figure.py`, `figure_spec.json`, JSON/CSV plotting data and `qa.json`. The manifest
records execution identity, source hashes, dependency versions, renderer version,
caption, selection and output hashes. Its status is `SUCCEEDED`, `PARTIAL`,
`SKIPPED` or `FAILED`; individual figures are `SUCCEEDED` or `FAILED`.

Generation uses a lock and staging directory before atomic commit. Identical
source hashes, settings and renderer versions reuse validated output. Failed or
corrupt figures are retried independently while valid figures are retained.
Normal completion, accepted-result recovery and interrupted-completed-execution
recovery use the same entry point.

Q finalization includes a figure index. Computational handoffs seal figure
manifests, their data and output dependencies. The web artifact index exposes
only verified committed figures, including CSV/JSON and QA downloads. The Q
supplement and Author report copy verified figures into the LaTeX project, check
their hashes, and insert captions in the matching evidence section. Supplement
validation also records final PDF text geometry.

If the Q figure service cannot even write a bundle, finalization records the
execution and an explicit `unavailable` reason in the figure index. Its numerical
evidence remains available to publication and Author.

Calling the integration functions for an already sealed run writes a separate
delivery under `RUN/figure_deliveries/`; the sealed experiment artifacts remain
immutable. The web index and Author resolver recognize these deliveries and
check their connection to the original evidence. Q report deliveries must match
the exact qualified execution IDs in the handoff's hash-bound finalization;
another execution of the same Q model and version is not sufficient.

## Verification

```bash
python -m pytest -q tests/test_result_figures.py tests/test_quantitative_workflow.py \
  tests/test_computational_experiments.py tests/test_webapp_features.py \
  tests/test_webapp_backend_contracts.py tests/test_webapp_api.py
```

These tests render real plots, check exported values, units and PDE geometry,
exercise failures/caching/recovery, reject modified evidence, and verify web and
report delivery. Supplement integration requires `pdflatex` and `pdftoppm`.
Docker acceptance tests in the computational suite retain their explicit
`QWENSCI_REAL_COMPUTATION_TESTS=1` opt-in.
