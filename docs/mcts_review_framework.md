# MCTS 节点、审查与交付契约

MCTS 将科学候选、审查覆盖、任务要求和运行依赖分别记录。搜索保留尚待验证的候选；只有通过当前任务验收的候选才能标为 `ready`。这些接口不包含某个研究课题的专用判据。

## 改动与验证映射

| 要求 | 主要入口 | 验证的不变量 |
| --- | --- | --- |
| 完整科学状态与版本 | `agent/mcts.py:IdeaState`、`utils/mcts/review_contracts.py`、`utils/prompting/review_packets.py` | 长方法的尾部、证据和假设完整保存；科学符号保留大小写；内容变化使签名和审查缓存失效 |
| 可定位的问题记录 | `review_contracts.py:ReviewIssue/reconcile_issues`、`mcts_runtime.py:simulate_node_value/expand_node_with_skills` | 遗漏旧问题不能关闭；只有实际复查才能解决；下一轮收到问题、用户要求 ID 和评语 |
| 独立任务提取 | `utils/core/run_inputs.py:_extract_task_contract`、`task_contract.py`、`run.py`、`MemoryGuidedMCTS.prepare_root_context` | 原始请求保留；主题识别成功也要独立提取；manifest 绑定主题后提取；失败状态与确认空清单不同 |
| 类型化检索与前置条件 | `utils/mcts/retrieval_contracts.py`、`MemoryGuidedMCTS._instantiate_skill_plan/_retrieve_references` | 缺索引、执行异常、无命中、预算耗尽分别记录；必需证据缺失时跳过；探索生成不声称有文献支持 |
| 按贡献语义判断漂移 | `scientific_intervention_ontology.py:detect_profile_drift` | 多义关键词只产生信号；合理跨领域工具可以继续探索；有任务边界依据的主要贡献替换才能确认为漂移 |
| 主张与证据关联 | `utils/workflow/claim_evidence.py`、`utils/mcts/review_execution.py` | 来源存在、可读、引句匹配和语义支持分开；证明不能引用主张自身充当推导；汇总不能凭空增加支持或换绑引用 |
| 明确修改范围与依赖 | `review_contracts.py:apply_field_updates/dependency_rechecks`、`mcts_runtime.py:materialize_child_state` | 父哈希必须匹配；未修改字段精确继承；空值可显式清空；机制变化触发支持关系复查 |
| 价值、收益与交付分开 | `review_contracts.py:transition_reward/delivery_assessment`、`mcts_runtime.py:best_candidate`、`MemoryGuidedMCTS.search` | 高分探索候选可保留；技能按操作带来的改善记分；已验收候选优先；无合格候选时显式返回 `partial`；停滞时换动作或结束 |

上述 Python 路径除 `run.py` 外均相对于 `src/agents/idea_agent`。主体回归位于 `tests/test_mcts_review_framework.py`，入口验证位于 `tests/test_idea_run_inputs.py`，并由现有 Idea Agent、gap 调度、Survey manifest 和持久化测试补充覆盖。

## 完整快照与提示词视图

`IdeaState` 保存完整文本、组件解释、学科列表、假设契约、`claims` 和 `evidence_records`。状态构造不按提示词长度截断方法或证据。单个快照最多 **4 MiB UTF-8 JSON**，超限显式报错，大材料应按引用存储。结构不合法的主张和证据记录显式报错，避免在规范化时静默丢弃；搜索拒绝不合法的子候选并保存 `invalid_candidate_contract` 运行事件，继续处理其他算子。

`scientific_content()` 列出参与内容身份的字段，排除访问次数、问题状态、检索日志等运行诊断。`IdeaState.signature` 对规范 JSON 生成 SHA-256。缓存键另外包括任务契约、证据版本、审查规则版本、上下文、模型和提示词预算配置。

选择与路由继续使用紧凑视图。科学审查使用 `build_review_packets()`，逐项传输完整字段，并返回：

```json
{
  "included_paths": ["method", "claims[0]"],
  "omitted_paths": ["evidence_records[0]"],
  "partial_paths": [],
  "content_hash": "..."
}
```

长字符串可拆成多个片段；单个片段不算已完整看到该字段。超过一个包时，另做有界的一致性汇总。某项审查必须共同看到主张、对应证据和可信来源才能给出支持判断；无法共同看到时保持 `unassessed`。汇总只能沿用已核查的正面判断及其引用，不能增加未经原始审查的支持。

