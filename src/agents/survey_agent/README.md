# Deep Survey

Deep Survey is an automated academic survey generation pipeline. Given a research topic, it collects related papers, expands the paper set through references and citations, reads and analyzes papers with LLMs, clusters related work, optionally builds relation/code analysis artifacts, generates a survey draft, revises it, refines citations, and optionally evaluates the final survey.

## Repository layout

```text
.
├── Dockerfile                    # Container environment for Deep Survey and MinerU
├── config/                       # Hydra/YAML runtime configurations
│   ├── evaluation/               # Evaluation experiment configs
│   └── *.yaml                    # Default and task-specific configs
├── scripts/                      # Main runnable entry points
├── modules/                      # Core pipeline modules
├── utils/                        # API, logging, file, PDF, markdown and helper utilities
├── topics/                       # Topic lists and benchmark topic definitions
├── baselines/                    # Baseline systems and baseline outputs
├── tests/                        # Development tests and scratch files
├── logs/                         # Runtime logs, ignored by git
├── outputs/                      # Generated surveys and artifacts, ignored by git
└── database/                     # Local paper/cache/database artifacts, ignored by git
```

`logs/`, `outputs/`, and `database/` are generated/runtime directories and are ignored by git. The `logs/` directory can usually be ignored when reading the codebase.

## Run Survey from the repository root

The supported source entry point is `uv run qwensci survey` from the Qwen-Sci repository root, not a bare `qwensci` command in an unrelated active virtual environment. On Linux/WSL, select one project environment and use the same setting in each new shell:

```bash
cd /path/to/qwensci
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
uv sync --all-groups --locked
source "$UV_PROJECT_ENVIRONMENT/bin/activate"
uv run qwensci doctor
```

Configure provider credentials in a private `.env` or configuration file before running. `src/config/default.yaml` is the canonical project configuration; copy it for project-specific settings and pass the copy with `--config /path/to/config.yaml`. Never commit credentials or generated research artifacts.

```bash
uv run qwensci survey \
  --topic "Global changes in flash-drought frequency" \
  --declared-domain "climate science" \
  --research-objective "Compare changes in flash-drought frequency and onset mechanisms."
```

Use `--base-dir`, `--save-path`, and `--save-json-path` to select output locations. For local research figures, repeat `--multimodal-file /path/to/figure.png` for each file. Local-only processing is the default; add `--allow-remote-perception` only after reviewing non-sensitive inputs and explicitly consenting to bounded remote visual inspection. Use `uv run qwensci survey --help` for all options. Do not pass `...` as a literal argument or use `uv run --no-sync`.

### Optional local embedding models

The repository does not include downloaded models. ModelScope is installed by the `--all-groups` step above (or by `uv sync --group pdf --locked` when setting up a smaller environment). If the configured retrieval paths require these models, download both from the repository root:

```bash
mkdir -p models/bge-m3 models/all-MiniLM-L6-v2
modelscope download --model BAAI/bge-m3 --local_dir "$PWD/models/bge-m3"
modelscope download --model sentence-transformers/all-MiniLM-L6-v2 --local_dir "$PWD/models/all-MiniLM-L6-v2"
```

Keep model directories, caches, PDFs, logs, and outputs outside commits. The repository-root README has the full provider and asset setup.

## Pipeline overview

The main Deep Survey pipeline follows these stages:

1. Related work collection
   - Searches seed papers for the target topic.
   - Expands papers through references and citations.
   - Can use local graph/cache data when configured.
2. Paper database construction
   - Builds an embedding/database view over collected papers.
3. Paper comprehension
   - Reads papers or abstracts.
   - Writes reusable paper keynotes into cache.
4. Clustering and analysis
   - Clusters related papers.
   - Optionally performs intra-cluster and inter-cluster analysis.
   - Optionally generates relation graphs and relation tables.
5. Optional code/environment report generation
   - Collects and analyzes code repositories linked to papers.
   - Generates code and environment reports when enabled.
