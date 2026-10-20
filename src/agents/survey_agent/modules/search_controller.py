"""Model-approved, feedback-driven literature retrieval for Survey."""

from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
from pathlib import Path

from src.agents.survey_agent.utils.utils import extract_json
from src.pipeline.candidate_search_schedule import dimension_satisfied, interleave, screening_dimensions
from src.pipeline.evidence_coverage_ledger import associate_papers_with_subhypotheses, paper_identity
from src.pipeline.paper_identity import canonical_paper_id
from src.pipeline.retrieval_budget import RetrievalBudgetExceeded, model_request_scope
from src.pipeline.retrieval_lanes import candidate_evidence_dimensions
from src.pipeline.scientific_candidates import (
    DECISION_ROLES, OBJECT_ROLES, build_candidate_ledger, evidence_id, freeze_candidate_ledger,
    grounded_spans, is_decision_candidate, normalize_evidence_assessment, register_candidates,
)
from src.pipeline.survey_search_controller import (
    CONTEXT_LEVELS, OPENALEX_SEARCH_SEMANTICS, activate_candidates, admit_query, bounded_seed_selection, canonical_query, comparison_metrics,
    query_metrics, recover_query_context_level, score, feedback_field_gaps, recover_feedback_fields, seed_assessments,
)
from src.pipeline.survey_evidence_judgments import (
    assessment_is_excluded, assessment_is_irrelevant, candidate_discovery_status,
    evidence_boundaries, normalize_evidence_boundaries, project_is_excluded,
)
from src.pipeline.survey_response_normalization import (
    FormatBatch, align_paper_assessments, graph_role_fields, normalize_model_response, record_list, score_field, score_fields_raw,
    slot_contributions, source_summaries,
)
from src.pipeline.survey_prompt_budget import compact_value, fit_payload, planning_batches, project_fields, serialize_prompt
from src.pipeline.source_context import assessment_source, has_source_content


PLAN_PROMPT = """Plan literature queries using the original topic and all supplied SHs. Return ONE JSON
object {queries: [query objects], decisions: [{sub_hypothesis_id, action, reason, references,
query_ids}]}; no bare arrays, Markdown or multiple documents.
Each query requires query_id, sub_hypothesis_id, query, purpose, context_level
(target_system|source_system|solution_class), context_reason, expected_contribution,
fit_score, purpose_score, context_score (integers 0..5). Fit 3 = partial/proxy, 4..5 = specific
SH fit; purpose 3 = coherent need, 4..5 = concrete decision; context 0..2 = ambiguous/bare,
3 = explicit system/class, 4..5 = distinctive object or grounded transfer relationship.
Optional term_origins: [{term, origin: original_topic|SH|observed_paper|justified_generalization,
source_id, reason}]. These are semantic planning notes, not verbatim checks or verified evidence.
Use justified synonyms/generalizations and cross-SH context; never invent sources.
OpenAlex joins space-separated terms with AND. Build one complete identifying system/object/
class plus one search purpose, usually 5..14 English words (advisory; preserve full names).
Use uppercase OR and parentheses for alternatives, e.g. ("optical sensor" OR "electrical sensor")
calibration, or separate queries within budget. Do not conjoin all SH requirements, candidates,
proxy systems or quality criteria. Joint candidates require a direct-comparison purpose.
General attributes/ambiguous abbreviations need context; distinctive complete names may stand
alone. `context_level` is ONLY target_system, source_system or solution_class. Evidence-dimension
labels such as boundary_variable, boundary_test, comparable_endpoint, external_validation,
measurement or validation belong in purpose/expected_contribution/query_design, never in
context_level; if one appears, restate the retrieval context using the three allowed values.
Keep endpoints, controls and statistics for post-retrieval assessment unless they are
the search purpose. Optional query_design: {essential_context, alternative_groups,
post_retrieval_criteria, relaxation_strategy}. No automatic alias/dimension/concept expansion.
Discover independent alternatives, transferable methods and counterevidence. Unrelated entities
need a justified comparison purpose. Initially aim for 2..4 queries per SH (preferred count
supplied), covering target/problem and source-system/class perspectives where useful; fewer
queries are acceptable. Respect remaining SH/global budgets; feedback allows at most TWO per
SH per round. Use new query IDs; the controller resolves collisions across batches.
EVERY feedback query MUST itself include action (narrow_scope|broaden_context|resolve_name|
compare_alternative|seek_counterevidence), feedback_reason and feedback_references (at least
one supplied historical query, paper or candidate ID). Decisions may additionally link query_ids
using the same action. Example feedback fields within a query: {"action": "broaden_context",
"feedback_reason": "Zero results; replace the target context with a source system",
"feedback_references": ["ACTUAL_HISTORY_ID"]}.
Replace the example reference with a supplied ID; do not emit placeholders.
Diagnose metrics.contribution_outcomes and revision_guidance before revising:
- Valid returned_unique=0: FIRST reduce intersections/separate alternatives/use OR, then move
optional requirements to post-retrieval assessment, then replace restrictive target context
with a justified source system/class. Preserve purpose, use broaden_context, reference the
failed query and name the relaxed condition. Appending constraints/synonyms is not relaxation.
- Identity only: retain the candidate and seek local method/mechanism evidence.
- Target validation gap: retain candidate identity, use justified transfer context and record
untested target conditions. Ranking gap: seek comparable endpoints/comparators.
- Actual unrelated/excluded results: restore identifying context/respect explicit exclusions.
useful=0 does not reject a candidate or mean returned_unique=0. Local/proxy contributions can
be useful without target validation or ranking evidence. Provider failure/budget deferral is
not scientific absence; incomplete assessments need assessment before query revision.
Precision >=.6 with novelty <.2 suggests uncovered questions. Matrices audit evidence; they
do not generate tasks automatically. Every continuation needs concrete historical references;
you may stop with no queries and an explicit stop decision while preserving unresolved gaps.
Inputs may be compacted/split: omitted text is unknown, not negative evidence. Propose only
gaps grounded in the visible batch; the controller merges proposals under shared round limits.
"""

EVIDENCE_BOUNDARIES_PROMPT = """For EVERY SH assessment include evidence_boundaries as an object:
{discovery_relevance: relevant|irrelevant|unknown,
local_contribution: supported|identity_only|none|unknown,
target_validation: direct|indirect|not_reported|unknown,
ranking_evidence: sufficient|insufficient|not_applicable|unknown,
exclusion_basis: explicit_criterion|irrelevant|insufficient_evidence|none|unknown,
validation_gaps: [string]}.
These are FOUR INDEPENDENT judgments. Discovery asks whether the object is worth investigating;
local contribution asks whether this paper supports an identifiable method, mechanism,
comparison principle, source-system fact or counterevidence. Target validation asks whether
applicability to the exact target was tested. Ranking asks whether enough comparable evidence
exists for the proposed ordering; a single interesting paper does not establish this.
Missing target validation or ranking data means insufficient evidence, NOT irrelevant/excluded.
Use discovery_relevance=relevant for a justified option even when only identity is established.
Use local_contribution=supported for a source-grounded partial/proxy contribution; keep its
claim limits and actual target_validation. Identity alone is identity_only, not efficacy evidence.
Set exclusion_basis=explicit_criterion only for an actual supplied exclusion with a stated match;
use irrelevant only for actual semantic irrelevance. An unreported outcome, unknown metadata,
missing abstract or unperformed target experiment is not an explicit exclusion. Record the
specific untested transfer conditions and missing comparisons in validation_gaps. Do not infer
negative findings from silence. These judgments add no evidence beyond the supplied sources.
"""

ASSESS_PROMPT = """Assess this batch against the FULL original topic and EVERY supplied SH, and extract
source-grounded scientific objects in the SAME response. Return JSON {papers: [{paper_id,
project_score, project_reason, excluded: boolean, exclusion_basis, exclusion_reason,
sh_assessments: [{sub_hypothesis_id, evidence_boundaries,
semantic_relevance_score, overall_relation, contribution_types: [string],
candidate_slot_contributions: [{slot_name: supplied slot ID,
support_level: direct|partial|indirect|none, reason: string}],
supported_minimal_claims, claim_limits, evidence_spans: [{source: title|abstract|source_excerpt, text: source-based summary}],
explicit_exclusion_matches, recommended_graph_role, confidence, reason}], scientific_objects:
[{name, aliases, candidate_kind, taxonomic_level, sub_hypothesis_ids,
roles_by_subhypothesis, role_reason, evidence_spans: [{source, text: source-based summary}],
dimension_assessments: [{sub_hypothesis_id, dimension, scope_pass: boolean,
evidence_role_pass: boolean, minimum_evidence_pass: boolean, stance: supporting|negative|mixed|neutral,
evidence_spans, claim_limits, reason}]}]}]}.
Role options: decision_candidate, comparator, target_system, source_system_proxy,
mechanism_or_component, background_entity, role_unresolved. Selection roles describe options
the research question actually chooses between, not every named entity. Identify objects and
summarize their contribution semantically from the supplied title, abstract or source_excerpt.
source_excerpt is actual retrieved content; source_context identifies its type, version and
reading range. A repository README or dataset description establishes only what it reports.
An abstract remains an abstract; never treat a discovery snippet as source evidence. Canonical names,
aliases and paraphrases need not match the source wording literally. Do not invent reported
findings; these summaries are model assessments, not verified verbatim quotations.
Project and SH scores are integers 0..5:
0 unrelated/excluded, 1 shared terms only, 2 background without identifiable contribution,
3 meaningful partial/proxy/exploratory contribution, 4 useful method/mechanism/comparison/
counterevidence, 5 specific key contribution. Counterevidence and transferable systems can score
high; state scope limits. Missing abstracts or insufficient information: still emit the required
integer score from the available title, query provenance and supplied context, explain uncertainty
in reason, and do not invent a specific finding. Project scores summarize breadth, not a veto on a useful SH contribution.
Do not lower local contribution merely because the paper does not supply the final target
validation or candidate ordering. Paper-level exclusion_basis uses the same allowed values as
evidence_boundaries.exclusion_basis; excluded=true requires actual irrelevance or an explicit
criterion, explained in exclusion_reason. Evidence dimensions have INDEPENDENT scope/minimum requirements;
a paper need not satisfy all dimensions. Evaluate only identifiable reported information.
Do not convert discovery identity or query hits into evidence of efficacy.
recommended_graph_role must be evidence_seed|exploration_seed|context_seed|do_not_expand|undetermined.
This field ONLY recommends citation-graph expansion. It does not decide seed relevance.
Use do_not_expand for a useful paper whose citation graph should not be followed; use
undetermined when this recommendation is unknown. Transferable methods, mechanisms,
context and counterevidence may contribute without graph expansion.
Every collection is a JSON array, including a single record. Use [] for no contributions,
never a keyed dictionary, a bare string or null in place of an array. aliases,
sub_hypothesis_ids, supported_minimal_claims, claim_limits and explicit_exclusion_matches
are arrays of strings; scientific_objects, sh_assessments, dimension_assessments and
evidence_spans are arrays of objects. name, candidate_kind, taxonomic_level, role_reason,
project_reason, overall_relation, recommended_graph_role, confidence and reason are strings.
roles_by_subhypothesis is an object mapping supplied SH IDs to one role string.
Use only this SH's supplied slot_recovery_tasks.slot_name in candidate_slot_contributions;
support_level is an explicit reported judgment, never guess it from a slot name.
Scores are integers 0..5 and are never null or omitted; scope_pass, evidence_role_pass,
minimum_evidence_pass and excluded are JSON booleans. All source summaries require
source="title", "abstract" or "source_excerpt" and a nonempty text string referring to the supplied source.
Always emit project_score on each paper and semantic_relevance_score on EVERY SH assessment.
Use JSON numbers, for example "project_score": 4 and "semantic_relevance_score": 3.
Do not use confidence as a relevance score or omit scores because a graph is not expanded.
If genuinely uncertain, emit the lowest defensible integer score and explain which source information
is missing in reason; never omit the score or replace it with confidence.
Example slot contribution: {"slot_name": "SUPPLIED_SLOT_ID", "support_level": "partial",
"reason": "This reported result addresses part of the required evidence."}
Replace SUPPLIED_SLOT_ID with a real supplied slot ID; do not emit the placeholder.
The top-level response MUST be one JSON object whose only collection wrapper is the `papers`
field. Do not return a bare array, one object per line, Markdown, or multiple JSON documents.
Return exactly one record for EACH input paper, with its supplied paper_id unchanged. Keep
assessments attached to that ID; do not substitute titles, reorder identities or omit records.
""" + EVIDENCE_BOUNDARIES_PROMPT + """

MANDATORY FINAL SCORE CHECK BEFORE RETURNING JSON:
1. Copy every input paper_id exactly once into the papers array.
2. For every paper, include project_score as a JSON integer from 0 through 5 and include a nonempty project_reason.
3. For every supplied SH ID, include exactly one sh_assessments entry with that exact sub_hypothesis_id.
4. In every sh_assessments entry, include semantic_relevance_score as a JSON integer from 0 through 5 and include a nonempty reason.
5. Never omit these score keys, emit null, use a string, use confidence, or stop after the first paper or SH.
Do this completeness check against the supplied input arrays before sending the response.
"""

