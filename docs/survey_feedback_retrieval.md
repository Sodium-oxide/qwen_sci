# Survey 的有限反馈检索

默认配置为 `ModuleInfo.WorkCollector.survey_search_strategy: model_feedback`。改动只替换 Survey 种子检索编排和必要预算、序列化接口。Idea、ExperimentDesign、Author 的算法保持原有接口。

## 数据流

原课题、研究上下文与已有 SH → 模型生成完整查询 → 程序验证格式与相关性评分 → 按 SH 轮转、每批最多四条查询 → OpenAlex → 论文身份去重 → 每四篇同时评估项目/SH 相关性、提取对象和独立维度证据 → 每二十四个合并对象确认角色和数值相关性 → 每 SH 最多三个激活候选 → 读取结果、指标和剩余预算后最多两轮反馈 → 硬上限种子集合与冻结候选登记表。

默认不逐概念、别名、证据槽位或候选矩阵展开查询。证据矩阵只记录适用范围、证据角色、最低独立来源要求、反证和缺口。新请求必须来自通过准入的模型查询。备用数据源只在请求失败时触发；有效零结果的改写由下一轮模型批准。


## 查询准入

查询记录包含 `query_id`、`sub_hypothesis_id`、`query`、`purpose`、`context_level`、`context_reason`、`expected_contribution`；`term_origins` 为可选规划说明，原样保留用于审计。

`context_level` 为目标系统、来源系统或方案类别。首轮建议每 SH 两到四条查询，覆盖目标视角和来源/方案类别视角。数量或视角不足只记录 `advisory`、`reason=missing_initial_perspectives` 和保留数量，已有合格查询继续执行；规划审计传入后续反馈，由模型判断是否补充。反馈每 SH 每轮最多两条，全局最多六十条，继续按 SH 轮转。

`context_level` 只描述检索上下文，不描述证据维度或研究目的。提示词要求把验证、边界测试、可比终点等写入 purpose、expected_contribution 或 query_design。对误填值先恢复合法枚举的大小写、空格及连字符；语义无法直接确定的值，每次 Survey 最多一次批量模型修复、最多 32 条，使用原课题、SH 和完整查询判断三种上下文之一，不把某个维度固定映射到某个系统层级。修复计入共享模型请求预算，保留原值及原因，仅修改上下文字段；成功汇总 recovery INFO，无法恢复的查询记录 warning 并保留审计，其他有效查询继续执行。

来源说明可引用原课题、任一 SH、已返回论文或泛化理由。查询准入不检查逐词来源、原文连续子串、来源词是否出现在查询中、来源 SH 是否等于当前 SH，也不要求所有查询词均被标注。词形变化、同义表达、跨 SH 信息共享和没有来源清单的查询均可通过格式与相关性评分检查。规划来源不是已验证的科学证据。保留完整科学名称，不按词数截断。是否相关由模型结合整个查询及研究任务判断，不因查询包含某个候选别名而直接拒绝。

查询规划输入提供 `search_semantics`，明确 OpenAlex 空格分隔的词默认按 AND 检索；真正的替代对象使用括号与大写 OR，或在既有预算内分开检索。模型区分必要上下文、替代对象和返回后评价条件，每条查询通常保留一个系统/对象/方案类别与一个检索目的。建议英文查询约 5–14 个词，仅作为长度指导；完整名称、必要的直接比较和其他语言不按词数裁剪。代理系统或方案类别查询不同时强制包含精确目标系统。质量、对照、统计方法等要求仅在其构成本条检索目的时加入查询，否则在论文返回后评价。模型返回前复核实际 AND/OR 含义，目的/上下文评分同时考虑是否存在不必要的交集。

可选 `query_design` 保存 `essential_context`、`alternative_groups`、`post_retrieval_criteria` 和 `relaxation_strategy`，仅作语义规划说明，不新增逐词审核或缺字段准入门禁。说明保留到查询审计及反馈历史，有结构化说明的合格查询输出 `Survey query design` INFO。

