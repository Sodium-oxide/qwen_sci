# Survey 原生检索与 Idea 的 AnySearch 检索

Survey 阶段禁止访问 AnySearch，继续使用原生 OpenAlex 等检索通道。共享预检索、附加 AnySearch 查询通道以及 AnySearch 能力发现均不会在 Survey 中发起请求；旧配置或恢复配置中的 `enable_anysearch_discovery: true` 不能重新授权。

Idea 继续使用科学需求规划器、AnySearch 能力清单、检索调度器和真实资料读取器。同一项目可以为不同子问题选择不同学科和资料通道。输入通过科学字段白名单构建，排除 rubric、评测指令、候选评分和裁决数据。

## 连接与通道

WSL 终端或项目根目录 `.env` 配置 `ANYSEARCH_API_KEY`。默认 REST Base URL 是 `https://api.anysearch.com`，可通过 `ANYSEARCH_BASE_URL` 覆盖。主机地址、`/v1` 地址和完整 `/v1/search` 地址均可配置；MCP 地址不适用于 REST 客户端。未设置 key 时不发送鉴权头。

共享检索启动时调用 `GET /v1/domains`，再按实际 domain 调用 `GET /v1/sub-domains?domain=academic` 等接口，获取用途、参数和必填字段，优先加载 academic、general、code、health、legal。能力发现独立限制最多 20 次请求、45 秒，在客户端缓存目录保存 `capabilities-<endpoint-hash>.json`，24 小时内复用。部分通道失败时保留此前验证的缓存；全部失败且没有缓存时使用内置 `academic.search` 无参数回退，计划也可选择已有 OpenAlex。

模型只能从能力清单选通道。程序校验标签、参数名、必填字段、接口提供的类型和枚举、年份顺序。客户端默认标签兼容旧调用；共享规划器逐次指定：

```python
client.search("alpha7 cannabidiol modulation", limit=5,
              tag="academic.biomedical", params={"field": "tiab"})
client.search("perovskite stability dataset", limit=5,
              tag="academic.dataset", params={})
```

官方请求是 `POST /v1/search`，JSON 包含 `query`、`tag`、`params`、`max_results`、`format: json`；读取 `data.results`，兼容顶层数组、`results`、`papers`、`data` 数组。通道以实际清单为准，引用追踪须有真实标识符。HTTP 200 的非零业务 code 按失败处理。网络、429、5xx 有有限重试，错误响应消息不会写入日志或检查点。成功结果默认缓存 7 天，空结果最多 6 小时，缓存身份包含 endpoint、通道、参数、查询和结果数。

## 规划、试搜和读取

`src/pipeline/search_planner.py` 从原始任务、研究对象、子问题、已读文献、候选机制和信息缺口形成多项需求。每项保存目的、目标子问题、学科、预期资料类型、研究对象、待覆盖条件、初始通道及参数、查询及理由、替代查询、请求预算和成功阅读目标。

查询使用“对象＋关系或方法＋条件”，同义词拆为替代查询；不再把主题前 700 个字符直接用于搜索。计划格式错误时保存原始回答，有限修复后使用简短词项的确定性回退。

`src/pipeline/adaptive_search.py` 先小规模试搜，再按新增相关资料、成功读取量、读取成功率和未覆盖条件排序。偏题或科普结果触发对象与资料类型调整；资料不足时换查询、放宽年份或补充通道；重复结果可沿真实 DOI 追踪引用。调整模型失败时用计划内替代查询，无有效替代则保存证据结束该需求。HTTP 成功和返回条数仅记录接口状态，覆盖指标来自实际读到的内容。关键词覆盖是调度提示，科学结论由后续阅读分析确定。

`src/pipeline/source_reader.py` 识别身份、去重后读取实际来源：

