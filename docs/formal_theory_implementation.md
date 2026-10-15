# Mathematical theory implementation

## 全局数学对象管理

`formal_object_registry.py` 为 Resolver、Skeleton 和 Target Proof 提供统一入口：
`build_registry`、`project_group_context`、`commit_group_delta`、
`resolve_reference`、`rewrite_live_references`、`inspect_dependency_graph`。
注册表区分对象的规范 ID 与数学符号，保存单位、条件、作用域、上游变量、
负责人、版本、历史 ID 和符号别名；来源与科学状态保留在活动记录中。
注册表不赋予数学结论“已验证”状态，也不要求候选证明逐步引用证据卡。

Resolver 在生成前复用原有 `V → D` 映射预登记主定义，并登记 `owner_group`。
组调度根据显式变量依赖和跨组 claim 共享情况优先处理公共对象，不包含课题专用物理量。
各组读取全局简表、本组与依赖详情；LLM 请求仍最多并行 3 个。
每轮结果由主线程按固定组顺序提交，下一轮读取更新后的注册表。
Skeleton 保留每组最多 24 个定义，压缩重试和子组恢复的结果同样统一提交。
已有对象因容量省略详情时标为 `context_only`；确实不存在的对象标为 `missing`。
新增局部 ID 的名称空间分配具有幂等性，已有规范 ID 持续复用。

组输出兼容旧集合以及可选的增量：

```json
{
  "object_delta": {
    "reused_object_ids": ["D1"],
    "updated_objects": [],
    "new_objects": [],
    "proposed_aliases": [],
    "dependency_updates": []
  }
}
```

`new_objects`、`updated_objects` 使用 `{collection, record}`；别名建议使用
`{alias_id, canonical_id, reason}`，依赖补丁使用 `{record_id, depends_on, premises, assumption_ids}`。
已完成对象的定向更新与未完成对象补齐分别处理；条件或作用域不同的对象可以独立存在。
不确定的相近对象只向 LLM 提供两个候选及最多 8 个直接消费者，支持合并、保持独立与局部修改。
证明新增的定义、关系、假设、引理通过相同提交入口，消费者的 ID 绑定和表达式同步改写。
全局符号变化保护量词、嵌套绑定和证明步骤局部变量，历史审计原文不参与改写。

依赖分为明确声明、已解析别名和推测相关对象。符号或变量关联只用于选择上下文，
不会直接制造证明前提或构造依赖边。缺失引用保留在草稿和诊断中；循环按强连通分量记录。
验证快照和修订提示词可包含相关上下文，但可执行验证任务只使用明确绑定的依赖与全局假设。
相关定义的条件不会自动加入证明约束，其循环状态也不会阻塞无明确依赖的目标。
计算步骤的局部结果名称与数学对象 ID 分开解析，避免将矩阵计算中的局部 `ref` 当作缺失定义。
默认在 Skeleton 后尝试一次局部修复（`planner.max_cycle_repairs`，最多 3 个分量）。
未解决循环继续保留为待研究定义，不作为已成立的证明前提；局部机器验证分别记录依赖就绪状态。

日志按 `raw_group_output`、`identity_unified`、`dependency_recovered` 区分三个时点，
记录缺失定义、缺失前提、歧义绑定、循环分量和受影响目标。
Resolver 在字段规范化、跨组过滤和局部 ID 改写之前记录原始响应中的可解析对象与引用；
补充轮次分别保留原始诊断，缓存重放仍输出这些诊断。紧凑响应中尚未展开的定义
只在后续规范对象图中统计，不将规范化后的数字冒充原始输出统计。
`missing_variable_reference_count` 仍只代表变量引用检查，不能表示整个数学依赖图完整。

Resolver 的关系使用 `depends_on` 保存对象 ID，文字前提保存为 `conditions`。
兼容旧 `premises` 时，引用与已有依赖合并，文字与已有条件合并，原字段存入
`format_originals`；无法解释的项目保留编码诊断，不静默删除。
原始图诊断分别统计 `textual_premise_count` 和 `uninterpreted_premise_count`，
文字条件不冒充缺失对象 ID，未声明的 ID 仍计入缺失依赖。
Resolver 组缓存身份升级为版本 5，防止复用旧转换曾丢失前提的规范化结果。
已启动的旧进程须重新启动才会载入修复；既有输出不自动改写。

Resolver 组缓存使用相关对象上下文与读取版本；Skeleton、Target Proof、对象对比较及循环审查
具有局部缓存。缓存保存生成结果、提交增量、读取版本及 ID 映射，命中后仍经过统一提交入口。
全局简表的无关变化不会导致所有组失效；提交时重新处理新增对象之间的身份关系。
组间重名的局部别名只保存在各自 `group_aliases` 中，不以最后一次写入覆盖全局身份。
增量适配仅展开一次；格式错误按操作记录，避免一个坏补丁丢掉同一响应中的合法对象。
Planner 默认继承 Resolver 的 checkpoint 配置，未提供稳定模型身份的自定义回调继续关闭缓存。

