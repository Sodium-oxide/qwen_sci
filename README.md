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
