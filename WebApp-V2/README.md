# Qwen-Sci WebApp V2

[English](#english) · [简体中文](#简体中文) · [Project README](../README.md) · [项目说明](../README.zh-CN.md)

## English

Use Linux x86_64 / WSL2, Python **3.12**, and `uv`. For the frontend, use Linux Node.js **20.19+ on 20.x, or 22.12+** and npm; **22 LTS** is recommended. Check `node --version`, `npm --version`, and `which node npm` inside WSL before installing dependencies.

`WebApp-V2/` contains the current React / TypeScript frontend. FastAPI provides the research and feature APIs, durable Jobs, SSE events, and artifact downloads. Run the commands below from the **repository root in Linux / WSL**, after [installing Python dependencies](../README.md#first-time-setup-windows-wsl2-and-linux) and [configuring `.env`](../README.md#configure-a-model-provider). Use the same `UV_PROJECT_ENVIRONMENT` in every backend terminal. If this checkout already uses the default `.venv/`, omit the `export UV_PROJECT_ENVIRONMENT=…` lines below; `uv run` will use that project environment.

| Mode | Processes | Browser URL |
| --- | --- | --- |
| Built frontend, recommended for local use | FastAPI serves `WebApp-V2/dist/` and `/api` | [http://localhost:8010/app](http://localhost:8010/app) |
| Frontend development with hot updates | FastAPI on `8010`, Vite on `5173` with an `/api` proxy | [http://localhost:5173/app](http://localhost:5173/app) |

### Build and run locally

Install the frontend dependencies from `package-lock.json`, build the client, and start the backend:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
npm --prefix WebApp-V2 ci
npm --prefix WebApp-V2 run build
uv run --locked qwensci-web
```

The equivalent module entry point is `uv run --locked python -m src.webapp.api`. The service listens on `127.0.0.1:8010`. Open [http://localhost:8010/](http://localhost:8010/) for the product homepage, or [http://localhost:8010/app](http://localhost:8010/app) for the workspace. A Windows browser can use these URLs through WSL localhost forwarding.

`npm run build` performs TypeScript checking and generates `WebApp-V2/dist/`. After changing frontend source, rebuild and restart `qwensci-web`; rerun `npm ci` when the dependency lockfile changes. If `dist/index.html` is absent when the backend starts, `/` returns **503** with a build instruction; the API and [Swagger UI](http://localhost:8010/docs) remain available.

From another terminal, check the service and optional capabilities:

```bash
curl -fsS http://127.0.0.1:8010/api/health
curl -fsS http://127.0.0.1:8010/api/capabilities
```

The health response includes `status: "ok"`. Capability responses distinguish installed dependencies and configured credentials from verified remote connectivity: `configured` with `verified: false` still requires a real provider check. The `multimodal` dependency group supplies local plotting and table tools; `pdf` supplies PDF parsing, DOCX, and PDF export.

### Develop the frontend with Vite

Keep two Linux / WSL terminals open, both in the repository root. Install frontend dependencies once with `npm --prefix WebApp-V2 ci` if you have not already done so.

Terminal 1 — backend:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/qwen-sci-dev"
uv run --locked qwensci-web
```

Terminal 2 — frontend:

```bash
npm --prefix WebApp-V2 run dev -- --port 5173 --strictPort
```

Open [http://localhost:5173/app](http://localhost:5173/app). Vite updates the page as source files change; this mode does not require a `dist/` build. [`vite.config.ts`](vite.config.ts) listens on `0.0.0.0` and proxies relative `/api` requests, including SSE, to `http://127.0.0.1:8010`. Keep the backend running for research, uploads, Jobs, and settings. Open API documentation directly at [http://localhost:8010/docs](http://localhost:8010/docs).

To change the backend port, replace the backend command with:

```bash
uv run --locked python -m uvicorn src.webapp.api:app --host 127.0.0.1 --port 8020
```

Then start Vite with the matching proxy target in its launch environment:

```bash
QWENSCI_API_URL=http://127.0.0.1:8020 npm --prefix WebApp-V2 run dev -- --port 5173 --strictPort
```

`QWENSCI_API_URL` is read by the Vite configuration process. Provider API keys belong in the backend's private `.env`.

### Pages and persistent data

Use the port for your selected mode with these routes:

| Route | Page |
| --- | --- |
| `/`, `/products`, `/products/qwensci` | Product homepage, catalog, and Qwen-Sci overview |
| `/app` | Workspace overview and task entry points |
| `/app/full-research` | Survey → Idea → ExperimentDesign → Author, with a selectable stopping point |
| `/app/light-research` | Survey and optional Idea; quantitative and computational branches are disabled |
| `/app/figure` | Python data plots or AI schematics, review, and figure artifacts |
| `/app/polish` | Academic revision with segment comparison, review, and document export |
| `/app/translate` | PDF translation with page review, terminology, and source mapping |
| `/app/preferences` | Versioned defaults for models, research, output, and privacy |

By default, `workspace/science-runs/` stores research runs, `workspace/qwensci.db` stores Job state and events, `workspace/jobs/` stores Job inputs and artifacts, `workspace/files/` stores shared uploads, and `workspace/preferences.json` stores workspace defaults. These locations follow [`src/config/default.yaml`](../src/config/default.yaml); preferences apply to newly created tasks. The browser and CLI share research-run artifacts.

The workspace currently uses a single workspace without multi-user authentication or ACLs. Figures, polishing, and translation expose review actions before final acceptance or document export; `/api/capabilities` reports which optional operations are available. PDF translation exports text structure and source mapping; reconstruction of the original PDF layout is unsupported.

### Common startup issues

| Symptom | Action |
| --- | --- |
| `EBADENGINE`, a Vite Node-version error, or `crypto.hash is not a function` | Switch to supported Linux Node.js, check `which node npm`, and rerun `npm --prefix WebApp-V2 ci`. |
| `503` / “Web client has not been built” on port `8010` | Run `npm --prefix WebApp-V2 run build`, then restart the backend. |
| Source edits do not appear on port `8010` | Rebuild and restart, or use Vite on port `5173` during development. |
| Homepage loads but API requests fail | Check `/api/health` on the backend; in development, verify `QWENSCI_API_URL` and restart Vite after changing it. |
| Port `8010` or `5173` is occupied | Stop the process using that port, or select a different port and match the proxy target. `--strictPort` makes Vite report a conflict instead of changing ports. |
| Missing plotting, parser, or export capability | Check `/api/capabilities` and install the required dependency groups into the same Python environment used by the backend. |

See the [main English README](../README.md) for CLI workflows and the [Web backend documentation](../docs/webapp-backend.md) for API and Job contracts.

### Runtime behavior and frontend checks

Research materials are stored under `workspace/science-runs/<run-id>/inputs/files/`, with a 50 MiB limit per file and 250 MiB per research run. Only supported, non-sensitive materials marked `survey_evidence` enter Survey's multimodal manifest; remote perception requires explicit consent. Materials become immutable after a science stage starts. Shared files used by figure, polish, and translation Jobs use the separate limits in `web.files` (50 MiB per file and 1 GiB per project by default).

Full research supports stage endpoints, resume, cancellation after the current stage, artifact inspection, and durable logs/events. Quantitative modeling exposes parameter evidence, approval, materialization, plan-specific execution consent, qualification, revision, and Author handoff. PDFs, TXT, Markdown, and CSV marked `Parameter source` can be registered as parameter evidence. See the [quantitative evidence workflow](../docs/quantitative_parameter_evidence_workflow.md).

Core API groups are `/api/runs`, `/api/jobs`, `/api/files`, `/api/figure/jobs`, `/api/polish/jobs`, `/api/translation/jobs`, and `/api/preferences`. Event streams use `/api/runs/{run_id}/events` and `/api/jobs/{job_id}/events`. [Swagger UI](http://localhost:8010/docs) documents the current request and response schemas.

Run frontend checks from the repository root:

```bash
npm --prefix WebApp-V2 run build
npm --prefix WebApp-V2 test
```

The build runs `tsc --noEmit && vite build`. The test command runs the current Vitest tests once. Both commands use the frontend's installed dependencies.

## 简体中文

运行环境为 Linux x86_64 / WSL2、Python **3.12** 与 `uv`。前端需要 Linux Node.js **20.x 的 20.19+，或 22.12+** 和 npm，推荐 **22 LTS**。安装依赖前，在 WSL 中检查 `node --version`、`npm --version` 与 `which node npm`。

`WebApp-V2/` 是当前 React / TypeScript 前端。FastAPI 提供科研与独立功能 API、持久化 Job、SSE 事件和成果下载。完成[安装与配置](../README.zh-CN.md#安装与配置)并保存 `.env` 后，在 **Linux / WSL 的仓库根目录**执行以下命令；每个后端终端均使用同一个 `UV_PROJECT_ENVIRONMENT`。如果当前仓库已使用默认 `.venv/`，可省略下面的 `export UV_PROJECT_ENVIRONMENT=…` 行，`uv run` 会使用该项目环境。

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

访问 [http://localhost:5173/app](http://localhost:5173/app)。Vite 会在源码变化后更新页面，开发模式无需先生成 `dist/`。[`vite.config.ts`](vite.config.ts)监听 `0.0.0.0`，将相对路径 `/api` 请求（包括 SSE）代理到 `http://127.0.0.1:8010`。科研运行、上传、Job 和偏好读写都需要后端持续运行；接口文档直接访问 [http://localhost:8010/docs](http://localhost:8010/docs)。

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

默认情况下，`workspace/science-runs/` 保存科研运行，`workspace/qwensci.db` 保存 Job 状态与事件，`workspace/jobs/` 保存 Job 输入与成果，`workspace/files/` 保存共享上传文件，`workspace/preferences.json` 保存工作区偏好。路径由 [`src/config/default.yaml`](../src/config/default.yaml)等配置决定；偏好设置只作用于新建任务。浏览器和 CLI 复用同一套科研运行产物。

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

CLI 工作流见[中文主 README](../README.zh-CN.md)，接口和 Job 契约见 [Web 后端说明](../docs/webapp-backend.md)。

### 运行行为与前端检查

科研材料保存在 `workspace/science-runs/<run-id>/inputs/files/`，单文件上限 50 MiB、单个科研运行总上限 250 MiB。只有受支持、未标记敏感且用途为 `survey_evidence` 的材料进入 Survey 多模态清单，远程感知需明确同意。任一科学阶段开始后，材料不可修改。绘图、润色和翻译 Job 使用的共享文件另按 `web.files` 限额处理，默认单文件 50 MiB、每项目 1 GiB。

全流程科研支持选择阶段终点、恢复、当前阶段结束后中止、查看成果及持久化日志与事件。量化建模依次提供参数证据、批准、物化、绑定具体计划的执行确认、资格审查、修订与 Author 交接。标记为 `Parameter source` 的 PDF、TXT、Markdown 和 CSV 可登记为参数证据，详见[量化参数证据流程](../docs/quantitative_parameter_evidence_workflow.md)。

主要 API 分组包括 `/api/runs`、`/api/jobs`、`/api/files`、`/api/figure/jobs`、`/api/polish/jobs`、`/api/translation/jobs` 与 `/api/preferences`。事件流位于 `/api/runs/{run_id}/events` 和 `/api/jobs/{job_id}/events`。[Swagger 接口文档](http://localhost:8010/docs)提供当前请求和响应结构。

在仓库根目录执行前端检查：

```bash
npm --prefix WebApp-V2 run build
npm --prefix WebApp-V2 test
```

构建命令执行 `tsc --noEmit && vite build`，测试命令执行一次当前 Vitest 测试。两者均使用已安装的前端依赖。