回归覆盖见 `test_formal_object_registry.py`：跨组复用、条件差异、ID 冲突、显式绑定、
局部符号保护、全局更新、来源与审计保留、循环与缺失诊断、并行提交顺序和缓存重放。
真实证明验证还由 `test_formal_verification.py` 和 `test_formal_theory_integration.py` 覆盖。

## Survey 原始论文作为 ExperimentDesign 参考

ExperimentDesign 已取消独立论文发现、查询规划与二次 LLM 论文筛选。
Survey 在深度阅读后导出 `survey_retrieval_manifest.json`，并将其作为
`retrieval_papers` 纳入 `survey_manifest.json`。该文件保存检索所得原论文的
元数据、原摘要、已有原全文、相关度和引用图来源，不包含生成的综述或 keynote。

论文池按 Survey 相关度排序，主检索论文与图扩展论文合计最多 32 篇。
默认最多选入 12 篇一跳图扩展论文，图论文的 Survey 相关度须至少为 3，
且其父论文必须入选；剩余额度由主检索论文补足。可通过
`experiment_design.evidence_papers` 调整配额和图相关度阈值，配置不能突破 32 篇。
Survey 已选出的论文直接接纳，不再调用可信度筛选模型。
仅对入选的同一论文身份补取缺失全文，不搜索或加入新论文。

证据卡标记为 `evidence_role: reference`、`usage: variables_and_definitions`。
它们为变量提取和定义构造提供原文参考，证明规划、反例分析、语义修订与
最终设计合成依赖上游变量和定义，不再将卡片原文塞入所有后续提示词。
LLM 可以补充数学定义、方程、假设、辅助引理、任意候选规则和证明步骤；
生成后的检查仍记录证明状态。循环定义保留为研究草稿，不能作为已成立的证明前提。

### 格式恢复与科学状态

符号协调补丁逐项接纳：一个无效改名只拒绝该操作及确实依赖它的操作，独立合法操作继续执行。
完全等价的重复定义合并时同步重定向依赖、前提和证明引用；同名但含义不同的定义保留并消歧，
无法确定所有者的引用仅影响其使用者。模型关系格式诊断不删除公式或关系。
Resolver、Planner 恢复、符号协调和语义修订使用同一关系格式规范化策略。

`machine_encoding_issues` 表示暂不能执行的局部字段，不作为科学错误沿依赖链改写状态。
真实缺失前提或循环依赖仍保留影响范围诊断；传播后的定义和关系保留自身科学状态，
日志只记录新出现或变化的依赖影响，同一状态重复恢复不重复警告。
验证汇总分别输出 `computation_results`、`semantic_status` 和 `encoding_diagnostic_count`。
后端通过说明声明的数学编码得到相应核验结果，语义待审与计算结果同时保留。

### 定义字段与分组修订

已明确的定义必须给出非空的 `symbol`、`statement`、`domain`、`codomain`、
`unit` 和 `selection_reason`。原始对象也须描述值域或对象类型，例如图的
`codomain` 可以是加权图；无物理量纲的结构对象可填写 `unit: not_applicable`，
比例等无量纲量填写 `dimensionless`。这些说明同步用于定义解析、全局协调、
证明规划和语义修订。没有机器编码的文字定义可以保持已明确状态。

缺失或为空的字段分别记录字段路径和补全建议，并进入对应定义的局部修订目标。
组内 `assigned_definition_ids` 只包含本组主定义；全局注册表保留所有变量和
对应主定义 ID，供跨组引用。误返回的其他组主定义归档在
`retrieval_audit.out_of_group_candidates`，不参与本组诊断和补全；
所需辅助定义及有效跨组依赖仍然保留。

`variable_references` 只存变量 ID。误放入其中的已知正式记录 ID 会移入
`depends_on`，并记录 `dependency_repairs`；未知引用保留诊断，不根据名称猜测。
全局协调保留字符串形式的研究缺口，不因对其调用对象方法而中断整个协调阶段。

完整 Science 流程自动传递对应 Survey manifest。单独重跑时可显式指定：

```bash
python -m src.cli exp_design --config src/config/default.yaml \
  --idea-json "$IDEA" --survey-manifest "$SURVEY" --output-dir "$ED_OUT"
```

未显式指定时优先使用 Idea 保存的 Survey 绑定。旧 Survey 运行没有原论文清单时，
仅从绑定 attempt 的 `sh_graph_provenance.json` 与仓库 `database` 中已有的
原摘要、MinerU 原文缓存恢复；不会读取 `survey.md` 或 `survey.json`。
旧缓存只能恢复已持久化的论文，缓存缺失会记录明确诊断并允许无参考数学构造继续，
不会启动独立搜索或替换成另一个 Survey attempt。自定义缓存位置的历史运行应提供
原论文清单，或重新运行 Survey 生成新的交接文件。

运行日志提供 `survey_paper_pool_loaded`、`survey_high_score_papers_selected`、
`citation_graph_expansion_completed`、`survey_selected_fulltext_acquisition` 和
`survey_evidence_cards_extracted`，便于核对原论文数量及参考卡来源。

