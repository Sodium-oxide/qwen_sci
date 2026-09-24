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

Install the optional backends into the Python environment that runs the workflow:

```powershell
python -m pip install sympy==1.14.0 z3-solver==4.15.4.0
```

Set `verification.backends` to `["sympy", "z3"]` and `timeout_seconds` to the desired
per-task wall-clock budget. The isolated backend process uses that same Python
interpreter. Missing dependencies produce `unsupported`, not successful checks.
The reserved proof-assistant backend currently returns `unsupported` when no
adapter is configured. Arbitrary commands or generated Python are never evaluated.

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
validated against the current plan before handoff. It is not a cryptographic
certificate or an independent proof-kernel attestation.

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

默认配置位于 `experiment_design.formal_reasoning.definition_retrieval`：每组最多 4 个变量，首轮最多 16 张原卡，默认最多补取 1 轮、每轮最多 10 张新卡；`max_cards_per_request: 40` 仍是单请求的硬上限。`max_prompt_chars: 120000` 是完整定义请求的字符预算，并非精确 token 预算；超出预算的请求不会发送。原卡不做摘录截断，相关性和来源多样性共同决定选择顺序。没有具体缺失定义或证据查询，以及连续两轮缺口不变时，不再补取。每组输出须通过定义契约和已见卡片的引文校验。

多组结果再进行一次语义协调，使用定义候选和已有引用，不重新发送原卡。协调不得添加未见引用或删除变量、模型关系。组内附加定义和关系统一使用组号前缀，并同步重写显式依赖，避免不同组都返回 `R1` 时误合并。关系对象仅缺少有效 ID 时，本地分配稳定的组内 ID，不改变其科学字段；非空字符串关系保留为未解决文本，单元素对象列表直接展开，其他无法解释的关系隔离为待审项并保存限长原文片段。校验错误记录具体数组位置和字段类型。协调响应无效、丢失关系或超预算时，保留各组已校验的候选并记录详细原因。随后本地合并检查 ID、符号、依赖及循环；冲突保留为未解决项，独立定义不因符号冲突被直接丢弃。局部结构检查和 LLM 协调均不是数学证明。

定义组与协调结果通过现有内容寻址缓存存储在 `.science/cache/experiment_design/definitions-v1`，缓存身份包含完整请求、模型和 provider。重跑相同输入可以复用已成功批次；输入或模型改变会失效。它不等于整个 science run 的阶段恢复，也不会改变已经发出的请求。

每 30 秒输出 `llm_request_waiting`，每组输出组号、补取轮次、卡片数、提示词字符数和缓存命中状态。ExperimentDesign 默认设置 `request_timeout_seconds: 1800`、`request_max_retries: 1`，传递给 SDK；这是请求超时/重试设置，不是整个阶段的硬墙钟截止时间。等待心跳表示本地仍在等待，不表示服务端正在生成。

形式推理采用两阶段流程。第一阶段 `v2_skeleton` 只生成假设、命题、引理、证明义务和依赖骨架，不生成详细证明步骤；第二阶段 `v2_target_proof` 按最多两个目标一批生成证明尝试和推导步骤。目标批次仅接收依赖子图中的假设、定义、关系、证明义务与对应证据。规划器默认每次最多接收 12 张相关证据卡，只保留这些卡片的 catalog 摘要，不再把完整证据库 catalog 传给 LLM。单次规划提示词默认上限为 70000 字符；超过上限时记录具体原因。单个目标批次失败会记录 `target_group_failed`，保留骨架与其他成功批次，并为失败目标留下人工审查项；骨架本身失败才整体降级。

设计组合和 Author 正文章节在证据超过 40 张时只保留一次相关卡片正文，嵌套重复证据转成 ID 索引；原始 EvidenceBundle、证据账本和引用许可集合不变。这些后续阶段目前执行一次相关性检索，尚无交互式补取循环。定义阶段才执行缺口补取。检索遗漏应作为不确定性处理，不能当成反证。

反例分析按命题或引理逐目标请求，每次传入其依赖子图；某个目标失败只标记该目标待人工审查，其余结果继续保留。即使所有目标都失败，也保留各目标的失败原因。Author handoff 和理论骨架保留所有目标的候选反例及其目标归属，不将候选反例直接当作已证伪结论。

语义修订逐目标接收局部验证报告、反例与最多 8 张相关证据卡。单目标准备、请求或验证失败会记录详细原因并继续处理其他目标；整轮无进展时停止后续轮次。形式验证按依赖层级调度，独立目标在同层最多并行 4 个任务。日志列出执行、复用、不支持和超时任务数；并发只缩短独立任务等待时间，不改变验证结论。
