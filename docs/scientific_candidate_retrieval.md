# Scientific candidate discovery and bounded comparison

Survey defaults to model-approved complete queries with early batch relevance assessment and bounded feedback. See [Survey feedback retrieval](survey_feedback_retrieval.md) for the current workflow, numerical admission rules and budgets. No discipline-specific candidate lists or evidence axes are embedded.

The four-stage mechanism described below remains available only with `survey_search_strategy: staged_legacy`. Its configuration table and automatic matrix scheduling do not describe the default workflow.

## Objects and decision roles

Extraction registers names and aliases only when visible in source titles or abstracts, with exact quotations. Each object has a role per SH: `decision_candidate`, `comparator`, `target_system`, `source_system_proxy`, `mechanism_or_component`, `background_entity`, or `role_unresolved`. Roles concern what the research question asks to select, not whether suitability in the target system has already been proven. Conflicting role observations remain unresolved; all objects remain in the audit roster.

Before evidence screening, a separate LLM relevance pass examines every registered object in batches of 24. Each prompt includes the original topic verbatim, the research context, SH questions and scope, and each object's identity, SH assignments, prior roles and grounded discovery quotations. It asks whether the object is a plausible decision candidate or comparator for the original research goal and the particular SH. Shared terminology alone does not qualify an object; plausible alternatives and transferable options need not already be proven in the exact target system. No domain-specific names or exclusion lists control admission.

Only `relevant` objects with decision/comparator roles receive comparison queries. A bounded clarification pass handles relevant objects with unresolved roles. Model omissions, invalid responses and unavailable models produce `assessment_unavailable`; unsubmitted batches produce `deferred_budget`. Neither becomes `irrelevant` or scientific negative evidence. Results must reference IDs and SH assignments from the current batch and include a boolean verdict, recognized role and reason. All objects retain per-SH relevance verdicts and reasons. Pending relevance judgments prevent a complete-comparison claim.

## Scheduling

Before discovery retrieval, a model classifies contract concepts as distinctive names, general properties, evaluation terms, ambiguous abbreviations or unresolved concepts. Only a distinctive name with an explicit semantic reason may be searched alone. All other concepts retain one research-system or solution-class context and one purpose in a short query. The model proposes a target-system → source-system → solution-class ladder; if classification fails or model capacity is unavailable, contract anchors remain attached. No domain keyword list decides whether a concept is distinctive.

Discovery submits at most one lane per SH per batch, rotating SHs before subsequent lanes. The default batch size is four and never exceeds remaining discovery HTTP capacity. Valid zero or fewer than `min_slot_candidates_before_relaxation` results trigger the next context level; provider failure does not justify dropping context. Expansions join the end of the SH queue so initial concept views receive an opportunity first. Context expansion is finite and never becomes a bare property query. Pending lanes are recorded as `deferred_budget` without entering a provider once stage or total capacity is exhausted. Actually executed failures or valid empty results can trigger one fallback per SH using supplement capacity even when other lanes are deferred; deferral alone cannot trigger fallback. Model planning consumes the existing discovery assessment allowance, grouped in four-SH batches. Cached requests can be reused within an admitted batch; exhausted discovery capacity conservatively defers queued lanes, including potentially cached ones.

Survey first assesses discovery papers against contract-derived screening dimensions. Decision candidates receive independent screening opportunities in round-robin order across SHs and candidates. By default, one screening dimension is used; explicit screening priorities take precedence over contract order. At most six candidates per SH are promoted, using admissible evidence dimensions, directness, independence and class diversity rather than paper volume. An independent challenger receives a reserved place when available.

Existing papers are assessed for promoted candidates before new queries are planned. Comparison queries target unsatisfied evidence requirements in batches of four. Explicit `minimum_independent_works` requirements use deduplicated work identities. Counterevidence remains a separate optional dimension. Canonical names are queried first; one purpose rewrite and one observed alias are queried only when evidence remains insufficient, using supplement capacity. Rewrites choose a different clean contract concept or meaning and are skipped if none exists. Provider fallback follows unsuccessful recall and uses the supplement reservation. Low-yield stopping applies after promoted candidates have received a first opportunity. Candidates outside the completed scope remain visible and cannot be presented as fully compared.

The query compiler recognizes candidate identities through the registry. Contaminated concepts fall back to a clean evidence-purpose concept or slot meaning; they do not append a fixed rival to every candidate's query. Direct comparison requires explicit metadata declaring comparator identities. This conservative compiler can lose useful detail embedded in a contaminated concept; clean contract concepts are preferred.

## Budgets and request reuse

Default configuration under `ModuleInfo.WorkCollector`:

| Setting | Default |
| --- | ---: |
| `candidate_http_attempt_limit` | 120 |
| `candidate_discovery_http_limit` | 20 |
| `candidate_discovery_planning_batch_size` | 4 SHs |
| `candidate_discovery_batch_size` | 4 lanes |
| `candidate_screening_http_limit` | 30 |
| `candidate_comparison_http_limit` | 50 |
| `candidate_supplement_http_limit` | 20 |
| `candidate_model_assessment_limit` | 160 |
| discovery / screening / comparison / supplement assessment limits | 60 / 40 / 60 / 20 |
| `candidate_relevance_assessment_limit` | 20 batches |
| `candidate_relevance_batch_size` | 24 objects |
| `candidate_role_clarification_limit` | 12 objects |
| `candidate_screening_dimensions` | 1 |
| `candidate_deep_comparison_limit_per_sh` | 6 |
| `candidate_comparison_batch_size` | 4 |
| `candidate_low_yield_batches` | 3 |