The implementation follows three functional batches in the existing checkout.

| Batch | Scope | Risk | Validation | Review |
| --- | --- | --- | --- | --- |
| 1 | Target-specific counterexamples, lossless Author handoff, P/S/L identity | Medium | Reasoning, artifact and theory-spine regressions | Included in final review |
| 2 | Versioned definitions, model relations, proof structures and dependencies | Medium | Contract, dependency and legacy-input tests | Included in final review |
| 3 | Verification adapters, revision budget, derived statuses and execution policy | High | Real solver examples, failure paths and integration | One independent final review |

## Acceptance

- A counterexample satisfies the target domain and premises and negates its conclusion.
- Only target dependencies and declared global assumptions constrain that target.
- Author retains definitions, formulas, premises, proof targets and provenance.
- Propositions and derivation steps retain their identities; only explicit lemmas have L labels.
- Missing definitions, unsupported encodings, timeouts and absent tools never count as proof.
- Revisions invalidate results for changed targets and dependencies.
- Numerical support, bounded verification and general proofs remain distinct.
- Version 1 artifacts remain readable without fabricating missing mathematics.

## Progress

- Batch 1: implemented; 45 targeted regressions passed.
- Batch 2: implemented; 44 contract/dependency/compatibility regressions passed.
- Batch 3: implemented; real backend, revision and Author integration checks passed.

## Configuration and execution

The normal configuration enables v2 definition resolution. Mathematical verification
is separately opt-in under `experiment_design.formal_reasoning.verification.enabled`.
Experimental execution remains governed by the existing discipline policy. A
`DESIGN_ONLY` artifact can contain mathematical verification evidence without
claiming experimental observations; its `observed_results` remains empty.

Install the optional Python backends into the environment that runs the workflow:

```powershell
uv sync --group formal
```

Lean is an external proof-assistant toolchain rather than a Python package. On
systems using Elan, install the pinned toolchain from the repository root:

```powershell
elan toolchain install (Get-Content lean-toolchain)
```

The pinned version is recorded in `lean-toolchain`. `requirements.txt` and
`uv.lock` therefore contain the Python backends, while Lean itself is managed
by Elan. Mathlib imports additionally require a Lean project that provides
Mathlib; the adapter continues to report `proof_assistant_unsupported` when
the configured executable or its imports are unavailable.

Set `verification.backends` to `["sympy", "z3"]` and `timeout_seconds` to the desired
per-task wall-clock budget. The isolated backend process uses that same Python
interpreter. Missing dependencies produce `unsupported`, not successful checks.
The proof-assistant backend is opt-in: `lean` must be listed in
`verification.backends` and `verification.proof_assistant.enabled` must be true.
When the backend is listed but disabled, it returns `unsupported` with an explicit
disabled reason. The current adapter generates a temporary theorem source and
invokes the configured Lean executable; only a successful Lean process exit is
recorded as `lean_kernel_checked`. Missing Lean, malformed theorem input, timeouts,
and rejected proofs never count as proof. The generated theorem source is retained
as `certificate_source` for auditability, while `certificate_ref` is a stable
generated filename rather than a path on the local machine. Arbitrary commands or
generated Python are never evaluated.

Lean diagnostics also retain explicit assistant states: `proof_assistant_verified`,
`proof_assistant_failed`, `proof_assistant_timeout`, and
`proof_assistant_unsupported`.

Verification results expose a capability level: `solver_verified` for Z3/SymPy,
`bounded_checked` for candidate-point search, `rule_verified` for the bounded local
rule engine, `kernel_verified` for a successful Lean check, and `unresolved` for
unsupported or incomplete work. These levels describe the checking mechanism and
scope; they do not turn a conditional or domain-limited result into a universal
scientific claim.

The restricted AST supports arithmetic, comparisons, Boolean connectives
(`implies`, `iff`, `xor`) and conditional expressions (`ite`). Proof attempts may
attach `derived_expression` to a step. Such steps are checked locally using only
assumption reuse, definition unfolding, order weakening, transitivity,
contradiction, or algebraic normalization. A text-only `rule_or_lemma` remains a
proof draft, and an unrecognized rule is never treated as trusted evidence. Local
rule evidence is reported as `rule_derivation` and does not carry a proof-assistant
certificate.

Verified lemmas can be reused with an explicit `lemma_instantiations` record on
the target. The record names the `lemma_id`, maps every quantified lemma symbol
through `instantiation` (or the compatibility alias `substitution`), and lists
AST `side_conditions`. The verifier substitutes the expressions, checks that the
result only uses declared target symbols, adds the side conditions to the target
constraints, and imports the instantiated lemma as an implication. Without this
record, the previous same-quantifier compatibility rule remains in force.

Example opt-in configuration:

```yaml
verification:
  enabled: true
  backends: ["sympy", "z3", "lean"]
  proof_assistant:
    enabled: true
    backend: "lean"
    executable: "lean"
```

