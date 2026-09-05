# Qwen-Sci

**Qwen-Sci** is a code-executed scientific research workflow with both a Python CLI and a browser control plane. Starting with a research topic, its orchestration runs an evidence-to-proposal process that produces literature survey artifacts, a structured research idea, a validated experimental design, and a research-plan package.

It provides one public command-line interface, `qwensci`, and uses Qwen/DashScope language-model endpoints.

[GitHub repository](https://github.com/Sodium-oxide/qwen_sci) · [PyPI](https://pypi.org/project/qwen-sci/)

[English](README.md) · [简体中文](README.zh-CN.md)

## First-time setup: Windows, WSL2, and Linux

The supported Windows setup uses a Linux distribution inside WSL2. Run the first block in **PowerShell as Administrator**, restart Windows if the installer asks you to, and complete the Ubuntu user creation step:

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
wsl --set-default-version 2
```

Open the new Ubuntu terminal and install the basic tools. `uv` supplies the locked Python 3.12 runtime, so a native Windows Python installation is not required:

```bash
sudo apt update
sudo apt install -y git curl ca-certificates build-essential
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
uv python install 3.12
```

Keep the checkout inside the WSL filesystem for faster dependency and build operations:

```bash
mkdir -p "$HOME/src"
cd "$HOME/src"
git clone https://github.com/Sodium-oxide/qwen_sci.git
cd qwen_sci
```

If the repository already exists on the Windows drive, use its WSL-mounted path instead, for example:

```bash
cd /mnt/c/Users/<WindowsUser>/Desktop/2026tzb/aiscientist-v0820
```

Create the project environment, install **all** dependency groups, activate that exact environment, and verify the interpreter:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
uv sync --all-groups
source "$UV_PROJECT_ENVIRONMENT/bin/activate"
python --version       # should report Python 3.12.x
which python
```

Next configure a model provider in [Configure a model provider](#configure-a-model-provider), then run the prerequisite check:

```bash
uv run qwensci doctor
```

`doctor` prints a check-by-check report for Python, `uv`, provider settings, credentials, and optional local retrieval assets. A non-zero result can be expected when optional models or provider keys have not been configured; fix every check required by the workflow you plan to run. In every new WSL shell, export `UV_PROJECT_ENVIRONMENT` and source its `bin/activate` file again. Do not use `uv run --no-sync`.

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

### Install local embedding models with ModelScope

The local vector-retrieval and novelty components use `all-MiniLM-L6-v2` and
`bge-m3` when their configured model paths point to the directories above.
Install the optional ModelScope dependency first (the `pdf` group includes
`modelscope`), then run the following commands from the repository root. Replace
`<repo_root>` with the absolute path to this checkout.

```bash
uv sync --group pdf

mkdir -p <repo_root>/models/bge-m3
mkdir -p <repo_root>/models/all-MiniLM-L6-v2

modelscope download --model BAAI/bge-m3 \
  --local_dir <repo_root>/models/bge-m3
modelscope download --model sentence-transformers/all-MiniLM-L6-v2 \
  --local_dir <repo_root>/models/all-MiniLM-L6-v2
```

For example, when the repository is the current directory, use `$PWD` in place
of `<repo_root>`:

```bash
modelscope download --model BAAI/bge-m3 \
  --local_dir "$PWD/models/bge-m3"
modelscope download --model sentence-transformers/all-MiniLM-L6-v2 \
  --local_dir "$PWD/models/all-MiniLM-L6-v2"
```

Keep these resources, `.env`, and any generated research artifacts outside commits. Review paths and contents before sharing logs because they can reveal local usernames, source documents, or organization information.

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
| `qwensci-web` | Serve the same-origin Web workspace and its controlled research-run API. |
| `qwensci install-mcp-wrappers` | Install local Bash-based MCP wrapper scripts on Linux/WSL. |

The package also exposes `qwensci-survey`, `qwensci-idea`, `qwensci-doctor`, and `qwensci-install-mcp-wrappers` as focused console-script entry points. Prefer the unified `qwensci` command in new scripts and documentation.

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

## Quick start: an auditable science run

The primary command runs the full code-executed workflow. This example uses a topic supplied for Qwen-Sci:

```bash
uv run qwensci science \
  --topic "Why do black holes exist? Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves." \
  --discipline-id "Physics and Astronomy" \
  --run-id black-hole-existence
```

The new run is created below `workspace/science-runs/black-hole-existence/` unless you provide `--output-root`. The command executes stages in order, records state after every transition, and prints the resulting run information.

The canonical OpenAlex field for astrophysics topics is `31` (`Physics and Astronomy`). The `--discipline-id` option also accepts the aliases `Astrophysics`, `Astronomy`, and `physics_astronomy`, as well as the OpenAlex field URL `https://openalex.org/fields/31`.

For a cheaper first pass, stop at an earlier stage:

```bash
uv run qwensci science \
  --topic "Why do black holes exist? Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves." \
  --discipline-id "Physics and Astronomy" \
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

## Explicit multimodal research materials

Survey can incorporate declared local research materials rather than treating arbitrary local files as evidence. The input contract accepts `image`, `table`, `signal`, `audio`, `video`, `threeD`, `trajectory`, `text`, `symbolic`, and `molecule` records, validates file size and metadata, and writes a path-free handoff. The default mode is **local-only**: local parsers may derive bounded native findings, but no remote model observation or scientific claim is created from a file unless remote perception is explicitly authorized.

Install optional local readers when a run needs them:

```bash
uv sync --group multimodal
```

For the standalone Survey command, provide each file explicitly (or provide one `multimodal_input_manifest_v1` manifest). Positional configuration overrides cannot enable multimodal runtime state.

```bash
uv run qwensci survey \
  --topic "How does electrode morphology affect cycle stability?" \
  --declared-domain "materials science" \
  --multimodal-file ./electrode-micrograph.png \
  --multimodal-file ./cycling-data.csv
```

`--allow-remote-perception` is a separate, per-run consent. It requires explicit multimodal input and permits only the configured Qwen `qwen3-vl-plus` route to inspect bounded, metadata-free PNG previews for supported non-sensitive modalities. Qwen-Sci does not send original paths, raw media, EXIF data, base64 payloads, or provider raw responses to downstream handoffs. Review materials before granting this consent. Molecule/RDKit handling currently reports an explicit unsupported-capability error rather than silently treating chemical structures as text.

The Web workspace stores browser uploads inside the selected run. Image and table modalities are inferred from safe file extensions; material records intended for Survey must be marked as `survey_evidence` and must not be marked sensitive. Other uploaded files remain run-scoped context and are not routed into the multimodal Survey manifest. Per-file uploads are limited to 50 MiB and the total per run to 250 MiB; all materials become immutable once a science stage starts.

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
  --discipline-id "Physics and Astronomy" \
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
  --discipline-id "Physics and Astronomy" \
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
  --discipline-id "Physics and Astronomy" \
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
- A Qwen/DashScope account and API key
- Linux x86_64 or **WSL2**
- [Node.js](https://nodejs.org/) and npm only when building or developing the Web workspace

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

Never commit `.env` or paste real credentials into source code, issues, logs, or screenshots.

### Environment variables and API keys

The following values cover the normal Qwen/DashScope workflow. Keep them in the private `.env` file at the repository root:

| Variable | Required? | Purpose |
| --- | --- | --- |
| `QWENSCI_LLM_PROVIDER` | Recommended | Set to `qwen`; the default is already `qwen`. |
| `DASHSCOPE_API_KEY` | **Required** | Qwen text, vision, and image-generation requests. |
| `DASHSCOPE_BASE_URL` | Optional | DashScope compatible-mode URL; defaults to `https://dashscope.aliyuncs.com/compatible-mode/v1`. |
| `DASHSCOPE_IMAGE_BASE_URL` | Optional | DashScope image API URL; defaults to `https://dashscope.aliyuncs.com/api/v1`. |
| `SEMANTIC_SCHOLAR_API_KEY` | **Required by `doctor`** | Literature metadata and evidence retrieval. |
| `OPENALEX_API_KEY` | Optional | Higher-rate OpenAlex literature discovery. |
| `OPENALEX_EMAIL` | Optional | Contact address for provider requests. |
| `UNPAYWALL_EMAIL` | Optional | Enables DOI-to-PDF resolution for available open-access papers. |
| `SERPER_API_KEY` | Optional | Serper search lane. |
| `JINA_API_KEY` | Optional | Jina search or reader lane. |
| `TAVILY_API_KEY` | Optional | Tavily search lane. |
| `GITHUB_AI_TOKEN` | Optional | GitHub-hosted AI or repository integration paths. |
| `HF_TOKEN` | Optional | Authenticated Hugging Face model downloads. |

For multimodal or generated-figure workflows, the model names can be overridden with `VISION_QUALITY_MODEL`, `VISION_BATCH_MODEL`, `IMAGE_ACADEMIC_FIGURE_MODEL`, `IMAGE_TEXT_RICH_FIGURE_MODEL`, and `IMAGE_DRAFT_MODEL`; these variables are optional and continue to use `DASHSCOPE_API_KEY`. `SURVEY_AGENT_API_KEY`, `SURVEY_AGENT_API_URL`, and `SURVEY_AGENT_MODEL_NAME` are only needed when invoking the legacy standalone Survey helper directly. Use `QWENSCI_CONFIG` or `QWENSCI_CONFIG_PATH` only when you intentionally select a different configuration file.

After saving `.env`, run the local prerequisite check from the activated WSL environment:

```bash
uv run qwensci doctor
```

For a complete development checkout, prefer `uv sync --all-groups`. Focused installations are available when you do not need every optional capability:

| Capability | Command |
| --- | --- |
| Core API-driven workflow | `uv sync` |
| Memory and vector retrieval | `uv sync --group memory --group ml` |
| PDF parsing and full-text survey paths | `uv sync --group pdf` |
| Explicit image, video, signal, table, audio, 3D, or trajectory inputs | `uv sync --group multimodal` |
| Complete development setup | `uv sync --all-groups` |

## Web workspace V2

The same workflow is available as a local, same-origin browser workspace. It is a control plane over the persistent `workspace/science-runs/` directory, not a browser-side simulation. Build the React client once, then start the Python service from the repository root:

```bash
npm --prefix WebApp-V2 install
npm --prefix WebApp-V2 run build
uv run qwensci-web
```

Open [http://127.0.0.1:8010](http://127.0.0.1:8010). The Web API serves the built client from `WebApp-V2/dist`; build it again after changing frontend source. On WSL, use the address printed by the service or the Windows browser's WSL localhost forwarding.

### Browser workflow

1. Enter a topic and choose one or two disciplines from the supported catalog (the interface currently exposes 20 supported scientific disciplines and can suggest up to two from the topic).
2. Optionally upload research materials before starting. The browser records them under this run only, checks their hash on later reads, and lets you set their scope and sensitive-data flag.
3. Choose a stopping point: `Survey`, `Survey + Idea`, `Survey + Idea + ExperimentDesign`, or the full run through `Author`. `required` quantitative mode stops before Author until the separate quantitative review path is complete.
4. Start or resume the trusted workflow. You can request cancellation while a stage is running; the current stage is allowed to persist atomically, completed outputs remain available, and no later science stage starts. Resume is a separate typed user action and lets you choose the stopping point again.
5. Inspect artifacts, the full durable event timeline, and controlled stage logs in the page. The timeline contains every persisted event rather than only stage start/end summaries. The log panel discovers `.jsonl` and `.log` files beneath the run's `survey`, `idea`, `experiment_design`, and `author` directories; it pages large files, follows active logs, and never accepts a browser-provided filesystem path.

Browser responses and log views redact local paths and credential-like fields such as API keys, tokens, Authorization headers, passwords, and cookies. The logging API deliberately excludes the uploaded `inputs/` directory. Do not rely on this UI redaction as a reason to place secrets into research prompts or files.

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
  --discipline-id "Physics and Astronomy"
```

Use `--selected-direction` to choose an Idea direction, `--model` to override the configured model, and `--output-dir` to control where the design artifacts are written. The output includes an `experiment_design_author_<timestamp>.json` handoff for Author.

### 4. Author

```bash
uv run qwensci author \
  --author-input /path/to/experiment_design_author_<timestamp>.json \
  --survey-manifest /path/to/survey_manifest.json
```

Author verifies the Survey and ExperimentDesign bindings before composing an English research-plan package. Add `--template-dir /path/to/latex-template` to render a copied template; use `--render-required` with `qwensci science` when a rendered document must be produced for the run to succeed. Rendered reports contain only the routed research-plan sections and fixed appendices—no acknowledgment section is emitted by default. Their default validated minimum is seven pages; `--minimum-pages 8` is treated as the legacy spelling of that seven-page minimum, while higher explicit minimums remain available.

## Security

- Treat every API key as a secret; rotate any key exposed in a commit, chat, log, or screenshot.
- Browser logs are a diagnostic view, not a raw file browser: the service exposes only allowlisted stage log files and redacts paths and credential-like values before response.
- Remote multimodal perception is disabled by default and requires both an explicit input and a per-run authorization. Avoid enabling it for sensitive, proprietary, or personally identifiable material.
- Run external experiments, simulations, and instruments under their own reviewed execution environment. Qwen-Sci's design artifacts are not a substitute for those controls.
- Review generated research plans and cited evidence before using them for scientific decisions, publication, or real-world experimental work.

## License

See [LICENSE](LICENSE).