| 资料 | 读取方式 | 来源范围 |
| --- | --- | --- |
| 论文、预印本 | DOI、PMCID、arXiv、明确 PDF；有学术元数据的实际正文页；PDF 沿用下载和 MinerU | `fulltext`、`fulltext_html`；按配置回退真实 `abstract` |
| 数据集 | 仓库页、仓库 ID 或 DOI、版本、下载链接；预算内探测下载响应 | `repository_metadata`，区分介绍页、声明下载地址、下载可访问 |
| GitHub 代码 | 仓库元数据、提交 SHA、固定提交的 README | `repository_readme`，记录提交版本 |
| 政策、标准、文档、统计 | 所选链接的实际页面；明确 PDF 继续 PDF 链路 | `source_page` 或 `fulltext` |

读取代码仓库不执行代码，下载探测不加载完整数据。其他仓库无可验证身份或实际内容时记录失败。官方来源由任务和通道选择优先访问，页面可读取不等于权威性已验证。

`snippet` 与搜索 `content` 只保存为 `discovery_snippet` / `discovery_content`。真实摘要、正文或仓库内容才能进入阅读结果。完整来源保存 SHA-256、类型、URL、DOI、版本、时间、访问状态和读取范围；超过上限保留完整文件，给模型标为 `*_excerpt` 的片段。Survey 相关性评估用独立 `source_excerpt` 字段，不把实际正文片段伪装为摘要。后续下载与分析按哈希复用已读来源，避免重复下载和 MinerU 解析。

论文按 DOI、PMID、PMCID、arXiv、标题等跨来源去重并保留来源；数据、代码等按类型和已知版本区分。无 OpenAlex ID 时使用稳定 `AS…` 编号，不当作外部 API 文献 ID。`AS…` 可作上下文阅读，真实 `W…` 论文仍可按原策略扩展图谱。

### 从检索链接到正文

PubMed URL 和外部标识中的 PMID 会保留在 `externalIds.PubMed` 中。缺少 DOI 或 PMCID 的生物医学记录，通过 Europe PMC 的标识查询补全正式题名、作者、DOI、PMCID、真实摘要和公开全文地址。返回记录必须与已有标识精确对应，任一共有标识冲突时不采用该记录。查询和匹配标识保存为 `identity_provenance`，请求与其他来源读取共用 HTTP 和时间预算。

PMC、bioRxiv、medRxiv 页面按真实主机和论文路径识别，AnySearch 来源标签不再阻止这些仓储页面解析。普通网页仍不能仅凭 `anysearch.oa_location` 标签进入全文页面解析。优先保留页面声明的 PDF；可用的文章 HTML 正文直接读取。PubMed 题录页不作为全文。PMC 页面或 PDF 获取失败时，可通过 Europe PMC 的 `fullTextXML` 接口读取 JATS，核对 XML 内 DOI、PMID、PMCID 和实际正文后再使用。原始 XML、SHA-256、来源 URL、文章类型与版本同时保留；搜索片段不进入正文。相同规范标识的已读来源在校验文件哈希后跨检索编号复用。

来源检查点保留 `source_attempts` 和 `retry`。403、404、无声明 PDF、无法解析的路线等确定性失败，在所有路线均未出现临时故障时标为 `when_source_changes`。调度器和读取器都跳过相同地址、标识和访问条件的重复获取；新增地址、补全标识或修改 `survey.ModuleInfo.WorkCollector.fulltext_access_context_generation` 后重新允许获取，并为新路线重计逐篇尝试次数。已用全局获取预算保留。网络错误、429、5xx 仍按有限重试处理。旧检查点缺少该分类时保持原有重试行为。

## 配置与预算

Survey 的 `survey.ModuleInfo.WorkCollector` 默认值：

