# Web 后端功能说明

后端把科研运行、绘图、学术润色和论文翻译统一为可恢复的持久化 Job。SQLite 保存状态、租约、幂等键和事件索引；工作目录保存冻结输入清单、Prompt 快照、检查点和 Artifact。浏览器只使用安全 ID，响应和错误不会返回服务器本地路径或凭据。

## Job 生命周期

Job 状态为 `QUEUED`、`RUNNING`、`WAITING_FOR_REVIEW`、`SUCCEEDED`、`FAILED`、`CANCEL_REQUESTED`、`CANCELLED` 和 `EXPIRED`。worker 领取 `QUEUED` Job 时递增 `attempt` 并获得租约；内容版本 `revision` 只在用户要求重生成时递增，重启恢复和失败重试继续使用原内容版本。服务重启后，恢复逻辑重新提交排队 Job，并把租约过期的运行 Job 放回队列；超过重试上限的 Job 进入 `FAILED`。取消在安全检查点生效。

图像调用账本使用输入 hash、内容版本、模型、provider、Prompt 和尺寸确定调用身份。已知远端 `task_id` 跨 worker attempt 恢复轮询；已成功的图片在验证 hash 后复用。取消或租约丢失不会丢弃已经获得的远端 task ID。只有新内容版本才创建新图像调用。提交结果未知且没有 task ID 时返回 `MODEL_CALL_OUTCOME_UNKNOWN`，需要核对 provider 记录后另行处理。文本调用复用已完成且通过校验的段落/block 检查点；provider 未返回的文本调用不具备远端任务查询能力。

SQLite schema 为 `job_store_v3`。Job 状态变化与事件在同一事务提交，SSE 直接读取数据库事件；`events.jsonl` 和 `job.json` 是可重建镜像。升级导入旧 JSONL 的事件序号，保持 cursor 连续。镜像文件缺失不会丢失事件或阻断已提交状态。

每个 Job 的 `input.json` 在注册前写入并计算 SHA-256。worker 读取时再次校验输入文件、manifest 和 Prompt hash。相同 scope 下的 `idempotency_key` 与 request hash 相同会返回原 Job；key 相同但请求不同返回 `409 IDEMPOTENCY_CONFLICT`。事件通过 `GET /api/jobs/{job_id}/events` 提供，支持 `after` 和 `Last-Event-ID` 重放。

## 共享文件和 Artifact

共享文件接口为 `POST /api/files`、`GET /api/files`、`GET /api/files/{file_id}`、`GET /api/files/{file_id}/content` 和 `DELETE /api/files/{file_id}`。上传会检查扩展名、magic bytes、声明 MIME、UTF-8 文本、Office ZIP 结构、ZIP Slip、符号链接、加密条目、解压后大小和 workspace 配额。Run material 同时登记到旧 run manifest 和共享 FileService；Job 与输入文件引用在同一数据库事务登记，启动时修复文件 JSON 中的引用镜像。一个输入可关联多个 run/Job；释放一个引用不会清除其他引用。

`POST /api/jobs/{job_id}/artifacts/{artifact_id}/files` 将已接受 Job 的产物登记为共享输入，保留项目、源 Artifact ID、内容 hash、敏感性与 `do_not_send` 限制。重复复用同一 Artifact 返回同一个文件 ID。

Artifact 先写临时文件，再做路径、大小、hash 和领域校验，最后原子移动到 `artifacts/attempt-xxx/`。SQLite 只有在 Artifact manifest 成功写入后才提交 `output_artifact_ids`。Artifact 以内容 hash 和来源元数据命名，只能通过所属 Job 的已提交 ID 读取；最终导出也会登记为 Artifact，并保存输入 hash、Prompt hash、review version 和 exporter version。

## 功能 Job

三个功能都支持创建、列表、详情、动作、Artifact 列表和 Job SSE：

