# Qwen-Sci

**Qwen-Sci** 是一个多智能体科研工作流：它将研究主题逐步转化为文献证据、结构化研究想法、实验工作空间和技术博客草稿。项目通过统一的 `qwensci` 命令行接口运行，并支持 Qwen 或 OpenAI 兼容的语言模型服务。

> **发布状态：0.2.0。** 仓库提供工作流代码和配置；API 凭据、下载的嵌入模型、图数据库/向量索引、PDF、实验产物和运行工作空间均只应保留在本地，不会随 Git 仓库发布。

[English](README.md) · [简体中文](README_CN.md) · [GitHub 仓库](https://github.com/Sodium-oxide/qwen_sci)

## 功能概览

| 组件 | 作用 | 公开命令 |
| --- | --- | --- |
| Survey Agent | 检索和分析文献、组织证据、生成综述产物。 | `qwensci survey` |
| Idea Agent（LigAgent） | 将主题、已有证据或种子想法转为结构化研究 proposal。 | `qwensci idea` |
| Experiment Agent | 准备资源、生成自包含实验项目、执行受控条件，并记录经审阅的证据。 | `qwensci experiment` |
| Blog Agent | 基于已完成的实验工作空间生成技术博客草稿。 | `qwensci blog` |
| Pipeline | 编排 Survey → Idea → Experiment → Blog 全流程。 | `qwensci pipeline` |

Pipeline 适合完整端到端运行；在配置、调试或开发阶段，建议先逐个运行 Agent，使每个阶段的输入和输出都可单独检查。

## 环境要求与支持范围

- Python **3.12**（`>=3.12,<3.13`）
- [`uv`](https://docs.astral.sh/uv/)
- Qwen/DashScope 账号，或一个 OpenAI 兼容 API 端点
- Linux x86_64 或 WSL2。当前 `uv` 锁定环境面向 Linux x86_64；Windows 用户建议使用 WSL，不建议在原生 Windows 虚拟环境中安装完整依赖。

不同功能需要的依赖和本地资源不同：

| 能力 | 安装或准备方式 |
| --- | --- |
| 基础 CLI 和 API 驱动流程 | `uv sync` |
| Memory 与向量检索 | `uv sync --group memory --group ml` |
| PDF 解析和 Survey 全文处理 | `uv sync --group pdf` |
| Blog 的 OCR、配图和去文字工具链 | `uv sync --group pdf --group blog` |
| 完整本地环境 | `uv sync --all-groups` |

第一次完整部署建议使用 `uv sync --all-groups`。这样可以避免 Survey 路径需要 PDF 解析时出现 `ModuleNotFoundError: pypdfium2`。

## 安装与配置

### 1. 克隆并安装依赖

```bash
git clone https://github.com/Sodium-oxide/qwen_sci.git
cd qwen_sci
uv sync --all-groups
```

PDF 依赖组已固定为 **MinerU 3.4.5**，并包含 Linux 下的 vLLM 后端。不要在已有项目环境中单独执行
`pip install -U 'mineru[all]'`：该命令不会重新求解已安装的 Qwen-Sci 元数据，可能留下相互不兼容的版本。修改依赖声明后，应将整个项目作为一组重新求解并安装：

```bash
uv lock
uv sync --all-groups
uv pip check
```

`uv sync` 会有意不在项目环境中安装 `pip` 包。请使用上面的 `uv pip check` 验证依赖，它不依赖 `pip` 模块。只有在你刻意使用由 pip 管理的传统虚拟环境时，才应在同一次求解中传入项目和依赖文件，并使用 pip 自身的检查命令：

```bash
python -m pip install --upgrade -e . -r requirements.txt
python -m pip check
```

推荐使用 `uv run` 启动命令，它会自动使用项目虚拟环境，无需手动激活。

如需手动激活，请根据终端类型选择正确命令：

```bash
# bash / zsh / WSL
source .venv/bin/activate
```

```powershell
# PowerShell（原生 Windows 不是完整依赖的支持目标）
.\.venv\Scripts\Activate.ps1
```

### 2. 创建私有环境变量文件

```bash
cp .env.example .env
```

PowerShell 中使用：

```powershell
Copy-Item .env.example .env
```

`.env` 已被 Git 忽略。密钥只应放在该文件或部署环境的密钥管理系统中；不要把真实凭据写入 YAML、Python 源码、Issue 或提交历史。

### 3. 配置模型服务

使用 `QWENSCI_LLM_PROVIDER` 选择统一模型 provider；公开项目名和命令均为 **Qwen-Sci** / `qwensci`。

使用 Qwen/DashScope 时，在 `.env` 中填写：

```dotenv
QWENSCI_LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=替换为你的密钥
# 除非 DashScope 兼容网关要求其他地址，否则保持默认值。
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 当前 `qwensci doctor` 会检查此项，文献检索也会使用它。
SEMANTIC_SCHOLAR_API_KEY=替换为你的密钥
```

使用 OpenAI 兼容端点时，改为：

```dotenv
QWENSCI_LLM_PROVIDER=openai
OPENAI_API_KEY=替换为你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
SEMANTIC_SCHOLAR_API_KEY=替换为你的密钥
```

新配置请使用 `OPENAI_BASE_URL`。`OPENAI_API_BASE` 是保留的兼容别名；请不要同时为二者填入相互冲突的值。

### 4. 检查本地环境

```bash
uv run qwensci doctor
```

`doctor` 的检查标准是严格的：它会输出当前 provider、角色模型、必需凭据以及下文列出的本地图检索资源。只有全部检查通过时才返回零退出码。因此，`graph.db` 或本地嵌入模型显示 `FAIL` 表示完整本地检索尚未就绪，并不等价于所有 API 驱动命令都无法运行。

## 快速开始

配置 `.env` 后，先从 Survey 开始：

```bash
uv run qwensci survey --topic "面向 LLM Agent 的免训练记忆系统"
```

再以相同主题生成研究想法：

```bash
uv run qwensci idea --topic "面向 LLM Agent 的免训练记忆系统"
```

默认统一配置位于 [`src/config/default.yaml`](src/config/default.yaml)。命令行中的 `--topic` 只覆盖当前运行所需主题，不会修改原配置。使用 `--config /path/to/config.yaml` 可运行自定义配置文件。

## 命令参考

以下命令均可写成 `uv run qwensci …`；激活环境或安装项目后，也可以直接使用 `qwensci …`。各 Agent 命令与 `doctor` 支持 `--config`，完整参数请执行 `uv run qwensci <命令> --help`。

### 环境诊断

```bash
uv run qwensci doctor
uv run qwensci-doctor
```

在完整检索、实验或 Pipeline 前执行该命令。它只会显示设置项名称和路径，不会打印密钥值。

### Survey

```bash
uv run qwensci survey --topic "你的研究主题"
```

常用参数：

```bash
uv run qwensci survey \
  --topic "你的研究主题" \
  --declared-domain "computer science" \
  --research-objective "填写要回答的科学问题" \
  --base-dir /path/to/survey-workspace \
  --save-path /path/to/survey.md \
  --save-json-path /path/to/survey.json
```

未指定输出路径时，Survey 产物会按照当前配置写入 `src/agents/survey_agent/outputs/` 下。

### Idea

```bash
uv run qwensci idea --topic "你的研究主题"
```

Idea Agent 还可接收补充输入或种子想法，并将结果写到指定目录：

```bash
uv run qwensci idea \
  --topic "你的研究主题" \
  --input "可选：已有证据或问题描述" \
  --mature-idea "可选：种子想法" \
  --output-root /path/to/idea-runs
```

Experiment Agent 的标准输入产物为 `idea_result.json`。

### Experiment

```bash
uv run qwensci experiment \
  --experiment memory-study \
  --idea-json /path/to/idea_result.json
```

默认情况下，命令会先把 idea 文件复制到 `workspace/memory-study/`，然后执行实验控制平面。主要阶段包括：

1. `prepare`：发现并验证仓库、数据集、模型和环境绑定；
2. `code`：生成自包含项目并记录 smoke evidence；
3. `science`：运行参考条件与组件禁用条件；
4. `finalization`：验证证据链并写入最终消融结果。

只准备资源而不运行后续阶段：

```bash
uv run qwensci experiment \
  --experiment memory-study \
  --idea-json /path/to/idea_result.json \
  --prepare-only
```

使用 `--resume` 继续已有运行；`--force` 重新运行 prepare；只有在资源确实已准备好且明确希望跳过时，才使用 `--skip-repos` / `--skip-datasets`。

关键实验产物通常位于 `workspace/<experiment-id>/`：

```text
idea.json / idea_result.json
project/                                  生成的实验实现
repos/, dataset_candidate/, model_candidate/ 已准备资源
results/science/<condition-id>/            日志、指标和条件输出
agent_reports/*/phase.json                 阶段报告
agent_reports/ablation/final/ablation_results.json
agent_reports/ablation/final/symbolic_memory_receipt.json
```

### Blog

```bash
uv run qwensci blog --experiment memory-study
```

默认情况下，Blog Agent 读取 `workspace/memory-study`。若实验工作空间位于其他目录，请明确传入：

```bash
uv run qwensci blog \
  --experiment memory-study \
  --source-workspace /path/to/experiment-workspace
```

使用 `--resume` 继续未完成的 Blog 工作流。完整的 OCR 和配图处理需要安装 `pdf` 与 `blog` 依赖组。

### Pipeline

```bash
uv run qwensci pipeline --topic "你的研究主题"
```

Pipeline 会编排 Survey → Idea → Experiment → Blog。后续阶段依赖前一阶段已成功产生的工作空间产物；若出现配置、数据或模型问题，建议先使用独立命令逐段排查。

### 包装脚本和 MCP wrapper

仓库保留 `run_survey.sh`、`run_idea.sh`、`run_experiment.sh`、`run_blog.sh` 和 `run_pipeline.sh` 等 Bash 包装脚本。它们优先调用 `qwensci`，在迁移期间才回退到旧命令；这些脚本只是便利入口，正式文档入口是 `qwensci`。

安装本地 MCP wrapper：

```bash
uv run qwensci install-mcp-wrappers
```

该命令会调用 Bash 脚本，因此仅面向 Linux/WSL。

## 可选本地图检索资源

仓库**不包含**下列大型或生成型资源：

```text
data/processed/graph.db
data/processed/core_component_summary_vector_store/build_stats.json
data/processed/core_component_summary_vector_store/faiss.index
data/processed/core_component_summary_vector_store/meta.json
models/all-MiniLM-L6-v2/
models/bge-m3/
```

请将外部准备的资源放到上述位置，或在 `src/config/default.yaml` 中更新相应路径。不要提交模型、向量索引、图数据库、下载论文、运行日志或已填充的 `workspace/`。

拥有图数据后，可从仓库根目录启动本地图服务：

```bash
uv run uvicorn graph.server:app --host 127.0.0.1 --port 8000
```

## 环境变量参考

请从 `.env.example` 复制 `.env`，仅填写实际使用的功能项。下表是模板中提供或统一配置实际读取的公开环境变量说明。

| 分组 | 变量 | 何时设置 |
| --- | --- | --- |
| Provider 选择 | `QWENSCI_LLM_PROVIDER` | 填 `qwen` 或 `openai`。 |
| 运行时配置 | `QWENSCI_CONFIG`、`QWENSCI_CONFIG_PATH` | 供直接运行模块时覆盖配置路径。日常 CLI 使用优先传入公开参数 `--config /path/to/config.yaml`。 |
| Experiment 运行时 | `QWENSCI_OPENHARNESS_HEARTBEAT_SECONDS`、`QWENSCI_SYMBOLIC_MEMORY_PATH`、`QWENSCI_WORKSPACE_ROOT` | Experiment Agent 的可选运行时控制项；只有明确希望覆盖配置行为时才设置。 |
| 受管 artifact shell | `QWENSCI_ARTIFACT_ID`、`QWENSCI_ARTIFACT_PATH` | 由受管 artifact 命令自动注入。不要写入 `.env`，也不要手动设置。 |
| Qwen 文本与视觉 | `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_IMAGE_BASE_URL` | Qwen 文本调用必需；Qwen 图像生成还需图像端点地址。 |
| OpenAI 兼容文本 | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_API_BASE`、`OPENAI_MODEL` | 当 provider 为 `openai` 时使用；优先设置 `OPENAI_BASE_URL`。 |
| 文献与检索 | `SEMANTIC_SCHOLAR_API_KEY`、`OPENALEX_EMAIL`、`UNPAYWALL_EMAIL`、`SERPER_API_KEY`、`GITHUB_AI_TOKEN`、`JINA_API_KEY`、`TAVILY_API_KEY`、`HF_TOKEN` | `doctor` 会检查 Semantic Scholar；其余变量分别开启对应检索、搜索、下载或 Hugging Face 能力。OpenAlex 没有邮箱仍可用；Unpaywall 的 DOI→PDF 解析需要邮箱。 |
| Survey 模型覆盖 | `SURVEY_LLM_MODEL`、`SURVEY_JUDGE_PROVIDER`、`SURVEY_JUDGE_MODEL` | 覆盖 Survey 或 Judge 的模型设置。 |
| Idea 模型覆盖 | `IDEA_LLM_MODEL`、`IDEA_GENERATION_MODEL`、`IDEA_EVALUATION_MODEL` | 覆盖 Idea Agent 的基础、生成或评估模型。 |
| Experiment 模型覆盖 | `EXPERIMENT_LLM_PROVIDER`、`EXPERIMENT_LLM_MODEL`、`EXPERIMENT_PLANNER_MODEL`、`EXPERIMENT_WORKER_MODEL`、`EXPERIMENT_REVIEWER_MODEL`、`EXPERIMENT_MASTER_MODEL` | 覆盖 Experiment Agent 的 provider、默认模型及角色模型。 |
| Memory | `MEMORY_LLM_PROVIDER`、`MEMORY_LLM_MODEL` | 覆盖共享 Memory 子系统使用的 LLM。 |
| Blog | `BLOG_LLM_PROVIDER`、`BLOG_LLM_MODEL`、`BLOG_RETRIEVAL_MODE`、`BLOG_GRAPH_DB_PATH`、`BLOG_AGENT_SOURCE_WORKSPACE` | 设置 Blog Agent 的 provider/model、检索倾向、图数据库位置或外部实验工作空间。 |
| 视觉与图像生成 | `VISION_LLM_PROVIDER`、`VISION_QUALITY_MODEL`、`VISION_BATCH_MODEL`、`IMAGE_GENERATION_PROVIDER`、`IMAGE_ACADEMIC_FIGURE_MODEL`、`IMAGE_TEXT_RICH_FIGURE_MODEL`、`IMAGE_DRAFT_MODEL` | 修改 Qwen 视觉审阅或图像生成的模型选择。 |
| 仅独立工具 | `SURVEY_AGENT_API_KEY`、`SURVEY_AGENT_API_URL`、`SURVEY_AGENT_MODEL_NAME`、`SURVEY_AGENT_DATA_DIR` | 只在直接运行 `src/agents/survey_agent/utils/step2v2.py` 时需要；`qwensci survey` 不依赖该独立工具配置。 |
| Agent 兼容项 | `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL` | 仅在明确配置了相应 Agent 路径时使用；它们不会单独选择统一 provider。 |

基础 provider 配置能够正常工作后，再设置角色模型覆盖。支持的 provider/model 能力在 `src/config/default.yaml` 中声明；若为某个角色选择了不具备所需能力的模型，`doctor` 会在运行前报错。

## 配置与输出位置

`src/config/default.yaml` 是统一配置的唯一主入口，其中包含 provider 注册、模型能力、各 Agent 设置、workspace root 与默认输出位置。

| 范围 | 主要配置位置 |
| --- | --- |
| 共享 provider / model 注册 | `src/config/default.yaml` 的 `llm:` |
| Survey Agent | `survey:`，以及 `src/agents/survey_agent/config/*.yaml` |
| Idea Agent | `idea:` |
| Experiment Agent | `experiment:` |
| Blog Agent | `blog:` |
| Pipeline | `pipeline:` |
| 工作空间根目录 | `workspace.root`，默认 `workspace/` |

若要保证研究运行可复现，建议复制默认 YAML 为独立的私有/项目配置，在副本中修改后通过 `--config` 指定。凭据与生成产物应始终位于版本控制之外。

## 安全与数据处理

- 将所有 API Key 视为密钥；任何出现在公开提交、聊天、日志或截图中的密钥都应立即轮换。
- 分享日志前检查路径：本地 workspace 路径可能泄露用户名或组织信息。
- 不要提交 `.env`、模型目录、图/向量数据、PDF 缓存、生成报告或运行工作空间。
- 文档、Issue 和示例中请使用 `/path/to/qwen-sci/workspace` 这样的通用路径。

## 许可证

见 [LICENSE](LICENSE)。