## 任务要求与问题生命周期

任务契约保留 `original_request` 和 `extraction_status: complete|partial|failed`。每条要求包含稳定的 `requirement_id`、`source_quote`、`requirement_kind` 和 `acceptance_description`。引文必须来自原始请求；单独配置的显式 refinement scope 保留其配置来源。引文匹配只能核验要求来源，验收解释是否准确仍依赖模型审查。

`task_mode` 用于调整搜索策略，实际交付按 `required_deliverables` 和 `user_constraints` 检查。背景前提保存在 `problem_premises` 中。原始文本、显式 topic、Survey manifest 和直接 MCTS 入口采用同一提取接口；已有完整任务契约可直接传递。提取失败后进行有限重试，然后携带原文与未完整解析状态继续搜索，交付资格保持 `partial`。

问题记录包括：

```json
{
  "issue_id": "issue:...",
  "kind": "validation_gap",
  "origin": "candidate",
  "target_path": "claims[0]",
  "claim_id": "claim:...",
  "requirement_id": "req:...",
  "status": "open",
  "rationale": "The prediction has no discriminating validation path.",
  "evidence_refs": ["claims[0].validation_plan"],
  "repair_hint": "Specify an observation that separates the alternatives.",
  "rechecked": false
}
```

`candidate` 表示候选内容问题，`context` 表示审查材料不足，`dependency` 表示来源或能力缺失。兼容字段 `detected_defects` 从仍开放的 candidate 问题派生。每个子节点收到父节点问题及未满足、未审查的任务要求；技能历史反馈也进入下一轮计划。

未被本轮提及的问题保持原状态。关闭问题需要明确复查、理由和实际可见的引用。程序生成的结构问题带有内部 `checker`；模型不能自行声明已完成程序检查。主张问题以稳定的 `claim_id` 跟踪，重排列表不会移除问题；程序核实补齐或删除对应主张后才能关闭。

## 检索能力与证据政策

`RetrievalResult.status` 有五种值：

| 状态 | 含义 | 后续处理 |
| --- | --- | --- |
| `success` | 有符合筛选条件的命中 | 将实际检索来源放入可信来源目录，再审查主张支持 |
| `no_hits` | 当前查询或筛选条件下没有合格结果 | 有备用查询时换查询，保留证据获取请求 |
| `unavailable` | provider、索引文件或依赖缺失 | 记录能力不可用，跳过依赖该能力的必需证据算子 |
| `error` | 查询生成或工具执行失败 | 有界重试，记录失败原因 |
| `budget_exhausted` | 本次搜索检索调用预算用尽 | 停止继续调用，保留证据获取请求 |

索引预检只检查本地文件，不初始化 embedding。`CapabilityState` 保存可用能力、失败事件和 `acquisition_requests`。这些请求是可追溯的待办记录；本次实现不会自动构建索引、下载模型或调度外部采集任务。

图谱的结构化入库、补充抽取队列、版本化索引构建、来源核验及运行时重新加载见 [paper_graph.md](paper_graph.md)。跨域候选按预算扩大窗口，并在领域/分数筛选后审查结构、假设和边界条件。`paper-graph check` 与 `doctor` 检查真实资源状态。

算子通过 `required_capabilities` 和 `evidence_policy` 声明条件。内置 `mechanism-commit-innovation` 使用 `paper_graph`，允许 `exploratory`；`theory-transfer-injection` 默认 `required`，需要合格的跨领域文献节点。自定义算子声明 `paper_graph` 后也走相同检索与证据检查。其他能力尚无默认适配器，运行时会记录未注册 provider 并跳过依赖它的必需算子。

探索模式会把检索状态和“缺少 grounding，生成内容仍为待验证假设”的要求写入生成提示词及节点元数据。基础设施受限的转换不更新科学技能先验；候选内容仍接受独立科学审查。缺来源的事实性主张会形成 dependency 问题；有验证路径的假设可以保留探索价值。

## 主张、来源与支持

主张类型包括 `user_premise`、`literature_fact`、`design_choice`、`hypothesis`、`prediction`、`observation`、`formal_derivation`。`support_refs` 指向 `evidence_records` 或运行中提供的来源 ID。候选自行声称来源已验证不能建立可信来源。