成功检索但返回零篇时，`metrics.revision_guidance` 按优先级建议减少交集、拆开替代对象或使用 OR、移出可在返回后评价的条件，再保留研究目的并将上下文从目标系统放宽到来源系统或方案类别。后续模型使用 `action=broaden_context`、引用零结果 query ID，并说明放宽的条件；这些改写仍受原有轮数、每 SH 和全局预算限制，不自动展开别名或请求矩阵。请求失败、预算延期或评估不可用不生成零结果改写建议，有效零结果不证明科学上不存在证据。

反馈轮的每条新查询必须带 `action`、非空 `feedback_reason` 和至少一个已有 query、paper、candidate 或 SH ID；缺失项按规划批次汇总为一个 warning。规划输入携带已使用 query ID，若多个并行规划批次仍返回重复 ID，控制器保留原值到 `source_query_id` 并分配唯一内部 `query_id`，不因 ID 冲突丢弃查询。评估批次默认包含 4 篇论文，以降低多 SH、对象和证据字段同时生成造成的输出形状错误。

默认反馈检索中的论文摘要、候选名称、别名和贡献说明按语义评估，不再要求名称或说明逐字出现在标题/摘要中。对象和证据仍绑定真实返回的论文 ID；摘要归纳标为 `model_semantic`，不标为已核验原文引文。维度适用范围、证据角色、最低独立来源和项目排除继续分别判断。旧检索路径和其他阶段原有的原文引文核验保持原有行为。

模型 JSON、字段类型、漏答、重复 ID 或无效评分等格式问题只记录 warning。规划、评估和候选确认都要求顶层 JSON 对象；评估阶段兼容论文数组、单篇对象、按论文 ID 组织的字典，以及有限层数的 `results/data/assessments/paper_assessments` 等明确包装，统一恢复为 `{"papers": [...]}`。单篇记录的 `assessment/evaluation/result` 包装也可恢复。成功恢复只输出批次级 recovery INFO。无法恢复的顶层响应只输出一个上游 response warning；由此产生的论文、SH 和图角色缺项仍完整保存到 `format_normalization_audit`，但不再在终端逐条重复 warning。无效项跳过，有效项继续。首轮没有可执行查询时，在原有反馈轮数和模型预算内重新规划；最终仍无种子时返回空结果和不足状态，跳过依赖论文的阶段，不抛出“无种子”异常。格式容错不生成虚构论文、评分或证据。

论文评估统一使用 `canonical_paper_id` 关联，OpenAlex 的 `W123`、大小写变化以及 `openalex.org` / `api.openalex.org` 的 Work URL 视为同一身份；输入论文的原 ID 保留。明确的 `paperId/openalex_id/id` 字段可恢复身份，但不同字段或字典键与内部 ID 真正冲突时不猜测。只依赖明确身份关联，不按论文位置或相似标题分配评分。完全相同的重复评估合并；冲突重复保留不足状态，其他论文继续处理。

每批输出 `Survey assessment alignment` INFO，包含 expected、returned、matched、missing、conflicting 和 unexpected 数量。`subhypothesis_retrieval.json` 的 `assessment_alignment_audit` 保存预期/返回原 ID、规范 ID、原返回记录位置、匹配状态、包装路径与原始解析响应；无效 JSON 保存原响应文本。每篇论文通过 `survey_assessment_alignment` 指向所属批次及返回记录。每批处理结束还追加写入运行目录的 `survey_assessment_alignment.jsonl`，连同格式诊断一起保存，便于后续阶段中断时排查；落盘失败只警告一次，继续在内存和最终检索产物中保留诊断。这些审计数据不进入反馈规划提示词。

同批的论文漏答、未知 ID 和冲突身份汇总为一个 `assessment_alignment_incomplete` 根因，派生的 SH/图角色缺项带 `derived_from` 保存在审计中。单个 SH 缺答或结构失败也按对应论文和 SH 聚合；已成功关联的其他论文或 SH 的真实字段问题仍单独记录，不因某篇漏答而隐藏。缺失或冲突评分保留未知状态，不转换成零分或负面科学证据。