`max_semantic_revisions` defaults to two, is capped at five, and stops early when
no content changes. Definitions and model relations are resolved before proofs.
Each revision records before/after scientific records and invalidated targets.
Successful solver results are reused only when their target, dependency snapshot,
diagnostics and encoded constraints are unchanged. No hash-based gate is used.

## Mathematical completion and notation repair

Evidence cards are reference material for mathematical construction. The definition
resolver, skeleton planner and proof planner may supply new definitions, parameterized
governing relations, assumptions and auxiliary lemmas from their own mathematical
reasoning. New mathematical models use origin modeling_convention; they do not need
a paper for every expression or derivation step. Source references remain attached to
records that actually use a source, and unknown numerical parameters can stay symbolic.

Global reconciliation now returns repair patches, equivalent-definition merges and
scoped symbol renames. It runs before duplicate notation can remove a candidate from
the active plan, including conflicts introduced during proof generation. A merge
redirects dependency IDs and preserves both candidates' source and variable references.
A symbol rename identifies its consumers explicitly so ASTs, quantifiers, formulas
and proof steps use the same notation. Original records and repair changes are retained
in the reconciliation audit.

Patch operations are checked individually. Invalid repairs, merges or renames are
excluded without discarding independent valid operations. Each rejected operation
records its original operation index, record ID, invalid referenced IDs and reason
in the audit and `reconciliation_operation_warning` log. Consumers affected by a
merge are redirected before dependency recovery; existing unrelated record errors
do not invalidate a notation repair.

Exact, specified mathematical duplicates are merged before requesting LLM notation
repair. Their source references and compatible variable bindings are retained, and
live dependency and proof-premise references use the canonical ID. Distinct meanings
remain separate definitions. If LLM reconciliation leaves a repeated symbol, recovery
assigns unique notation and updates consumers whose explicit dependencies or unique
variable bindings identify the definition. Ambiguous consumers retain their drafts
with review diagnostics. Audit history is never rewritten, and unresolved dependency
cycles remain drafts. `plan_symbol_repair_input_profiled` records prompt size and the
conflict and consumer IDs submitted for review.

Proof generation can add supporting definitions, model relations, assumptions and
lemmas, complete unresolved input records and retain rules outside the local checker's
small rule set. Such drafts can be evaluated by the configured mathematical backends.
The final planner keeps these completions rather than replacing them with its original
input definitions. Cyclic definitions remain available as drafts; neither circular
premises nor unresolved cycles can establish a verified proof.

## Result interpretation

The design JSON and Author handoff carry `formal_verification_report` and
`formal_revision_audit`; the Markdown includes both. Each backend result records
the encoded task, assumptions, scope, version, outcome and witness or residual.
The report is the persisted verification artifact; its embedded evidence is
validated against the current plan before handoff. Solver and local-rule results
are not cryptographic certificates. A `lean_kernel_checked` result records the
configured Lean process check for the generated theorem, including its source and
environment scope; it is not a portable certificate independent of that Lean
installation.

SymPy verifies polynomial identities; Z3 checks satisfiable domains and searches
for witnesses to premises AND NOT conclusion. Division is restricted to nonzero
constants, and exponents to small nonnegative integer constants. Unsupported
nonlinear physics, PDEs, numerical calibration and arbitrary quantifiers remain
explicit obligations rather than being encoded as empty constraints.

Numerical candidate checks retain the analyzer's counterexample ID and never
award general proof or certified-refutation status. SMT witnesses apply only to
the encoded model. A verified conditional lemma is imported as an implication,
preserving its domain, and cannot silently shrink the target's domain.

Legacy v1 handoffs remain readable. Conversion marks unspecified formulas as
unresolved and does not claim newly constructed historical proofs. Reader-visible
P/S/L identifiers retain their upstream kinds; the internal `lemma_units` name is
retained only for compatibility with the existing document registry.

## Final validation (2026-09-10)

- Final full suite: 943 passed, 7 failed, 1 skipped. Log:
  `tmp/formal-final-suite-v2.log`.
- The same seven failures reproduced against an unmodified HEAD archive (ordinary
  files, not a Git worktree): `tmp/formal-baseline-results.log`. They comprise five
  ExperimentDesign cache tests, one quantitative parameter evidence test and one
  Qwen vision response-format test. No unrelated fixes were applied.
- Final sdist and wheel build succeeded using `python -m build --no-isolation`;
  artifacts are under `tmp/formal-dist-final`, log `tmp/formal-build-final.log`.
  Wheel contents include all six new implementation modules, including the worker.
- Focused Ruff F checks for all six new implementation modules and `git diff --check`
  passed. No full lint, browser E2E or frontend build was needed for this backend change.
- One independent comprehensive review was performed; its substantive findings
  were repaired by the implementation agent and covered by targeted regressions.
  The reviewer did not repeat tests. There were no per-task dual-review gates.
- Validation used the available Anaconda Python 3.13.9 interpreter. Project metadata
  declares Python 3.12; runtime validation on that exact version remains an environment
  limitation. Z3 4.15.4.0 and build dependencies were installed in temporary project
  directories without replacing existing environment packages.