程序分别记录 `source_exists`、`readable`、`quote_matches` 和 `locator_supplied`。`locator_supplied` 只说明提供了定位信息，不等于已核对页码或段落位置。语义支持单独使用 `support_assessment`，不能从“找到引用”直接推导为 supported。

用户前提需要原请求中的准确 `source_quote`，改写后的前提还需要语义审查。假设和预测需要验证计划。形式推导需要假设、推导和证明义务，支持判断必须引用实际推导。因果或测量主张额外提供 `measurement_link`：`construct`、`observable`、`linking_argument`、`conditions`，并单独审查连接是否成立。

`evidence_basis` 保持兼容；只有旧文本、尚无类型化主张关联时，系统保留待审查问题，不把这段文字当作已获文献支持。

## 修改、收益与最终交付

生成优先返回 delta：

```json
{
  "parent_content_hash": "...",
  "field_updates": {
    "scientific_intervention.hypothesis_contract.discriminating_observation": "...",
    "claims": [],
    "evidence_records": []
  },
  "rationale": "..."
}
```

未改字段由程序从完整父快照继承；显式空值清空字段。父哈希不匹配则拒绝应用。分包生成只允许编辑当前完整可见的路径；旧式全量返回只有在完整看到父候选时才接受。每次修改记录 `changed_paths` 与 `dependency_rechecks`。机制、研究对象或干预改变后，相关证据、判别观测、适用范围及主张需要重新检查。

树回传继续使用候选质量。技能先验使用相对于本次实际父节点的改善，包括问题修复、要求满足、有效支持的增加和退化；重复转换不重复记功。停滞跟踪忽略只改标题的变化，默认在连续 12 轮无进展时结束，在中途轮换动作。

`best_candidate()` 优先选择可交付候选；另保留按分数选择的 `best_available`。`delivery` 检查任务提取完整性、用户要求、重要问题、审查覆盖和当前内容哈希。没有合格候选时返回 `partial`，同时输出 `unresolved`、`operational_events`、`acquisition_requests` 和 `stop_reason`。

Debate、synthesis 和最终 introduction / algorithm / scientific_spec 生成只要改写科学内容，就撤销旧的 ready。**当前最终 materialization 后没有自动科学复审**，新增内容以 `partial` 交付，工作流状态为 `degraded`；原审查快照和问题记录继续持久化，Experiment Agent 交接也保留此状态。下游应检查 `delivery.delivery_ready`，不能仅凭搜索分数或 JSON 生成成功判断已验收。

## 默认预算与离线验收

| 配置 | 默认值与范围 |
| --- | --- |
| 快照大小 | 4 MiB，超限显式失败 |
| `mcts.review_prompt_token_budget` | 48000；使用 UTF-8 字节数作为保守 token 上界，前缀和上下文共同计入 |
| `mcts.max_review_packets` | 32 个初审包；一致性最多 4 层，每层最多同样数量的包 |
| `run.task_contract_max_attempts` | 2 次，限制在 1–3 次 |
| `mcts.retrieval_call_budget` | 每次搜索 32 次 |
| `mcts.retrieval_max_attempts` | 每次查询过程 2 次，限制在 1–3 次 |
| `mcts.stagnation_patience` | 12 轮，最小 2 轮 |

默认预算限制总调用数量和提示词输入，不保证所有大型候选都能完整审查。包预算、上下文预算或一致性预算不足时返回覆盖信息与 `partial`。

可复现的离线回归命令（仓库根目录，使用已有虚拟环境）：

```bash
.venv/bin/python -m pytest -q \
  tests/test_mcts_review_framework.py \
  tests/test_idea_task_contract.py tests/test_idea_run_inputs.py \
  tests/test_gap_search_orchestration.py tests/test_gap_search_schedule.py \
  tests/test_discipline_taxonomy.py tests/test_idea_cli_survey_manifest.py \
  tests/test_survey_idea_loader.py tests/test_idea_introduction_json.py \
  src/agents/idea_agent/tests
.venv/bin/python -m compileall -q src/agents/idea_agent
```

回归使用合成科学任务、本地 fixture 和 mock chat，验证状态及调度不变量。科学论证的语义判断仍依赖模型；这些测试不证明真实文献检索质量、机制正确性或实验可重复性。部署环境缺失的论文组件索引仍需从实际数据构建或恢复。
