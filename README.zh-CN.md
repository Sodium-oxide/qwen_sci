# Qwen-Sci

**Qwen-Sci** 是一个可执行、可恢复、可审计的科研工作流：既提供 Python 命令行，也提供浏览器控制台。用户从一个研究课题出发，依次生成可追溯的文献综述、结构化研究想法、实验设计和研究计划；每一步都在服务端持久化，并可在安全边界处恢复。

[English](README.md) · [简体中文](README.zh-CN.md)

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

可选的量化建模支线与主四阶段状态机隔离。它只能使用代码库已注册的 ODE、优化、Monte Carlo 和 PDE 模型族；每次参数确认、模拟执行、结果解释和修订均需要明确人工授权，不能把数值模拟描述为实验或观测事实。

## 工作流产物

| 阶段 | 程序执行的工作 | 主要产物 |
| --- | --- | --- |
| **Survey** | 检索、分析并整理研究问题相关的文献证据。 | 综述产物和已验证的 Survey manifest。 |
| **Idea** | 基于证据形成研究问题、假设与方向。 | `idea_result.json`。 |
| **ExperimentDesign** | 生成、检索支撑并校验 design-only 研究设计。 | JSON、Markdown、Author 交接 JSON、JSONL 运行日志。 |
| **Author** | 仅根据已经验证的 Survey/Idea/Design 交接组织研究计划。 | 研究计划产物；可选 LaTeX 项目与经校验 PDF。 |

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
- 构建或开发 Web 控制台时，还需要 Node.js 与 npm

## 安装与配置

以下命令在 WSL 的仓库根目录执行。把开发环境放在仓库外部，避免在仓库中创建或同步 `.venv`：

```bash
git clone https://github.com/Sodium-oxide/qwen_sci.git
cd qwen_sci

export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
uv sync --all-groups --locked
uv run qwensci --help
```

在每个使用该仓库的 shell 中设置同一个 `UV_PROJECT_ENVIRONMENT`。如果只需部分能力，可按需同步：

| 能力 | 命令 |
| --- | --- |
| 核心 API 驱动工作流 | `uv sync` |
| 向量检索与本地模型 | `uv sync --group memory --group ml` |
| PDF 解析与全文综述路径 | `uv sync --group pdf` |
| 显式图像、表格、信号、音频、视频、3D 或轨迹材料 | `uv sync --group multimodal` |
| 完整开发环境 | `uv sync --all-groups --locked` |

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
| `qwensci-web` | 启动 Web 控制台及其受控运行 API。 |
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

Web 控制台是持久化科研运行的同源控制面，不是浏览器中的模拟页面。它直接管理 `workspace/science-runs/` 中的真实运行状态和受控产物。

首次使用或前端源码更新后，在仓库根目录构建并启动：

```bash
npm --prefix WebApp-V2 install
npm --prefix WebApp-V2 run build
uv run qwensci-web
```

然后打开 [http://127.0.0.1:8010](http://127.0.0.1:8010)。服务会从 `WebApp-V2/dist` 提供已构建的 React 页面。在 WSL 环境中可使用服务输出的地址，或使用 Windows 浏览器的 WSL localhost 转发。

### 在页面中开始研究

1. 输入课题，从当前支持的 20 个学科中选 1–2 个；页面可以根据课题建议最多两个学科。
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

## 安全

- 任何 API key 都应视为密钥；一旦出现在提交、聊天、日志或截图中，应立即轮换。
- Web 日志是诊断视图，不是任意文件浏览器；服务只公开允许的阶段日志并进行脱敏。
- 远程多模态感知默认关闭，且需要显式输入与逐次授权。
- 外部实验、仪器和数值模拟应在各自经过审查的执行环境中运行；Qwen-Sci 的设计产物不能替代这些控制。
- 在科研决策、发表或现实实验前，请人工审阅生成的计划、引用与证据。

## 许可证

见 [LICENSE](LICENSE)。