6. Survey generation
   - Generates an outline.
   - Drafts sections/subsections.
   - Reviews and revises the draft.
   - Refines final paper text and references.
7. Optional evaluation
   - Evaluates generated survey quality and citation quality when enabled.

## Core modules

- `modules/work_collector.py`: collects seed papers and expands them via references/citations.
- `modules/database.py`: builds retrieval databases over collected papers.
- `modules/work_analyzer.py`: reads papers, extracts keynotes, clusters papers, and performs relation/cluster analysis.
- `modules/survey_generator.py`: generates outlines, drafts survey sections, reviews/revises drafts, and saves final survey outputs.
- `modules/judge.py`: evaluates survey outputs when evaluation is enabled.
- `modules/code_collector.py`: collects code repository information.
- `modules/code_report_generator.py`: generates code/environment reports from collected repositories.
- `modules/paper_graph_retriever.py`: retrieves papers from local graph/database resources.

## Important scripts

The scripts below are advanced standalone/Hydra entry points. Run their relative paths from `src/agents/survey_agent/` with a compatible environment and their own configs; they are not the recommended Qwen-Sci CLI workflow above.

### Single-topic Hydra entry point

```bash
python3 scripts/run_deep_survey.py
```

This uses Hydra with the default config declared in the script:

```text
config/deep_survey_fast.yaml
```

You can override Hydra config values from the command line, for example:

```bash
python3 scripts/run_deep_survey.py BasicInfo.topic="Graph Neural Networks"
```

### Batch entry point with explicit YAML config

```bash
python3 scripts/run_deep_survey_batch_arg.py --config ./config/personal/deep_survey_batch_0514.yaml
```

This is the most explicit batch runner. It reads a YAML file, loads topics according to `BasicInfo`, and runs the pipeline for each topic. For example, `config/personal/deep_survey_batch_0514.yaml` uses:

- `BasicInfo.user_defiend_benchmarks: True`
- `BasicInfo.topic_path: ./topics/human_compare_topics.txt`
- `BasicInfo.output_base_dir: ./outputs/0514_mimo_pro_human_test`
- `BasicInfo.skip_exist: True`

### Adapter entry point

```bash
python3 scripts/run_deep_survey_adapter.py --workspace /workspace --config /workspace/config/runtime.yaml
```

The adapter is designed for external orchestration. It writes standardized artifacts such as:

```text
/workspace/survey/output/survey.md
/workspace/survey/output/survey.json
/workspace/survey/output/evaluation.txt
/workspace/logs/relation_graph.json
/workspace/logs/relation_table.json
/workspace/logs/clustering_result.json
/workspace/logs/draft.json
/workspace/logs/deep_survey.log
```

### Baseline evaluation

```bash
python3 scripts/baseline_evaluation.py
```

This script evaluates outputs from Deep Survey and baseline systems such as AutoSurvey, SurveyForge, LiRA, and human-written surveys according to the configured benchmark/evaluation settings.

### Other utility scripts

- `scripts/run_keynotes_gen.py`: pre-generate paper keynotes.
- `scripts/run_work_clusters.py`: run work clustering utilities.
- `scripts/memory_monitor.sh`: monitor memory usage during long-running jobs.
- `scripts/run_model_ablation.sh`: run model ablation experiments.

## Configuration

The unified CLI uses `src/config/default.yaml` by default, or a project-specific copy supplied through `--config`. The following `config/` examples describe the standalone Hydra scripts only; do not assume their relative paths or settings apply to `uv run qwensci survey`.

For the unified Survey workflow, `survey.ModuleInfo.SurveyGenerator.outline_evidence_plan_max_input_tokens` is `120000` in `src/config/default.yaml`. The standalone `config/deep_survey.yaml` also uses `120000`. This is the compact evidence-plan component limit, not a guarantee that the whole outline prompt fits: `outline_prompt_max_input_tokens` also bounds the total input. If preflight still rejects a plan, reduce allowed-paper constraints or adjust the relevant limits explicitly in a private config and pass it with `--config`.