评估提示词明确数组元素及字段类型，槽位贡献统一为 `[{slot_name, support_level, reason}]`；`slot_name` 来自当前 SH 的 `slot_recovery_tasks`，`support_level` 为 `direct/partial/indirect/none`。解析器恢复单对象、按槽位键组织的字典、明确的 `槽位:支持级别` 字符串以及常见字段别名。只有槽位名、缺少支持级别的字符串不猜测级别，保留到 `unresolved_slot_contributions`；冲突身份、未知槽位和无效级别同样保存原始值及原因。

成功恢复仅输出批次级 `Survey format recovery` INFO。实际丢弃或未能完成的评估按批次输出一条 `Survey format warning`，详情携带论文 ID、SH、字段和具体缺项；终端最多显示八个问题样例，其余完整记录在 `subhypothesis_retrieval.json` 的 `format_normalization_audit`。论文记录同时保留本次 `format_issues`，后续有限补评估仍使用原预算。成功恢复不触发额外模型或网络请求。

相关性评分在准入前恢复明确的 0–5 整数表示，包括 `"4"`、`4.0`、`"4/5"` 和单字段包装 `{"score": 4}` / `{"value": "4"}`。项目评分允许明确同义字段 `project_relevance_score`、`relevance_score`；SH 评分允许 `sh_score`、`semantic_score`、`relevance_score`，候选确认的 `sh_score` 允许 `semantic_relevance_score`、`sh_relevance_score`。同时出现多个评分字段时必须有效且一致，否则保留未判定状态；不使用 confidence、百分比或文字等级推算相关性，不对小数取整或越界评分截断。原始论文/SH 评分保存为 `score_fields_raw`，无法恢复的评分进入完整审计；缺失、null、布尔值和冲突评分不会变成零分。查询评分和候选确认使用相同的数值恢复规则，准入阈值保持原值。

模型输出整数评分：F 为课题与 SH 契合度，P 为检索目的清晰度，A 为上下文辨识度，均为 0–5。

`Q = 20 × (0.5F + 0.25P + 0.25A)`。

准入要求 `Q ≥ 75`、`F ≥ 3`、`A ≥ 3`，同时必要结构有效。裸属性与歧义缩写应得 A≤2；辨识度清楚的系统、对象或方案类别至少 A=3。评分来自语义判断，程序验证格式和数值，不能替代人工相关性标注。

## 论文与对象

论文项目分 r_p 和 SH 分 r_ps 均为整数 0–5：0 无关/排除；1 仅词汇重合；2 背景但无可指出贡献；3 合理部分贡献、代理或探索；4 明确方法、机制、比较或反证贡献；5 具体关键贡献。反证和可迁移方法可获高分，必须记录边界及原文摘录。

候选发现要求真实论文身份和有内容的语义依据，来源不必已经达到最终证据准入要求。每个论文–SH 评估与候选确认增加 `evidence_boundaries`，分别保存 `discovery_relevance`、`local_contribution`、`target_validation`、`ranking_evidence`、`exclusion_basis` 和 `validation_gaps`。候选记录将其保存到 `candidate_evidence_boundaries_by_subhypothesis`，来源摘要、反馈规划、确认缓存、冻结台账和 Survey→Idea 的精简交接均保留这些字段，不增加模型调用。精简交接同时保留 `ranking_readiness_by_subhypothesis` 中的缺失维度与排名资格，不改变下游算法。

局部贡献要求已完成评估、有来源依据、没有实际排除或语义无关。明确的 `local_contribution=supported` 可以支持部分方法、机制、比较原则、来源系统信息或反证；缺少新字段的旧响应兼容 SH 分≥3 的语义。项目总分不再否决合格的局部贡献。仅确认身份的 `identity_only` 可以支持候选发现，不能单独成为有局部贡献的种子或有效维度证据。每个维度仍独立要求适用范围、证据角色、最低独立来源与来源依据，不把候选身份转换成效力证据。缺摘要、漏答、无效评分或缺少正向依据记录 `uncertain` 或 `assessment_unavailable`，分数为 null；可用摘要的暂时漏答仍仅允许一次补评估。