- No standalone hash checks were run. Existing artifact provenance mechanisms remain.
- No live research-provider run or re-generation of the historical astronomy report
  was performed. LLM interactions are contract-tested with deterministic responses;
  mathematical verification tests execute real SymPy and Z3 backends.

| Requirement | Regression evidence |
| --- | --- |
| Correct negation and target-specific assumptions | `test_formal_dependency.py` |
| Lossless mathematics and P/S/L identities | `test_formal_dependency.py`, `test_research_plan_author_theory_spine.py` |
| Explicit definitions, model choices, source grounding and legacy conversion | `test_formal_contracts_v2.py` |
| Cycles, malformed targets, independent-target retention | `test_formal_contracts_v2.py` |
| Actual proof/refutation, unsatisfiable domains and bounded execution | `test_formal_verification.py` |
| Missing encodings/backends and numerical evidence cannot become proof | `test_formal_verification.py` |
| Obligations, conditional lemma scope and usable lemma chains | `test_formal_verification.py` |
| Versioned scientific repair and stale-result invalidation | `test_formal_verification.py` |
| Solver-to-orchestrator-to-Author-to-artifact integration | `test_formal_theory_integration.py` |
# 按问题检索定义证据

`formal_definition_resolver` 现在先建立本地词项索引，按变量的显式依赖、共同 claim 和名称关联分组，再检索相关证据。无需向量数据库或新增依赖。英文词项和中文字符匹配不保证召回所有同义词；模型可通过 `evidence_requests` 提出补取查询，仍未解决的缺口会保留。

Resolver 的 LLM 请求使用 `formal_definition_wire_v1` 紧凑传输格式。定义和关系只返回科学内容、条件对象、来源和必要的变量引用；`symbol_references`、`depends_on`、`condition_expressions`、`definition_status`、`verification_readiness` 与 `variable_dependency_registry` 由 Python 在响应后确定性补全。条件在传输中使用 `{text, formal_expression}` 对象数组，随后展开为内部契约的可读条件和形式条件数组。完整的 `formal_definition_resolution_v1` 仍作为后续 Planner、Verifier 和 Author 的稳定接口，旧版完整 LLM 响应继续兼容。

默认配置位于 `experiment_design.formal_reasoning.definition_retrieval`：每组最多 4 个变量，首轮最多 24 张原卡，默认最多补取 1 轮、每轮最多 10 张新卡；`max_cards_per_request: 40` 仍是单请求的硬上限。提示词长度会记录，但不会因本地字符预算被拒绝发送；模型服务端的上下文限制仍然适用。原卡不做摘录截断，相关性和来源多样性共同决定选择顺序。没有待修复记录、缺失定义或证据查询，以及连续两轮缺口和字段诊断不变时，不再补取。没有新卡时，可使用已有相关证据完成有限的记录修复，不将缺失文献改写成已证实事实。引用的卡片 ID 未出现在当前证据包中不再导致整组失败；不再通过 `locator` 是否为卡片 `source_location` 的子串判断来源定位有效性，不产生 `definition_source_locator_not_grounded` 报错。来源引用仍需对象结构及非空字符串 `card_id`、`locator`，定位原文保留用于溯源。引文可以是释义或省略，不要求逐字匹配卡片原文。

首轮按组生成，后续请求使用 `request_mode: targeted_patch` 和 `repair_targets`，列出待修复 definition/relation ID、缺失变量、字段诊断与证据请求。模型只返回这些记录及必要的新支持记录；已接受记录作为只读上下文。补充结果按 ID 合并，未返回的记录继续保留；模型误返回已接受记录时，本地忽略覆盖并写入 `supplement_patch_merged.ignored_record_ids`。无效补充或请求失败保留原候选。仅关系失败也会触发定向修复，不要求同时缺少变量定义。

definition 和 relation 逐条检查必要字段、状态、引用数组和来源。字段检查前，先按已有记录、主定义 ID 和修复目标确定 ID 的集合归属；可确认的错放记录移到正确集合并修正 ID 字段，数学内容和来源引用保持原样。新记录可依据明确的 ID 字段纠正集合，不按 `D`/`R` 字符前缀猜测类型。提示词明确区分两类修复目标的返回集合，并要求返回完整目标记录。同 ID 跨类型冲突、互相矛盾的 ID 字段或科学类型不符时，逐条忽略并归档原文，保留既有记录和独立合法补丁；归属修复保存在 `retrieval_audit.record_collection_repairs`。

