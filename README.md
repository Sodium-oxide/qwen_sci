# Qwen-Sci

**Qwen-Sci** is a multi-agent research workflow that turns a research topic into literature evidence, a structured research idea, a validated experimental design, and an English research plan. It provides one public command-line interface, `qwensci`, backed by Qwen or OpenAI-compatible language-model endpoints.

> **Release status — 0.2.0.** This repository contains the workflow code and configuration. API credentials, downloaded embedding models, graph/vector indexes, PDFs, experiment outputs, and runtime workspaces are intentionally local-only and are not included in Git.

[English](README.md) · [简体中文](README_CN.md) · [GitHub repository](https://github.com/Sodium-oxide/qwen_sci)

## What Qwen-Sci does

| Component | Purpose | Public command |
| --- | --- | --- |
| Survey Agent | Retrieves and analyses literature, groups evidence, and writes survey artifacts. | `qwensci survey` |
| Idea Agent (LigAgent) | Turns a topic, prior evidence, or a seed idea into a structured research proposal. | `qwensci idea` |
| ExperimentDesign Agent | Builds and validates a design-only experimental plan from an Idea result and evidence; it never executes experiments. | `qwensci exp_design` |
| Research Plan Author | Composes an English research-plan package from verified Survey and ExperimentDesign artifacts, optionally rendering a copied LaTeX template. | `qwensci author` |
| Science workflow | Creates or resumes the auditable Survey → Idea → ExperimentDesign → Author workflow. | `qwensci science` |

The `science` workflow is useful for an end-to-end design-only run. During development and debugging, running one agent at a time is usually clearer and gives each stage an explicit input and output.

## Requirements and supported environment

- Python **3.12** (`>=3.12,<3.13`)
- [`uv`](https://docs.astral.sh/uv/)
- A Qwen/DashScope account **or** an OpenAI-compatible endpoint
- Linux x86_64 or WSL2. The locked `uv` environment is currently targeted at Linux x86_64; Windows users should use WSL rather than a native Windows virtual environment.

Some workflows also require optional local assets and dependency groups:

| Capability | Install / provision |
| --- | --- |
| Core CLI and API-driven flows | `uv sync` |
| Memory and vector retrieval | `uv sync --group memory --group ml` |
| PDF parsing and survey full-text processing | `uv sync --group pdf` |
| Explicit image, video, signal, table, audio, 3D, or trajectory input | `uv sync --group multimodal` |
| Optional OCR, figure, and text-removal stack | `uv sync --group pdf --group blog` |
| Full local setup | `uv sync --all-groups` |

For the first complete setup, use `uv sync --all-groups`. It avoids the common `ModuleNotFoundError: pypdfium2` failure when a survey path needs PDF parsing.

## Install and configure

### 1. Clone and install

```bash
git clone https://github.com/Sodium-oxide/qwen_sci.git
cd qwen_sci
uv sync --all-groups
```

The PDF group is pinned to **MinerU 3.4.5** and includes its Linux vLLM
backend. Do not update it in an existing project environment with a separate
`pip install -U 'mineru[all]'`: that command does not re-resolve Qwen-Sci's
installed metadata and can leave incompatible package versions behind. After
changing dependency declarations, resolve and install the project as one set:

```bash
uv lock
uv sync --all-groups
uv pip check
```

`uv sync` deliberately does not install the `pip` package in a project
environment. Use `uv pip check` above for validation; it works without a
`pip` module. For a legacy virtual environment that is intentionally managed
with pip, pass the project and requirements file to the same resolver
invocation, then use pip's own check command:

```bash
python -m pip install --upgrade -e . -r requirements.txt
python -m pip check
```

`uv run` is the recommended way to run commands because it selects the project environment without manually activating it.

If you prefer activation, use the command appropriate for your shell:

```bash
# bash / zsh / WSL
source .venv/bin/activate
```

```powershell
# PowerShell (native Windows is not the supported dependency target)
.\.venv\Scripts\Activate.ps1
```

### 2. Create a private environment file

```bash
cp .env.example .env
```

In PowerShell, use:

```powershell
Copy-Item .env.example .env
```

`.env` is ignored by Git. Keep keys only in this file or in your deployment secret manager; never put a real credential in YAML, Python source, an issue, or a commit.

### 3. Configure a provider

Select the unified model provider with `QWENSCI_LLM_PROVIDER`. The public package and command are **Qwen-Sci** and `qwensci`.

For Qwen/DashScope, set the following in `.env`:

```dotenv
QWENSCI_LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=replace-with-your-key
# Leave this default unless your DashScope-compatible gateway says otherwise.
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Required by the current `qwensci doctor` check and used by literature retrieval.
SEMANTIC_SCHOLAR_API_KEY=replace-with-your-key
```

For an OpenAI-compatible endpoint, use instead:

```dotenv
QWENSCI_LLM_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
SEMANTIC_SCHOLAR_API_KEY=replace-with-your-key
```

Use `OPENAI_BASE_URL` for new configurations. `OPENAI_API_BASE` is an older compatibility alias; do not set conflicting values for both.

### 4. Inspect the local setup

```bash
uv run qwensci doctor
```

`doctor` is deliberately strict. It reports the active provider and role models, required credentials, and the optional local retrieval assets listed below. It exits non-zero until *all* of those checks pass, so a `FAIL` line for a graph database or a local embedding model means that full local retrieval is not ready—not that every API-only command is necessarily unusable.

## Quick start

After configuring `.env`, start with a survey. The topic is the research question; provide supporting context separately with `--research-brief`:

```bash
uv run qwensci survey \
  --topic "Why do black holes exist?" \
  --declared-domain "astrophysics" \
  --research-brief "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves."
```

Then create an idea from the same question and context:

```bash
uv run qwensci idea \
  --topic "Why do black holes exist?" \
  --input "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves."
```

The default configuration is [`src/config/default.yaml`](src/config/default.yaml). A command-line `--topic` overrides the relevant topic for that run without editing the file. Use `--config /path/to/config.yaml` to run a separate configuration.

## Command reference

All commands below can be called as `uv run qwensci …`, or as `qwensci …` after activation/install. The agent commands and `doctor` accept `--config`; run `uv run qwensci <command> --help` for the complete option list.

### Environment diagnostics

```bash
uv run qwensci doctor
uv run qwensci-doctor
```

Use this before a full retrieval, ExperimentDesign, Author, or `science` run. It prints paths and setting names but never prints secret values.

### Survey

```bash
uv run qwensci survey \
  --topic "Why do black holes exist?" \
  --declared-domain "astrophysics" \
  --research-brief "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves."
```

Useful survey options:

```bash
uv run qwensci survey \
  --topic "Why do black holes exist?" \
  --declared-domain "astrophysics" \
  --research-objective "Explain the theoretical and astrophysical basis for black-hole formation." \
  --research-brief "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves." \
  --base-dir /path/to/survey-workspace \
  --save-path /path/to/survey.md \
  --save-json-path /path/to/survey.json
```

Without output overrides, survey artifacts are written below `src/agents/survey_agent/outputs/` according to the active configuration.

#### Explicit multimodal input

Multimodal input is disabled by default. Text-only Survey and Idea users do not need the multimodal group: Survey does not scan directories or read media unless you explicitly provide either repeatable `--multimodal-file` paths or one manifest. Before using explicit media input, install its bounded local readers:

```bash
uv sync --group multimodal
```

Use local-only analysis when the input must remain on your machine:

```bash
uv run qwensci survey \
  --topic "Microstructure mechanisms under humidity cycling" \
  --multimodal-file /data/micrograph-01.png \
  --multimodal-file /data/micrograph-02.png
```

Use `multimodal_input_manifest_v1` when the modality is ambiguous or records need grouping metadata. Each `file` is relative to the manifest directory; absolute paths, `..` traversal, and symlinks outside that directory are rejected.

```json
{
  "schema_version": "multimodal_input_manifest_v1",
  "dataset_id": "experiment-042",
  "records": [
    {
      "record_id": "img-001",
      "file": "files/micrograph-01.tif",
      "modality": "image",
      "group": "batch-A",
      "condition": "high-humidity",
      "timepoint": "cycle-20"
    }
  ]
}
```

```bash
uv run qwensci survey \
  --topic "Microstructure mechanisms under humidity cycling" \
  --multimodal-evidence-manifest /data/experiment-042/manifest.json
```

With both explicit input and `--allow-remote-perception`, Survey additionally allows the fixed `qwen3-vl-plus` model to inspect a bounded preview:

```bash
uv run qwensci survey \
  --topic "Microstructure mechanisms under humidity cycling" \
  --multimodal-file /data/micrograph-01.tif \
  --allow-remote-perception
```

Without `--allow-remote-perception`, Survey performs bounded local-only metadata and aggregate native analysis. With it, only image, signal, audio, 3D, and trajectory records are eligible for a size-limited, re-encoded PNG preview sent to `qwen3-vl-plus`; video, table, text, and symbolic records remain local-only. Every eligible preview has EXIF and source paths removed. Raw media, Base64 payloads, preview paths, unfiltered model replies, and full tables never enter runtime evidence. Validated observations can become at most three data-anchored `MM_SH_*` retrieval questions, each with supporting and counter/alternative evidence queries. They are scheduled ahead of automatically decomposed SHs but remain hypotheses, not scientific conclusions.

Common input errors fail before Survey starts: `--allow-remote-perception` requires a file or manifest, `--multimodal-file` and `--multimodal-evidence-manifest` are mutually exclusive, and missing optional readers report `uv sync --group multimodal`. Molecular files are not treated as text: the first release rejects them until an independent chemistry group with RDKit support is introduced.

### Idea

```bash
uv run qwensci idea \
  --topic "Why do black holes exist?" \
  --input "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves."
```

The Idea Agent can also receive an input or seed idea and write to a selected output root:

```bash
uv run qwensci idea \
  --topic "Why do black holes exist?" \
  --input "Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves." \
  --mature-idea "Optional seed idea" \
  --survey-manifest /path/to/survey_manifest.json \
  --output-root /path/to/idea-runs
```

The expected artifact for ExperimentDesign is `idea_result.json` (or an Idea run directory containing it).

### ExperimentDesign

```bash
uv run qwensci exp_design \
  --idea-json /path/to/idea_result.json \
  --discipline-id "Astrophysics"
```

ExperimentDesign retrieves design evidence, composes and validates a design-only plan, and writes JSON, Markdown, an Author handoff JSON, and a JSONL run log. It does not run code, simulations, or experiments.

By default, outputs are placed beside the Idea result. Use `--output-dir` to select another directory, `--selected-direction` to choose a specific Idea direction, and `--model` to override the configured ExperimentDesign model.

### Research Plan Author

```bash
uv run qwensci author \
  --author-input /path/to/experiment_design_author_<timestamp>.json \
  --survey-manifest /path/to/survey_manifest.json
```

Author requires the ExperimentDesign handoff and a completed, verified Survey manifest. It composes an English-only proposal package; with `--template-dir` or a configured rendering template, it can copy the template into the run output and render a validated PDF. Use `--idea-result` only to include source-anchored Idea checkpoints.

### Science workflow

```bash
uv run qwensci science \
  --topic "Why do black holes exist?" \
  --discipline-id "Astrophysics"
```

`science` initializes or resumes an auditable, design-only run under `workspace/science-runs/`. Its stages bind Survey, Idea, ExperimentDesign, and Author artifacts by identity and fingerprints. Use `--resume /path/to/run` to continue a run, and `--restart-from <stage> --force` to invalidate that stage and downstream stages without deleting historical artifacts.

### Helper scripts and MCP wrappers

To install local MCP wrapper scripts, run:

```bash
uv run qwensci install-mcp-wrappers
```

This command invokes a Bash script and is therefore intended for Linux/WSL.

## Local retrieval assets

The repository does **not** ship the following large or generated resources:

```text
data/processed/graph.db
data/processed/core_component_summary_vector_store/build_stats.json
data/processed/core_component_summary_vector_store/faiss.index
data/processed/core_component_summary_vector_store/meta.json
models/all-MiniLM-L6-v2/
models/bge-m3/
```

Place externally provisioned assets at those paths, or update the appropriate paths in `src/config/default.yaml`. Do not commit models, vector stores, graph databases, downloaded papers, run logs, or a populated `workspace/` directory.

If you have the graph data and want to start the local graph service:

```bash
uv run uvicorn graph.server:app --host 127.0.0.1 --port 8000
```

## Environment variable reference

Copy `.env.example` and leave settings blank unless you need the corresponding feature. The following table is the public configuration reference for variables currently supplied by the template or read by the unified configuration.

| Group | Variables | When to set them |
| --- | --- | --- |
| Provider selection | `QWENSCI_LLM_PROVIDER` | Set to `qwen` or `openai`. |
| Runtime configuration | `QWENSCI_CONFIG`, `QWENSCI_CONFIG_PATH` | Optional runtime overrides for direct module invocation. Prefer the public `--config /path/to/config.yaml` option for normal CLI use. |
| ExperimentDesign | `EXPERIMENT_DESIGN_LLM_PROVIDER`, `EXPERIMENT_DESIGN_LLM_MODEL` | Override the ExperimentDesign provider or model. |
| Research Plan Author | `RESEARCH_PLAN_AUTHOR_LLM_PROVIDER`, `RESEARCH_PLAN_AUTHOR_LLM_MODEL`, `RESEARCH_PLAN_AUTHOR_QUALITY_MODEL` | Override the Author provider, composition model, or whole-document quality model. |
| Qwen text and vision | `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, `DASHSCOPE_IMAGE_BASE_URL` | Required for Qwen text calls; image endpoint/base URL is needed for Qwen figure generation. |
| OpenAI-compatible text | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_API_BASE`, `OPENAI_MODEL` | Use when the selected provider is `openai`; prefer `OPENAI_BASE_URL`. |
| Literature and retrieval | `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_EMAIL`, `UNPAYWALL_EMAIL`, `SERPER_API_KEY`, `GITHUB_AI_TOKEN`, `JINA_API_KEY`, `TAVILY_API_KEY`, `HF_TOKEN` | Semantic Scholar is checked by `doctor`; the others enable their corresponding retrieval, search, download, or Hugging Face paths. OpenAlex can work without an email; Unpaywall DOI resolution needs one. |
| Survey role overrides | `SURVEY_LLM_MODEL`, `SURVEY_JUDGE_PROVIDER`, `SURVEY_JUDGE_MODEL` | Override the configured survey or judge model settings. |
| Idea role overrides | `IDEA_LLM_MODEL`, `IDEA_GENERATION_MODEL`, `IDEA_EVALUATION_MODEL` | Override the base, generation, or evaluation model for Idea Agent. |
| Memory | `MEMORY_LLM_PROVIDER`, `MEMORY_LLM_MODEL` | Override the LLM used by the shared memory subsystem. |
| Vision and image generation | `VISION_LLM_PROVIDER`, `VISION_QUALITY_MODEL`, `VISION_BATCH_MODEL`, `IMAGE_GENERATION_PROVIDER`, `IMAGE_ACADEMIC_FIGURE_MODEL`, `IMAGE_TEXT_RICH_FIGURE_MODEL`, `IMAGE_DRAFT_MODEL` | Change Qwen vision review or figure-generation model choices. |
| Direct legacy utility only | `SURVEY_AGENT_API_KEY`, `SURVEY_AGENT_API_URL`, `SURVEY_AGENT_MODEL_NAME`, `SURVEY_AGENT_DATA_DIR` | Required only when running `src/agents/survey_agent/utils/step2v2.py` directly; `qwensci survey` does not require this standalone utility configuration. |
| Agent-specific compatibility | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` | Needed only by code paths explicitly configured to use them; they do not select the unified provider by themselves. |

Use role-model overrides only after the basic provider setup works. The supported provider/model capabilities are declared in `src/config/default.yaml`; assigning a model to a role that needs unsupported capabilities can make `doctor` fail before a run starts.

## Configuration and output locations

`src/config/default.yaml` is the canonical unified configuration. It contains the provider registry, model capabilities, agent settings, workspace root, and default output locations.

| Area | Primary configuration |
| --- | --- |
| Shared provider/model registry | `llm:` in `src/config/default.yaml` |
| Survey Agent | `survey:` plus `src/agents/survey_agent/config/*.yaml` |
| Idea Agent | `idea:` |
| ExperimentDesign | `experiment_design:` |
| Research Plan Author | `research_plan_author:` |
| Workspace root | `workspace.root` (defaults to `workspace/`) |

For a reproducible research run, copy the default YAML to a separate private/project configuration, make changes there, and pass it with `--config`. Keep generated output and credentials outside source-controlled files.

## Security and data handling

- Treat every API key as a secret and rotate any key that has appeared in a public commit, chat, log, or screenshot.
- Review paths before sharing logs: local workspace paths may reveal usernames or organization information.
- Do not commit `.env`, model directories, graph/vector data, PDF caches, generated reports, or runtime workspaces.
- Use public, generic paths such as `/path/to/qwen-sci/workspace` in documentation and issue reports.

## License

See [LICENSE](LICENSE).