候选项目分 g、SH 分 s 的优先级仍为 `R = 20 × (0.6g + 0.4s)`。完成确认且没有实际无关判断的对象，R≥70 为 `relevant`，其余保留为 `exploratory`；不再因任一分数低于 3 自动判为无关。显式的语义无关仍为 `irrelevant`；旧响应在两个分数均为 0–1 且没有正向边界判断时保留原无关语义。未能判断/未提交分别为 `assessment_unavailable`/`deferred_budget`。角色继续独立：高相关背景或机制对象保留原角色，不自动激活为待比较方案。

`candidate_source_evidence_by_subhypothesis` 独立保存来源状态、论文 ID、项目/SH 评分、边界和原因：`eligible`、`insufficient_evidence`、`assessment_unavailable`、`source_relevance_conflict`、`excluded`。来源不足不改写角色。`candidate_admission_by_subhypothesis` 中的 `evidence_supported` 或 `discovery_only` 可获得有上限的调查机会；辅助对象为 `auxiliary`，角色未明确为 `role_unresolved`。实际无关或明确排除的全部来源仍阻止激活；存在可用来源时继续调查。若结构化 `exclusion_basis=insufficient_evidence` 却同时返回排除/无关标记，恢复为证据不足，保留原标记并按批次记 recovery INFO。缺少摘要的旧 `excluded=true` 不自动成为已确认排除；可判定的实际排除继续保留。

最终排名另存于 `ranking_readiness_by_subhypothesis`，记录缺失维度、目标验证状态、待验证条件和比较资格。模型声明 `ranking_evidence=sufficient` 不能跳过证据矩阵；声明不足时保留缺口。排名还需要必需维度满足独立来源要求、存在非纯负向证据以及同类同层级的比较对象。没有目标直接证据时记录 `indirect/not_reported/unknown` 和待验证条件；需要直接目标证据的结论仍必须满足对应维度，代理证据不能代替。全局最佳候选结论继续受发现覆盖与比较充分性约束。

查询反馈增加 `contribution_outcomes` 原因计数：`identity_only`、`target_validation_gap`、`ranking_evidence_gap`、`insufficient_evidence`、`irrelevant`、`explicit_exclusion`、`assessment_unavailable` 或局部贡献。`useful` 统计可用局部贡献，`returned_unique` 单独统计检索命中。低收益不等于零命中，也不直接淘汰候选。身份线索不足时保留对象补方法/机制，目标验证不足时放宽精确目标上下文，排名不足时寻找可比终点/对照；实际无关噪声才建议收窄辨识上下文。`revision_guidance` 保留具体原因与优先级，原有轮数和预算继续约束执行。

SH 分解从用户的研究决策和不确定性出发，区分已有文献能提供的局部依据与未来实验应验证的结果，不预设精确目标上已有获胜方案。直接目标与可比终点要求只用于需要它们的结论，不成为所有发现槽位的准入要求。提示词修订号进入分解缓存指纹，避免重用旧规则生成的 SH。

论文种子资格由项目/SH 相关性、语义依据和明确排除独立判断，不受 `recommended_graph_role` 限制。图角色允许 `evidence_seed`、`exploration_seed`、`context_seed`、`do_not_expand`、`undetermined`；缺失或未知值恢复为 `undetermined`，保留 `recommended_graph_role_raw` 和 `graph_role_assessment_status`，缺项按批次 warning，常见格式恢复按批次 INFO。有效的 `do_not_expand` 不等于种子拒绝。只有合格 SH 明确推荐 `evidence_seed` 或 `exploration_seed` 时才扩展引用图；其余选中论文进入上下文种子并正常阅读。多 SH 论文只采用满足种子相关性要求的 SH 推荐，避免无关 SH 扩展图。

每 SH 激活最多三个候选，先保留高相关性主方案和同分类层级的独立 challenger。剩余查询机会按 SH 轮转分配，已有基础合格证据或已完成候选查询可满足已有机会。其余候选为 `relevant_holdout`。冻结后 Idea 的主根/challenger 必须激活且有选中种子来源；holdout 继续保留在全体相关候选分母。

## 预算