- `POST /api/figure/jobs`：Python 数据图支持 line、bar、scatter、hist、box、分组、非负误差条和 Welch t-test。`planning_mode=auto` 在省略图型时使用选定的 Qwen 文本模型生成 `FigureSpec`；显式图型使用本地模板，`planning_mode=model` 可要求模型规划标签、配色和尺寸。模型不能生成执行代码，也不能改变用户提供的变量映射。worker 发布可复查的 Python 源文件、FigureSpec、图像和 QA。AI schematic 使用原 `academic_figure` Qwen 图像模型，并将上传文本证据及其 hash 写入图像 brief，必须显式授权并人工复核。
- `POST /api/polish/jobs`：按段落切分文本，调用 allow-list 中的 Qwen 文本模型，校验数字、单位、公式、引用键、变量名和保留词，再进入 `WAITING_FOR_REVIEW`。`accept_segments`、`reject_segments` 和整体接受/退回都带 review version。
- `POST /api/translation/jobs`：复用项目 MinerU adapter 解析 PDF，按页和 block 翻译，保留页码、图表/表格/方程标记、源 block ID、术语 ledger 和 OCR 未决项。`accept_pages`、`reject_pages` 可单独处理页面。

润色和翻译的最终导出接口为 `POST /api/polish/jobs/{job_id}/export` 和 `POST /api/translation/jobs/{job_id}/export`，支持 `markdown`、`json`、`docx` 和 `pdf`。只有当前 attempt 的整体 review 为 `accept` 才能导出；导出时会再次校验 review version。DOCX/PDF 当前导出文本、标题和页标记，尚未重建原始 PDF 的原生表格、图片位置和公式对象。

`regenerate_segments` 与 `regenerate_pages` 只重生成选定段落或页面，复用其余内容并保留未修改内容的审阅决定。动作需附非空 `notes`，可同时提交 `expected_attempt` 和 `expected_review_version` 防止覆盖新结果。`reject_segments` 与 `reject_pages` 表示最终导出使用对应原文，与重生成动作分开。

数据图可在创建请求中使用 `figure_style` 设置 `x_label`、`y_label`、`title`、`width_mm`、`height_mm` 和 `palette`。配色只接受 `colorblind`、`blue`、`neutral`；宽度为 80–300 mm，高度为 60–250 mm。显式本地图形退回时，必须提供确实改变当前结果的样式字段；缺失、空对象或未改变样式的退回返回 `409`，不消耗 revision。连续退回会累计样式修改，未指定的字段保持原值，整个显式本地流程不调用规划模型。模型规划模式也会落实用户指定的样式约束。AI 示意图通过文字反馈修改，不接受数据图样式字段。

```json
{
  "type": "reject",
  "notes": "改用中性配色，并补上横轴标签。",
  "figure_style": {"palette": "neutral", "x_label": "Condition"},
  "expected_attempt": 1,
  "expected_review_version": 0
}
```

以上动作发送到 `POST /api/figure/jobs/{job_id}/actions`。Artifact 列表保留历史 attempt；展示当前图形时，应选择 `attempt` 等于 Job 当前 attempt 的 `figure_spec`、图像及 QA。

润色和翻译都发布 `document_source_map`，记录稳定 block ID、顺序、源 hash、页码或文本偏移。DOCX 按正文中段落与表格的真实顺序提取；代码块和表格逐字保留，含原生公式的 DOCX 输入明确拒绝。MinerU 的图表内容与 caption 分成不同 block，保留图表/公式内容、翻译 caption。空 MinerU 内容回退到 pypdf，解析异常类型、回退原因和缺失文本页分别记录在 `parser_diagnostics` 与 `unresolved_items`。

Python renderer 只执行服务器模板，使用每次 attempt 独立目录、清理后的环境、可取消的子进程和超时。Python audit hook 阻止网络和子进程；Linux/WSL 额外限制 CPU、虚拟内存、文件大小、文件描述符和 core dump。Windows 原生执行不具备这些 POSIX 资源限制。QA 保存数据绑定 hash、随机种子、依赖版本、文件格式检查、文字碰撞和可用时的 PDF 文本边界审计；缺少审计依赖时记录 `NOT_AUDITABLE`。当前为单面板图，多面板对齐不适用；科学主张仍需作者复核。

## 模型、Prompt 和隐私

文本模型只允许 `qwen3.6-flash`、`qwen3.7-plus`、`qwen3.8-flash` 和 `qwen3.8-max`。Prompt 从版本化 Python `PromptSpec` 注册表解析，嵌套输出 schema 不可修改。Job manifest 保存 Prompt ID、版本、skill source hash、基础与实际规则组合后的 Prompt hash、输出 schema 版本、模型、provider、temperature 和输出 token 上限。Artifact 继承这些来源信息。运行时不会读取用户的 `.codex/skills` 文件；skill 只在开发时提炼为稳定规则。四个文本模型都可以通过偏好或创建请求选择，任务创建后选择和 Prompt 快照不可变。