Configurations live under `config/`. The common top-level sections are:

```yaml
BasicInfo:
  topic: ""
  topic_path: ./topics/human_compare_topics.txt
  output_base_dir: ./outputs/example
  cache_path: ./database
  topic_max_retry: 5
  skip_exist: True

APIInfo:
  llm_api_key: "..."
  llm_api_base_url: "..."
  llm_model_name: "..."
  # Required for OpenAlex literature retrieval; do not commit the literal key.
  openalex_api_key: "${oc.env:OPENALEX_API_KEY,''}"
  batch_chat_agent_worker: 2
  chat_timeout: 3600
  batch_chat_timeout: 1800

ModuleInfo:
  WorkCollector:
    max_seed_paper_num: 15
    reference_graph_depth: 1
  WorkAnalyzer:
    abstract_only_mode: False
    paper_reading_max_retry: 6
  SurveyGenerator:
    include_initial_analysis: True
    include_relation_graph: False
    include_relation_table: False
    include_code_report: False
    enable_review_and_revise: True
  Judge:
    skip_evaluation: True
```

Before running experiments, check at least these fields:

- `BasicInfo.topic` or `BasicInfo.topic_path`
- `BasicInfo.output_base_dir`
- `BasicInfo.cache_path`
- `APIInfo.llm_api_key`
- `APIInfo.llm_api_base_url`
- `APIInfo.llm_model_name`
- `APIInfo.openalex_api_key` (or the `OPENALEX_API_KEY` environment variable)
- `APIInfo.batch_chat_agent_worker`
- `ModuleInfo.Judge.skip_evaluation`

Avoid committing real API keys. Prefer using environment variables or local-only config files for secrets.

## Topics

Topic lists are stored in `topics/`. Batch runs can use:

```yaml
BasicInfo:
  user_defiend_benchmarks: True
  topic_path: ./topics/human_compare_topics.txt
```

Benchmark topic dictionaries are defined in:

```text
topics/Benchmark_topics.py
```

Relevant switches include:

- `BasicInfo.AutoSurvey_benchmark`
- `BasicInfo.SurveyGen_benchmark`
- `BasicInfo.sub_benchmark_test`
- `BasicInfo.user_defiend_benchmarks`

## Outputs

Generated files are typically written under `BasicInfo.output_base_dir`. A batch run stores per-domain/per-topic results and may produce:

- Markdown survey files
- JSON survey files with paper text and references
- Evaluation result files
- Analysis artifacts such as clustering results, relation graphs, relation tables, draft files, code reports, and environment reports

The exact outputs depend on `ModuleInfo.SurveyGenerator` and `ModuleInfo.Judge` switches.

## Docker environment

This directory includes a standalone Dockerfile at `Dockerfile`. It is separate from the repository-root `uv` environment and may have different dependency versions; use the root workflow above for current Qwen-Sci runs.

The image is based on:

```dockerfile
FROM vllm/vllm-openai:v0.10.1.1
```

It installs:

- Noto fonts and fontconfig for Chinese text rendering
- `libgl1` for OpenCV support
- `mineru[core]` for PDF parsing
- `hydra-core`, `asciinet`, `tenacity`, `trafilatura`, `readability-lxml`, `html2text`
- OpenJDK 25
- `rich`, `loguru`, `sentence-transformers`, `hdbscan`

It also sets:

```dockerfile
ENV HF_ENDPOINT=https://hf-mirror.com
ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
```

and downloads MinerU models during image build:

```bash
mineru-models-download -s huggingface -m all
```

Build example:

```bash
docker build -t deep-survey:latest .
```

Run example:

