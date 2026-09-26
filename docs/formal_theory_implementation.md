# Mathematical theory implementation

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

默认配置位于 `experiment_design.formal_reasoning.definition_retrieval`：每组最多 4 个变量，首轮最多 24 张原卡，默认最多补取 1 轮、每轮最多 10 张新卡；`max_cards_per_request: 40` 仍是单请求的硬上限。提示词长度会记录，但不会因本地字符预算被拒绝发送；模型服务端的上下文限制仍然适用。原卡不做摘录截断，相关性和来源多样性共同决定选择顺序。没有待修复记录、缺失定义或证据查询，以及连续两轮缺口和字段诊断不变时，不再补取。没有新卡时，可使用已有相关证据完成有限的记录修复，不将缺失文献改写成已证实事实。引用的卡片 ID 未出现在当前证据包中不再导致整组失败；不再通过 `locator` 是否为卡片 `source_location` 的子串判断来源定位有效性，不产生 `definition_source_locator_not_grounded` 报错。来源引用仍需对象结构及非空字符串 `card_id`、`locator`，定位原文保留用于溯源。引文可以是释义或省略，不要求逐字匹配卡片原文。

首轮按组生成，后续请求使用 `request_mode: targeted_patch` 和 `repair_targets`，列出待修复 definition/relation ID、缺失变量、字段诊断与证据请求。模型只返回这些记录及必要的新支持记录；已接受记录作为只读上下文。补充结果按 ID 合并，未返回的记录继续保留；模型误返回已接受记录时，本地忽略覆盖并写入 `supplement_patch_merged.ignored_record_ids`。无效补充或请求失败保留原候选。仅关系失败也会触发定向修复，不要求同时缺少变量定义。

definition 和 relation 逐条检查必要字段、状态、引用数组和来源。字段检查前，先按已有记录、主定义 ID 和修复目标确定 ID 的集合归属；可确认的错放记录移到正确集合并修正 ID 字段，数学内容和来源引用保持原样。新记录可依据明确的 ID 字段纠正集合，不按 `D`/`R` 字符前缀猜测类型。提示词明确区分两类修复目标的返回集合，并要求返回完整目标记录。同 ID 跨类型冲突、互相矛盾的 ID 字段或科学类型不符时，逐条忽略并归档原文，保留既有记录和独立合法补丁；归属修复保存在 `retrieval_audit.record_collection_repairs`。

可明确解释的引用对象、单对象来源引用等先转换为规范格式。缺少单位、定义域、关系适用范围等科研内容时，保留原始候选，缺失字段用空值占位，并标记 `unresolved`/`blocked`；不自动补造科研内容。来源引用缺失或字段结构错误仍保留候选与诊断，将来源标为未解决；定位字符串与卡片位置元数据不匹配不影响记录状态、定向补充或语义修订接收。无法可靠解析的引用或记录结构才隔离单条。`record_warning` 按记录汇总字段诊断，保留稳定的 `record_id`、`field_path`、`field`、`error_code`、`error_detail` 和 `disposition`，并提供 `fields`、`field_diagnostics`；缺失状态字段不再重复报状态无效。`unknown_items` 保留逐字段诊断、原始数组位置及限长原文片段。`group_completed` 的 `record_diagnostic_count` 统计诊断条目，`unresolved_record_count` 统计保留但未解决的记录，`quarantined_record_count` 统计本轮隔离的记录，`discarded_record_count` 统计本轮隔离、排除的外组定义与拒绝的合并操作，不把字段诊断当成丢弃记录。成功修复后清除该记录当前的旧诊断，历史诊断仍保存在 `retrieval_audit.record_diagnostics`。局部异常保持警告，不触发 resolver 阶段降级。

多组结果再进行一次精简语义审阅：请求只包含定义与关系的科学字段目录、简短研究范围和变量索引，不重新发送原卡、完整引文或完整候选。LLM 仅返回有冲突的已有记录 ID 与原因；原始定义、关系、引用和详细条件由本地保留，不要求 LLM 重写。审阅指出的记录标记为未解决，并留下人工审查项。组内附加定义和关系统一使用组号前缀，并同步重写显式依赖，避免不同组都返回 `R1` 时误合并。关系对象仅缺少有效 ID 时，本地分配稳定的组内 ID，不改变其科学字段；非空字符串关系保留为未解决文本，单元素对象列表直接展开，其他无法解释的关系隔离为待审项并保存限长原文片段。校验错误记录具体数组位置和字段类型。审阅响应无效或超预算时，保留各组已校验的候选并记录详细原因。随后本地合并检查 ID、依赖及循环；定义 ID 和明确的函数基名仍可做无损归一，但不再按字符串精确匹配符号目录，也不生成 `symbol_diagnostics` 或 `symbol_notice`。原始符号引用、公式和局部记号保持不变。真实缺失的前提、声明冲突和依赖循环仍留下待审项。局部结构检查和 LLM 审阅均不是数学证明。

