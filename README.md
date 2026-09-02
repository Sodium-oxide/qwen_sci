# Qwen-Sci

**Qwen-Sci** is a code-executed scientific research workflow. Starting with a research topic, its Python orchestration runs an evidence-to-proposal process that produces literature survey artifacts, a structured research idea, a validated experimental design, and an English research-plan package.

It provides one public command-line interface, `qwensci`, and supports Qwen/DashScope or OpenAI-compatible language-model endpoints.

[GitHub repository](https://github.com/Sodium-oxide/qwen_sci) · [PyPI](https://pypi.org/project/qwen-sci/)

## Code-executed scientific workflow

```text
Research topic
    │
    ▼
Survey ──► Idea ──► ExperimentDesign ──► Author
evidence    proposal      design              research plan
```

`qwensci science` executes this workflow in Python. It calls the stage services, records their inputs and outputs, validates handoffs, and persists an auditable run directory. A complete run includes:

- an isolated `attempt-001`, `attempt-002`, … directory for every stage execution;
- stage manifests whose identity and fingerprints are checked before downstream use;
- `science_state.json` for resumable process state and `events.jsonl` for durable event history;
- a copied configuration snapshot and run metadata for reproducibility; and
- restart support that invalidates a selected stage and its downstream stages **without deleting historical attempts**.

The default four-stage workflow is deliberately **design-only**. Qwen-Sci executes its orchestration, retrieval, validation, and document-generation code, but it does **not** execute arbitrary research programs, laboratory instruments, data-collection jobs, or physical experiments. `ExperimentDesign` creates and validates a plan for such work; it does not perform the work or claim experimental results.

The repository also provides an **optional, supervised quantitative-modeling sidecar** for the bounded numerical models registered in the codebase. It is not a fifth stage in the primary science state machine, never changes `idea_result_v5` or the ExperimentDesign input, and has separate execution authorization. See [Optional supervised quantitative modeling](#optional-supervised-quantitative-modeling).

## Workflow outputs

| Stage | What the code does | Main output |
| --- | --- | --- |
| **Survey** | Retrieves and analyses literature evidence for the research question. | Survey artifacts and a verified survey manifest. |
| **Idea** | Develops a structured, evidence-informed research proposal and directions. | `idea_result.json`. |
| **ExperimentDesign** | Retrieves design evidence, composes a testable design, and validates the design-only plan. | JSON, Markdown, Author handoff JSON, and a JSONL run log. |
| **Author** | Composes an English research-plan package from verified Survey and ExperimentDesign handoffs. | Research-plan artifacts; optionally a copied LaTeX project and validated PDF. |

The recommended entry point is `qwensci science`. Each stage is also available as an individual command when you want to inspect, supply, or reuse a particular handoff.

## Optional supervised quantitative modeling

When enabled, Idea can create at most two independent quantitative ideas, `Q1` and `Q2`, in `quantitative_ideas.json` and `quantitative_ideas_manifest.json`. The main four-stage artifacts remain unchanged. Quantitative modeling may start only after the same run has a completed, design-only ExperimentDesign artifact.

```text
Survey -> Idea -> ExperimentDesign -> Author
             |          ^
             |          | main workflow remains unchanged
             v          |
      Q1/Q2 sidecar -----+
             |
             v
model blueprint -> parameter evidence -> human parameter approval
             -> materialized MathIR/PDEIR plan -> explicit simulation
             -> human qualification -> optional human-accepted revision
             -> standalone mathematical-model PDF -> controlled Author handoff
```

The numerical sidecar supports the registered ODE, optimization, Monte Carlo, and PDE families only. PDE execution uses validated declarative `PDEIR`/`execution_ir` contracts and fixed trusted solver adapters; an LLM can propose a model contract but cannot provide or execute arbitrary Python, Julia, MATLAB, or shell code. Numerical outputs are retained as simulated, non-empirical evidence and are not presented as laboratory or observational results.

### Human confirmation is required

The quantitative branch is deliberately **not an autonomous closed loop**. It can generate non-executing artifacts and report the next required action, but it stops at the following human-controlled decisions:

| Decision point | Required human action | Why the workflow stops |
| --- | --- | --- |
| Parameter selection | Review the provenance, units, conditions, and candidate values; create the explicit selection proposal and run `quantitative parameters approve --approve`. | No executable model can be materialized from the evidence-bound path until one complete parameter set is explicitly approved. |
| Network evidence retrieval | Add `--fetch` to parameter-discovery or open-access full-text retrieval commands. | Academic metadata and full-text network requests are not implicit. |
| Numerical execution | Run `quantitative simulate --execute --plan-identity <EXACT_PLAN_ID>`. | Authorization is bound to one immutable plan identity; changed parameters, scenarios, refinements, or revisions require a new authorization. |
| Result interpretation | Supply the hypothesis relation and bounded result summary to `quantitative qualify`. | A solver result is not automatically interpreted as support, refutation, or a scientific conclusion. |
| Hypothesis/model revision | Review the proposal and run `quantitative accept-revision --accept`. | A proposed revision cannot alter the model or launch a new run by itself; each Q idea is limited to `v0 -> v1 -> v2`. |

`qwensci quantitative continue` and `qwensci science --continue-quantitative` may advance only safe, non-executing transitions such as blueprint generation, materialization after approval, PDF publication, or Author handoff. They never execute a solver and return at parameter review, parameter approval, execution authorization, qualification, and revision-decision states.

### Main workflow remains automatically closable without quantitative execution

Quantitative modeling is off by default. Therefore, when you do **not** request or execute the quantitative branch, the existing primary workflow can run its complete auditable closure:

```text
Survey -> Idea -> ExperimentDesign -> Author
```

For example, the following default command runs the primary workflow through Author, subject to normal service and artifact-validation success:

```bash
uv run qwensci science \
  --topic "Why do black holes exist?" \
  --discipline-id "Astrophysics" \
  --run-id black-hole-existence
```

You may state the default explicitly with `--quantitative-mode off`. By contrast, `--quantitative-mode required` intentionally stops the primary run after ExperimentDesign until the supervised Q1/Q2 branch reaches a completed quantitative Author handoff (unless the Idea sidecar contains no quantitative candidates). Use `--quantitative-mode optional` when the sidecar may be created without making it a prerequisite for the main Author stage.

### Quantitative branch entry points

Start from an existing completed science run and inspect its next safe action:

```bash
uv run qwensci quantitative status \
  --run-dir /path/to/science-run
```

The typical evidence-bound sequence is `blueprint` -> `parameters discover`/`fetch-fulltext`/`extract` -> `parameters propose` -> `parameters approve --approve` -> `materialize` -> `simulate --execute --plan-identity ...` -> `qualify` -> `finalize` -> `publish` -> `author-handoff`. Use `uv run qwensci quantitative --help` and `uv run qwensci quantitative parameters --help` for exact arguments. `pde-validate`, `pde-dry-run`, `pde-refine`, `pde-refine-plans`, `pde-convergence-plans`, and `pde-verify` inspect, estimate, refine, or verify PDE artifacts without running a solver.

### Worked example: pulsar formation

The following WSL examples use the same research question in both paths. The question deliberately contains only the scientific topic; do **not** add words such as "numerical simulation" to `--topic` to try to force a quantitative candidate. The `--quantitative-mode` option controls whether the isolated Q1/Q2 sidecar is requested.

#### Path A: primary workflow only (no mathematical modeling)

Run this from the repository root. It explicitly keeps the quantitative sidecar off and proceeds through the normal `Survey -> Idea -> ExperimentDesign -> Author` closure. It does not invoke a numerical solver or produce a mathematical-model PDF.

```bash
uv run qwensci science \
  --topic "How are pulsars formed? Pulsars are rotating neutron stars that produce pulses of radio waves, X-rays, and gamma rays. They are formed when a massive star runs out of fuel and collapses in on itself. The remnants are neutron stars with magnetic fields that range in strength from 100 million times to 1 quadrillion (a million billion) times that of Earth’s. The correct mix of spin frequency and magnetic field strength is needed for a neutron star to be a pulsar. A pulsar’s radiation bursts typically repeat in a time range anywhere from milliseconds to seconds. It is believed that millisecond pulsars may have formed by consuming fuel from another companion object, thus earning the moniker “black widow pulsars.”" \
  --discipline-id "Astrophysics" \
  --run-id "pulsar-formation-mainline" \
  --quantitative-mode off
```

The run directory is `workspace/science-runs/pulsar-formation-mainline`. If a stage fails for a transient reason, resume the same run rather than creating a new one:

```bash
uv run qwensci science \
  --resume "workspace/science-runs/pulsar-formation-mainline" \
  --until author
```

#### Path B: supervised mathematical modeling and numerical simulation

This path asks Idea to create up to two independent, quantitative candidates while preserving `idea_result_v5` and the normal ExperimentDesign input. `required` makes the initial command complete Survey, Idea, and ExperimentDesign, then intentionally stop before Author until a completed quantitative Author handoff is available. The selected candidate, parameter values, execution plan, result interpretation, and every revision remain subject to human approval.

```bash
uv run qwensci science \
  --topic "How are pulsars formed? Pulsars are rotating neutron stars that produce pulses of radio waves, X-rays, and gamma rays. They are formed when a massive star runs out of fuel and collapses in on itself. The remnants are neutron stars with magnetic fields that range in strength from 100 million times to 1 quadrillion (a million billion) times that of Earth’s. The correct mix of spin frequency and magnetic field strength is needed for a neutron star to be a pulsar. A pulsar’s radiation bursts typically repeat in a time range anywhere from milliseconds to seconds. It is believed that millisecond pulsars may have formed by consuming fuel from another companion object, thus earning the moniker “black widow pulsars.”" \
  --discipline-id "Astrophysics" \
  --run-id "pulsar-formation-quantitative" \
  --quantitative-mode required

export RUN_DIR="workspace/science-runs/pulsar-formation-quantitative"
uv run qwensci quantitative status --run-dir "$RUN_DIR"
```

Read the `status` output first. It reports whether the Q sidecar exists, the available `Q1`/`Q2` IDs, its next safe action, and artifact paths. The commands below use `Q1` and `v0` only as an example: set `Q_ID` to an ID actually present in `quantitative_ideas.json` (use `Q2` when that is the applicable candidate), and copy the exact manifest path reported by `status`.

```bash
export Q_ID="Q1"
export Q_VERSION="0"
export Q_MANIFEST="<EXACT_PATH_TO_quantitative_ideas_manifest.json_REPORTED_BY_STATUS>"

uv run qwensci quantitative blueprint \
  --run-dir "$RUN_DIR" \
  --quantitative-ideas-manifest "$Q_MANIFEST" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION"
```

The generated `model_blueprint.json` names every required parameter, its unit/condition constraints, and the evidence query plan. Review it before retrieving evidence. The following metadata request is an explicit network action; it does not execute a model or solver:

```bash
uv run qwensci quantitative parameters discover \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION" \
  --fetch
```

If the discovered sources include declared open-access full text and their abstract-level metadata is insufficient for the values and conditions required by the blueprint, explicitly retrieve the available full text, then choose one controlled source to extract:

```bash
uv run qwensci quantitative parameters fetch-fulltext \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION" \
  --fetch

export DOCUMENT_ID="<DOCUMENT_ID_FROM_DISCOVERY_OR_A_CONTROLLED_LOCAL_IMPORT>"
uv run qwensci quantitative parameters extract \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION" \
  --document-id "$DOCUMENT_ID"
```

Review the extracted, quote-anchored candidates against the blueprint. A human must provide a complete selection—one entry for every requested parameter—using the actual `parameter_id` and `candidate_id` returned for this run. Do not replace a candidate-backed normalized value with an invented value. The following is a schema example, not a pulsar parameter list; replace every placeholder after review:

```bash
export SELECTIONS_JSON='[
  {
    "parameter_id": "<PARAMETER_ID_FROM_model_blueprint.json>",
    "candidate_id": "<CANDIDATE_ID_FROM_extraction>",
    "provenance_status": "APPROVED_LITERATURE_SINGLE_SOURCE",
    "selection_rationale": "<why this source and its conditions match the model>"
  },
  {
    "parameter_id": "<ANOTHER_REQUIRED_PARAMETER_ID>",
    "candidate_id": "",
    "provenance_status": "APPROVED_MODEL_ASSUMPTION",
    "selected_value": 0.0,
    "selection_rationale": "<human-reviewed sensitivity baseline>"
  }
]'

uv run qwensci quantitative parameters propose \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION" \
  --selections-json "$SELECTIONS_JSON"
```

`parameters propose` creates a reviewable proposal only. Inspect its parameter provenance, dimensional consistency, source context, and the complete list before freezing it. The following command is the first explicit human approval gate:

```bash
uv run qwensci quantitative parameters approve \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION" \
  --approve

uv run qwensci quantitative materialize \
  --run-dir "$RUN_DIR" \
  --quantitative-ideas-manifest "$Q_MANIFEST" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION"
```

Materialization creates the audited model artifacts and `simulation_run_plan.json`; it still does **not** execute a numerical solver. Open that exact plan, inspect its equation/solver family, initial and boundary conditions, scenarios, parameter provenance, resource limits, and `plan_identity`. Only after accepting that immutable plan, copy its exact identity into `PLAN_ID` and authorize one simulation:

```bash
export PLAN_ID="<EXACT_plan_identity_FROM_simulation_run_plan.json>"

uv run qwensci quantitative simulate \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION" \
  --execute \
  --plan-identity "$PLAN_ID"
```

After execution, read the produced result and ledger material before interpreting it. Set `EXECUTION_ID` to the identifier reported by the completed run and select the relation that your review supports: `SUPPORTED_WITHIN_MODEL`, `CONSTRAINED`, `REFUTED_WITHIN_MODEL`, or `INCONCLUSIVE`. The result summary must be bounded to what the model actually established; it must not claim observational or laboratory confirmation.

```bash
export EXECUTION_ID="<EXECUTION_ID_REPORTED_BY_SIMULATION>"

uv run qwensci quantitative qualify \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION" \
  --execution-id "$EXECUTION_ID" \
  --hypothesis-relation "INCONCLUSIVE" \
  --result-summary "<HUMAN_REVIEWED_MODEL_INTERNAL_SUMMARY>"
```

The `INCONCLUSIVE` value above is only a safe placeholder, not a conclusion about pulsar formation; replace it with the relationship warranted by the actual result. If the qualified version is final, create the standalone mathematical-model PDF, create the controlled Author handoff, and resume only the final Author stage:

```bash
uv run qwensci quantitative finalize \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version "$Q_VERSION"

uv run qwensci quantitative publish --run-dir "$RUN_DIR"
uv run qwensci quantitative author-handoff --run-dir "$RUN_DIR"

uv run qwensci science \
  --resume "$RUN_DIR" \
  --until author
```

`publish` writes the quantitative result as a standalone mathematical-model PDF. `author-handoff` supplies its qualified final outcome and necessary revision lineage to Author; Author then creates the normal primary research report without needing to parse the mathematical-model chapter as part of the main article.

If human review requires a revised model or hypothesis, do **not** overwrite `v0` or rerun its plan. During the first release, each Q idea has at most two accepted revisions (`v0 -> v1 -> v2`). Create the refinement with its concrete model/parameter changes, review it, and explicitly accept it. Then repeat the parameter-evidence, approval, materialization, and new plan-identity authorization steps for the new version. Every new simulation requires a separate `--execute` command.

```bash
uv run qwensci quantitative propose-refinement \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --version 0 \
  --revision-reason "<HUMAN_REVIEWED_REASON_FOR_REVISION>" \
  --hypothesis-delta "<EXPLICIT_CHANGE_TO_THE_HYPOTHESIS>" \
  --model-delta-json '<MODEL_DELTA_JSON>' \
  --parameter-or-boundary-delta-json '<PARAMETER_OR_BOUNDARY_DELTA_JSON>' \
  --expected-discriminating-result "<WHAT_THE_REVISION_WOULD_DISTINGUISH>" \
  --falsification-condition "<MODEL_INTERNAL_FALSIFICATION_CONDITION>"

uv run qwensci quantitative accept-revision \
  --run-dir "$RUN_DIR" \
  --idea-id "$Q_ID" \
  --parent-version 0 \
  --accept
```

After acceptance, run `quantitative status --run-dir "$RUN_DIR"` again and use its returned paths and next action for `v1`; acceptance itself neither materializes nor executes the revised model.

## Requirements

- Python **3.12** (`>=3.12,<3.13`)
- [`uv`](https://docs.astral.sh/uv/) for source/development installation
- A Qwen/DashScope account or an OpenAI-compatible endpoint
- Linux x86_64 or **WSL2**

The locked development environment targets Linux x86_64. On Windows, use WSL rather than a native Windows virtual environment.

## Installation

### Install a published package

When using a released package from PyPI, create a separate virtual environment outside the repository:

```bash
python3.12 -m venv "$HOME/.venvs/qwen-sci"
"$HOME/.venvs/qwen-sci/bin/python" -m pip install --upgrade pip
"$HOME/.venvs/qwen-sci/bin/python" -m pip install qwen-sci
"$HOME/.venvs/qwen-sci/bin/qwensci" --help
```

### Install from source (recommended for contributors)

Run these commands in WSL. Use an external environment so `uv` never creates, replaces, or synchronizes a repository-local `.venv`:

```bash
git clone https://github.com/Sodium-oxide/qwen_sci.git
cd qwen_sci

export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
uv sync --all-groups --locked
uv run qwensci --help
```

Set `UV_PROJECT_ENVIRONMENT` in every shell where you run `uv` for this checkout. `--all-groups` is the complete local setup; focused installations may use only the groups required for their work:

| Capability | Command |
| --- | --- |
| Core API-driven workflow | `uv sync` |
| Memory and vector retrieval | `uv sync --group memory --group ml` |
| PDF parsing and full-text survey paths | `uv sync --group pdf` |
| Explicit image, video, signal, table, audio, 3D, or trajectory inputs | `uv sync --group multimodal` |
| Complete development setup | `uv sync --all-groups --locked` |

## Configure a model provider

Copy the template and keep the resulting `.env` private:

```bash
cp .env.example .env
```

For Qwen/DashScope, add the following values to `.env`:

```dotenv
QWENSCI_LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=replace-with-your-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
SEMANTIC_SCHOLAR_API_KEY=replace-with-your-key
```

For an OpenAI-compatible endpoint, use:

```dotenv
QWENSCI_LLM_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
SEMANTIC_SCHOLAR_API_KEY=replace-with-your-key
```

`OPENAI_API_BASE` remains a compatibility alias, but new configurations should use `OPENAI_BASE_URL`. Never commit `.env` or paste real credentials into source code, issues, logs, or screenshots.

Check local prerequisites before a full run:

```bash
uv run qwensci doctor
```

`doctor` reports provider settings, required credentials, and optional local retrieval assets. It can return a non-zero status when optional models or credentials are absent; inspect the individual checks to decide whether the command you plan to use needs them.

## Quick start: an auditable science run

The primary command runs the full code-executed workflow. This example uses a topic supplied for Qwen-Sci:

```bash
uv run qwensci science \
  --topic "Why do black holes exist?" \
  --discipline-id "Astrophysics" \
  --run-id black-hole-existence
```

The new run is created below `workspace/science-runs/black-hole-existence/` unless you provide `--output-root`. The command executes stages in order, records state after every transition, and prints the resulting run information.

For a cheaper first pass, stop at an earlier stage:

```bash
uv run qwensci science \
  --topic "Why do black holes exist?" \
  --discipline-id "Astrophysics" \
  --run-id black-hole-existence \
  --until idea
```

Resume the same run rather than starting another directory:

```bash
uv run qwensci science \
  --resume workspace/science-runs/black-hole-existence
```

If a stage needs to be re-run, restart from that point with an explicit confirmation. Earlier attempts remain available for audit:

```bash
uv run qwensci science \
  --resume workspace/science-runs/black-hole-existence \
  --restart-from exp_design \
  --force
```

Use `--json` when another program needs the stable `science_run_result_v1` result on standard output. Use `qwensci science --help` for all supported options, including Author template and PDF-rendering settings.

## Run stages individually

Individual commands are useful when a stage needs a carefully reviewed input, a custom output location, or a separately managed handoff.

### 1. Survey

Use the research question as `--topic` and put the supplied scientific context in `--research-brief`:

```bash
uv run qwensci survey \
  --topic "Why do black holes exist?" \
  --declared-domain "astrophysics" \
  --research-brief "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves."
```

`--research-objective`, `--base-dir`, `--save-path`, and `--save-json-path` let you refine the question and choose output locations. Survey accepts explicit multimodal input only when you provide `--multimodal-file` or `--multimodal-evidence-manifest`; install the `multimodal` group first for those paths.

### 2. Idea

Create a structured research proposal from the question and contextual seed:

```bash
uv run qwensci idea \
  --topic "Why do black holes exist?" \
  --input "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves." \
  --survey-manifest /path/to/survey_manifest.json \
  --output-root /path/to/idea-runs
```

`--survey-manifest` is optional for a standalone Idea run, but it is the preferred way to give Idea verified literature context. The `idea_result.json` output is the input to ExperimentDesign.

### 3. ExperimentDesign

```bash
uv run qwensci exp_design \
  --idea-json /path/to/idea_result.json \
  --discipline-id "Astrophysics"
```

Use `--selected-direction` to choose an Idea direction, `--model` to override the configured model, and `--output-dir` to control where the design artifacts are written. The output includes an `experiment_design_author_<timestamp>.json` handoff for Author.

### 4. Author

```bash
uv run qwensci author \
  --author-input /path/to/experiment_design_author_<timestamp>.json \
  --survey-manifest /path/to/survey_manifest.json
```

Author verifies the Survey and ExperimentDesign bindings before composing an English research-plan package. Add `--template-dir /path/to/latex-template` to render a copied template; use `--render-required` with `qwensci science` when a rendered document must be produced for the run to succeed. Rendered reports contain only the routed research-plan sections and fixed appendices—no acknowledgment section is emitted by default. Their default validated minimum is seven pages; `--minimum-pages 8` is treated as the legacy spelling of that seven-page minimum, while higher explicit minimums remain available.

## CLI reference

All commands are available through `uv run qwensci …` from source, or `qwensci …` from a published-package environment.

| Command | Purpose |
| --- | --- |
| `qwensci survey` | Produce literature-survey evidence and artifacts. |
| `qwensci idea` | Develop structured research ideas and directions. |
| `qwensci exp_design` | Produce and validate a design-only experimental plan. |
| `qwensci author` | Create an English research-plan package from verified handoffs. |
| `qwensci science` | Run, resume, or restart the complete auditable workflow. |
| `qwensci doctor` | Report local runtime prerequisites. |
| `qwensci install-mcp-wrappers` | Install local Bash-based MCP wrapper scripts on Linux/WSL. |

The package also exposes `qwensci-survey`, `qwensci-idea`, `qwensci-doctor`, and `qwensci-install-mcp-wrappers` as focused console-script entry points. Prefer the unified `qwensci` command in new scripts and documentation.

## Reproducibility and local assets

`src/config/default.yaml` is the canonical configuration for provider capabilities, role models, workflow settings, workspace paths, and default output locations. For a reproducible project, copy it to a private/project-specific file and pass that file with `--config /path/to/config.yaml`.

The repository intentionally does not include credentials, downloaded embedding models, graph/vector stores, cached PDFs, generated documents, or runtime workspaces. Examples of locally provisioned assets include:

```text
models/all-MiniLM-L6-v2/
models/bge-m3/
data/processed/graph.db
data/processed/core_component_summary_vector_store/
workspace/science-runs/
```

Keep these resources, `.env`, and any generated research artifacts outside commits. Review paths and contents before sharing logs because they can reveal local usernames, source documents, or organization information.

## Security

- Treat every API key as a secret; rotate any key exposed in a commit, chat, log, or screenshot.
- Run external experiments, simulations, and instruments under their own reviewed execution environment. Qwen-Sci's design artifacts are not a substitute for those controls.
- Review generated research plans and cited evidence before using them for scientific decisions, publication, or real-world experimental work.

## License

See [LICENSE](LICENSE).
