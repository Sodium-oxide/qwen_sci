# Qwen-Sci

**Qwen-Sci** 是一个可执行、可恢复、可审计的科研工作流：既提供 Python 命令行，也提供浏览器工作台。用户从一个研究课题出发，依次生成可追溯的文献综述、结构化研究想法、实验设计和研究计划；每一步都在服务端持久化，并可在安全边界处恢复。

当前工作台使用 React 19 / TypeScript 与 FastAPI，提供全流程科研、轻度研究、科研绘图、学术润色、论文翻译和研究偏好六个模块。网页中的模型功能使用 Qwen/DashScope，科研运行、Job、事件与成果保存在服务端。

[GitHub 仓库](https://github.com/Sodium-oxide/qwen_sci) · [PyPI](https://pypi.org/project/qwen-sci/)

[English](README.md) · [简体中文](README.zh-CN.md)

| 从这里开始 | 文档入口 |
| --- | --- |
| 准备 Linux / WSL 与 Python | [安装与配置](#安装与配置) |
| 启动或开发前端 | [Web 控制台 V2](#web-控制台-v2) · [前端 README](WebApp-V2/README.md) |
| 从命令行开始研究 | [科研运行示例](#快速开始命令行科研运行) |
| 查看后端接口与计算实验 | [Web 后端](docs/webapp-backend.md) · [计算实验](docs/computational_experiments.md) |

## 能力与边界

```text
研究课题
    │
    ▼
Survey ──► Idea ──► ExperimentDesign ──► Author
证据综述       研究提案          设计方案              研究计划
```

`qwensci science` 负责执行、校验和连接上述四个阶段。一次运行会保存在独立的 `workspace/science-runs/<run-id>/` 目录，其中包括：

- 每个阶段的历史尝试目录，失败或重跑不会删除先前尝试；
- 阶段输入/输出清单及其受校验的交接关系；
- 可恢复状态 `science_state.json` 与持久化事件日志 `events.jsonl`；
- 配置快照、运行元数据、已登记材料和生成产物。

主流程默认是 **design-only**：Qwen-Sci 会检索证据、生成与校验方案、组织文稿，但不会执行任意 Python/Shell/Matlab 程序、实验仪器、采集任务或真实物理实验。`ExperimentDesign` 产出可审查的设计，而不是实验结果。

Survey 默认以每个子假设（SH）至少选中两篇不同的种子论文为目标，通过 `survey.ModuleInfo.WorkCollector.min_seed_papers_per_sh` 配置；默认全局种子预算为 36 篇，通过 `max_seed_paper_num` 配置。SH 检索合并去重后的全部候选进入项目相关性筛选，不再按 `subhypothesis_max_unique_papers` 在筛选前截断；通过该阶段保留的候选进入 SH 语义评估，然后执行种子选择。先满足各 SH 的最低名额，再分配其余种子预算；总预算不足时自动提高到最低名额所需的上限。正常语义相关性门槛不足时，可以保留已经评估为背景、方法或间接贡献的低分论文，并记录为最低名额补位，保留原有证据等级和使用限制。无关、明确排除或评估失败的论文不能补位。穷尽候选后仍不足时仅发出警告，使用已选种子继续 Survey；缺口保留在 `subhypothesis_retrieval.json` 和 `sh_graph_provenance.json` 中。每次选择会保存 `subhypothesis_retrieval.json`，记录候选评估、种子选择、各 SH 数量和补评批次。最低名额是选择目标，全文是否可以下载和解析仍由后续获取记录说明。

在 WSL/Bash 中，运行 `bash scripts/run_mpa_fresh.sh` 可使用预设的 mPA 课题从 Survey 执行到 Author；添加 `--until survey` 可只运行 Survey。脚本每次生成新的运行 ID 和独立缓存路径，关闭结果缓存及 Idea 历史记忆，并要求每个 SH 至少两篇种子；旧运行和旧缓存保留。运行 `bash scripts/run_mpa_fresh.sh --prepare-only` 只生成配置并通过项目加载器验证完整解析，不调用科研流程。生成配置时保留 `${repo_root}` 等占位符，由项目加载器统一处理。

Survey 的提纲生成、论文分配、提纲修复、小节初稿（含代码上下文模板）及章节引言统一传入 `original_research_question`，内容为 `--topic` 对应的完整 `BasicInfo.topic`，不会替换成领域标签或 SH 摘要，也不会截断原问题。提示词使用原问题约束研究范围，同时遵守证据计划，不把问题中的前提当成已验证证据；原问题计入输入预算，无法容纳时明确报错。

可选的量化建模支线与主四阶段状态机隔离。它只能使用代码库已注册的 ODE、优化、Monte Carlo 和 PDE 模型族；每次参数确认、模拟执行、结果解释和修订均需要明确人工授权，不能把数值模拟描述为实验或观测事实。

## 工作流产物

| 阶段 | 程序执行的工作 | 主要产物 |
| --- | --- | --- |
| **Survey** | 检索、分析并整理研究问题相关的文献证据。 | 综述产物和已验证的 Survey manifest。 |
| **Idea** | 基于证据形成研究问题、假设与方向。 | `idea_result.json`。 |
| **ExperimentDesign** | 生成、检索支撑并校验 design-only 研究设计。 | JSON、Markdown、Author 交接 JSON、JSONL 运行日志。 |
| **Author** | 仅根据已经验证的 Survey/Idea/Design 交接组织研究计划。 | 研究计划产物；可选 LaTeX 项目与经校验 PDF。 |

Author 也支持在成稿完成后生成概念性科研图并插入最终 LaTeX/PDF 报告。它复用 Survey 的 `SurveyVisualizer`，但默认只以 Author 成稿的章节文字作为视觉输入，不要求 Survey 的证据计划或论文路径逐条对照。该功能默认关闭，可在配置中开启：

```yaml
research_plan_author:
  visualization:
    enabled: true
    strict_evidence: false
```

图像、`author_visual_manifest.json` 和 TeX 工程会保存在本次 Author render project 中；图像服务或视觉质检失败时，默认 `fail_open: true` 会保留无图报告并继续渲染。

## 快速开始：命令行科研运行

主命令会运行完整的可执行科研工作流。下面的示例使用 Qwen-Sci 提供的研究问题：

```bash
uv run qwensci science \
  --topic "Why do black holes exist? Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves." \
  --discipline-id "Astrophysics" \
  --run-id black-hole-existence
```

新运行默认写入 `workspace/science-runs/black-hole-existence/`，除非提供 `--output-root`。命令按顺序执行各阶段，在每次状态转换后记录状态，并输出运行信息。

如果只想先完成较早阶段：

```bash
uv run qwensci science \
  --topic "Why do black holes exist? Nobel laureate Sir Roger Penrose proved Einstein’s prediction of the existence of black holes, which form when supermassive stars burn out and collapse in on themselves." \
  --discipline-id "Astrophysics" \
  --run-id black-hole-existence \
  --until idea
```

恢复同一运行，而不是新建另一个目录：

```bash
uv run qwensci science \
  --resume workspace/science-runs/black-hole-existence \
  --until author
```

如果需要重新运行某个阶段，请从该阶段开始并显式确认；此前的尝试仍会保留以供审计：

```bash
uv run qwensci science \
  --resume workspace/science-runs/black-hole-existence \
  --restart-from exp_design \
  --force
```

当其他程序需要稳定的 `science_run_result_v1` 标准输出时使用 `--json`。使用 `qwensci science --help` 查看全部选项，包括 Author 模板和 PDF 渲染设置。

## 环境要求

- Python **3.12**（`>=3.12,<3.13`）
- [`uv`](https://docs.astral.sh/uv/)
- Qwen/DashScope 账户，或兼容 OpenAI 的模型服务
- Linux x86_64 或 **WSL2**；Windows 请优先使用 WSL
- 构建或开发 Web 控制台时，需要 [Node.js](https://nodejs.org/) **20.x 的 20.19+，或 22.12+** 与 npm，推荐使用 **22 LTS**

## 安装与配置

锁定的依赖环境面向 **Linux x86_64 与 Python 3.12**。Windows 用户先在**管理员 PowerShell** 中安装 WSL2；按提示重启并完成 Ubuntu 用户创建。已有 Linux 环境可从后续 Ubuntu 命令开始。

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
wsl --set-default-version 2
```

在 Ubuntu / WSL 终端安装基础工具和 `uv`。Python 由 `uv` 管理，无需另外安装 Windows Python：

```bash
sudo apt update
sudo apt install -y git curl ca-certificates build-essential
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
uv python install 3.12
```

推荐把仓库放在 WSL 的 Linux 文件系统中，以减少依赖安装和构建时的文件访问开销：

```bash
mkdir -p "$HOME/src"
cd "$HOME/src"
git clone https://github.com/Sodium-oxide/qwen_sci.git
cd qwen_sci
```

后续命令均在仓库根目录执行。如果仓库已有 Windows 磁盘副本，请在 WSL 中使用 `/mnt/c/Users/<WindowsUser>/path/to/qwen_sci` 等对应路径。

前端需要在同一个 Linux / WSL 环境安装 **Node.js 22 LTS**，可按 [Node.js 安装说明](https://nodejs.org/en/download)或使用 [nvm](https://github.com/nvm-sh/nvm#installing-and-updating)。Vite 7 要求 Node.js **20.x 的 20.19+，或 22.12+**。如果已经安装 nvm：

```bash
nvm install 22
nvm use 22
node --version
npm --version
which node npm
```

`node` 与 `npm` 应指向 Linux 路径，避免调用 `/mnt/c/` 下的 Windows 程序。只使用 CLI 时无需安装 Node.js。

需要 Lean 证明检查时，在同一个 WSL 环境中安装工具链管理器 Elan：

```bash
curl https://elan.lean-lang.org/elan-init.sh -sSf | sh
source "$HOME/.elan/env"
elan --version
```

安装本仓库 [`lean-toolchain`](lean-toolchain) 锁定的 Lean 版本，并检查安装结果：

```bash
elan toolchain install "$(cat lean-toolchain)"
lean --version
```

然后创建并同步 Python 环境。以下完整开发安装会包含所有依赖组；环境保存在仓库外部，也可以按后面的能力表选择安装范围：

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
uv sync --all-groups --locked
source "$UV_PROJECT_ENVIRONMENT/bin/activate"
python --version       # Python 3.12.x
which python
uv run qwensci --help
```

在每个后端终端中设置同一个 `UV_PROJECT_ENVIRONMENT`，需要直接使用环境中的工具时再激活其 `bin/activate`。不要使用 `uv run --no-sync`。如果只需部分能力，可按需同步：

| 能力 | 命令 |
| --- | --- |
| 核心 API 驱动工作流 | `uv sync` |
| 数学形式化推理（SymPy/Z3） | `uv sync --group formal` |
| 向量检索与本地模型 | `uv sync --group memory --group ml` |
| PDF 解析与全文综述路径 | `uv sync --group pdf` |
| 显式图像、表格、信号、音频、视频、3D 或轨迹材料 | `uv sync --group multimodal` |
| 完整开发环境（包含数学形式化推理） | `uv sync --all-groups --locked` |

`uv sync --all-groups --locked` 会自动同步 `[dependency-groups]` 下的全部组，
因此也会安装 `formal` 组中的 SymPy 和 Z3。

数学形式化推理组提供 `experiment_design` 数学理论分支使用的 SymPy/Z3
Python 后端。Lean 内核校验属于外部工具链：请安装 Elan，并按
[`lean-toolchain`](lean-toolchain) 中锁定的版本执行
`elan toolchain install "$(cat lean-toolchain)"`，
再确保 `lean` 在 `PATH` 中。Lean 不是 Python 包，因此不会写入
`requirements.txt`；未安装 Lean 时后端会返回
`proof_assistant_unsupported`，不会把缺失工具当成证明成功。

复制配置模板，并确保密钥文件不进入版本控制：

```bash
cp .env.example .env
```

Qwen/DashScope 示例：

```dotenv
QWENSCI_LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=replace-with-your-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
SEMANTIC_SCHOLAR_API_KEY=replace-with-your-key
```

当前统一 Qwen-Sci 运行模式使用仓库内的本地 embedding 模型目录：

```dotenv
BGE_MODEL_PATH=./models/bge-m3
MINILM_MODEL_PATH=./models/all-MiniLM-L6-v2
```

兼容 OpenAI 的服务示例：

```dotenv
QWENSCI_LLM_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
SEMANTIC_SCHOLAR_API_KEY=replace-with-your-key
```

检查本机能力和配置：

```bash
uv run qwensci doctor
```

`doctor` 可能因未安装的可选模型或可选凭证返回非零状态；请根据计划运行的功能逐项查看输出，而不是把它当作所有工作流的硬性失败。

## 可复现性与本地资源

`src/config/default.yaml` 是模型提供方、角色模型、工作流设置、工作区路径和默认输出位置的规范配置。需要可复现实验项目时，请复制一份私有/项目专用配置并通过 `--config /path/to/config.yaml` 指定。

仓库不会提交 API 密钥、下载的 embedding 模型、图/向量存储、缓存 PDF、生成文档或运行工作区。常见的本地资源目录包括：

```text
models/all-MiniLM-L6-v2/
models/bge-m3/
data/processed/graph.db
data/processed/core_component_summary_vector_store/
workspace/science-runs/
```

### 使用 ModelScope 安装本地 embedding 模型

先安装包含 `modelscope` 的可选 PDF 依赖组，然后在仓库根目录执行以下命令。请将 `<repo_root>` 替换为当前 checkout 的绝对路径：

```bash
uv sync --group pdf

mkdir -p <repo_root>/models/bge-m3
mkdir -p <repo_root>/models/all-MiniLM-L6-v2

modelscope download --model BAAI/bge-m3 \
  --local_dir <repo_root>/models/bge-m3
modelscope download --model sentence-transformers/all-MiniLM-L6-v2 \
  --local_dir <repo_root>/models/all-MiniLM-L6-v2
```

如果当前目录就是仓库根目录，可以直接使用 `$PWD`：

```bash
modelscope download --model BAAI/bge-m3 \
  --local_dir "$PWD/models/bge-m3"
modelscope download --model sentence-transformers/all-MiniLM-L6-v2 \
  --local_dir "$PWD/models/all-MiniLM-L6-v2"
```

## CLI 参考

从源码运行时，命令前加 `uv run`；通过发布包安装时可直接使用 `qwensci …`。

| 命令 | 作用 |
| --- | --- |
| `qwensci survey` | 生成文献综述证据与产物。 |
| `qwensci idea` | 生成结构化研究想法与方向。 |
| `qwensci exp_design` | 生成并校验 design-only 实验设计。 |
| `qwensci author` | 基于已验证交接生成研究计划。 |
| `qwensci science` | 初始化、恢复或重启完整可审计流程。 |
| `qwensci quantitative status` | 查看量化侧车状态和下一步操作。 |
| `qwensci doctor` | 检查模型提供方与本地可选能力。 |
| `qwensci quantitative` | 查看和推进需要人工审批的量化建模支线。 |
| `qwensci computation` | 查看、恢复或取消可选计算实验。 |
| `qwensci-web` | 启动 Web 工作台、功能 Job 与受控运行 API。 |
| `qwensci install-mcp-wrappers` | 在 Linux/WSL 上安装本地 Bash MCP 包装脚本。 |

软件包也提供 `qwensci-survey`、`qwensci-idea`、`qwensci-doctor` 和 `qwensci-install-mcp-wrappers` 这些专用入口；新脚本和文档优先使用统一的 `qwensci` 命令。

## 显式多模态材料

Qwen-Sci 不会自动扫描本机文件夹或把任意文件当作科研证据。只有用户显式提供的材料才会进入多模态输入契约。契约可声明以下模态：`image`、`table`、`signal`、`audio`、`video`、`threeD`、`trajectory`、`text`、`symbolic` 和 `molecule`；记录会经过文件大小、元数据和路径安全检查，向下游交接时不包含原始路径。

默认模式是 **仅本地处理**：本地解析器可以产生受限的原生发现，但不会由远程模型生成观察或科学主张。单独运行 Survey 时，可以重复提供文件，或传入一个 `multimodal_input_manifest_v1` 清单：

```bash
uv run qwensci survey \
  --topic "How does electrode morphology affect cycle stability?" \
  --declared-domain "materials science" \
  --multimodal-file ./electrode-micrograph.png \
  --multimodal-file ./cycling-data.csv
```

远程视觉分析必须额外且逐次授权：

```bash
uv run qwensci survey \
  --topic "How does electrode morphology affect cycle stability?" \
  --declared-domain "materials science" \
  --multimodal-file ./electrode-micrograph.png \
  --allow-remote-perception
```

`--allow-remote-perception` 必须与显式多模态输入同时使用。它只允许已配置的 Qwen `qwen3-vl-plus` 路由读取已支持、非敏感模态的有界、无元数据 PNG 预览；不会把原始路径、媒体字节、EXIF、base64 内容或供应商原始响应写进下游交接。不要对敏感、专有或含个人信息的资料开启该选项。

安装可选本地读取器：

```bash
uv sync --group multimodal
```

不要尝试通过位置式配置覆盖开启多模态运行时；请使用 `--multimodal-file` 或 `--multimodal-evidence-manifest`，并在确有需要时增加 `--allow-remote-perception`。当前分子/RDKit 路径会明确报告“未支持的能力”，不会把化学结构静默降级为普通文本。

## Web 控制台 V2

`WebApp-V2/` 是当前 React / TypeScript 前端。FastAPI 提供科研与独立功能 API、持久化 Job、SSE 事件和成果下载。完成[安装与配置](#安装与配置)并保存 `.env` 后，在 **Linux / WSL 的仓库根目录**执行以下命令；每个后端终端均使用同一个 `UV_PROJECT_ENVIRONMENT`。如果当前仓库已使用默认 `.venv/`，可省略下面的 `export UV_PROJECT_ENVIRONMENT=…` 行，`uv run` 会使用该项目环境。

| 方式 | 运行进程 | 浏览器地址 |
| --- | --- | --- |
| 构建运行，推荐用于本地使用 | FastAPI 同时提供 `WebApp-V2/dist/` 和 `/api` | [http://localhost:8010/app](http://localhost:8010/app) |
| 前端开发与热更新 | FastAPI 使用 `8010`，Vite 使用 `5173` 并代理 `/api` | [http://localhost:5173/app](http://localhost:5173/app) |

### 构建并在本地运行

按 `package-lock.json` 安装前端依赖、构建页面，再启动后端：

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
npm --prefix WebApp-V2 ci
npm --prefix WebApp-V2 run build
uv run --locked qwensci-web
```

等价的模块启动方式是 `uv run --locked python -m src.webapp.api`。服务默认监听 `127.0.0.1:8010`。[http://localhost:8010/](http://localhost:8010/) 是产品首页，[http://localhost:8010/app](http://localhost:8010/app) 是工作台；Windows 浏览器可通过 WSL 的 localhost 转发访问。

`npm run build` 会先检查 TypeScript，再生成 `WebApp-V2/dist/`。修改前端源码后，重新构建并重启 `qwensci-web`；依赖锁文件变化后，重新执行 `npm ci`。后端启动时若没有 `dist/index.html`，根路径 `/` 会返回 **503** 并提示构建，API 与 [Swagger 接口文档](http://localhost:8010/docs)仍可访问。

在另一个终端检查服务与可选能力：

```bash
curl -fsS http://127.0.0.1:8010/api/health
curl -fsS http://127.0.0.1:8010/api/capabilities
```

健康响应包含 `status: "ok"`。能力接口区分依赖是否存在、凭据是否配置和远程连通性是否验证；`configured` 且 `verified: false` 表示仍需实际调用确认。`multimodal` 依赖组提供本地绘图与表格工具，`pdf` 组提供 PDF 解析、DOCX 与 PDF 导出。

### 使用 Vite 开发前端

打开两个 Linux / WSL 终端，均进入仓库根目录。若尚未安装前端依赖，先执行一次 `npm --prefix WebApp-V2 ci`。

终端 1：后端。

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
uv run --locked qwensci-web
```

终端 2：前端。

```bash
npm --prefix WebApp-V2 run dev -- --port 5173 --strictPort
```

访问 [http://localhost:5173/app](http://localhost:5173/app)。Vite 会在源码变化后更新页面，开发模式无需先生成 `dist/`。[`vite.config.ts`](WebApp-V2/vite.config.ts)监听 `0.0.0.0`，将相对路径 `/api` 请求（包括 SSE）代理到 `http://127.0.0.1:8010`。科研运行、上传、Job 和偏好读写都需要后端持续运行；接口文档直接访问 [http://localhost:8010/docs](http://localhost:8010/docs)。

需要修改后端端口时，将后端启动命令替换为：

```bash
uv run --locked python -m uvicorn src.webapp.api:app --host 127.0.0.1 --port 8020
```

然后在 Vite 启动命令中设置对应的代理目标：

```bash
QWENSCI_API_URL=http://127.0.0.1:8020 npm --prefix WebApp-V2 run dev -- --port 5173 --strictPort
```

`QWENSCI_API_URL` 由 Vite 配置进程读取。模型 API 密钥保存在后端私有 `.env` 中。

### 页面入口与持久化数据

根据所选运行方式，使用对应端口访问以下路由：

| 路由 | 页面 |
| --- | --- |
| `/`、`/products`、`/products/qwensci` | 产品首页、产品列表与 Qwen-Sci 介绍 |
| `/app` | 工作台概览与任务入口 |
| `/app/full-research` | Survey → Idea → ExperimentDesign → Author，可选择流程终点 |
| `/app/light-research` | Survey 与可选 Idea，量化和计算实验分支关闭 |
| `/app/figure` | Python 数据图或 AI 示意图、人工复核与图形成果 |
| `/app/polish` | 学术润色、段落差异、人工复核与文档导出 |
| `/app/translate` | PDF 翻译、逐页复核、术语与来源映射 |
| `/app/preferences` | 带版本的模型、研究、输出与隐私默认设置 |

默认情况下，`workspace/science-runs/` 保存科研运行，`workspace/qwensci.db` 保存 Job 状态与事件，`workspace/jobs/` 保存 Job 输入与成果，`workspace/files/` 保存共享上传文件，`workspace/preferences.json` 保存工作区偏好。路径由 [`src/config/default.yaml`](src/config/default.yaml)等配置决定；偏好设置只作用于新建任务。浏览器和 CLI 复用同一套科研运行产物。

当前使用单工作区，未提供多人认证或 ACL。绘图、润色和翻译在最终接受或文档导出前提供人工复核动作；可选功能以 `/api/capabilities` 的实际状态为准。PDF 翻译导出保留文本结构和来源映射，尚不重建原 PDF 版面。

### 常见启动问题

| 现象 | 处理方法 |
| --- | --- |
| `EBADENGINE`、Vite 提示 Node 版本不符，或 `crypto.hash is not a function` | 切换到支持的 Linux Node.js，检查 `which node npm`，重新执行 `npm --prefix WebApp-V2 ci`。 |
| `8010` 返回 `503` / “Web client has not been built” | 执行 `npm --prefix WebApp-V2 run build`，然后重启后端。 |
| `8010` 页面未显示源码修改 | 重新构建并重启，或在开发时使用 `5173` 的 Vite 页面。 |
| 首页可打开，但 API 请求失败 | 检查后端 `/api/health`；开发模式还需确认 `QWENSCI_API_URL`，修改后重启 Vite。 |
| `8010` 或 `5173` 端口被占用 | 停止占用进程，或修改端口并同步代理目标。`--strictPort` 会直接报告冲突，避免 Vite 自动换端口。 |
| 缺少绘图、解析或导出能力 | 查看 `/api/capabilities`，在运行后端的同一 Python 环境安装所需依赖组。 |

前端检查命令见[双语前端 README](WebApp-V2/README.md)，接口和 Job 契约见 [Web 后端说明](docs/webapp-backend.md)。

### 在页面中开始研究

1. 进入全流程或轻度研究，输入课题，从 20 个支持学科中选 1–2 个。可选模型识别使用 `qwen3.8-flash`；识别不可用或无建议时仍可手动选择。
2. 在启动前可上传研究材料并设置其用途与敏感标记。文件只保存到当前运行，并在再次读取时进行哈希校验。
3. 选择流程终点：只生成 `Survey`、生成到 `Idea`、生成到 `ExperimentDesign`，或完整运行到 `Author`。`required` 量化模式会在 Author 前停在独立的量化审阅流程。
4. 启动或恢复运行。运行中可请求“在当前阶段后中止”：当前阶段会先原子持久化，已完成产物会保留，后续阶段不会启动。恢复是一个新的受控用户动作，且可重新选择终点。
5. 在右侧查看已登记材料和归档成果；在流程区查看完整事件、错误上下文以及可分页的阶段日志。

### 浏览器材料限制

- 支持的安全扩展名包括常见图像、表格、音视频、PDF/Office、科学数据、代码和文本格式。
- 单个文件最大 **50 MiB**，同一研究运行的材料总量最大 **250 MiB**。
- 图像和表格会按安全扩展名自动识别模态；只有标为 `survey_evidence` 且未标记敏感的材料才会进入 Survey 的多模态输入清单。
- 一旦任一科学阶段开始，材料即不可修改，避免运行输入被事后替换。

### 完整日志与事件

页面展示的是服务端持久化数据：

- **完整运行事件**：显示所有事件（包括阶段、重试、恢复、取消和量化动作），可按全部/错误/当前阶段过滤，并展开查看已脱敏 JSON 数据。
- **完整阶段日志**：发现当前运行的 `survey`、`idea`、`experiment_design`、`author` 目录中的 `.jsonl` 与 `.log` 日志；大文件按块读取，可手动“加载更多”或“读取新增内容”。运行时会定期发现新增日志，勾选自动跟随后会续读当前日志。
- 日志服务只接受服务端签发的日志 ID，不能由浏览器提交任意本机路径；上传材料目录 `inputs/` 不会被当作日志扫描。
- 返回浏览器前，本机路径和敏感字段会脱敏，例如 API key、token、Authorization/Bearer、密码和 Cookie 都会显示为 `[redacted]` 或 `[local path]`。

这些机制用于减少诊断信息暴露，但不应成为把密钥、敏感提示词或私有数据写入日志的理由。

## 可选量化建模

启用量化模式后，Idea 最多提出两个候选（`Q1`、`Q2`），并写入独立的量化侧车状态；它不会修改主流程的 Idea 产物或 ExperimentDesign 输入。典型顺序为：

```text
模型蓝图 → 参数证据检索/提取 → 人工选择与批准
→ 物化 MathIR/PDEIR 计划 → 对精确计划 ID 的显式执行授权
→ 人工限定结果关系 → 可选的人工接受修订 → 独立模型 PDF → Author 受控交接
```

以下节点不会自动越过：

| 节点 | 必要的人工动作 |
| --- | --- |
| 参数取值 | 审查来源、单位、条件和候选值，再提交完整选择并批准。 |
| 网络检索 | 对参数发现或开放全文检索显式增加 `--fetch`。 |
| 数值执行 | 对精确、不可变的 `plan_identity` 使用 `--execute` 授权一次运行。 |
| 结果解释 | 人工提交模型内的假设关系与有界摘要。 |
| 修订 | 人工检查并使用 `accept-revision --accept` 接受；每次新版本需要新的参数与执行授权。 |

使用 `uv run qwensci quantitative status --run-dir <RUN_DIR>` 查看某个运行的当前状态和下一步安全动作。完整的英文命令示例见 [README.md](README.md#optional-supervised-quantitative-modeling)。

如果全文清单中有多篇彼此独立的论文，可使用受控并行参数抽取：

```bash
uv run qwensci quantitative parameters extract-batch \
  --run-dir "$RUN_DIR" \
  --idea-id Q1 --version 0 \
  --document-ids PFD-001,PFD-002,PFD-003 --workers 3
```

抽取器会先按参数符号、含义、单位、适用条件和检索词筛选页面，只把命中页面及
有限前后文交给模型；没有命中时直接跳过模型调用。PDF 页面按 SHA-256 缓存，
运行锁只覆盖输入读取和结果提交，避免远程请求把并行任务串行化。`--workers`
以及 `extraction_workers`/`fulltext_workers`/`fulltext_per_host_concurrency` 应根
据模型服务和提供方速率限制调整；并行不会替代人工候选选择、参数批准或仿真授
权。全文下载默认每篇最多尝试两个声明的 PDF URL，并对临时 HTTP 失败重试一次。

## 在 WSL 中运行可选计算实验

使用 `--computation-mode run` 可以在 ExperimentDesign 期间生成并执行计算实验。它与 Q1/Q2 量化建模分支分别控制；只启用这里的计算实验时，保留 `--quantitative-mode off`。

| 模式 | 行为 |
| --- | --- |
| `--computation-mode off` | 默认值，关闭计算实验。 |
| `--computation-mode plan` | 生成计算协议，不执行程序。 |
| `--computation-mode run` | 生成协议和代码，在 Docker 中执行、验证和分析结果。 |

### 1. 连接 WSL 与 Docker Desktop

在 Windows 中安装并启动 Docker Desktop。在 **Settings → General** 中启用 **Use the WSL 2 based engine**，再在 **Settings → Resources → WSL Integration** 中开启当前发行版并应用设置。在 WSL 中执行：

```bash
docker info
docker run --rm hello-world
```

`docker info` 必须能显示 **Server** 信息。WSL 使用指向 `unix:///var/run/docker.sock` 的 `default` context 即可；连接正常时保留该设置，不要切换到 Windows 命名管道地址。

- `docker.sock` 报 `no such file or directory`：启动 Docker Desktop 并检查 WSL 集成。如果使用的是直接安装在 WSL 内的 Docker Engine，则用 `sudo systemctl start docker` 启动服务；没有 systemd 时使用 `sudo service docker start`。
- `docker.sock` 报 `permission denied`：先执行 `ls -l /var/run/docker.sock` 和 `sudo docker info`。如果 socket 属于 `docker` 组，且带 `sudo` 能正常连接，将当前 WSL 用户加入该组并刷新 shell：

```bash
sudo groupadd -f docker
sudo usermod -aG docker "$USER"
newgrp docker
docker info
```

加入 `docker` 组会获得 Docker daemon 的控制权限。保持 socket 原有权限，不要执行 `chmod 666`。使用 Docker Desktop 集成或单独管理的 WSL Docker Engine 中的一种，确保 CLI 连接的是预期服务。

### 2. 构建并验证执行镜像

在 WSL 的项目根目录中执行（例如先运行 `cd ~/qwen_sci-main`）：

```bash
docker build \
  -t qwensci-computation:py312-v1 \
  -f src/agents/computational_experiment_agent/execution/Dockerfile \
  .

docker run --rm qwensci-computation:py312-v1 \
  python -c "import numpy, scipy, sympy, pyscf; print('Computational environment OK')"
```

验证应输出 `Computational environment OK`。首次使用时构建一次；修改 Dockerfile 或镜像依赖后再重新构建。镜像内包含 Python、NumPy、SciPy、SymPy 和 PySCF。

### 3. 启动包含数值实验的研究运行

在当前 WSL shell 中定义完整课题，并明确希望执行的数值任务。例如：

```bash
run_id="cpallidicaule-pathosystem-$(date +%Y%m%d-%H%M%S)"
topic=$(cat <<'TOPIC'
Propose and justify a model pathogen and pathovar screening design for
Chenopodium pallidicaule. Execute numerical experiments to assess sample
size, statistical power, and ranking robustness under measurement noise.
Declare assumed parameters and sensitivity ranges. Use simulations to
evaluate the screening design; base biological virulence claims on
experimental or cited empirical evidence.
TOPIC
)

uv run qwensci science \
  --config src/config/default.yaml \
  --topic "$topic" \
  --discipline-id "24" \
  --discipline-id "11" \
  --run-id "$run_id" \
  --output-root workspace/science-runs \
  --quantitative-mode off \
  --computation-mode run \
  --until author
```

将示例课题替换为你的完整问题。关闭 shell 后变量会丢失，新会话需要重新定义 `topic` 和 `run_id`；用于其他研究领域时，也要调整学科 ID。

计算分支在 Survey 和 Idea 完成后启动，与 ExperimentDesign 并行。Author 在预算内等待计算分支结束，并通过独立证据包使用已验证结果。当前默认最多生成 2 个实验、总计执行 12 次，计算分支总预算为 3600 秒，单次执行最多 900 秒。缺少数据、软件或验证失败时，计算分支可能未完成而主报告仍正常生成，因此要单独查看计算状态。

### 4. 查看状态与恢复计算

在另一个终端中使用实际运行目录：

```bash
uv run qwensci computation status --run-dir workspace/science-runs/ACTUAL_RUN_ID
uv run qwensci computation resume --run-dir workspace/science-runs/ACTUAL_RUN_ID
```

`status` 查看进度；`resume` 恢复可恢复的计算失败，也适用于修复 Docker 和镜像后的 `ENVIRONMENT_UNAVAILABLE` 状态。日志与产物位于 `workspace/science-runs/ACTUAL_RUN_ID/computation/`。计算模式和模型在创建运行时固定：原来以计算模式 `off` 创建的运行，需要新建运行 ID 才能启用计算。

如果 Author 已完成，而计算结果是在恢复后才生成，需要重跑 Author 才能将新交接结果纳入报告：

```bash
uv run qwensci science \
  --resume workspace/science-runs/ACTUAL_RUN_ID \
  --restart-from author --force \
  --until author
```

输入数据、支持方法、联网与隔离设置、取消、预算和结果验证详见[计算实验说明](docs/computational_experiments.md)。

## 安全

- 任何 API key 都应视为密钥；一旦出现在提交、聊天、日志或截图中，应立即轮换。
- Web 日志是诊断视图，不是任意文件浏览器；服务只公开允许的阶段日志并进行脱敏。
- 远程多模态感知默认关闭，且需要显式输入与逐次授权。
- 外部实验、仪器和数值模拟应在各自经过审查的执行环境中运行；Qwen-Sci 的设计产物不能替代这些控制。
- 在科研决策、发表或现实实验前，请人工审阅生成的计划、引用与证据。

## 许可证

见 [LICENSE](LICENSE)。