```bash
docker run --gpus all --rm -it \
  -v /path/to/deep-survey:/workspace/deep-survey \
  -w /workspace/deep-survey \
  deep-survey:latest \
  python3 scripts/run_deep_survey_batch_arg.py --config ./config/personal/deep_survey_batch_0514.yaml
```

If building the standalone image, review its dependency versions and Dockerfile independently before using it for a current Qwen-Sci run.

## PDF and MinerU utilities

PDF/markdown related utilities are under `utils/`, especially:

```text
utils/mineru_utils.py
utils/convert_to_md.py
utils/html_utils.py
```

`utils/mineru_utils.py` contains MinerU-based parsing helpers for converting PDFs into markdown-like outputs. The Dockerfile installs MinerU and pre-downloads its models so PDF parsing can run with local MinerU model sources.

## Recommended run patterns

For normal Survey runs, use `uv run qwensci survey` as shown above. The batch examples below apply only to the standalone scripts and their YAML configs.

### Foreground run

```bash
CUDA_VISIBLE_DEVICES=0 python3 scripts/run_deep_survey_batch_arg.py \
  --config ./config/personal/deep_survey_batch_0514.yaml
```

### Background run with log capture

```bash
mkdir -p logs
nohup bash -lc 'CUDA_VISIBLE_DEVICES=0 python3 scripts/run_deep_survey_batch_arg.py --config ./config/personal/deep_survey_batch_0514.yaml' \
  > ./logs/deep_survey_batch.log 2>&1 &
```

### Memory monitoring

```bash
bash scripts/memory_monitor.sh
```

For long experiments on remote/HPC machines, prefer using `tmux`, `screen`, or a job scheduler so the process is not interrupted by SSH session disconnection.

## Troubleshooting

### `qwensci: command not found` or Hydra rejects `...`

From source, run `uv run qwensci survey --help` in the repository root with `UV_PROJECT_ENVIRONMENT` set to the environment used for `uv sync`. Activating a different environment does not install the CLI there. Replace `...` in examples with real flags; Hydra treats it as an invalid override.

### Compact outline evidence plan exceeds its prompt budget

The current evidence-plan component limit is `120000` tokens. A larger allowed-paper set may still exceed this limit or the overall outline-prompt budget. Narrow the paper constraints first; if a larger budget is justified, edit a private copy of `src/config/default.yaml` and supply it with `--config`.

### `cv2` or MinerU import errors

Multiple OpenCV distributions can overwrite the same `cv2` namespace and cause import or missing-attribute errors. The root `pyproject.toml` pins `opencv-python-headless` and overrides GUI OpenCV dependencies; synchronize with `uv` and avoid bare `pip install` into that environment. The root `scripts/install_heavy.sh` also targets the selected `uv` environment.

### `Killed`

`Killed` can be caused by OOM, scheduler limits, or external signals. Check:

- system/job scheduler logs
- shell/session disconnection
- memory logs
- GPU/CPU memory usage
- custom signal traps if enabled

### `ProxyError` or API timeout

In this project, repeated `ProxyError` can also indicate upstream API timeout, connection reset, gateway failure, or too much concurrent traffic. Consider reducing:

```yaml
APIInfo:
  batch_chat_agent_worker: 1
  low_flow_mode: True
  low_flow_latency: 2
  exponential_backoff: True
```

### Hugging Face network issues

The Dockerfile sets:

```bash
HF_ENDPOINT=https://hf-mirror.com
```

If the environment cannot access Hugging Face, use a mirror, pre-download models, or configure offline cache paths.

### Logs directory

`logs/` is runtime-only and ignored by git. It is useful for debugging local runs but should not be treated as source code.

## Development notes

- The codebase is Python-based and uses Hydra/OmegaConf-style YAML configs.
- Most modules are initialized from the selected config, so behavior is usually controlled by YAML rather than command-line flags.
- Long-running batch jobs depend heavily on API stability, retry settings, and concurrency settings.
- Generated caches under `database/` can speed up later runs but are not source files.