`RetrievalBudget` atomically reserves every actual literature transport attempt across workers. The first request consumes its stage reservation; retries, fallback and alias queries consume supplement capacity. All share the same total cap. OpenAlex charges at its HTTP adapter, including redirects. arXiv and Semantic Scholar charge before each explicit attempt and disable redirects. Metadata and graph retrieval through providers sharing the run configuration retain the same budget after seed selection. PDF acquisition and unrelated services are outside this literature HTTP budget.

Persistent cache hits consume no network budget. Run-local identical requests are coalesced even when persistent caching is disabled. Results and failure states are reused with isolated copies while logical lane provenance and candidate-specific assessments remain independent.

Candidate model budgeting counts extraction, relevance screening, clarification and evidence-assessment submissions, not token usage or internal LLM transport retries. Relevance screening uses its own stage allowance under the unchanged global model cap of 160. With available capacity, 346 objects require 15 relevance requests rather than 346. Stage ceilings share the global cap and do not guarantee dedicated capacity. Evidence-assessment prompts are created lazily in round-robin order. Deferred assessments do not permanently occupy a dimension; unavailable evidence assessments have bounded reattempts.

Candidate extraction constructs prompts only for budget-admitted batches and parses only those submitted batches. The extraction audit distinguishes `planned_batches`, `submitted_batches`, `failed_batches`, `deferred_batches` and `deferred_paper_ids`. Unsubmitted batches are budget deferrals, not missing model responses. Per-SH roles must be single recognized strings; arrays, objects and other malformed values preserve the grounded object with `role_unresolved` instead of aborting registration or admitting it for comparison.

## Scientific admission and balance

Effective evidence requires grounded quotations and independent scope, evidence-role and minimum-evidence checks. Explicit project exclusions apply. Query hits, cache success and paper counts cannot establish evidence. Fulltext acquisition remains separate from title/abstract admission.

Effective works are deduplicated across providers using DOI where possible. Shared works contribute `1/k` to each of their k candidates. Coverage, entropy and normalized Gini describe decision candidates, including those with zero evidence. Entropy is `-sum(p_i log(p_i))`; normalized entropy divides by `log(N)`. Normalized Gini multiplies Gini by `N/(N-1)`. Concentration is flagged at normalized Gini >= 0.6 or normalized entropy < 0.5. These are diagnostics, not reasons to search solely to equalize naturally different literature volumes.

`comparison_scope` separately reports discovered objects, decision candidates, screening assignments/completions, screening coverage, promoted assignments, deep-comparison completions/coverage, unresolved roles and deferred candidates. Completing the promoted subset never establishes coverage over all registered decision candidates.

Comparison permission requires successful extraction and observed discovery, at least two candidates in each comparison group, complete required matrices, resolved roles and matching explicit kind/classification level. Staged runs also require complete screening and no budget deferrals. Matching kind and level is necessary but does not prove scientific comparability. Neither metrics nor discovery establish global candidate completeness, query stability, effect quality or scientific optimality.

## States, persistence and logging

`deferred_budget`, `unsearched`, valid `searched_zero`, `failed`, `assessment_unavailable`, `retrieved_but_not_eligible`, incomplete evidence and explicit `negative_evidence` remain distinct. Budget exhaustion is never scientific absence. Stop reasons identify completion, exhausted stage budgets, low yield, exhausted query variants, provider failures, assessment availability and absence of admitted decision candidates.

Promoted candidates reserve seed representation; unpromoted candidates stay in the audit roster without expanding seed quotas for every discovered object. Survey freezes the ledger; its handoff preserves roles, scope, budget, primary/challenger identities and comparison permission. The final saved ledger refreshes usage after metadata/graph retrieval and verifies the snapshot fingerprint. Ordinary source edits do not use hash gates.

Logs expose extraction counts, relevance-screening object counts and batch counts, screening totals and unique candidates, batch phases and sizes, HTTP attempts by stage, model submissions, cache/reuse hits, stop reason, comparison scope and entropy/Gini. `eligible`, `completed` and `deferred` in evidence screening count candidate–SH assignments; `unique_candidates` counts distinct identities. Relevance audit counts and per-object reasons are saved in the candidate ledger. Exact queries and provenance remain in the artifact. Survey writing receives comparison restrictions and checks explicit unsupported best-candidate assertions, independently of optional claim traces.

## Verification boundaries

Regression tests use controlled provider/model responses and exercise production scheduling, transport attempt caps, retries, redirects, request reuse, hundreds of candidates, deferrals, grounded admission, frozen handoff and challenger retention. No fresh external-provider/model run is implied by these tests. Source extraction and role/evidence judgments still depend on model accuracy.

The whole-repository regression completed with 1642 passed, 28 failed and 7 skipped. Its failing tests match the earlier baseline and concern CLI/experiment-design contracts, formal backends, model defaults, parameter-literature validation and vision formats. Later local refinements receive targeted regression checks. Those unrelated issues are not repaired by this retrieval change.