CONFIRM_PROMPT = """Confirm merged objects' relevance and roles in batches using the FULL original
topic, all SH questions and previously assessed source summaries. Return JSON {candidates:
[{candidate_id, assessments: [{sub_hypothesis_id, project_score, sh_score,
candidate_role, reason, evidence_boundaries}]}]}. Scores describe DISCOVERY relevance, not
target efficacy or ranking maturity. Scores are integers 0..5, with 0 unrelated/excluded, 1 lexical
overlap only, 2 background without identifiable contribution, 3 meaningful partial/proxy,
4 useful specific contribution, 5 key contribution. Unknown: null, not zero.
Role options: decision_candidate, comparator, target_system, source_system_proxy,
mechanism_or_component, background_entity, role_unresolved. Assess each requested object-SH
pair. Decision candidates are solutions the question selects/compares, not incidental names.
Do not demand proven target suitability just to admit a candidate. Transferability and
counterevidence are legitimate. Confirmation resolves merged role conflicts, not new extraction.
Score object relevance independently of its role and the source paper's evidence strength.
A background or mechanism object can be highly relevant; a selectable option can be relevant
while its source establishes identity only. Preserve its role and describe source limitations.
The top-level response MUST be one JSON object with a `candidates` array. Do not return a bare
array, Markdown, or multiple JSON documents.
""" + EVIDENCE_BOUNDARIES_PROMPT + """
Before returning, check every supplied candidate_id and each of its sub_hypothesis_ids:
emit exactly one assessments entry per requested candidate-SH pair. EACH entry MUST contain
both project_score and sh_score as JSON integers 0..5, candidate_role and a nonempty reason.
These are the candidate's own discovery-relevance judgments; do not simply copy a source
paper's score. Missing target validation or ranking evidence does not make relevance unknown.
Never omit either score key, substitute confidence, or put scores outside assessments entries.
Use null only when the supplied information cannot support a relevance judgment, explain the
specific missing information in reason, and retain all other valid fields. Do not invent scores.
"""

CONFIRM_SCORE_REPAIR_PROMPT = """Complete only the missing or invalid discovery-relevance scores
for the supplied repair_items using the original topic, SHs, candidate and source assessments.
Return ONE JSON object {candidates: [{candidate_id, assessments: [{sub_hypothesis_id,
project_score, sh_score}]}]}. Copy candidate_id and sub_hypothesis_id exactly from repair_items.
For EACH requested pair, return the fields in missing_fields as JSON integers 0..5:
0 unrelated/excluded, 1 shared terms only, 2 background without identifiable contribution,
3 meaningful partial/proxy contribution, 4 useful specific contribution, 5 key contribution.
Score the candidate itself; a source paper's score is context, not an automatic replacement.
Missing target validation or ranking is not missing discovery relevance. Preserve the existing
role, reason, evidence boundaries and any valid score; do not reassess or return other fields.
If source information cannot support a score, return null for that field. Do not invent scores,
new evidence, candidate IDs or SH IDs. Return JSON only: group all requested SH assessments
under exactly one candidates entry per candidate_id, with one assessment per requested pair.
"""


FEEDBACK_REPAIR_PROMPT = """Repair only the feedback metadata of the supplied existing queries.
Return ONE JSON object {queries: [{repair_item_id, action, feedback_reason, feedback_references}]}.
Allowed actions: narrow_scope, broaden_context, resolve_name, compare_alternative, seek_counterevidence.
Use the original query and its own batch decisions plus supplied history to resolve metadata.
References must be actual supplied historical query, paper, candidate or SH IDs. Do not invent
evidence or rewrite queries, scores, purposes or IDs. Keep already valid fields unchanged.
If the association or action remains uncertain, omit that item; do not guess. No Markdown.
"""

CONTEXT_REPAIR_PROMPT = """Repair retrieval-context labels for the supplied queries using the original
topic, all SHs, each complete query and its purpose. Return ONE JSON object
{queries: [{repair_item_id, context_level, context_reason}]}.
context_level must be target_system (exact research target), source_system (a justified
transfer/proxy system), or solution_class (a broad method/object class). Evidence dimensions
and study purposes are independent of this level; the same dimension can use any context.
Determine the level semantically from the complete query, never from the erroneous label
alone. Do not alter the query, IDs, scientific purpose, scores or feedback fields. If the
context cannot be determined, omit that item. No Markdown or invented evidence.
"""