反馈查询的 `action`、`feedback_reason`、`feedback_references` 必须放在每条 `queries` 记录内。提示词给出完整 JSON 示例；`decisions` 使用 `query_ids` 明确关联新查询。当字段缺失时，先从同一个模型子批次、同一个 SH 中唯一关联的决策恢复有效字段；历史输出理由中明确提及查询 ID 也可用于关联。此关联只处理记录身份，不判断科学相关性。保留原始查询和恢复后的查询，不将未知动作（例如 `cover_gap`）自动映射为确定动作。

仍有歧义且满足基本查询要求的项可进入结构修复：默认每次 Survey 最多一次模型修复请求、最多十二条记录，计入共享模型请求预算，并受相同输入上限约束。修复仅补反馈字段，不能改写查询、评分或身份；有效历史引用仍须核验。无法恢复、重复修复记录、超额或预算不足的项保留缺口；反馈缺项汇总 WARNING 保存全部原始记录，成功恢复汇总 INFO。`Survey planning outcome` 区分 `no_queries_proposed`、`response_unavailable`、`all_queries_rejected_by_feedback_contract`、`all_queries_filtered` 和 `queries_admitted`。格式拒绝导致无检索执行时，不再将最终停止原因标为 `no_information_gain`。

| 配置 | 默认 |
| --- | ---: |
| `survey_initial_queries_per_sh` | 3（首轮允许 2–4） |
| `survey_queries_per_sh` | 60（全局上限与轮转仍约束总量） |
| `survey_logical_query_limit` | 60 |
| `survey_feedback_rounds` | 2 |
| `survey_query_workers` | 4 |
| `survey_results_per_query` | 32（代码入口硬上限） |
| `survey_paper_assessment_batch_size` | 4 |
| `candidate_relevance_batch_size` | 24 |
| `survey_active_candidates_per_sh` | 3 |
| `survey_http_attempt_limit` | 120 |
| `survey_primary_http_limit` | 96 |
| `survey_retry_fallback_http_limit` | 24 |
| `survey_model_request_limit` | 80 |
| `survey_prompt_input_limit` | 120000（按请求入口同一编码器计数） |
| `survey_planning_batch_limit` | 64（每轮，共用模型请求预算） |
| `survey_planning_workers` | 10（查询规划与反馈批次并行上限） |
| `survey_feedback_repair_limit` | 1（每次 Survey 的结构修复模型请求次数） |
| `survey_feedback_repair_item_limit` | 12（单次修复记录上限） |
| `max_seed_paper_num` | 18（反馈路径硬上限） |
| `min_seed_papers_per_sh` | 2 |

逻辑检索机会、不同请求、实际 HTTP 尝试、缓存命中与实际模型请求分别计数。缓存不消耗 HTTP，但模型重复提出的工具机会仍有预算。相同 provider/query/filter/sort/result-limit 的请求在本次运行合并，SH 来源独立保留。

文献 HTTP 预算只统计 OpenAlex 带 query 的论文搜索，包含该搜索的重试和重定向；总上限 120，默认 primary 96、retry_fallback 24。论文详情、DOI 解析、批量元数据、参考文献和被引关系、下载解析，以及其他文献数据源请求均不扣该预算，预算耗尽后这些操作仍可执行。标题回退若实际执行 OpenAlex query 搜索，仍计费。所有请求继续遵守原有速率、超时与重试上限。预算快照使用 `http_budget_scope=openalex_query_search_only` 标识口径。模型在实际 `requests.post` 前使用独立模型预算计费，内部重试和并发线程共享八十次上限。

发出检索批次前预留 `ceil(查询数×10/8)` 个论文评估请求，并独立保留一次反馈请求。预留容量不能被其他请求重试抢占；预算不足减少当前批次，未执行查询记录延期。停止后释放未使用容量，关闭的请求作用域阻止超时线程继续发起新尝试。

六个 SH 首轮最多十八条查询、返回最多一百八十条原始记录；全程逻辑上限为六十条、六百条原始记录。两轮反馈、每轮每 SH 两条的规则通常会提前停止，不保证用满上限。这个上限与登记对象数量及证据维度数量无关。

## 输入预算和不足状态