```yaml
enable_anysearch_discovery: false
shared_search_enabled: false
shared_search_use_llm: true
shared_search_max_needs: 5
shared_search_max_requests: 12
shared_search_max_http_requests: 80
shared_search_max_model_calls: 12
shared_search_max_acquisition_attempts: 20
shared_search_read_limit: 8
shared_search_max_seconds: 900
shared_search_max_rounds: 3
shared_search_plan_repair_attempts: 1
shared_search_checkpoint_attempts: 2
shared_search_result_limit: 5
shared_search_prefer_fulltext: true
shared_search_max_source_chars: 60000
```

Survey 的这些字段保留以兼容已有配置。Survey 的阶段权限始终禁止 AnySearch，即使将 `enable_anysearch_discovery` 或 `shared_search_enabled` 改为 `true`，也不会运行共享预检索或附加 AnySearch 查询。Survey 原生检索控制器沿用自己的预算。

Idea 的 `idea.agent.anysearch` 默认值：

```yaml
enabled: true
planner_use_llm: true
initial_queries: 5       # 初始阶段信息需求数上限
candidate_queries: 4     # 候选阶段信息需求数上限
initial_read_limit: 4
candidate_read_limit: 4
max_total_papers: 8      # 两阶段合计成功新增阅读上限
max_acquisition_attempts: 20
max_total_acquisition_attempts: 20
max_requests: 12
max_http_requests: 80
max_model_calls: 12
max_seconds: 900
max_rounds: 3
plan_repair_attempts: 1
checkpoint_attempts: 2
result_limit: 5
prefer_fulltext: true
allow_abstract_fallback: true
max_source_chars: 60000
```

初始知识获取和候选路线准备分别调用规划器。每阶段查询、HTTP、规划器调用和时间预算独立；新增成功阅读与获取尝试有跨阶段总上限。已拒绝或合并的候选不生成新需求。

目标读 8 篇、允许获取 20 次时，前 4 个失败后仍尝试后续候选。重试占获取尝试，失败不占成功名额；每项还受 `checkpoint_attempts` 限制。作用域中的 HTTP 重试和重定向逐次计入预算。能力发现独立限额，模型客户端底层重试由原配置约束。时间在下一项操作或下一次 HTTP 前检查；已经进入 MinerU 的解析继续沿用既有超时，不会在第 900 秒强杀外部解析进程。

## 保存、交接与恢复

已有 Survey 产物中的 `search/project.json`、`search/project_model/`、`search/reading/` 和 `search_history.json` 可以保留。已缓存的文献元数据和已读来源仍可供恢复与交接使用；恢复任务不会重新开启 AnySearch。旧交接无历史时仍可加载。

Idea 在当前目录的 `external_search/` 保存 `initial.json`、`candidate.json`、`initial_model/`、`candidate_model/`、`search_cache/`、`reading/`。原有 `keynote_compression/` 保存摘要及 JSON 修复检查点。

操作执行前预留预算并保存，完成后更新状态，模型原始回答在解析前落盘。恢复同一阶段复用已完成请求和阅读，只在预算内重试未完成项目；重启不清零已用预算。Idea 能看到已查目的、通道、参数、查询、候选、已读资料、未覆盖条件和调整理由，再针对候选补检索。

通道不可用、计划解析失败、预算耗尽时记录问题，保留已完成资料。后续摘要仍用原始 keynote 保留及有限 JSON 修复。最终 Idea JSON 的 `external_searches` / `external_references` 保留来源信息。

## 验证

模拟 HTTP、来源和模型，不启动研究任务或调用付费模型：

```bash
.venv/bin/python -B -m pytest -q \
  tests/test_adaptive_search.py tests/test_anysearch.py \
  tests/test_idea_anysearch.py tests/test_survey_anysearch.py \
  tests/test_survey_search_controller.py tests/test_survey_handoff_persistence.py \
  tests/test_survey_fulltext_resolution.py tests/test_fulltext_http.py
```

覆盖 Survey 的 AnySearch 访问阻断、旧配置隔离、Idea 能力缓存、逐请求参数、多学科计划、rubric 隔离、失败补位、预算、重复调整、真实读取、断点复用和交接哈希。