定义组与协调结果通过现有内容寻址缓存存储在 `.science/cache/experiment_design/definitions-v1`，缓存身份包含完整请求、模型和 provider。定向修复的定义组请求使用第 2 版缓存身份，避免复用旧的整组替换响应。含未解决记录、待审诊断或未完成证据请求的定义组不写入或复用；只有无冲突的协调审阅可以缓存。重跑相同输入可以复用已成功批次；输入或模型改变会失效。它不等于整个 science run 的阶段恢复，也不会改变已经发出的请求。

变量与主张提取、形式证明规划、反例分析及模板合成的有效产物使用 `experiment_design.retrieval.cache` 指定的内容寻址缓存。缓存身份包含各阶段完整输入、相关设置及 LLM provider/model；上游输入变化会使下游阶段失效。变量、证明规划和初轮反例产物在跨工件推理校验通过后才写入；无法通过契约校验、含失败目标或需要重新生成的降级产物不写入缓存。自定义 LLM 回调默认不复用缓存，只有显式提供 `experiment_design_cache_identity` 时才允许复用。缓存命中和写入会出现在对应阶段的运行日志中；只读模式下缓存缺失不会调用 LLM。定义解析的变量组、形式推理的证明目标组、反例分析的目标在各自模块内最多并行 3 个，结果按原顺序合并；有明确前置依赖的定义组和证明目标组等待上游组完成。模块之间仍按定义、推导、反例的依赖顺序串行执行。组内的补充检索仍依赖前一轮结果，继续串行。

每 30 秒输出 `llm_request_waiting`，每组输出组号、补取轮次、卡片数、提示词字符数和缓存命中状态。ExperimentDesign 默认设置 `request_timeout_seconds: 1800`、`request_max_retries: 1`，传递给 SDK；这是请求超时/重试设置，不是整个阶段的硬墙钟截止时间。等待心跳表示本地仍在等待，不表示服务端正在生成。

形式推理采用两阶段流程。第一阶段 `v2_skeleton` 只生成假设、命题、引理、证明义务和依赖骨架，不生成详细证明步骤；它接收已编码定义与关系的关键数学字段、未编码项的简短索引及默认最多 36 张相关证据卡的正文。检索查询只使用数学内容摘要与主张，避免完整来源引文影响相关性检索。提示词明确要求假设的 `assumption_id` 与候选状态、证明义务的 `obligation_id` 与未解决状态；可确定的通用 ID 字段和缺失状态由本地归一化。仍缺 ID 时最多发送一次只含缺口记录及引用索引的小型修复请求，修复结果须与目标引用一致。修复请求失败时保留骨架，为缺 ID 记录分配仅用于追踪的 ID，不猜测其科学关联。完整定义和关系在本地注入骨架产物，模型无需复述。可明确识别的单对象包装会展开；`depends_on`、`premises` 和 `assumption_ids` 中误用的变量 ID，在主定义关联明确或匹配唯一时转换为正式定义 ID，记录 `dependency_reference_repaired`。有歧义的引用保留原文并阻止受影响记录参与验证。

骨架提示词通过共享的 `output_contract.required_target_fields` 和完整示例明确列出每个命题、引理的 `statement`、`scope`、`premises`、`conclusion`、`quantifiers`、`domain_expression`、`conclusion_expression`、`required_obligation_ids`，所有键必须出现；无法编码的数学表达式用 `null` 并解释缺口。可明确识别的字段别名先归一化，然后只对仍缺失或格式错误的字段发起 `v2_skeleton_repair_round_<n>_batch_<n>`。修复返回 `skeleton_record_patch_v1` 的 `patches`，仅允许修改指定 ID 的指定字段；拒绝覆盖合格字段、删除前提以规避检查或增加未请求的记录。默认 `planner.max_skeleton_repairs: 1`（可设 0–2）、`planner.max_records_per_skeleton_repair: 4`（可设 1–8），每轮只请求剩余问题，无进展时停止。补丁部分有效时逐字段接收，错误字段、请求失败或无补丁时保留原稿，历史候选和批次结果分别写入 `construction_archive` 与 `skeleton_repair_audit`。