反馈输入只保留决策所需的 SH 合同、论文摘要与评估摘要、候选身份与相关性、证据矩阵缺口；不回传重复的完整查询 lane、候选注册内部结构和整套上下文。长字段带显式截断标记，原始数据保留在 Survey 产物中。论文、对象和矩阵记录轮转装入多个完整 JSON 批次，各批共享研究问题、SH 和预算，返回的查询合并后继续接受原有去重、每 SH 每轮限额和全局限额。其他模型输入超过上限时也按字段结构缩减，避免直接切坏 JSON。

输入上限取 `min(survey_prompt_input_limit, llm_max_context_length - 16000 - 1024)`，为输出和批次标记保留空间。计量使用请求入口的编码器；Qwen 默认 `utf8_bytes` 回退按 UTF-8 字节估算，日志中的 tokens 并非模型实际 tokenizer 的精确计数。分批模型请求计入现有八十次预算，超出每轮批次或剩余预算的部分标为延期，不无限追加请求。`prompt_budget_audit` 保留各批次大小、论文和候选 ID，以及延期范围。

Survey 通用批量模型调用使用 `APIInfo.batch_chat_agent_worker: 10`，论文与对象评估、候选相关性确认和相关度评分等独立请求最多十路并行。同一轮规划批次统一提交给现有 `batch_remote_chat`，使用 `survey_planning_workers: 10`，空闲 worker 接续处理后面的批次。调度前根据模型剩余预算限制提交数，并统一预留批次容量；实际请求和内部重试仍共享模型预算。结果按输入批次顺序合并，查询去重、SH 每轮限额和检索全局限额保持原规则。单批响应缺失或格式错误只记录批次诊断，其他有效响应继续处理。进度条显示整轮总批次数；日志显示 `Survey planning dispatch: ... batches=14 workers=10`。全文分析仍遵守独立的总输入量限制，可实际并发的请求数取决于每批长度。

空种子时写入 `survey_status.json`，保存 `insufficient_evidence`、停止原因和检索诊断指针。顶层 science 工作流返回 `PARTIAL`，Survey 尝试保留未完成状态与 `outcome=insufficient_evidence`，下游阶段保持待处理；不会验证不存在的成功 manifest 或伪造成功 handoff。

## 反馈指标

对查询返回的去重论文数 m，有效 SH 评估数 a，SH 分≥3 的论文数 u，此前未收集的相关论文数 v：

`P_q = u/a`，`A_q = a/m`，`N_q = v/m`。

分母为零报告 null。网络失败单独报告；有效空结果可提示放宽上下文。a≥5、A≥0.8、P<0.3 提示收紧；P≥0.6、N<0.2 提示转向未覆盖问题。评估不足先补评估。模型必须以已有查询、论文或候选 ID 说明 `narrow_scope`、`broaden_context`、`resolve_name`、`compare_alternative`、`seek_counterevidence` 或 `stop` 的理由。

SH 种子覆盖 `C_SH = mean(min(n_SH/2,1))`，n_SH 是实际选中且相关性合格的独立论文数。种子优先分 `U = 20 × (0.4r_p + 0.6max(r_ps))`，先为各 SH 保留主方案和 challenger 来源，再满足 SH 配额、补充其他激活候选与高分论文。未达配额输出缺口，不降低分数或自动扩大十八篇上限。

种子保留模型判定的图扩展角色：相关的 `do_not_expand`、`context_seed` 和 `undetermined` 论文均可进入种子配额，同时不扩展引用图。共享 DOI 等可靠身份的论文只计一次，不重复出现在不同来源记录的种子角色列表。补评估后候选和维度证据必须读取论文最新的项目/SH 排除状态，历史合格记录不能覆盖最新排除结论。

激活机会覆盖 = 已满足基础证据或完成候选检索的激活候选—SH配对数 / 激活配对数。

全体基础证据覆盖 = 满足基础维度最低独立来源要求的相关候选—SH配对数 / 全部相关配对数，包含 relevant_holdout。

相关性评估完成率 = 有有效判定的已提交对象—SH配对数 / 已提交配对数；未提交与未判定配对数同时单独报告。基础维度采用合同优先级和直接观察/比较角色，避免任意取矩阵第一行。