`privacy_mode=local-only` 会阻止需要远程模型的润色、翻译和 AI schematic。`do_not_send` 材料不能进入远程文本或图像调用。`/api/capabilities` 区分配置存在与远程连通性验证：模型和图像模型默认显示 `configured`、`verified=false`，不会把配置文件存在误报为 API 已连通。

本地模式下绘图需提供显式图型并使用本地模板；模型规划会发送表的列名、类型和缺失值计数，因此也受隐私限制。provider 凭据或 endpoint 缺失时能力接口返回 `unavailable`，不会标记为已配置。

## 全流程科研和偏好

`POST /api/runs` 支持 `research_depth`、`workflow_profile`、`prompt_profile`、`model_name`、`project_id`、`quantitative_mode` 和独立的 `computation_mode`（`off`、`plan`、`run`）。量化分支负责参数证据、数学模型和量化审批；数值计算实验负责独立的计算方案与隔离执行，两者分别写入不可变运行选项。轻度研究只允许 Survey 和可选 Idea，且不能启用任一分支；完整研究才允许 ExperimentDesign 和 Author。旧 run 读取时默认为完整研究，锁内原子补全元数据并记录 `RUN_METADATA_MIGRATED`，不会根据旧的 `until` 值猜测为轻度研究。

偏好接口为 `GET /api/preferences/schema`、`GET /api/preferences` 和 `PUT /api/preferences`。当前是单 workspace 文件存储，更新使用版本号和文件锁；偏好只影响之后创建的 run 或 Job，Job manifest 会保存创建时的偏好快照。

## 联调接口

通用和各功能 Job 列表支持 `project_id`、`run_id`、`status`、`limit` 和 `offset`；详情包含 `available_actions`、`attempt` 与 `revision`。绘图、润色和翻译均可关联已有 run，服务端校验项目一致性。功能路径下的 SSE 与 Artifact 下载复用通用 Job 协议。

`GET /api/translation/jobs/{job_id}/pages` 返回页面摘要、解析来源、OCR 标记、未决项数量和当前审阅状态；单页详情附当前 review version。

产品模块接口为 `GET /api/product/modules`、`GET /api/product/capabilities` 和 `GET /api/product/preview/{module_id}`。模块 ID 为 `full-research`、`light-research`、`figure`、`polish`、`translate` 和 `preferences`。预览的 `data_source` 为 `static_registry` 或 `representative`，`is_live=false`、`last_verified_at=null`，不会生成虚构运行状态。这些接口仅提供后端契约，前端页面尚待单独设计。

## 首发边界

首发版本暂不提供 R 绘图、参考图编辑、页图翻译、多人认证和 ACL。`/api/capabilities` 会返回这些能力的实际状态，创建接口会返回明确的能力错误，不会静默切换到其他模型或后端。MinerU、DOCX、ReportLab、Matplotlib、Pandas 和 Pillow 是否可用也由能力接口报告；远程 provider 和 MinerU parser 的真实连通性需要部署环境另行执行 smoke test。

## 运行和验证

`GET /api/disciplines` 返回全部 20 个支持学科。研究启动页提供中文手动选择，最多两项，并显示目录加载、失败重试和已选状态。

运行详情页的“运行日志”同时展示持久化系统事件和各阶段日志。Survey 启动时，后端把子进程的标准输出与标准错误合并写入当前 attempt 的 `console.log`，并设置无缓冲 UTF-8 输出；Idea、ExperimentDesign 和 Author 使用各自的 JSONL 或文本日志。前端默认每 2 秒刷新日志目录和当前日志游标，可单独关闭自动同步或自动滚动，也可手动切换日志源。日志读取按完整行增量推进，服务端清理终端控制序列、脱敏密钥和本机路径，并拒绝阶段目录外的符号链接；页面最多保留最近 100 万字符，完整文件仍留在运行目录。

系统事件使用现有的 `GET /api/runs/{run_id}/events?follow=false&after=<event_id>`，阶段文件使用 `GET /api/runs/{run_id}/logs` 和 `GET /api/runs/{run_id}/logs/{log_id}?offset=<byte_offset>`。历史运行中已经丢弃的终端输出无法回补；更新后的新运行会从 Survey 启动时开始同步。

`POST /api/disciplines/resolve` 保留默认的 `method="taxonomy"` 本地分类；传入 `method="model"` 时固定使用 `qwen3.8-flash` 识别中英文课题。模型只能返回目录内的 1–2 个 ID，并附简短原因；无法判断或不在支持范围时返回空建议。结果经服务端校验后才交给页面，用户仍可手动修改。识别失败不会退回本地规则冒充模型结果，也不会阻止手动选科。