第二阶段 `v2_target_proof` 按最多两个目标一批生成证明尝试和推导步骤，按显式依赖先安排前置引理、命题，再处理依赖它们的目标；独立目标仍可并行。未补齐的目标仍进入草稿生成，并携带构造诊断；`construction_status: blocked` 限制机器验证，不跳过整个目标的草稿。目标批次接收相关假设、已编码定义、关系、命题、引理、证明义务、前置目标的证明尝试，以及默认最多 36 张相关证据卡。前置引理自身的依赖上下文也递归纳入。已接受的命题内容和证明记录不被后续响应同 ID 覆盖，冲突候选进入 `construction_archive`。目标返回的引理实例化只允许填入尚未提供的元数据，冲突记录待人工审查。

记录先做可解释的格式转换，再逐条校验。符号名称不匹配仅产生非阻断提示，同一份产物中的重复诊断不反复记录；表达式、量词、引用和证明草稿保持完整。无法解决的前提引用、量词格式和引理应用保留原始内容与精确的 ID/字段诊断，受影响记录标记 `construction_status: blocked`；仅这些记录及其依赖目标不能参与机器验证。同一目标缺少多个必需字段时合并为一条日志，列出全部字段名。结构合法的证明尝试即使依赖待审前提也作为草稿保留；非法尝试单独归档，其他尝试、定义和命题继续保留。默认 `experiment_design.formal_reasoning.planner.max_target_repairs: 1`，可设置 0–2：只请求失败或遗漏的目标，传入 `targeted_repair` 的目标 ID、失败原因与对应原始候选，不重生成成功目标。结构修复不能补造科学前提，也不能把缺失依赖删去后宣称证明成立。规则检查及 SMT、符号计算和 Lean 均阻止被标记的构造参与验证；求解器仍需要合法的类型和数学编码才能给出验证结论。原始候选以完整 JSON 字符串归档，避免归档中的未经验证状态被误当作当前证明声明。

规划、反例和语义修订阶段记录提示词长度，但不执行本地字符预算门禁。单个目标批次失败记录 `target_group_warning`；局部恢复记录 `record_warning` 和 `target_repair_completed`，保留已生成骨架和其他成功批次。生成骨架时请求失败保留上游定义与关系，生成后的异常保留最近的候选，不采用空计划替换全部成果。跨工件校验对 v2 使用局部恢复，单个无效反例目标也只替换为该目标的待审分析，原始分析归档；其他目标与有效变量模型继续保留。含未完成构造诊断的规划不写入阶段缓存。反例分析只有在存在命题或引理时才按目标依赖子图请求 LLM；若没有可否定的形式化目标，记录 `not_applicable/not_run` 并正常继续，不发送无目标的通用请求。

设计组合和 Author 正文章节在证据超过 40 张时只保留一次相关卡片正文，嵌套重复证据转成 ID 索引；原始 EvidenceBundle、证据账本和引用许可集合不变。这些后续阶段目前执行一次相关性检索，尚无交互式补取循环。定义阶段才执行缺口补取。检索遗漏应作为不确定性处理，不能当成反证。

反例分析按命题或引理逐目标请求，每次传入其依赖子图；某个目标失败只标记该目标待人工审查，其余结果继续保留。即使所有目标都失败，也保留各目标的失败原因。Author handoff 和理论骨架保留所有目标的候选反例及其目标归属，不将候选反例直接当作已证伪结论。

语义修订逐目标接收局部验证报告、反例与最多 8 张相关证据卡。`affected_ids` 与 `editable_records` 直接从实际输入的局部子图生成，涵盖目标的证明义务及其依赖；`editable_target_ids` 明确可更新证明尝试的目标，`forward_derivation` 等顶层字段为只读上下文。补丁逐条接收：越界、缺失 ID、类型错误、重复操作、无依据的新假设或错误证明归属只忽略相应操作。合法且相互依赖的新增记录与替换记录一起校验；无效操作及依赖它们的操作逐条撤回，保留独立有效修订。未经验证的科学内容不能通过补丁宣称已经验证。原始失败操作以完整 JSON 字符串保存到 `formal_revision_audit.iterations[].rejected_operations`，每条含操作类型、序号、collection、record_id、target_id、错误码和原因；日志使用 `operation_warning`、`level/status: WARNING`，不输出原始补丁正文。部分成功的完成日志同时记录 `result_status: revised` 与警告数量。仅有忽略操作时保持计划和 revision 不变。单目标准备、请求或验证失败记录 `WARNING`、保留原计划和报告，已有补丁另存 `raw_patch_json`，继续处理其他目标；整轮无进展时停止后续轮次。形式验证按依赖层级调度，独立目标在同层最多并行 4 个任务。日志列出执行、复用、不支持和超时任务数；并发只缩短独立任务等待时间，不改变验证结论。