有效证据熵和 Gini 保留原登记表算法。同一独立论文覆盖 k 个候选时各计 1/k。熵低用于审计集中程度，不触发为了均匀而搜索。检索机会与科学证据充分性分别报告，`seed_pool_ready` 不等于全部候选证据充分。

## 停止、产物与日志

论文—SH 关联和证据覆盖台账按 SH 合同生成，不再要求检索策略为旧的 `slot_driven_required_slot_recovery`。`model_feedback` 使用已保存的 `sh_semantic_assessments` 和槽位贡献建立被动证据台账，不生成额外查询；缺少有效评估或仅有部分/间接支持时保留缺口，不能以查询命中或关键词匹配补成直接证据。缺失任务元数据的 required slot 仍保留在台账中。

写作入口遇到历史台账缺少 SH 报告时，利用同项目检索产物的候选论文语义评估重建缺失报告，保留已有报告。无法恢复的槽位输出不足状态；缺失报告和无合同报告的 ID 汇总记录 warning，并在 `survey_evidence_plan.json` 的 `coverage_ledger_recovery` 中保存恢复来源及 SH 列表。恢复不发起模型或文献网络请求，项目身份和证据范围约束继续生效。

引用图更新分别记录种子 ID 解析、节点存在、详情获取和各方向关系获取状态。详情与关系请求独立处理，关系请求失败保留已获取的标题、摘要及节点；详情缺失或获取失败的根只记录 warning，跳过其图扩展并保留原种子证据。扩展深度为零的根保留元数据，不参与邻居筛选。更新函数只返回实际存在且允许扩展的根，筛选函数再次检查节点存在性；全部根缺失或没有可用邻居时返回空扩展结果，不加载嵌入模型，并清除本次扩展临时结果。

状态保存在引用图缓存的 `seed_update_statuses`，启用 SH 溯源时也写入 `sh_graph_provenance.json` 的 `graph_seed_update_statuses`。`failed`、`unavailable`、`skipped_missing_node` 和 `skipped_depth_limit` 分别保留；关系接口返回空列表记录为 `returned_empty`，不据此认定没有相关文献或生成负证据。日志 `Graph seed update` 汇总 resolved、present、eligible_for_expansion、missing 和 incomplete_relations，避免把全图节点数当成本轮种子全部入图的证明。

终止原因包括 `seed_pool_ready`、`query_budget_exhausted`、`http_budget_exhausted`、`model_budget_exhausted`、`no_information_gain`、`provider_unavailable`、`feedback_round_limit`、`model_stop`、`query_plan_unavailable`。连续两轮没有新增相关论文、候选或合格证据可停止；持续请求失败不能记为有效空结果或负证据。

`subhypothesis_retrieval` 保留查询历史、来源、评分、准入审计、失败/延期、种子、被动证据矩阵、比较范围、预算和冻结登记表。handoff 保留数值相关性、角色、active/holdout、机会状态、选中根来源和覆盖指标，通过来源指针访问完整查询历史。

示例日志格式（非实测效果）：

```text
Survey search plan: SHs=6 initial_queries_per_SH=3 logical_limit=36 http_limit=60 model_limit=80.
Query feedback: SH=SH2 query=SH2.q1 returned=10 assessed=10 useful=2 precision=0.2 novelty=0.2 status=success.
Object relevance: registered=120 active_pairs=3 relevant_holdout_pairs=117 assessment_completion=1.0.
Survey search stop: reason=query_budget_exhausted logical_calls=36/36 http_attempts=31/60 metrics=...
```

## 验证与校准

定向测试使用合成模型和受控传输，验证完整查询准入、多 SH 轮转、对象数量不扩大矩阵、相关性前置、补评估、缓存失效、失败状态、实际模型重试/线程计费、HTTP 重试/元数据共享预算、种子硬上限、holdout 分母和 handoff。

离线校准使用已检索且人工标注的论文—SH及对象—SH配对，按课题划分校准/验证集。`calibration_metrics` 返回 TP、FP、FN、Precision=TP/(TP+FP)、Recall=TP/(TP+FN)，零分母为 null。精确率0.85、合理代理与替代候选召回率0.80只能作为验收目标；当前没有人工标签支撑这些实测成绩，也不能据此宣称候选空间完整。
