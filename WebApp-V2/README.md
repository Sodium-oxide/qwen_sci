# Qwen-Sci WebApp V2

`WebApp-V2` 是 Qwen-Sci 的同源 Web 工作台，不覆盖旧版 `WebApp`。它不再生成 CLI 命令或回退到演示会话：浏览器只调用受控 API，由后端直接调用已有的 `science` 状态机。

## 启动

在仓库根目录执行：

```bash
npm --prefix WebApp-V2 install
npm --prefix WebApp-V2 run build
uv run qwensci-web
```

然后访问 `http://127.0.0.1:8010/`。`npm run build` 会生成 React/TypeScript 工作台的 `WebApp-V2/dist/`；FastAPI 仅托管该生产构建和 API，避免跨端口的演示降级。若尚未构建，根路径会返回明确的构建提示，而不会回退到静态演示页面。

### 在 WSL 中启动

请在 WSL 终端中使用 Linux 版的 `uv`、Python、Node.js 和 npm，不要直接使用 Windows 的 `.venv`。如果仓库位于 Windows 磁盘，可为 WSL 单独创建环境而不改动现有 Windows 环境：

```bash
cd /mnt/c/Users/31390/Desktop/2026tzb/aiscientist-v0820/Xcientist
export UV_PROJECT_ENVIRONMENT=.venv-wsl
uv sync --all-groups
npm --prefix ./WebApp-V2 install
npm --prefix ./WebApp-V2 run build
uv run qwensci-web
```

随后在 Windows 浏览器访问 `http://localhost:8010/`。可用 `curl http://127.0.0.1:8010/api/health` 确认服务状态。若入口命令不可用，使用等价的显式启动命令：

```bash
uv run python -m uvicorn src.webapp.api:app --host 0.0.0.0 --port 8010
```

不要使用 `uv run --no-sync`。前端源代码变更后，需要重新执行 `npm --prefix ./WebApp-V2 run build` 并重启服务。

## 使用边界

- 课题必须选择 1–2 个项目支持的学科。界面从现有 OpenAlex 目录加载 20 个自然科学、工程和健康科学字段，并可按课题给出建议；明确排除的领域由服务端拒绝。
- 创建或恢复运行时可选择终点：仅 `Survey`、`Survey + Idea`、至 `ExperimentDesign`，或完整至 `Author`。到达所选终点后运行会以 `PARTIAL` 状态保留全部已验证成果，用户可在网页端选择新的终点后继续。
- 科学阶段运行时可请求“在当前阶段后中止研究”。中止请求会持久化并通过 SSE 显示；当前阶段完成其原子结果写入后，服务端停止后续阶段、保留成果并标记 `CANCELLED`。恢复必须由用户再次提交受控动作，取消请求不会自动重启。
- 研究材料会流式存入 `workspace/science-runs/<run-id>/inputs/files/`，并以相对路径登记。单文件上限为 50 MiB、单个运行总上限为 250 MiB。
- 只有标记为 `Survey evidence`、不含敏感数据、且属于受支持模态的材料才会进入 Survey 的受控多模态清单。远程视觉分析还需要创建运行时的显式同意。
- 运行、恢复、事件和产物均以 `run_id` 为边界；浏览器不提交 shell 命令、文件路径或任意配置覆盖。
- 已完成运行会自动发现受控 `survey`、`idea`、`experiment_design` 和 `author` 目录下生成的图片成果；它们会在成果面板的 `Figure` 筛选中提供预览和下载。原始上传资料继续显示在材料面板，不会被混入成果索引。
- 对启用量化的运行，工作区会依次暴露 Q1/Q2 的模型蓝图、带显式网络同意的参数发现/开放全文、受证据约束的参数选择与人工批准、计划物化、逐字匹配 `plan identity` 的一次执行确认、结果资格审查、修订/冻结、补充 PDF、Author handoff 与 Author 继续动作。
- 上传时标记为 `Parameter source` 的 PDF、TXT、Markdown 或 CSV 可在对应 Q 版本中登记为受控参数证据；浏览器只能选择登记的材料 ID，不能提交本地路径。

## API

核心端点为：

- `GET /api/health`、`GET /api/disciplines`、`POST /api/disciplines/resolve`
- `GET /api/runs`、`POST /api/runs`、`GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/materials`、`GET|DELETE /api/runs/{run_id}/materials/{material_id}`、`POST /api/runs/{run_id}/actions`
- `GET /api/runs/{run_id}/events`（SSE）
- `GET /api/runs/{run_id}/artifacts/{artifact_id}`

量化动作全部复用既有服务层的不可变工件和契约：浏览器只提交受限的 Q1/Q2、版本、已登记材料/文档 ID、有限数值、枚举关系和明确确认；服务端在执行前再次检查当前状态、批准参数集与计划身份。网络发现和开放全文分别要求 `network_authorized: true`，不会因前端勾选之外的字段被隐式开启。