可明确解释的引用对象、单对象来源引用、单个量词对象先转换为规范数组。模型关系的格式失败不移出 `model_relations`：保留数学陈述、公式、原始字段和精确诊断，无法解释的整条内容以完整 `original_record` 留在活动草稿中。来源元数据不完整时将来源标为 `unresolved`，不编造 locator，也不据此否定公式；来源、选择理由等元数据诊断使用 `record_encoding`，不统一升级计划为人工待审。无法转换的执行引用或条件记录在 `machine_encoding_issues`，只跳过依赖这些字段的机器任务，不将格式问题传播为科学内容未解决。缺少单位、定义域、关系适用范围等科研描述仍保留候选和内容诊断。编码完整的关系即使科学状态为 `unresolved`，也允许后端检查其声明的条件体系；计算结果与科学状态分别记录，不能因此宣称科学问题已经解决。成功修复后清除相应当前编码问题，保留历史原文。`group_completed` 的诊断数与丢弃记录数分别统计，局部异常不触发 resolver 阶段降级。

多组结果按轮提交到全局数学对象注册表，确定等价的定义先复用规范 ID，不确定的对象对进行局部比较。只有仍有定义冲突时才运行既有 reconciliation 审阅；其输入限定为冲突记录与直接消费者，不重新发送原卡或完整候选。组内附加定义和关系使用稳定名称空间，同步改写活动引用和明确绑定的表达式；局部量词与证明绑定保持原含义。关系仅缺少有效 ID 时本地分配稳定 ID；非空字符串关系保留为未解决文本，单元素对象列表直接展开，无法解释的记录保留原文与字段诊断。审阅无效时保留已生成候选。合并后检查实际对象图中的缺失引用、歧义与循环，并分别报告，不把删去引用当作修复成功。局部结构检查和 LLM 审阅均不是数学证明。

定义组与协调结果通过现有内容寻址缓存存储在 `.science/cache/experiment_design/definitions-v1`，缓存身份包含完整请求、模型和 provider。定义组请求使用第 3 版身份、协调请求使用第 2 版身份，以隔离旧缓存语义。缓存保存进度，不要求全部定义为 `specified/encoded`，也不要求诊断、未解决关系或参考证据请求为空。可解析、记录 ID 可识别的规范化组写入 `definition_groups`，每轮最新合并结果写入 `definition_group_progress`；原始对象响应另存 `definition_group_responses`，规范化中断后也可复用原始响应。缓存读取不改变数学状态，循环依赖仍为草稿，未编码结果仍为 `requires_encoding`。

重跑相同初始请求先恢复最新定义组快照，已完成定义保持只读，只对未完成 definition/relation ID 和缺失变量进行定向补充；编码能力和已完成的格式修复不会单独触发再生成。剩余问题受现有 `max_supplement_rounds` 限制；设为 0 时只恢复，`read_only` 模式下有部分快照也不会发出修复请求。输入、提示词或模型改变会失效，单纯调整补充轮数不会使初始组快照失效。协调缓存保留首次审阅及后续修复的补丁序列，恢复时按顺序重放，仍有冲突时仅继续局部修复；协调中断不丢失首次结果。`checkpoint_written` 明确记录写入命名空间和快照 ID，`group_resumed` 记录恢复组与剩余修复 ID。它不等于整个 science run 的阶段恢复，也不会改变已经发出的请求。

变量与主张提取、形式证明规划、反例分析及模板合成的有效产物使用 `experiment_design.retrieval.cache` 指定的内容寻址缓存。缓存身份包含各阶段完整输入、相关设置及 LLM provider/model；上游输入变化会使下游阶段失效。变量、证明规划和初轮反例产物在跨工件推理校验通过后才写入；无法通过契约校验、含失败目标或需要重新生成的降级产物不写入缓存。自定义 LLM 回调默认不复用缓存，只有显式提供 `experiment_design_cache_identity` 时才允许复用。缓存命中和写入会出现在对应阶段的运行日志中；只读模式下缓存缺失不会调用 LLM。定义解析的变量组、形式推理的证明目标组、反例分析的目标在各自模块内最多并行 3 个，结果按原顺序合并；有明确前置依赖的定义组和证明目标组等待上游组完成。模块之间仍按定义、推导、反例的依赖顺序串行执行。组内的补充检索仍依赖前一轮结果，继续串行。

每 30 秒输出 `llm_request_waiting`，每组输出组号、补取轮次、卡片数、提示词字符数和缓存命中状态。ExperimentDesign 默认设置 `request_timeout_seconds: 1800`、`request_max_retries: 1`，传递给 SDK；这是请求超时/重试设置，不是整个阶段的硬墙钟截止时间。等待心跳表示本地仍在等待，不表示服务端正在生成。

