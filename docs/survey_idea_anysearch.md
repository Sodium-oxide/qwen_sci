# Survey 和 Idea 的 AnySearch 接入

Survey 和 Idea 共用 `src/pipeline/anysearch.py` 中的 HTTP 客户端。Survey 在现有文献发现计划中加入 AnySearch；Idea 在读取 Survey 文献和形成候选想法之后分别补检索。返回的论文经过实际全文或摘要阅读后才进入模型上下文。

## 连接服务

默认直接调用 AnySearch 官方 REST API，Base URL 为 `https://api.anysearch.com`。不需要部署桥接服务，也不需要额外填写地址；需要代理或兼容部署时，通过 `ANYSEARCH_BASE_URL` 或各模块配置覆盖。

```bash
# 在启动 qwen_sci 的 WSL 终端中设置，也可以写入项目根目录 .env。
# 默认地址可省略。
export ANYSEARCH_BASE_URL='https://api.anysearch.com'
export ANYSEARCH_API_KEY='your-service-key'
```

请求遵循 [AnySearch 官方 REST 文档](https://www.anysearch.com/docs/api-endpoints/v1-search)：

```http
POST https://api.anysearch.com/v1/search
Content-Type: application/json
Authorization: Bearer <ANYSEARCH_API_KEY>

{"query":"receptor mechanism","tag":"academic.search","max_results":10,"format":"json"}
```

`max_results` 按官方限制收敛到 1–10；学术发现默认使用 `academic.search` 标签，已通过 `/v1/sub-domains?domain=academic` 核对。`anysearch_tag` / Idea 的 `tag` 可以覆盖该标签。未设置 key 时不发送 Authorization 头，使用服务支持的匿名访问；填写 key 时使用 Bearer 鉴权。请求连接超时为 5 秒，默认读取超时为 30 秒。

Base URL 可以填主机地址、以 `/v1` 结尾的地址或完整的 `/v1/search` 地址，客户端会生成同一个搜索端点。`https://api.anysearch.com/mcp` 属于 MCP 协议，本适配器不接收它作为 REST 地址；误填时记录服务失败并继续现有流程。

官方响应从 `data.results` 读取：

```json
{
  "code": 0,
  "message": "success",
  "request_id": "server-generated-request-id",
  "data": {
    "results": [
      {
        "title": "A receptor mechanism study",
        "url": "https://doi.org/10.1000/example",
        "snippet": "Search discovery text.",
        "content": "Provider-cleaned discovery content."
      }
    ],
    "metadata": {"total_results": 1, "search_time_ms": 100}
  }
}
```

也兼容论文数组和顶层 `results`、`papers`、`data` 数组。HTTP 200 中的非零业务 `code` 按失败处理，错误响应不作为空结果缓存。

`title` 是本项目接收记录的必需字段，其余字段按实际返回使用。DOI 既可来自明确的 `doi` 字段，也可来自 `doi.org` 链接。兼容服务若额外返回 `abstract`、作者、年份、PDF 或真实 `openalex_id`，这些元数据会一并保留。缺少 `openalex_id` 时生成稳定的本地 `AS…` 编号；该编号不会发给 OpenAlex 或 Semantic Scholar 当作文献编号查询。DOI、标题和文献编号用于去重，合并后保留各来源和下载入口。

`snippet` 和 `content` 分别保存在 `discovery_snippet` 和 `discovery_content`，不会自动视作论文摘要或全文。阅读使用来源链接和既有下载、解析流程；只有明确的 `abstract` 字段才能作为服务提供的摘要回退。仅有搜索文本、且无法取得实际来源的条目会记录为不可读。

显式空地址的客户端记录 `unconfigured`。网络错误、超时、HTTP 429 和 5xx 进行有限重试；HTTP 4xx（429 除外）及响应格式错误直接记录失败。成功结果默认缓存 7 天，空结果最多缓存 6 小时；缓存身份包含 REST 端点、检索标签和请求参数。

## Survey 配置与行为

`src/config/default.yaml` 中：

```yaml
survey:
  APIInfo:
    anysearch_base_url: "${oc.env:ANYSEARCH_BASE_URL,'https://api.anysearch.com'}"
    anysearch_tag: "academic.search"
    anysearch_timeout_seconds: 30
    anysearch_max_retries: 1
  ModuleInfo:
    WorkCollector:
      enable_anysearch_discovery: true
      anysearch_result_limit: 10
```

项目、子假设（SH）、证据槽位和已缓存的检索计划都会在 OpenAlex 检索式后加入 AnySearch 查询，保留原来的 SH、槽位和任务身份。OpenAlex 专用过滤条件不会传给 AnySearch。种子数、筛选与阅读策略仍由现有配置控制；既有 HTTP 检索预算的统计范围仍是 OpenAlex query-search。

AnySearch 的来源记录与候选论文一起进入筛选。带真实 `W…` 编号的论文可以继续走图谱扩展；本地图谱缺少它时仍可阅读。`AS…` 论文作为上下文阅读，不作为图谱扩展根节点。全文失败时，是否使用真实摘要由既有 `WorkAnalyzer.abstract_only_mode` / `abstract_when_full_text_fail` 配置决定。

元数据保存在 `BasicInfo.cache_path/discovery_metadata`，请求缓存位于 `BasicInfo.cache_path/anysearch`。恢复时可以根据本地编号重新找到标题、摘要和下载入口，参考文献生成也使用这些元数据。

## Idea 配置与行为

默认配置：

```yaml
idea:
  agent:
    anysearch:
      enabled: true
      base_url: "${oc.env:ANYSEARCH_BASE_URL,'https://api.anysearch.com'}"
      tag: "academic.search"
      timeout_seconds: 30
      max_retries: 1
      initial_queries: 2
      candidate_queries: 2
      result_limit: 8
      initial_read_limit: 4
      candidate_read_limit: 4
      max_total_papers: 8
      checkpoint_attempts: 2
      prefer_fulltext: true
      allow_abstract_fallback: true
      max_source_chars: 60000
```

Idea 在两个位置使用外部检索：

1. **初始文献整理**：从主题和原始研究请求生成最多 2 条检索式，与 Survey 已有文献去重，最多新增阅读 4 篇，然后参与评分、摘要压缩和分析。
2. **候选路线准备**：从候选的标题、假设、机制、证据缺口和开放问题生成最多 2 条检索式，最多新增阅读 4 篇。读取结果马上提供给相关候选的证据上下文。

两阶段合计默认最多阅读 8 篇新论文，失败的阅读也占据名额。每个阶段在同一运行目录内固定查询集合，后续工作流或 MCTS 节点复用记录。没有候选时暂不创建候选阶段检查点，等候选形成后再检索。

查询只读取科学任务字段；不会序列化 rubric、评价分数或评测指令。已拒绝的候选与已合并的重复候选不生成检索式。

新增文献优先走现有下载与解析链路。全文不可用时使用服务返回的真实摘要；只返回 snippet 的论文标记为不可读。正文超过 `max_source_chars` 时保留完整来源文件，只向后续模型传递标记为 `fulltext_excerpt` / `abstract_excerpt` 的截断文本。模型压缩和后续分析能够看到 `reading_mode` 来源范围。

## 保存与恢复

Idea 当前运行目录下新增：

```text
external_search/
  initial.json       # 初始查询、状态、返回元数据、逐篇阅读状态与结果
  candidate.json     # 候选查询与阅读检查点
  search_cache/      # 成功或有效空结果的 HTTP 响应缓存
  reading/
    AS….md           # 阅读到的完整来源正文，真实 W 编号使用 W….md
    sh_graph_provenance.json
keynote_compression/  # 既有摘要压缩与 JSON 修复检查点
```

每次请求和阅读前后保存检查点。在同一 `run_dir` 再次进入阶段时，成功检索和已完成阅读直接复用；只尝试未完成或失败的项目。每个查询或论文最多执行 `checkpoint_attempts` 次，单次查询另受 `max_retries` 限制。创建新的运行目录会开始新的阶段记录。

单篇阅读、评分或结构化摘要失败时保留已有资料并记录问题。摘要继续使用既有的有限 JSON 修复与原始 keynote 回退机制。Idea 的运行报告写入当前 Idea 目录，下载与解析缓存可以共享，原 Survey 交接文件保持冻结。

最终 Idea JSON 及方向结果 JSON 保存 `external_searches` 和 `external_references`。后者包括实际来源范围、来源文件、DOI、检索来源和摘要检查点；合并摘要保留逐篇来源。它们是运行级来源记录，某篇论文是否支持特定方向由该方向的证据上下文决定。

要停用接入，设置 `survey.ModuleInfo.WorkCollector.enable_anysearch_discovery: false` 和/或 `idea.agent.anysearch.enabled: false`。修改代码或环境变量后，新启动的进程才会加载这些设置。

## 验证

接入测试使用模拟 HTTP、文献阅读和模型响应，不调用真实服务或付费模型：

```bash
.venv/bin/python -B -m pytest -q \
  tests/test_anysearch.py \
  tests/test_survey_anysearch.py \
  tests/test_idea_anysearch.py
```

这些测试覆盖官方请求方法与响应格式、地址拼接、MCP 地址误填、业务失败、去重、来源保留、搜索文本隔离、重试上限、缓存失效、断点复用、阅读名额、Survey 图谱缺文献场景和 Idea 最终结果持久化。

数值实验的参数文献发现和 WebApp 参数搜索也使用同一 REST 请求构建与响应解析约定，地址与标签分别位于 `quantitative_modeling.parameter_evidence.anysearch_base_url` 和 `anysearch_tag`。