class SurveySearchController:
    def __init__(self, collector, topic, research_context, plan, subhypotheses):
        self.collector, self.topic, self.context, self.plan = collector, topic, research_context, plan
        self.subhypotheses = list(subhypotheses)
        self.by_sh = {sh["sub_hypothesis_id"]: sh for sh in self.subhypotheses}
        self.budget = collector._candidate_retrieval_budget
        self.papers, self.registry, self.observations, self.history, self.lanes, self.summaries = [], [], [], [], [], []
        self.query_audit, self.decisions = [], []
        self.object_audit = []
        self.format_audit = []
        self.assessment_alignment_audit = []
        self.assessment_audit_write_failed = False
        self.prompt_audit = []
        self.format_batch_counts = Counter()
        self.counts = Counter()
        self.query_ids = set()
        self.per_sh_limit = self.setting("survey_queries_per_sh", 60)
        self.logical_limit = min(self.setting("survey_logical_query_limit", 60), self.per_sh_limit * len(self.subhypotheses))
        self.result_limit = min(self.setting("survey_results_per_query", 32), 32)
        self.paper_batch = self.setting("survey_paper_assessment_batch_size", 4)
        self.object_batch = self.setting("candidate_relevance_batch_size", 24)
        self.query_batch = self.setting("survey_query_workers", 4)
        self.dimensions = {sh_id: candidate_evidence_dimensions(sh) or sh.get("slot_recovery_tasks", []) for sh_id, sh in self.by_sh.items()}
        self.stop_reason = "feedback_round_limit"
        self.confirmed_sources = {}
        self.feedback_lease = None
        self.feedback_repair_attempts = 0
        self.context_repair_attempts = 0
        self.confirmation_score_repair_requests = 0
        self.confirmation_score_repaired_pairs = set()
        self.planning_outcome = {}

    def setting(self, key, default):
        value = self.collector._work_collector_setting(key, default)
        try:
            return max(1, int(value))
        except (TypeError, ValueError, OverflowError):
            self.collector.logger.warning("Survey setting format warning: key=%s value=%r; using default=%s.", key, value, default)
            return default

    def unique_query_id(self, proposed):
        proposed = str(proposed or "query").strip() or "query"
        used = self.query_ids | {entry.get("query_id") for entry in self.history if isinstance(entry, Mapping)}
        if proposed not in used:
            return proposed
        suffix = 1
        while f"{proposed}.r{len(self.history)}.{suffix}" in used:
            suffix += 1
        return f"{proposed}.r{len(self.history)}.{suffix}"

    def format_batch(self, stage, **context):
        self.format_batch_counts[stage] += 1
        return FormatBatch(stage, self.format_batch_counts[stage], **context)

    def publish_format(self, diagnostics):
        if diagnostics.recoveries or diagnostics.issues or diagnostics.suppressed_issues:
            self.format_audit.append(diagnostics.publish(self.collector.logger))

    def records(self, value, field, stage, diagnostics=None, **context):
        if diagnostics is None and isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
            return value
        owned = diagnostics is None
        diagnostics = diagnostics or self.format_batch(stage)
        result = record_list(value, field, diagnostics, **context)
        if owned:
            self.publish_format(diagnostics)
        return result

    def checkpoint_assessment_alignment(self, alignment, diagnostics):
        base_dir = str(self.collector._basic_info_value("base_dir", "") or "").strip()
        if not base_dir or self.assessment_audit_write_failed:
            return
        path = Path(base_dir) / "survey_assessment_alignment.jsonl"
        record = {**alignment, "recoveries": dict(diagnostics.recoveries),
            "visible_issues": diagnostics.issues, "suppressed_issues": diagnostics.suppressed_issues}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError) as exc:
            self.assessment_audit_write_failed = True
            self.collector.logger.warning("Survey assessment audit checkpoint unavailable: path=%s reason=%s; retaining diagnostics in retrieval artifacts.", path, exc)

    def model(self, prompts, description, lease=None, diagnostics=None, workers=None):
        if not prompts:
            return []
        bounded_prompts = []
        for prompt in prompts:
            original_size = self.measure_prompt(prompt)
            if original_size > self.prompt_limit():
                offset = prompt.find('{"original_topic"')
                if offset >= 0:
                    prefix, payload = prompt[:offset], json.loads(prompt[offset:])
                    prompt = serialize_prompt(prefix, fit_payload(prefix, payload, self.measure_prompt, self.prompt_limit()))
                self.collector.logger.info("Survey input compacted: stage=%s input_units=%s limit=%s.",
                    description, self.measure_prompt(prompt), self.prompt_limit())
                self.prompt_audit.append({"stage": description, "original_input_units": original_size,
                    "submitted_input_units": self.measure_prompt(prompt), "input_limit": self.prompt_limit(),
                    "status": "compacted"})
            if self.measure_prompt(prompt) > self.prompt_limit():
                self.collector.logger.warning("Survey input unavailable: stage=%s reason=prompt_budget_too_small; preserving results.", description)
                return [{"_survey_response_unavailable": True} for _prompt in prompts]
            bounded_prompts.append(prompt)
        prompts = bounded_prompts
        chat = getattr(self.collector, "chat_agent", None)
        owned = lease is None
        format_batches = diagnostics or [self.format_batch(description) for _prompt in prompts]
        try:
            lease = lease or self.budget.reserve_model_capacity(len(prompts))
        except RetrievalBudgetExceeded:
            self.stop_reason = "model_budget_exhausted"
            for batch in format_batches:
                batch.unresolved("response", "model_budget_unavailable")
            return [{"_survey_response_unavailable": True} for _prompt in prompts]
        try:
            if chat is None:
                for batch in format_batches:
                    batch.unresolved("response", "model_unavailable")
                return [{"_survey_response_unavailable": True} for _prompt in prompts]
            with model_request_scope(self.budget, lease):
                if not getattr(chat, "accounts_model_attempts", False):
                    for _prompt in prompts:
                        self.budget.charge_model_attempt(lease)
                options = {"workers": workers} if workers is not None else {}
                responses = chat.batch_remote_chat(prompts, desc=description, temperature=0.0,
                    strict_input_budget=True, max_output_tokens=16000, **options)
            parsed = []
            for index in range(len(prompts)):
                try:
                    value = extract_json(responses[index])
                    collection_field = ("papers" if description == "Assessing Survey Papers and Objects"
                        else "candidates" if description == "Confirming Survey Candidate Relevance" else "queries")
                    parsed.append(normalize_model_response(value, collection_field=collection_field,
                        diagnostics=format_batches[index]))
                except (IndexError, TypeError, ValueError, AttributeError) as exc:
                    if description == "Assessing Survey Papers and Objects":
                        format_batches[index].response_audit = {"status": "invalid_or_missing_JSON",
                            "raw_response": responses[index] if isinstance(responses, (list, tuple)) and index < len(responses) else None}
                    format_batches[index].unresolved("response", "invalid_or_missing_JSON", error=str(exc), response_index=index)
                    parsed.append({"_survey_response_unavailable": True})
            return parsed
        except Exception as exc:
            self.collector.logger.warning("Survey model batch unavailable: stage=%s reason=%s.", description, exc)
            for batch in format_batches:
                batch.unresolved("response", "request_layer_failure", error=str(exc))
            return [{"_survey_response_unavailable": True} for _prompt in prompts]
        finally:
            if owned:
                self.budget.release_model_capacity(lease)
            if diagnostics is None:
                for batch in format_batches:
                    self.publish_format(batch)

    def payload(self):
        context = project_fields(self.context, ("project_id", "research_question", "objective", "research_objective",
            "normalized_objective", "target_system", "scientific_scope", "constraints", "decision_question",
            "declared_domain", "primary_discipline", "secondary_disciplines", "core_entities", "exclude_anchors"))
        hypotheses = [project_fields(sh, ("sub_hypothesis_id", "title", "question", "question_kind",
            "scientific_scope", "required_slots", "slot_definitions", "research_role", "challenge_target",
            "allowed_evidence_scope", "excluded_evidence_scope", "slot_recovery_tasks")) for sh in self.subhypotheses]
        for sh in hypotheses:
            sh["slot_recovery_tasks"] = [project_fields(task, ("slot_name", "evidence_role", "meaning",
                "minimum_evidence", "required", "minimum_independent_works", "admission_rule"))
                for task in sh.get("slot_recovery_tasks", []) if isinstance(task, Mapping)]
        return {"original_topic": self.topic, "research_context": compact_value(context),
                "subhypotheses": [compact_value(sh) for sh in hypotheses], "budget": self.budget.snapshot(),
                "logical_calls": sum(self.counts.values()), "logical_limit": self.logical_limit,
                "queries_used_by_sh": dict(self.counts), "per_sh_query_limit": self.per_sh_limit}

    def measure_prompt(self, prompt):
        chat = getattr(self.collector, "chat_agent", None)
        encoder = getattr(chat, "encode_with_fallback", None)
        if callable(encoder):
            return len(encoder(prompt, model=getattr(chat, "model_name", "gpt-4o-mini"))[0])
        return len(prompt.encode("utf-8"))

    def prompt_limit(self):
        chat = getattr(self.collector, "chat_agent", None)
        api_config = getattr(getattr(chat, "config", None), "APIInfo", None)
        available = int(getattr(api_config, "llm_max_context_length", 880000)) - 16000 - 1024
        return min(self.setting("survey_prompt_input_limit", 160000), max(0, available))

    def source_is_eligible(self, paper, sh_id):
        return any(item.get("sub_hypothesis_id") == sh_id for item in seed_assessments(paper))

    def source_evidence(self, record, sh_id):
        sources = []
        for paper in self.papers:
            if paper_identity(paper) not in record["discovery_paper_ids"]:
                continue
            project = paper.get("project_relevance", {})
            assessment = next((item for item in paper.get("sh_semantic_assessments", [])
                if item.get("sub_hypothesis_id") == sh_id), {})
            project_score, sh_score = score(project.get("relevance_score")), score(assessment.get("semantic_relevance_score"))
            if project_is_excluded(project) or assessment_is_excluded(assessment):
                status = "excluded"
            elif self.source_is_eligible(paper, sh_id):
                status = "eligible"
            elif project.get("assessment_status") != "assessed" or assessment.get("assessment_status") != "assessed" or project_score is None or sh_score is None:
                status = "assessment_unavailable"
            elif assessment_is_irrelevant(assessment):
                status = "source_relevance_conflict"
            else:
                status = "insufficient_evidence"
            sources.append({"paper_id": paper_identity(paper), "status": status,
                "project_score": project_score, "sh_score": sh_score,
                "project_reason": project.get("reason", ""), "sh_reason": assessment.get("reason", ""),
                "evidence_boundaries": evidence_boundaries(assessment)})
        statuses = {item["status"] for item in sources}
        status = next((value for value in ("eligible", "insufficient_evidence", "assessment_unavailable", "source_relevance_conflict", "excluded")
            if value in statuses), "assessment_unavailable")
        return {"status": status, "sources": sources,
            "eligible_paper_ids": [item["paper_id"] for item in sources if item["status"] == "eligible"]}

    def recover_feedback_queries(self, queries, scoped_decisions, references, diagnostic, round_index):
        normalized = []
        pending = []
        for index, raw in enumerate(queries):
            result, recovered = recover_feedback_fields(raw, scoped_decisions[index], references)
            for field in recovered:
                diagnostic.recovered(field, "associated_decision_to_query")
            normalized.append(result)
            gaps = feedback_field_gaps(result, references)
            candidate = dict(result)
            for field in ("fit_score", "purpose_score", "context_score"):
                candidate[field] = score_field(raw, field, diagnostic)
            eligible, _reason = admit_query(candidate, self.subhypotheses, self.topic, self.papers)
            if gaps and eligible:
                pending.append({"repair_item_id": str(index), "query": result, "missing_fields": gaps,
                                "decisions": scoped_decisions[index]})
        if not pending:
            return normalized
        limit = self.setting("survey_feedback_repair_limit", 1)
        item_limit = self.setting("survey_feedback_repair_item_limit", 12)
        if self.feedback_repair_attempts >= limit or not self.budget.model_remaining():
            self.collector.logger.info("Survey feedback repair skipped: round=%s pending=%s reason=%s.",
                round_index, len(pending), "repair_limit" if self.feedback_repair_attempts >= limit else "model_budget_exhausted")
            return normalized
        selected = pending[:item_limit]
        payload = self.payload()
        payload.update(round=round_index, repair_items=selected, known_reference_ids=sorted(references),
                       query_history=compact_value(self.history))
        payload = fit_payload(FEEDBACK_REPAIR_PROMPT, payload, self.measure_prompt, self.prompt_limit())
        prompt = serialize_prompt(FEEDBACK_REPAIR_PROMPT, payload)
        self.feedback_repair_attempts += 1
        repair_diagnostic = self.format_batch("feedback_repair", retrieval_round=round_index)
        self.collector.logger.info("Survey feedback repair: round=%s attempt=%s/%s items=%s deferred=%s.",
            round_index, self.feedback_repair_attempts, limit, len(selected), len(pending) - len(selected))
        results = self.model([prompt], "Repairing Survey Feedback Structure", diagnostics=[repair_diagnostic], workers=1)
        patches = self.records(results[0].get("queries", []), "queries", "feedback_repair", repair_diagnostic)
        by_id = {}
        for patch in patches:
            identifier = patch.get("repair_item_id")
            if isinstance(identifier, str):
                by_id.setdefault(identifier, []).append(patch)
        for item in selected:
            patches_for_item = by_id.get(item["repair_item_id"], [])
            if len(patches_for_item) != 1:
                continue
            patch = patches_for_item[0]
            result = dict(item["query"])
            for field in item["missing_fields"]:
                if field in patch:
                    result[field] = patch[field]
            if feedback_field_gaps(result, references):
                continue
            normalized[int(item["repair_item_id"])] = result
            diagnostic.recovered("queries", "bounded_feedback_metadata_repair")
        self.publish_format(repair_diagnostic)
        self.prompt_audit.append({"stage": "feedback_repair", "round": round_index,
            "attempt": self.feedback_repair_attempts, "submitted_items": len(selected),
            "deferred_items": len(pending) - len(selected), "input_units": self.measure_prompt(prompt),
            "repair_response": results[0]})
        return normalized

    def repair_query_contexts(self, queries, diagnostic, round_index):
        normalized = [recover_query_context_level(query, diagnostic) for query in queries]
        pending = []
        for index, query in enumerate(normalized):
            level = query.get("context_level")
            if isinstance(level, str) and level in CONTEXT_LEVELS:
                continue
            pending.append({"repair_item_id": str(index), "query": query})
        if not pending or self.context_repair_attempts >= 1 or not self.budget.model_remaining():
            return normalized
        selected = pending[:32]
        payload = self.payload()
        payload.update(round=round_index, repair_items=selected)
        payload = fit_payload(CONTEXT_REPAIR_PROMPT, payload, self.measure_prompt, self.prompt_limit())
        self.context_repair_attempts += 1
        repair_diagnostic = self.format_batch("context_repair", retrieval_round=round_index)
        response = self.model([serialize_prompt(CONTEXT_REPAIR_PROMPT, payload)],
            "Repairing Survey Query Context", diagnostics=[repair_diagnostic], workers=1)[0]
        patches = self.records(response.get("queries", []), "queries", "context_repair", repair_diagnostic)
        by_id = {}
        for patch in patches:
            identifier = patch.get("repair_item_id")
            if isinstance(identifier, str):
                by_id.setdefault(identifier, []).append(patch)
        recovered = 0
        for item in selected:
            matches = by_id.get(item["repair_item_id"], [])
            if len(matches) != 1:
                continue
            patch = recover_query_context_level(matches[0], repair_diagnostic)
            level, reason = patch.get("context_level"), patch.get("context_reason")
            if not isinstance(level, str) or level not in CONTEXT_LEVELS or not isinstance(reason, str) or not reason.strip():
                continue
            result = dict(item["query"], context_level_raw=item["query"].get("context_level"),
                context_reason_raw=item["query"].get("context_reason"), context_level=level,
                context_reason=reason, context_level_recovery="model_semantic_repair")
            normalized[int(item["repair_item_id"])] = result
            diagnostic.recovered("context_level", "model_semantic_repair")
            recovered += 1
        self.publish_format(repair_diagnostic)
        self.prompt_audit.append({"stage": "context_repair", "round": round_index,
            "submitted_items": len(selected), "recovered_items": recovered,
            "unresolved_items": len(pending) - recovered, "repair_response": response})
        return normalized

    def planning(self, round_index):
        diagnostic = self.format_batch("planning", retrieval_round=round_index)
        payload = self.payload()
        payload.update(round=round_index, preferred_initial_queries=self.setting("survey_initial_queries_per_sh", 3),
            search_semantics=deepcopy(OPENALEX_SEARCH_SEMANTICS),
            used_query_ids=sorted({entry.get("query_id") for entry in self.history if isinstance(entry, Mapping)} | self.query_ids),
            query_history=[compact_value(project_fields(entry, ("query_id", "sub_hypothesis_id", "query",
                "query_design", "retrieval_round", "metrics"))) for entry in self.history],
            query_planning_audit=compact_value(self.query_audit), comparison_metrics=getattr(self, "metrics", {}))
        papers = []
        for paper in self.papers:
            assessments = [project_fields(item, ("sub_hypothesis_id", "assessment_status", "semantic_relevance_score",
                "overall_relation", "candidate_slot_contributions", "supported_minimal_claims", "claim_limits",
                "explicit_exclusion_matches", "evidence_boundaries", "reason")) for item in paper.get("sh_semantic_assessments", [])]
            papers.append(compact_value({"paper_id": paper_identity(paper), **assessment_source(paper),
                "project_relevance": paper.get("project_relevance"),
                "sh_semantic_assessments": assessments}))
        collections = {"paper_results": papers,
            "registered_objects": [compact_value(project_fields(record, ("candidate_id", "name", "canonical_name",
                "aliases", "roles_by_subhypothesis", "candidate_relevance_by_subhypothesis", "discovery_paper_ids",
                "candidate_relevance_scores_by_subhypothesis", "candidate_relevance_reasons",
                "candidate_source_evidence_by_subhypothesis", "candidate_admission_by_subhypothesis",
                "candidate_evidence_boundaries_by_subhypothesis"))) for record in self.registry],
            "evidence_ledger": [compact_value(project_fields(record, ("candidate_id", "minimum_evidence_matrix",
                "retrieval_status", "admission_status", "ranking_readiness_by_subhypothesis"))) for record in getattr(self, "ledger", {}).get("records", [])]}
        batches = planning_batches(PLAN_PROMPT, payload, collections, self.measure_prompt, self.prompt_limit())
        capacity = self.budget.model_remaining() + (self.feedback_lease["remaining"] if self.feedback_lease else 0)
        maximum = min(self.setting("survey_planning_batch_limit", 64), capacity)
        self.collector.logger.info("Survey planning input: round=%s batches=%s submitted=%s deferred=%s input_limit=%s.",
            round_index, len(batches), min(len(batches), maximum), max(0, len(batches) - maximum), self.prompt_limit())
        response = {"queries": [], "decisions": []}
        prompts = []
        for batch_index, batch in enumerate(batches[:maximum]):
            if not batch["paper_results"] and papers:
                batch["paper_results"] = [project_fields(papers[0], ("paper_id", "title", "project_relevance"))]
            batch["input_batch"] = batch_index + 1
            batch["input_batches"] = len(batches)
            prompt = serialize_prompt(PLAN_PROMPT, batch)
            if self.measure_prompt(prompt) > self.prompt_limit():
                batch = fit_payload(PLAN_PROMPT, batch, self.measure_prompt, self.prompt_limit())
                prompt = serialize_prompt(PLAN_PROMPT, batch)
            self.collector.logger.info("Survey planning batch: round=%s batch=%s/%s input_units=%s papers=%s objects=%s.",
                round_index, batch_index + 1, len(batches), self.measure_prompt(prompt), len(batch["paper_results"]), len(batch["registered_objects"]))
            self.prompt_audit.append({"stage": "planning", "round": round_index, "batch": batch_index + 1,
                "input_batches": len(batches), "input_units": self.measure_prompt(prompt), "input_limit": self.prompt_limit(),
                "paper_ids": [paper.get("paper_id") for paper in batch["paper_results"]],
                "candidate_ids": [record.get("candidate_id") for record in batch["registered_objects"]], "status": "submitted"})
            prompts.append(prompt)
        if self.feedback_lease is not None:
            self.budget.release_model_capacity(self.feedback_lease)
            self.feedback_lease = None
        workers = min(10, self.setting("survey_planning_workers", 10))
        self.collector.logger.info("Survey planning dispatch: round=%s batches=%s workers=%s.", round_index, len(prompts), workers)
        results = self.model(prompts, "Planning Survey Queries" if not round_index else "Reviewing Survey Search Feedback",
            diagnostics=[diagnostic for _prompt in prompts], workers=workers)
        scoped_decisions = []
        for result in results:
            local_records = {}
            for field in response:
                raw_value = result.get(field, [])
                if field == "queries" and raw_value is None:
                    diagnostic.unresolved("queries", "expected_record_list", None, retrieval_round=round_index)
                    raw_value = []
                records = self.records(raw_value, field, "planning", diagnostic)
                response[field].extend(records)
                local_records[field] = records
            scoped_decisions.extend([local_records["decisions"] for _query in local_records["queries"]])
        if len(batches) > maximum:
            deferred_papers = [paper.get("paper_id") for batch in batches[maximum:] for paper in batch["paper_results"]]
            deferred_candidates = [record.get("candidate_id") for batch in batches[maximum:] for record in batch["registered_objects"]]
            diagnostic.unresolved("planning_batches", "deferred_model_budget_or_batch_limit", deferred=len(batches) - maximum,
                paper_ids=deferred_papers, candidate_ids=deferred_candidates)
            self.prompt_audit.append({"stage": "planning", "round": round_index, "status": "deferred_budget",
                "deferred_batches": len(batches) - maximum, "paper_ids": deferred_papers, "candidate_ids": deferred_candidates})
        decisions = self.records(response.get("decisions", []), "decisions", "planning", diagnostic)
        self.decisions.extend(decisions)
        for decision in decisions:
            self.collector.logger.info("Query decision: SH=%s action=%s reason=%s references=%s.", decision.get("sub_hypothesis_id"), decision.get("action"), decision.get("reason"), decision.get("references"))
        groups = {sh_id: [] for sh_id in self.by_sh}
        raw_queries = self.records(response.get("queries", []), "queries", "planning", diagnostic)
        context_queries = self.repair_query_contexts(raw_queries, diagnostic, round_index)
        references = ({entry["query_id"] for entry in self.history}
            | {paper_identity(paper) for paper in self.papers}
            | {record["candidate_id"] for record in self.registry}
            | set(self.by_sh))
        feedback_violations = []
        normalized_queries = (self.recover_feedback_queries(context_queries, scoped_decisions, references, diagnostic, round_index)
            if round_index else context_queries)
        round_audit_start = len(self.query_audit)
        for raw, normalized in zip(raw_queries, normalized_queries):
            normalized = recover_query_context_level(normalized, diagnostic)
            for field in ("fit_score", "purpose_score", "context_score"):
                normalized[field] = score_field(raw, field, diagnostic)
            query, reason = admit_query(normalized, self.subhypotheses, self.topic, self.papers, feedback=bool(round_index))
            if query:
                sh_id = query["sub_hypothesis_id"]
                maximum = 2 if round_index else min(4, self.setting("survey_initial_queries_per_sh", 3))
                if round_index and (not isinstance(query.get("feedback_references"), list)
                    or not any(isinstance(reference, str) and reference in references for reference in query["feedback_references"])):
                    feedback_violations.append({"query_id": query.get("query_id"), "sub_hypothesis_id": sh_id,
                        "reason": "missing_or_unknown_feedback_reference", "raw": raw,
                        "missing_fields": feedback_field_gaps(normalized, references)})
                    reason = "missing_feedback_justification"
                elif any(canonical_query(entry["query"]) == canonical_query(query["query"]) and entry["sub_hypothesis_id"] == sh_id for entry in [*self.history, *groups[sh_id]]):
                    reason = "duplicate_query"
                else:
                    original_query_id = query["query_id"]
                    query["query_id"] = self.unique_query_id(original_query_id)
                    if query["query_id"] != original_query_id:
                        query["source_query_id"] = original_query_id
                if reason == "admitted" and (len(groups[sh_id]) >= maximum or self.counts[sh_id] + len(groups[sh_id]) >= self.per_sh_limit):
                    reason = "deferred_query_budget"
                if reason == "admitted":
                    self.query_ids.add(query["query_id"])
                    groups[sh_id].append(query)
            elif reason == "missing_feedback_justification" and round_index:
                feedback_violations.append({"query_id": raw.get("query_id"), "sub_hypothesis_id": raw.get("sub_hypothesis_id"),
                    "reason": "missing_feedback_fields", "raw": raw,
                    "missing_fields": feedback_field_gaps(normalized, references)})
            elif reason != "query_quality_below_threshold":
                diagnostic.unresolved("queries", reason, raw, sub_hypothesis_id=raw.get("sub_hypothesis_id"), query_id=raw.get("query_id"))
            self.query_audit.append({"query": raw, "normalized_query": normalized, "admission_status": reason})
            reported = normalized
            scores = [score(reported.get(key)) for key in ("fit_score", "purpose_score", "context_score")]
            quality = None if None in scores else 20 * (0.5 * scores[0] + 0.25 * scores[1] + 0.25 * scores[2])
            self.collector.logger.info("Survey query admission: SH=%s query_id=%s status=%s quality=%s context=%s.", reported.get("sub_hypothesis_id"), reported.get("query_id"), reason, quality, reported.get("context_level"))
            if query and reason == "admitted" and isinstance(query.get("query_design"), Mapping):
                self.collector.logger.info("Survey query design: SH=%s query_id=%s design=%s.",
                    query["sub_hypothesis_id"], query["query_id"], json.dumps(query["query_design"], ensure_ascii=False))
        if feedback_violations:
            diagnostic.unresolved("queries", "feedback_contract_violations",
                {"count": len(feedback_violations), "examples": feedback_violations[:8], "violations": feedback_violations},
                retrieval_round=round_index)
        if not round_index:
            for sh_id, queries in groups.items():
                levels = {query["context_level"] for query in queries}
                if len(queries) < 2 or "target_system" not in levels or not levels & {"source_system", "solution_class"}:
                    self.query_audit.append({"sub_hypothesis_id": sh_id, "admission_status": "advisory",
                        "reason": "missing_initial_perspectives", "retained_queries": len(queries),
                        "context_levels": sorted(levels)})
                    self.collector.logger.info("Survey query coverage: SH=%s status=advisory reason=missing_initial_perspectives retained_queries=%s context_levels=%s.", sh_id, len(queries), sorted(levels))
        self.publish_format(diagnostic)
        planned = list(interleave(groups.values()))
        reasons = Counter(item["admission_status"] for item in self.query_audit[round_audit_start:])
        reason = ("queries_admitted" if planned else "response_unavailable" if any(result.get("_survey_response_unavailable") for result in results)
            else "no_queries_proposed" if not raw_queries else "all_queries_rejected_by_feedback_contract"
            if reasons.get("missing_feedback_justification") == len(raw_queries) else "all_queries_filtered")
        self.planning_outcome = {"round": round_index, "proposed": len(raw_queries), "admitted": len(planned),
                                 "reason": reason, "admission_counts": dict(reasons)}
        self.prompt_audit.append({"stage": "planning_outcome", **self.planning_outcome})
        self.collector.logger.info("Survey planning outcome: round=%s proposed=%s admitted=%s reason=%s admission_counts=%s.",
            round_index, len(raw_queries), len(planned), reason, dict(reasons))
        return planned

    def assess(self, papers, lease):
        pending = [paper for paper in papers if paper.get("survey_assessment_status") != "assessed"]
        batches = [pending[index:index + self.paper_batch] for index in range(0, len(pending), self.paper_batch)]
        diagnostics = [self.format_batch("assessment", paper_ids=[paper_identity(paper) for paper in batch]) for batch in batches]
        prompts = [ASSESS_PROMPT + json.dumps({**self.payload(), "papers": [
            {"paper_id": paper_identity(paper), **assessment_source(paper),
             "metadata": {key: paper.get(key) for key in ("doi", "year", "publication_year", "journal", "externalIds")},
             "query_provenance": paper.get("retrieval_provenance", [])} for paper in batch]}, ensure_ascii=False) for batch in batches]
        responses = self.model(prompts, "Assessing Survey Papers and Objects", lease, diagnostics=diagnostics)
        for batch, response, diagnostic in zip(batches, responses, diagnostics):
            response_unavailable = bool(response.get("_survey_response_unavailable"))
            if response_unavailable:
                diagnostic.suppress_derived = True
            aligned, alignment = align_paper_assessments([paper_identity(paper) for paper in batch],
                response.get("papers", []), diagnostic)
            alignment_record = {"stage": "assessment", "batch_id": diagnostic.batch_id,
                "response_status": "unavailable" if response_unavailable else "received",
                **diagnostic.response_audit, **alignment}
            self.assessment_alignment_audit.append(alignment_record)
            self.collector.logger.info("Survey assessment alignment: batch=%s expected=%s returned=%s matched=%s missing=%s conflicting=%s unexpected=%s.",
                diagnostic.batch_id, len(batch), len(alignment["returned_records"]),
                sum(record["status"] == "matched" for record in alignment["expected_records"]),
                len(alignment["missing_paper_ids"]), len(alignment["conflicting_paper_ids"]),
                len(alignment["unexpected_paper_ids"]))
            for paper in batch:
                context = {"paper_id": paper_identity(paper)}
                paper["survey_assessment_attempts"] = paper.get("survey_assessment_attempts", 0) + 1
                raw = aligned.get(canonical_paper_id(paper_identity(paper)), {})
                paper["survey_assessment_alignment"] = {"batch_id": diagnostic.batch_id,
                    **next(record for record in alignment["expected_records"] if record["paper_id"] == paper_identity(paper))}
                available = has_source_content(paper)
                project_score = score_field(raw, "project_score", diagnostic) if available else None
                valid = project_score is not None and isinstance(raw.get("project_reason"), str) and bool(raw["project_reason"].strip())
                if raw and not valid and available:
                    if project_score is None:
                        diagnostic.unresolved("project_score", "missing_invalid_or_conflicting_score_0_to_5", score_fields_raw(raw, "project_score"), **context)
                    if not isinstance(raw.get("project_reason"), str) or not raw["project_reason"].strip():
                        diagnostic.unresolved("project_reason", "missing_reason", raw.get("project_reason"), **context)
                paper["project_relevance"] = {"relevance_score": project_score if valid else None,
                    "score_fields_raw": score_fields_raw(raw, "project_score"),
                    "reason": raw.get("project_reason", ""), "excluded": raw.get("excluded") is True,
                    "excluded_raw": raw.get("excluded"),
                    "exclusion_basis": normalize_evidence_boundaries(
                        {"exclusion_basis": raw.get("exclusion_basis")}, diagnostic, **context)["exclusion_basis"],
                    "exclusion_reason": raw.get("exclusion_reason", ""),
                    "assessment_status": "assessed" if valid else "uncertain" if not available else "assessment_unavailable"}
                project = paper["project_relevance"]
                project["excluded"] = project_is_excluded(project)
                if project["excluded_raw"] is True and not project["excluded"]:
                    diagnostic.recovered("excluded", "evidence_shortage_or_unavailable_is_not_exclusion")
                assessments = []
                sh_issue_start = len(diagnostic.issues)
                values = self.records(raw.get("sh_assessments", []), "sh_assessments", "assessment", diagnostic, **context)
                sh_structure_issues = diagnostic.issues[sh_issue_start:]
                if sh_structure_issues:
                    diagnostic.root_cause("sh_assessments", "invalid_SH_assessment_structure", raw.get("sh_assessments"),
                        dependent_scopes=[{**context, "sub_hypothesis_id": sh_id} for sh_id in self.by_sh
                            if not any(item.get("sub_hypothesis_id") == sh_id for item in values)],
                        derived_issues=sh_structure_issues, **context)
                for sh_id, sh in self.by_sh.items():
                    sh_context = {**context, "sub_hypothesis_id": sh_id}
                    matches = [item for item in values if isinstance(item, Mapping) and item.get("sub_hypothesis_id") == sh_id]
                    if raw and len(matches) != 1:
                        diagnostic.root_cause("sh_assessments", "missing_SH_assessment" if not matches else "duplicate_SH_id",
                            matches, **sh_context)
                    item = matches[0] if len(matches) == 1 else {}
                    item = dict(item)
                    if "evidence_boundaries" in item:
                        item["evidence_boundaries"] = normalize_evidence_boundaries(item["evidence_boundaries"], diagnostic, **sh_context)
                    raw_score = score_fields_raw(item, "semantic_relevance_score")
                    value = score_field(item, "semantic_relevance_score", diagnostic) if available else None
                    item["semantic_relevance_score"] = value
                    item["evidence_spans"] = source_summaries(item.get("evidence_spans", []), paper, diagnostic, **sh_context)
                    allowed_slots = {task["slot_name"] for task in sh.get("slot_recovery_tasks", [])
                        if isinstance(task, Mapping) and isinstance(task.get("slot_name"), str)}
                    item["candidate_slot_contributions"], unresolved_slots = slot_contributions(
                        item.get("candidate_slot_contributions", []), allowed_slots, diagnostic, **sh_context)
                    spans = grounded_spans(item.get("evidence_spans"), paper, literal_verification=False)
                    has_reason = isinstance(item.get("reason"), str) and bool(item["reason"].strip())
                    status = "assessed" if value is not None and has_reason and (value < 3 or spans) else "uncertain" if not available else "assessment_unavailable"
                    assessment = self.collector._normalise_sh_semantic_assessment(item, paper=paper, subhypothesis=sh,
                        research_context=self.context, cache_key="", status=status, assessment_source="survey_combined_batch",
                        literal_verification=False)
                    assessment.update(graph_role_fields(item.get("recommended_graph_role"), diagnostic, **sh_context))
                    for field in ("explicit_exclusion_matches", "overall_relation"):
                        if field + "_raw" in assessment:
                            diagnostic.recovered(field, "evidence_boundary_reconciliation")
                    assessment["score_fields_raw"] = raw_score
                    assessment["unresolved_slot_contributions"] = unresolved_slots
                    if status != "assessed":
                        assessment["semantic_relevance_score"] = None
                        if available:
                            missing = []
                            if len(matches) != 1:
                                missing.append("missing_SH_assessment" if not matches else "duplicate_SH_id")
                            if value is None:
                                missing.append("semantic_relevance_score")
                            if not has_reason:
                                missing.append("reason")
                            if value is not None and value >= 3 and not spans:
                                missing.append("usable_evidence_spans")
                            diagnostic.unresolved("sh_assessments", "incomplete_assessment", raw_score,
                                missing_fields=missing, **sh_context)
                    assessments.append(assessment)
                paper["sh_semantic_assessments"] = assessments
                paper["survey_assessment_status"] = "assessed" if valid and all(item["assessment_status"] == "assessed" for item in assessments) else "assessment_unavailable"
                objects = self.records(raw.get("scientific_objects", []), "scientific_objects", "assessment", diagnostic, **context)
                for obj in objects:
                    object_context = {**context, "object_name": obj.get("name"),
                        "sub_hypothesis_ids": obj.get("sub_hypothesis_ids", [])}
                    observation = dict(obj, paper_id=paper_identity(paper))
                    observation["evidence_spans"] = source_summaries(obj.get("evidence_spans", []), paper, diagnostic, **object_context)
                    dimensions = self.records(obj.get("dimension_assessments", []), "dimension_assessments", "assessment", diagnostic, **object_context)
                    observation["dimension_assessments"] = []
                    for dimension in dimensions:
                        dimension_context = {**object_context, "sub_hypothesis_id": dimension.get("sub_hypothesis_id"),
                            "dimension": dimension.get("dimension")}
                        observation["dimension_assessments"].append({**dimension, "evidence_spans": source_summaries(
                            dimension.get("evidence_spans", []), paper, diagnostic, **dimension_context)})
                    identifiers = obj.get("sub_hypothesis_ids", [])
                    if isinstance(identifiers, str):
                        diagnostic.recovered("sub_hypothesis_ids", "string_to_list")
                        identifiers = [identifiers]
                    if not isinstance(identifiers, list):
                        self.object_audit.append({"paper_id": paper_identity(paper), "name": obj.get("name"), "status": "invalid_SH_assignments"})
                        diagnostic.unresolved("sub_hypothesis_ids", "expected_ID_list", identifiers, **object_context)
                        continue
                    observation["sub_hypothesis_ids"] = [identifier for identifier in identifiers if isinstance(identifier, str) and identifier in self.by_sh]
                    for identifier in identifiers:
                        if not isinstance(identifier, str) or identifier not in self.by_sh:
                            diagnostic.unresolved("sub_hypothesis_ids", "unknown_SH_id", identifier, **object_context)
                    related = [identifier for identifier in self.by_sh if self.source_is_eligible(paper, identifier)]
                    observation["eligible_source_sh_ids"] = related
                    if register_candidates([observation], [paper], literal_verification=False):
                        self.observations.append(observation)
                        self.object_audit.append({"paper_id": paper_identity(paper), "name": obj.get("name"), "status": "model_semantic"})
                    else:
                        self.object_audit.append({"paper_id": paper_identity(paper), "name": obj.get("name"), "status": "incomplete_object"})
                        missing = []
                        if not isinstance(obj.get("name"), str) or not obj["name"].strip():
                            missing.append("name")
                        if not observation["evidence_spans"]:
                            missing.append("usable_evidence_spans")
                        if not observation["sub_hypothesis_ids"] and not paper.get("retrieval_provenance"):
                            missing.append("sub_hypothesis_ids")
                        diagnostic.unresolved("scientific_objects", "incomplete_object", missing_fields=missing, **object_context)
                paper["format_issues"] = [issue for issue in [*diagnostic.issues, *diagnostic.suppressed_issues]
                    if issue.get("paper_id") == paper_identity(paper)]
            self.publish_format(diagnostic)
            self.checkpoint_assessment_alignment(alignment_record, diagnostic)

    def repair_confirmation_scores(self, returned, batch, sources, diagnostic):
        returned = deepcopy(returned)
        pending = []
        for record in batch:
            matches = [item for item in returned if item.get("candidate_id") == record["candidate_id"]]
            if len(matches) != 1:
                continue
            candidate = matches[0]
            context = {"candidate_id": record["candidate_id"], "paper_ids": record["discovery_paper_ids"]}
            candidate["assessments"] = self.records(candidate.get("assessments", []), "assessments",
                "confirmation", diagnostic, **context)
            for sh_id in record["sub_hypothesis_ids"]:
                matches = [item for item in candidate["assessments"] if item.get("sub_hypothesis_id") == sh_id]
                if len(matches) != 1:
                    continue
                item = matches[0]
                pair = (record["candidate_id"], sh_id)
                if (pair in self.confirmation_score_repaired_pairs or not isinstance(item.get("candidate_role"), str)
                    or item["candidate_role"] not in OBJECT_ROLES
                    or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
                    continue
                missing = [field for field in ("project_score", "sh_score") if score_field(item, field, diagnostic) is None]
                if missing:
                    pending.append((record, item, missing))
        item_limit = self.setting("survey_confirmation_score_repair_item_limit", 8)
        request_limit = self.setting("survey_confirmation_score_repair_request_limit", 8)
        for start in range(0, len(pending), item_limit):
            if self.confirmation_score_repair_requests >= request_limit or not self.budget.model_remaining():
                self.collector.logger.info("Survey confirmation score repair skipped: pending=%s reason=%s.",
                    len(pending) - start, "repair_limit" if self.confirmation_score_repair_requests >= request_limit else "model_budget_exhausted")
                break
            selected = pending[start:start + item_limit]
            repair_items = [{"candidate_id": record["candidate_id"], "sub_hypothesis_id": item["sub_hypothesis_id"],
                "missing_fields": missing, "assessment": deepcopy(item),
                "candidate": project_fields(record, ("name", "candidate_kind", "role_reason", "discovery_evidence_spans")),
                "source_assessments": {identifier: sources[identifier] for identifier in record["discovery_paper_ids"]
                    if identifier in sources}} for record, item, missing in selected]
            self.confirmation_score_repair_requests += 1
            self.confirmation_score_repaired_pairs.update((record["candidate_id"], item["sub_hypothesis_id"])
                for record, item, _missing in selected)
            repair_diagnostic = self.format_batch("confirmation_score_repair")
            self.collector.logger.info("Survey confirmation score repair: request=%s/%s pairs=%s.",
                self.confirmation_score_repair_requests, request_limit, len(selected))
            payload = {**self.payload(), "repair_items": repair_items}
            response = self.model([serialize_prompt(CONFIRM_SCORE_REPAIR_PROMPT, payload)],
                "Repairing Survey Confirmation Scores", diagnostics=[repair_diagnostic], workers=1)[0]
            patches = self.records(response.get("candidates", []), "candidates", "confirmation_score_repair", repair_diagnostic)
            recovered = 0
            for record, item, missing in selected:
                matches = [patch for patch in patches if patch.get("candidate_id") == record["candidate_id"]]
                if len(matches) != 1:
                    continue
                assessments = self.records(matches[0].get("assessments", []), "assessments", "confirmation_score_repair", repair_diagnostic)
                matches = [patch for patch in assessments if patch.get("sub_hypothesis_id") == item["sub_hypothesis_id"]]
                if len(matches) != 1:
                    continue
                patch = matches[0]
                for field in missing:
                    value = score_field(patch, field, repair_diagnostic)
                    if value is None:
                        continue
                    for key in score_fields_raw(item, field):
                        item.pop(key)
                    item[field] = value
                    recovered += 1
                    diagnostic.recovered(field, "bounded_confirmation_score_repair")
            self.prompt_audit.append({"stage": "confirmation_score_repair", "batch_id": diagnostic.batch_id,
                "repair_items": repair_items, "response": deepcopy(response), "recovered_scores": recovered})
            self.publish_format(repair_diagnostic)
        return returned

    def confirmation_inputs(self, pending):
        pair_limit = self.setting("survey_confirmation_pairs_per_batch", 16)
        batches, batch, pairs = [], [], 0
        for record in pending:
            count = len(record["sub_hypothesis_ids"])
            if batch and (len(batch) >= self.object_batch or pairs + count > pair_limit):
                batches.append(batch)
                batch, pairs = [], 0
            batch.append(record)
            pairs += count
        if batch:
            batches.append(batch)
        jobs = []
        while batches:
            batch = batches.pop(0)
            sources = {paper_identity(paper): {"project_relevance": paper.get("project_relevance"),
                "sh_semantic_assessments": [compact_value(project_fields(item, ("sub_hypothesis_id", "assessment_status",
                    "semantic_relevance_score", "reason", "evidence_spans", "claim_limits", "explicit_exclusion_matches", "evidence_boundaries")), text_limit=600)
                    for item in paper.get("sh_semantic_assessments", [])]}
                for paper in self.papers if any(paper_identity(paper) in record["discovery_paper_ids"] for record in batch)}
            candidates = [compact_value(project_fields(record, ("candidate_id", "name", "aliases", "candidate_kind",
                "taxonomic_level", "sub_hypothesis_ids", "roles_by_subhypothesis", "role_reason", "discovery_paper_ids",
                "discovery_evidence_spans")), text_limit=600) for record in batch]
            payload = {**self.payload(), "candidates": candidates, "prior_source_assessments": sources}
            prompt = serialize_prompt(CONFIRM_PROMPT, payload)
            if len(batch) > 1 and self.measure_prompt(prompt) > self.prompt_limit():
                midpoint = len(batch) // 2
                batches[:0] = [batch[:midpoint], batch[midpoint:]]
                continue
            jobs.append((batch, sources, prompt))
        return jobs

    def confirm(self):
        old = {record["candidate_id"]: record for record in self.registry}
        self.registry = register_candidates(self.observations, self.papers, literal_verification=False)
        pending = []
        for record in self.registry:
            record["candidate_source_evidence_by_subhypothesis"] = {
                sh_id: self.source_evidence(record, sh_id) for sh_id in record["sub_hypothesis_ids"]}
            previous = old.get(record["candidate_id"], {})
            source_key = self.confirmation_key(record)
            if self.confirmed_sources.get(record["candidate_id"]) == source_key:
                for key in ("candidate_relevance_by_subhypothesis", "candidate_relevance_scores_by_subhypothesis", "candidate_relevance_status", "candidate_relevance_reasons", "candidate_relevance_admission_reasons", "candidate_admission_by_subhypothesis", "candidate_evidence_boundaries_by_subhypothesis", "roles_by_subhypothesis", "opportunity_by_subhypothesis", "relevance_assessment_submitted_by_subhypothesis"):
                    if key in previous:
                        record[key] = deepcopy(previous[key])
                continue
            record["candidate_relevance_by_subhypothesis"] = {sh_id: "assessment_unavailable" for sh_id in record["sub_hypothesis_ids"]}
            record["candidate_relevance_status"] = "assessment_unavailable"
            record["relevance_assessment_submitted_by_subhypothesis"] = {sh_id: False for sh_id in record["sub_hypothesis_ids"]}
            pending.append(record)
        jobs = self.confirmation_inputs(pending)
        capacity = self.budget.model_remaining()
        for batch, _sources, _prompt in jobs[capacity:]:
            for record in batch:
                record["candidate_relevance_by_subhypothesis"] = {sh_id: "deferred_budget" for sh_id in record["sub_hypothesis_ids"]}
                record["candidate_relevance_status"] = "deferred_budget"
        jobs = jobs[:capacity]
        diagnostics = [self.format_batch("confirmation", paper_ids=list(sources)) for _batch, sources, _prompt in jobs]
        responses = [{"_survey_response_unavailable": True} for _job in jobs]
        submitted = []
        for index, (_batch, _sources, prompt) in enumerate(jobs):
            if self.measure_prompt(prompt) > self.prompt_limit():
                diagnostics[index].unresolved("response", "prompt_budget_too_small",
                    input_units=self.measure_prompt(prompt), input_limit=self.prompt_limit())
            else:
                submitted.append(index)
        completed = self.model([jobs[index][2] for index in submitted], "Confirming Survey Candidate Relevance",
            diagnostics=[diagnostics[index] for index in submitted], workers=self.setting("survey_confirmation_workers", 10))
        for index, response in zip(submitted, completed):
            responses[index] = response
        for (batch, sources, _prompt), response, diagnostic in zip(jobs, responses, diagnostics):
            if response.get("_survey_response_unavailable"):
                if not diagnostic.issues:
                    diagnostic.unresolved("response", "confirmation_response_unavailable")
                diagnostic.suppress_derived = True
            returned = self.records(response.get("candidates", []), "candidates", "confirmation", diagnostic)
            returned = self.repair_confirmation_scores(returned, batch, sources, diagnostic)
            for record in batch:
                context = {"candidate_id": record["candidate_id"], "paper_ids": record["discovery_paper_ids"]}
                record["relevance_assessment_submitted_by_subhypothesis"] = {sh_id: True for sh_id in record["sub_hypothesis_ids"]}
                matches = [item for item in returned if isinstance(item, Mapping) and item.get("candidate_id") == record["candidate_id"]]
                items = self.records(matches[0].get("assessments", []) if len(matches) == 1 else [], "assessments", "confirmation", diagnostic, **context)
                for sh_id in record["sub_hypothesis_ids"]:
                    matches = [item for item in items if isinstance(item, Mapping) and item.get("sub_hypothesis_id") == sh_id]
                    item = matches[0] if len(matches) == 1 else {}
                    project = score_field(item, "project_score", diagnostic)
                    sh_score = score_field(item, "sh_score", diagnostic)
                    role = item.get("candidate_role")
                    if project is None or sh_score is None or not isinstance(role, str) or role not in OBJECT_ROLES or not isinstance(item.get("reason"), str) or not item["reason"].strip():
                        missing = []
                        if project is None:
                            missing.append("project_score")
                        if sh_score is None:
                            missing.append("sh_score")
                        if not isinstance(role, str) or role not in OBJECT_ROLES:
                            missing.append("candidate_role")
                        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                            missing.append("reason")
                        diagnostic.unresolved("assessments", "incomplete_confirmation",
                            {**score_fields_raw(item, "project_score"), **score_fields_raw(item, "sh_score")},
                            missing_fields=missing, sub_hypothesis_id=sh_id, **context)
                        continue
                    source_status = record["candidate_source_evidence_by_subhypothesis"][sh_id]["status"]
                    item = dict(item)
                    if "evidence_boundaries" in item:
                        item["evidence_boundaries"] = normalize_evidence_boundaries(item["evidence_boundaries"], diagnostic,
                            sub_hypothesis_id=sh_id, **context)
                    status, value = candidate_discovery_status(item, project, sh_score)
                    record["candidate_relevance_by_subhypothesis"][sh_id] = status
                    record.setdefault("candidate_evidence_boundaries_by_subhypothesis", {})[sh_id] = evidence_boundaries(item)
                    record["roles_by_subhypothesis"][sh_id] = role
                    record.setdefault("candidate_relevance_scores_by_subhypothesis", {})[sh_id] = {"project_score": project, "sh_score": sh_score, "weighted_score": value}
                    record.setdefault("candidate_relevance_reasons", {})[sh_id] = item["reason"]
                    boundary = evidence_boundaries(item)
                    admission = "irrelevant" if status == "irrelevant" else "excluded" if boundary["exclusion_basis"] == "explicit_criterion" else source_status if source_status in {"excluded", "source_relevance_conflict"} else "role_unresolved" if role == "role_unresolved" else "auxiliary" if role not in DECISION_ROLES else "evidence_supported" if source_status == "eligible" else "discovery_only"
                    record.setdefault("candidate_admission_by_subhypothesis", {})[sh_id] = admission
                    record.setdefault("candidate_relevance_admission_reasons", {})[sh_id] = admission
                statuses = set(record["candidate_relevance_by_subhypothesis"].values())
                record["candidate_relevance_status"] = "relevant" if statuses & {"relevant", "exploratory"} else "irrelevant" if statuses == {"irrelevant"} else "partial"
                if not statuses & {"assessment_unavailable", "deferred_budget"}:
                    self.confirmed_sources[record["candidate_id"]] = self.confirmation_key(record)
            self.publish_format(diagnostic)

    def confirmation_key(self, record):
        return json.dumps({"paper_ids": record["discovery_paper_ids"], "sh_ids": record["sub_hypothesis_ids"],
            "source_assessments": [{"paper_id": paper_identity(paper), "project": paper.get("project_relevance"),
                "SH": paper.get("sh_semantic_assessments")} for paper in self.papers if paper_identity(paper) in record["discovery_paper_ids"]],
            "source_roles": [obj.get("roles_by_subhypothesis") for obj in self.observations if obj.get("name") in record["aliases"]
                and obj["paper_id"] in record["discovery_paper_ids"]]}, sort_keys=True, ensure_ascii=False)

    def attach_evidence(self):
        by_id = {paper_identity(paper): paper for paper in self.papers}
        for paper in self.papers:
            paper["candidate_evidence_assessments"] = []
        for obj in self.observations:
            paper = by_id.get(obj["paper_id"])
            candidate = next((record for record in self.registry if obj.get("name") in record["aliases"] and obj["paper_id"] in record["discovery_paper_ids"]), None)
            if paper is None or candidate is None:
                continue
            raw_assessments = self.records(obj.get("dimension_assessments", []), "dimension_assessments", "evidence")
            for raw in raw_assessments:
                raw = dict(raw)
                raw["evidence_spans"] = self.records(raw.get("evidence_spans", []), "evidence_spans", "evidence")
                sh_id = raw.get("sub_hypothesis_id")
                if not isinstance(sh_id, str) or sh_id not in self.by_sh or not is_decision_candidate(candidate, sh_id) or not self.source_is_eligible(paper, sh_id):
                    continue
                dimension = next((dimension for dimension in self.dimensions.get(sh_id, []) if dimension["slot_name"] == raw.get("dimension")), None)
                if dimension is not None:
                    assessment = normalize_evidence_assessment(raw, paper=paper, candidate=candidate, sh_id=sh_id, dimension=dimension)
                    paper["candidate_evidence_assessments"].append(assessment)

    def search_batch(self, queries, round_index):
        remaining = self.logical_limit - sum(self.counts.values())
        queries = queries[:remaining]
        needed = math.ceil(len(queries) * self.result_limit / self.paper_batch)
        reserve_feedback = 0 if self.feedback_lease is not None else 1
        if not queries or self.budget.model_remaining() < needed + reserve_feedback:
            self.stop_reason = "model_budget_exhausted" if queries else "query_budget_exhausted"
            return False
        if self.feedback_lease is None:
            self.feedback_lease = self.budget.reserve_model_capacity(1)
        lease = self.budget.reserve_model_capacity(needed)
        prior_ids = {evidence_id(paper) for paper in self.papers}
        lanes = []
        for query in queries:
            self.counts[query["sub_hypothesis_id"]] += 1
            lane = {**query, "lane_id": query["query_id"], "lane": "model_approved", "provider": "openalex",
                "provider_filter": {}, "discipline_filter_policy": "broad", "result_limit": self.result_limit,
                "budget_phase": "primary", "retrieval_stage": "candidate_discovery" if not round_index else "model_feedback",
                "retrieval_round": round_index}
            lanes.append(lane)
        self.lanes.extend(lanes)
        try:
            with ThreadPoolExecutor(max_workers=self.query_batch) as executor:
                results = list(executor.map(self.collector._execute_slot_recovery_lane, lanes))
            collections, result_info = [], []
            for lane, result in zip(lanes, results):
                returned_lane, papers = result
                self.lanes[self.lanes.index(lane)] = returned_lane
                cache = returned_lane.get("retrieval_cache", {})
                status = cache.get("provider_status") or ("success" if papers else "valid_empty")
                provenance_lane = returned_lane
                self.record_summary(returned_lane, papers, status)
                if status in {"provider_failure", "rate_limited"} and self.budget.remaining("retry_fallback"):
                    fallback = {**lane, "provider": "semantic_scholar", "lane_id": lane["lane_id"] + ".fallback", "budget_phase": "retry_fallback"}
                    fallback_lane, fallback_papers = self.collector._execute_slot_recovery_lane(fallback)
                    self.lanes.append(fallback_lane)
                    provenance_lane = fallback_lane
                    status = fallback_lane.get("retrieval_cache", {}).get("provider_status") or ("success" if fallback_papers else "valid_empty")
                    papers = fallback_papers
                    self.record_summary(fallback_lane, papers, status)
                papers = self.collector._merge_retrieval_candidates([(provenance_lane, papers[:self.result_limit])])
                collections.append(papers)
                result_info.append((lane, papers, status))
            self.papers = self.collector._merge_candidate_collections([self.papers, *collections])
            new_papers = [paper for paper in self.papers if evidence_id(paper) not in prior_ids]
            # Cross-provider deduplication can retain an earlier AS identifier
            # for a later W identifier. Resolve by every identity, not only ID.
            by_identity = {key: paper for paper in self.papers for key in self.collector._candidate_identity_keys(paper)}

            def canonical_source(paper):
                return next((by_identity[key] for key in self.collector._candidate_identity_keys(paper)
                             if key in by_identity), paper)

            returned_ids = {evidence_id(canonical_source(paper)) for collection in collections for paper in collection}
            self.assess([paper for paper in self.papers if evidence_id(paper) in returned_ids and paper.get("survey_assessment_attempts", 0) < 2], lease)
            for lane, returned, status in result_info:
                relevant = [canonical_source(paper) for paper in returned]
                metrics = query_metrics(relevant, lane["sub_hypothesis_id"], {evidence_id(paper) for paper in new_papers}, status)
                self.history.append({**lane, "metrics": metrics, "paper_ids": [paper_identity(paper) for paper in relevant],
                    "new_paper_ids": [paper_identity(paper) for paper in relevant if evidence_id(paper) not in prior_ids]})
                self.collector.logger.info("Query feedback: SH=%s query=%s returned=%s assessed=%s useful=%s precision=%s novelty=%s status=%s outcomes=%s hint=%s.", lane["sub_hypothesis_id"], lane["query_id"], metrics["returned_unique"], metrics["assessed"], metrics["useful"], metrics["precision"], metrics["novelty"], status, metrics["contribution_outcomes"], metrics["feedback_hint"])
                if metrics["revision_guidance"]:
                    self.collector.logger.info("Query relaxation guidance: SH=%s query=%s reason=%s action=%s priority=%s.",
                        lane["sub_hypothesis_id"], lane["query_id"], metrics["revision_guidance"]["reason"],
                        metrics["revision_guidance"]["preferred_action"],
                        ",".join(metrics["revision_guidance"]["priority_order"]))
        finally:
            self.budget.release_model_capacity(lease)
        return True

    def record_summary(self, lane, papers, status):
        self.summaries.append({"raw_candidates_by_lane": {lane["lane_id"]: len(papers)},
            "failed_lanes": [lane["lane_id"]] if status in {"provider_failure", "rate_limited"} else [],
            "deferred_lanes": [lane["lane_id"]] if status == "deferred_budget" else []})

    def complete_pending_assessments(self):
        pending = [paper for paper in self.papers if paper.get("survey_assessment_status") != "assessed" and has_source_content(paper)
            and paper.get("survey_assessment_attempts", 0) < 2]
        capacity = max(0, self.budget.model_remaining() - (0 if self.feedback_lease else 1))
        pending = pending[:capacity * self.paper_batch]
        if pending:
            lease = self.budget.reserve_model_capacity(math.ceil(len(pending) / self.paper_batch))
            try:
                self.assess(pending, lease)
            finally:
                self.budget.release_model_capacity(lease)

    def update(self):
        by_id = {paper_identity(paper): paper for paper in self.papers}
        for entry in self.history:
            returned = [by_id[pid] for pid in entry["paper_ids"] if pid in by_id]
            new_ids = {evidence_id(by_id[pid]) for pid in entry["new_paper_ids"] if pid in by_id}
            entry["metrics"] = query_metrics(returned, entry["sub_hypothesis_id"], new_ids, entry["metrics"]["provider_status"])
        self.confirm()
        self.attach_evidence()
        for record in self.registry:
            for sh_id in record["sub_hypothesis_ids"]:
                searched = any(entry["sub_hypothesis_id"] == sh_id and entry["metrics"]["provider_status"] in {"success", "valid_empty"}
                    and entry.get("candidate_id") == record["candidate_id"] for entry in self.history)
                record.setdefault("opportunity_by_subhypothesis", {})[sh_id] = "completed" if searched else "unsearched"
        opportunities = {sh_id: 0 for sh_id in self.by_sh}
        model_capacity = max(0, self.budget.model_remaining() - (0 if self.feedback_lease else 1)) * self.paper_batch // self.result_limit
        remaining = min(self.logical_limit - sum(self.counts.values()), self.budget.remaining("primary"), model_capacity)
        for sh_id in interleave([[sh_id] * max(0, self.per_sh_limit - self.counts[sh_id]) for sh_id in self.by_sh]):
            if not remaining:
                break
            opportunities[sh_id] += 1
            remaining -= 1
        for sh_id in self.by_sh:
            base_dimensions = screening_dimensions(self.dimensions[sh_id], 1)
            already = sum(bool(base_dimensions) and all(dimension_satisfied(self.papers, record, sh_id, dimension) for dimension in base_dimensions)
                or record.get("opportunity_by_subhypothesis", {}).get(sh_id) == "completed" for record in self.registry)
            opportunities[sh_id] += already
        activate_candidates(self.registry, self.subhypotheses, self.setting("survey_active_candidates_per_sh", 3), opportunities)
        self.papers = associate_papers_with_subhypotheses(self.papers, self.subhypotheses,
            project_fingerprint=str(self.context.get("input_fingerprint") or ""), relevance_threshold=3, max_slots_per_paper=2)
        self.selection = bounded_seed_selection(self.papers, self.subhypotheses, self.registry,
            self.setting("max_seed_paper_num", 40), self.setting("min_seed_papers_per_sh", 2))
        self.ledger = build_candidate_ledger(self.registry, self.papers, self.dimensions, self.lanes, self.summaries,
            selected_paper_ids=[paper_identity(paper) for paper in self.selection["selected_papers"]], discovery_status="completed")
        self.metrics = comparison_metrics(self.ledger, self.subhypotheses, self.selection["minimum_seed_counts_by_sh"], self.setting("min_seed_papers_per_sh", 2))
        self.collector.logger.info("Object relevance: registered=%s active_pairs=%s relevant_holdout_pairs=%s assessment_completion=%s.", len(self.registry), self.metrics["active_pairs"], self.metrics["relevant_holdout_pairs"], self.metrics["relevance_assessment_completion"])

    def ready(self):
        if self.metrics["sh_seed_coverage"] != 1 or self.metrics["active_opportunity_coverage"] not in {None, 1} or self.metrics["relevance_pending_pairs"]:
            return False
        selected = {paper_identity(paper) for paper in self.selection["selected_papers"]}
        for sh_id in self.by_sh:
            relevant = [record for record in self.registry if is_decision_candidate(record, sh_id)]
            needs_comparison = self.by_sh[sh_id].get("question_kind") in {"COMPARATIVE_EVALUATION", "COMPARATIVE_DESIGN", "COMPARATIVE_SELECTION"} or any(
                dimension.get("direct_comparison") or dimension.get("evidence_role") == "DIRECT_COMPARATIVE_EVIDENCE" for dimension in self.dimensions[sh_id])
            if needs_comparison and len(relevant) < 2:
                return False
            if len(relevant) >= 2:
                represented = [record for record in relevant if record.get("active_status_by_subhypothesis", {}).get(sh_id) == "active" and selected & set(record["discovery_paper_ids"])]
                if len(represented) < 2:
                    return False
        return self.metrics["relevance_assessment_completion"] in {None, 1}

    def run(self):
        self.collector.logger.info("Survey search plan: SHs=%s initial_queries_per_SH=%s logical_limit=%s http_limit=%s model_limit=%s.", len(self.by_sh), self.setting("survey_initial_queries_per_sh", 3), self.logical_limit, self.budget.total, self.budget.assessment_limit)
        shared = list(getattr(self.collector, "_shared_search_candidates", []) or [])
        if shared:
            self.papers = self.collector._merge_candidate_collections([self.papers, shared])
            self.complete_pending_assessments()
            self.update()
            self.prompt_audit.append({"stage": "shared_source_ingestion", "source_count": len(shared),
                                      "assessed": sum(p.get("survey_assessment_status") == "assessed" for p in self.papers)})
        stagnant = 0
        prior_gain = None
        rounds = min(2, self.setting("survey_feedback_rounds", 2))
        for round_index in range(rounds + 1):
            if round_index:
                self.complete_pending_assessments()
                self.update()
            queries = self.planning(round_index)
            if queries and self.stop_reason == "query_plan_unavailable":
                self.stop_reason = "feedback_round_limit"
            for start in range(0, len(queries), self.query_batch):
                batch = queries[start:start + self.query_batch]
                while batch and self.budget.model_remaining() < math.ceil(len(batch) * self.result_limit / self.paper_batch) + (0 if self.feedback_lease else 1):
                    batch = batch[:-1]
                if not batch or not self.search_batch(batch, round_index):
                    self.stop_reason = "model_budget_exhausted" if not batch else self.stop_reason
                    break
            self.update()
            gain = (sum(bool(seed_assessments(paper)) for paper in self.papers),
                sum(is_decision_candidate(record, sh_id) for record in self.registry for sh_id in record["sub_hypothesis_ids"]),
                sum(len(cell["paper_ids"]) for record in self.ledger["records"] for cell in record["minimum_evidence_matrix"].values()))
            stagnant = stagnant + 1 if round_index and gain == prior_gain else 0
            prior_gain = gain
            if self.ready():
                self.stop_reason = "seed_pool_ready"
                break
            if (self.history and all(entry["metrics"]["provider_status"] in {"provider_failure", "rate_limited"} for entry in self.history)
                and (not self.budget.remaining("retry_fallback") or round_index >= 1)):
                self.stop_reason = "provider_unavailable"
                break
            if sum(self.counts.values()) >= self.logical_limit:
                self.stop_reason = "query_budget_exhausted"
                break
            if not self.budget.model_remaining():
                self.stop_reason = "model_budget_exhausted"
                break
            if not self.budget.remaining("primary"):
                self.stop_reason = "http_budget_exhausted"
                break
            if stagnant >= 2 and self.history:
                recent = self.history[-sum(1 for entry in self.history if entry["retrieval_round"] == round_index):]
                self.stop_reason = ("query_plan_unavailable" if not queries and self.planning_outcome.get("reason")
                    in {"response_unavailable", "all_queries_rejected_by_feedback_contract", "all_queries_filtered"}
                    else "provider_unavailable" if recent and all(entry["metrics"]["provider_status"] in {"provider_failure", "rate_limited"} for entry in recent)
                    else "no_information_gain")
                break
            if not queries:
                if any(item.get("action") == "stop" for item in self.decisions if isinstance(item, Mapping)):
                    self.stop_reason = "model_stop"
                    break
                self.collector.logger.warning("Survey query plan unavailable: round=%s reason=%s proposed=%s admitted=0; preserving results and using remaining feedback rounds if available.",
                    round_index, self.planning_outcome.get("reason"), self.planning_outcome.get("proposed", 0))
                self.stop_reason = "query_plan_unavailable"
        return self.finish()

    def finish(self):
        if self.feedback_lease is not None:
            self.budget.release_model_capacity(self.feedback_lease)
            self.feedback_lease = None
        executed = {entry["query_id"] for entry in self.history}
        for record in self.query_audit:
            raw = record.get("query")
            if record.get("admission_status") == "admitted" and isinstance(raw, Mapping):
                record["execution_status"] = "executed" if raw["query_id"] in executed else "deferred_budget"
        self.ledger.update(comparison_metrics=self.metrics, retrieval_budget=self.budget.snapshot(), stop_reason=self.stop_reason,
            retrieval_strategy="model_feedback", search_controller={"logical_calls": sum(self.counts.values()), "logical_limit": self.logical_limit,
            "per_sh_calls": dict(self.counts), "query_admission_audit": self.query_audit, "decisions": self.decisions})
        selected_ids = {paper_identity(paper) for paper in self.selection["selected_papers"]}
        for record in self.ledger["records"]:
            record["root_seed_source_ids"] = sorted(selected_ids & set(record["discovery_paper_ids"]))
        self.ledger["funnel"].update(raw_candidate_objects=len(self.object_audit), grounded_observations=len(self.observations),
            invalid_candidate_objects=sum(record["status"] not in {"source_grounded", "model_semantic"} for record in self.object_audit))
        if any(self.metrics.get(key) != 1 for key in ("all_candidate_base_evidence_coverage", "relevance_assessment_completion")):
            self.ledger["best_candidate_claim_allowed"] = False
            self.ledger["comparison_status"] = "insufficient"
        self.ledger = freeze_candidate_ledger(self.ledger)
        self.collector._scientific_candidate_registry = self.registry
        self.collector._candidate_stop_reason = self.stop_reason
        self.selection.update(candidate_comparison_status=self.ledger["comparison_status"], best_candidate_claim_allowed=self.ledger["best_candidate_claim_allowed"])
        coverage = self.collector._build_sh_evidence_coverage_ledger(self.papers, self.subhypotheses, self.context)
        artifact = {"schema_version": "subhypothesis_feedback_retrieval_execution_v1", "project_id": self.collector._project_id(self.context),
            "project_context_fingerprint": str(self.context.get("input_fingerprint") or ""), "plan": dict(self.plan),
            "slot_retrieval_summaries": self.summaries, "candidate_papers": self.papers,
            "scientific_candidate_papers": self.papers, "candidate_discovery": self.ledger,
            "evidence_coverage_ledger_initial": coverage, "evidence_coverage_ledger_final": coverage,
            "seed_selection": self.selection, "query_history": self.history, "retrieval_funnel": self.ledger["funnel"],
            "object_extraction_audit": self.object_audit,
            "format_normalization_audit": self.format_audit,
            "assessment_alignment_audit": self.assessment_alignment_audit,
            "prompt_budget_audit": self.prompt_audit,
            "candidate_balance": self.ledger["balance"], "comparison_metrics": self.metrics, "stop_reason": self.stop_reason}
        self.collector._store_subhypothesis_retrieval_artifact(artifact)
        self.collector._initialize_sh_graph_provenance(self.context, self.selection, coverage)
        self.collector.logger.info("Survey search stop: reason=%s logical_calls=%s/%s http_attempts=%s/%s metrics=%s.", self.stop_reason, sum(self.counts.values()), self.logical_limit, self.budget.snapshot()["http_attempts"], self.budget.total, self.metrics)
        return self.selection["selected_papers"], self.selection