形式推理采用两阶段流程。第一阶段 `v2_skeleton` 只生成假设、命题、引理、证明义务和依赖骨架，不生成详细证明步骤；它在首次请求时按依赖闭包分组，每组最多 24 个定义和 16 个关系。组外记录只以 `external_dependencies`/`omitted_context` 的短索引出现，完整定义和关系在本地注入骨架产物，模型无需复述。Skeleton 请求禁用底层原样重试；单组请求失败时先缩短数学文本和证据摘要，再以压缩输入重试，仍失败则拆成更小组并保留失败组的待审草稿，不清空其他组结果。Skeleton 不设置专用提示词字符上限、900 秒超时或 12000 输出 token 上限；请求超时沿用 ExperimentDesign 的通用设置，输出仍服从模型服务及项目通用配置。它接收已编码定义与关系的关键数学字段、未编码项的简短索引及默认最多 36 张相关证据卡的正文。检索查询只使用数学内容摘要与主张，避免完整来源引文影响相关性检索。提示词明确要求假设的 `assumption_id` 与候选状态、证明义务的 `obligation_id` 与未解决状态；可确定的通用 ID 字段和缺失状态由本地归一化。仍缺 ID 时最多发送一次只含缺口记录及引用索引的小型修复请求，修复结果须与目标引用一致。修复请求失败时保留骨架，为缺 ID 记录分配仅用于追踪的 ID，不猜测其科学关联。可明确识别的单对象包装会展开；`depends_on`、`premises` 和 `assumption_ids` 中误用的变量 ID，在主定义关联明确或匹配唯一时转换为正式定义 ID，记录 `dependency_reference_repaired`。有歧义的引用保留原文并阻止受影响记录参与验证。

骨架提示词通过共享的 `output_contract.required_target_fields` 和完整示例明确列出每个命题、引理的 `statement`、`scope`、`premises`、`conclusion`、`quantifiers`、`domain_expression`、`conclusion_expression`、`required_obligation_ids`，所有键必须出现；同时提供 assumption 和配套 lemma/proof_obligation 示例。数字叶节点使用字符串、符号声明与表达式分开、参数使用表达式对象。无法编码的数学表达式用 `null` 并解释编码缺口，不把编码缺口等同于科学错误。可明确识别的字段别名和有限数值叶节点先归一化，然后只对仍缺失或格式错误的字段发起 `v2_skeleton_repair_round_<n>_batch_<n>`。

修复返回 `skeleton_record_patch_v1` 的 `patches`，仅允许修改指定 ID 的指定字段，拒绝覆盖合格字段或增加未请求的记录。错误引用允许删除或替换，不按列表长度判断是否削弱；有效前提、有效依赖及属于当前目标的有效证明义务必须保留。`required_obligation_ids` 必须引用 proof_obligation，且其 `target_id` 与目标一致；目标也须登记关联到它的义务。关联冲突的目标和义务放入同一批，在临时副本中应用所有补丁后统一校验；拒绝某字段后重新检查依赖它的其他字段，独立有效字段继续保留。默认 `planner.max_skeleton_repairs: 1`（可设 0–2）、`planner.max_records_per_skeleton_repair: 4`（可设 1–8）；批次大小是独立记录的打包目标，互有关联的修复组件不拆开，可以超过此大小。每轮只请求剩余问题，无进展时停止。

修复请求提供错误引用、合法义务 ID、相关记录的类型、`target_id` 和状态；目录仅选相关记录。表达式校验返回 `node_path`、`error_code`、`actual_type` 和 `expected`，诊断同时进入请求、`skeleton_patch_warning` 和审计记录。修复请求记录 `prompt_chars`。历史候选、修改前后内容和批次结果分别写入 `construction_archive`、`candidate_completions` 与 `skeleton_repair_audit`。

结构合法的数学补充以 `unverified` 保存，自动进入目标证明、验证、反例分析和语义审查，不因模型补充而统一要求人工确认。成功补充记录 `INFO/REPAIRED`，保留数学文本但编码未完成时记录 `INFO/ENCODING_PENDING`，不合法补丁记录 `WARNING` 并附失败路径。模型明确报告 `semantic_conflict` 或 `needs_user_decision` 且提供具体原因时才产生 `WARNING/REVIEW_REQUIRED`；API 失败仍保留原始错误类型。旧产物的通用 `candidate_completion_pending` 和修复节点的 `model_completion` 诊断不再独立阻止验证；实际缺失依赖、循环依赖和不可执行编码仍分别处理。循环定义可保留为研究草稿，但不能作为已成立的证明前提。

第二阶段 `v2_target_proof` 按最多两个目标一批生成证明尝试和推导步骤，按显式依赖先安排前置引理、命题，再处理依赖它们的目标；独立目标仍可并行。未补齐的目标仍进入草稿生成，并携带构造诊断；`construction_status: blocked` 限制机器验证，不跳过整个目标的草稿。目标批次接收相关假设、已编码定义、关系、命题、引理、证明义务、前置目标的证明尝试，以及默认最多 36 张相关证据卡。前置引理自身的依赖上下文也递归纳入。已接受的命题内容和证明记录不被后续响应同 ID 覆盖，冲突候选进入 `construction_archive`。目标返回的引理实例化只允许填入尚未提供的元数据，冲突记录待人工审查。

目标证明首轮和定向修复均携带 `output_contract`，复用 Skeleton 的完整辅助引理、假设与证明义务示例，并补充合法的嵌套证明尝试示例。辅助引理必须提供 `lemma_id`、全部 `TARGET_FIELDS` 与候选状态；证明尝试必须提供 `attempt_id`、`target_id`、有序对象数组 `steps` 和同一尝试内的 `final_step_id`。每步明确包含 `step_id`、字符串 ID 数组 `premises`、`derived_statement`、`rule_or_lemma` 与 `status`，可选 `derived_expression` 遵循表达式契约。步骤只能引用已声明记录或本尝试内更早的步骤；同一步不能同时出现在证明尝试和 `derivation_steps` 中。示例仅说明结构，实际输出使用当前研究的 ID 和数学内容；候选数学规则仍可自由选择。