远程识别遵守工作区 `local-only` 与 `network_access="never"` 限制，模型调用超时为 45 秒；开发代理为识别接口单独保留 60 秒超时。输入课题变化、用户手动修改学科或页面卸载时，前端取消等待并忽略过期结果。

使用 Python 3.12 环境，通过 `.venv/bin/python -m src.webapp.api` 启动服务，默认监听 `127.0.0.1:8010`。`/docs` 提供 OpenAPI 页面；`/api/capabilities` 显示当前依赖和模型配置状态。服务按原有生命周期恢复持久化任务，测试应使用独立的临时 `run_root`，避免对实际研究运行触发恢复。

可选依赖维持现有 extras：`multimodal` 提供 Python 绘图与表格处理，`pdf` 提供 MinerU、pypdf、DOCX 和 PDF 导出。缺失依赖通过 capability 或明确错误反馈。前端构建产物不属于本轮交付；缺少 `WebApp-V2/dist/index.html` 时，网站根路径按现有逻辑返回 `503`，API 与 `/docs` 可独立访问。

后端回归测试使用 WSL 项目虚拟环境：

```text
wsl.exe -d Ubuntu-24.04 --cd /home/dlutee2026/qwen_sci-main -- .venv/bin/python -m pytest -q tests/test_webapp_jobs.py tests/test_webapp_features.py tests/test_webapp_document_workflows.py tests/test_webapp_backend_contracts.py
```

测试不会调用真实付费模型；测试中的 provider、MinerU 和图像客户端均使用受控替身。部署前还需要用实际 `DASHSCOPE_API_KEY` 运行一次文本 JSON 调用、Qwen 图像任务恢复和 MinerU PDF 解析 smoke test。

本轮与改造相关的 17 个测试文件回归结果为 **218 passed、1 deselected、4 warnings**，耗时 105.77 秒。范围覆盖新 Job/文件/Prompt/文档工作流、原 Web API、参数检索与取消、科研模型冻结、science workflow/CLI/config/manifest，以及模型 provider 和多模态适配。被排除的 `test_same_origin_frontend_uses_real_api_controls` 依赖现有前端构建；当前缺少构建产物，单独执行时根路径返回 `503`。四个告警来自现有 requests 依赖版本与 SWIG 弃用提示。Python 编译检查和变更文件空白检查通过。

## 首版验收清单

| 范围 | 已实现行为 | 验证方式 |
| --- | --- | --- |
| 任务控制 | SQLite 迁移、租约、互斥领取、重启恢复、取消、重试、幂等、attempt/revision 分离 | JobStore/JobRunner 回归与故障注入 |
| 事件与产物 | 状态和事件同事务、SSE cursor 重放、不可变 Artifact、接受后复用为文件 | 事务回滚、镜像缺失恢复、下载与复用集成测试 |
| 输入与隐私 | 文件类型/大小/路径校验、数据库引用保护、local-only 与 do_not_send | 文件上传、引用崩溃窗口、隐私校验测试 |
| 模型与 Prompt | 四种 Qwen 文本模型可选、沿用 academic_figure、冻结版本与参数 | Prompt 不可变、模型冻结、图像调用恢复测试 |
| 科研流程 | 完整/轻度 profile、旧运行迁移、保留原有量化流程 | science workflow、API 与参数检索取消回归 |
| 科研绘图 | 单面板 Python 模板、模型规划、结构化样式修改、统计与 QA、人工接受 | 渲染、非法列绑定、禁止网络、连续样式修改测试 |
| 润色与翻译 | 段落/页审阅、局部重生成、文本源映射、MinerU adapter 与回退、四格式导出 | 文档工作流、术语/锚点校验、DOCX 顺序与解析诊断测试 |
| 偏好与联调 | 单工作区版本化偏好、项目/run 关联、分页筛选、六模块静态预览 | 请求冲突、项目约束、SSE 别名与预览来源测试 |

这份清单对应原方案的首版后端范围。R、参考图编辑、页图翻译、多人认证/ACL 和原 PDF 版面重建尚未实现；它们在能力接口中有明确边界。自动化测试证明受控条件下的本地行为，远端模型与 MinerU 的实际部署验证另列为待完成的 smoke test。
