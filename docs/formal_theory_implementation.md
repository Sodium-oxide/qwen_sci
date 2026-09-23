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

默认配置位于 `experiment_design.formal_reasoning.definition_retrieval`：每组最多 4 个变量，初始最多 16 张原卡，单请求最多 40 张，最多补取 2 轮。`max_prompt_chars: 120000` 是完整定义请求的字符预算，并非精确 token 预算；超出预算的请求不会发送。原卡不做摘录截断，相关性和来源多样性共同决定选择顺序。每组输出须通过定义契约和已见卡片的引文校验。

多组结果再进行一次语义协调，使用定义候选和已有引用，不重新发送原卡。协调不得添加未见引用或删除变量、模型关系。随后本地合并检查 ID、符号、依赖及循环；冲突保留为未解决项，独立定义不因符号冲突被直接丢弃。局部结构检查和 LLM 协调均不是数学证明。

定义组与协调结果通过现有内容寻址缓存存储在 `.science/cache/experiment_design/definitions-v1`，缓存身份包含完整请求、模型和 provider。重跑相同输入可以复用已成功批次；输入或模型改变会失效。它不等于整个 science run 的阶段恢复，也不会改变已经发出的请求。

每 30 秒输出 `llm_request_waiting`，每组输出组号、补取轮次、卡片数、提示词字符数和缓存命中状态。ExperimentDesign 默认设置 `request_timeout_seconds: 600`、`request_max_retries: 1`，传递给 SDK；这是请求超时/重试设置，不是整个阶段的硬墙钟截止时间。等待心跳表示本地仍在等待，不表示服务端正在生成。

形式推理和修订使用最多 40 张相关原卡及轻量索引。设计组合和 Author 正文章节在证据超过 40 张时只保留一次相关卡片正文，嵌套重复证据转成 ID 索引；原始 EvidenceBundle、证据账本和引用许可集合不变。这些后续阶段目前执行一次相关性检索，尚无交互式补取循环。定义阶段才执行缺口补取。检索遗漏应作为不确定性处理，不能当成反证。