依赖恢复先完成循环识别与传播，达到稳定状态后统一生成诊断。每条传播或循环诊断保存排序去重的 `dependency_ids` 和对应 `dependency_states`，只在新增、阻塞集合变化或依赖健康状态变化时记录 WARNING 和原始候选归档。当前 `unknown_items` 每个记录、每类依赖问题只保留一条完整诊断；兼容旧版文本诊断并合并重复项。已修复的传播或循环问题从当前诊断中移除，已有历史归档保留。未变化的依赖问题仍保留供后续推理、验证参考，但重复合并不会继续刷日志或增加相同问题的归档。

记录先做可解释的格式转换，再逐条校验。符号名称不匹配仅产生非阻断提示，同一份产物中的重复诊断不反复记录；表达式、量词、引用和证明草稿保持完整。无法解决的前提引用、量词格式和引理应用保留原始内容与精确的 ID/字段诊断，受影响记录标记 `construction_status: blocked`；仅这些记录及其依赖目标不能参与机器验证。同一目标缺少多个必需字段时合并为一条日志，列出全部字段名。结构合法的证明尝试即使依赖待审前提也作为草稿保留；非法尝试单独归档，其他尝试、定义和命题继续保留。默认 `experiment_design.formal_reasoning.planner.max_target_repairs: 1`，可设置 0–2：只请求失败或遗漏的目标，传入 `targeted_repair` 的目标 ID、失败原因与对应原始候选，不重生成成功目标。结构修复不能补造科学前提，也不能把缺失依赖删去后宣称证明成立。规则检查及 SMT、符号计算和 Lean 均阻止被标记的构造参与验证；求解器仍需要合法的类型和数学编码才能给出验证结论。原始候选以完整 JSON 字符串归档，避免归档中的未经验证状态被误当作当前证明声明。

规划、反例和语义修订阶段记录提示词长度，但不执行本地字符预算门禁。单个目标批次失败记录 `target_group_warning`；局部恢复记录 `record_warning` 和 `target_repair_completed`，保留已生成骨架和其他成功批次。生成骨架时请求失败保留上游定义与关系，生成后的异常保留最近的候选，不采用空计划替换全部成果。跨工件校验对 v2 使用局部恢复，单个无效反例目标也只替换为该目标的待审分析，原始分析归档；其他目标与有效变量模型继续保留。含未完成构造诊断的规划不写入阶段缓存。反例分析只有在存在命题或引理时才按目标依赖子图请求 LLM；若没有可否定的形式化目标，记录 `not_applicable/not_run` 并正常继续，不发送无目标的通用请求。

设计组合和 Author 正文章节在证据超过 40 张时只保留一次相关卡片正文，嵌套重复证据转成 ID 索引；原始 EvidenceBundle、证据账本和引用许可集合不变。这些后续阶段目前执行一次相关性检索，尚无交互式补取循环。定义阶段才执行缺口补取。检索遗漏应作为不确定性处理，不能当成反证。

反例分析按命题或引理逐目标请求，每次传入其依赖子图；某个目标失败只标记该目标待人工审查，其余结果继续保留。即使所有目标都失败，也保留各目标的失败原因。Author handoff 和理论骨架保留所有目标的候选反例及其目标归属，不将候选反例直接当作已证伪结论。

语义修订逐目标接收局部验证报告、反例与最多 8 张相关证据卡。`affected_ids` 与 `editable_records` 直接从实际输入的局部子图生成，涵盖目标的证明义务及其依赖；`editable_target_ids` 明确可更新证明尝试的目标，`forward_derivation` 等顶层字段为只读上下文。补丁逐条接收：越界、缺失 ID、类型错误、重复操作、无依据的新假设或错误证明归属只忽略相应操作。合法且相互依赖的新增记录与替换记录一起校验；无效操作及依赖它们的操作逐条撤回，保留独立有效修订。未经验证的科学内容不能通过补丁宣称已经验证。原始失败操作以完整 JSON 字符串保存到 `formal_revision_audit.iterations[].rejected_operations`，每条含操作类型、序号、collection、record_id、target_id、错误码和原因；日志使用 `operation_warning`、`level/status: WARNING`，不输出原始补丁正文。部分成功的完成日志同时记录 `result_status: revised` 与警告数量。仅有忽略操作时保持计划和 revision 不变。单目标准备、请求或验证失败记录 `WARNING`、保留原计划和报告，已有补丁另存 `raw_patch_json`，继续处理其他目标；整轮无进展时停止后续轮次。形式验证按依赖层级调度，独立目标在同层最多并行 4 个任务。日志列出执行、复用、不支持和超时任务数；并发只缩短独立任务等待时间，不改变验证结论。
