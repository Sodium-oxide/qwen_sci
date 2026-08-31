from utils.rich_logger import get_logger
from utils.api_call import SemanticScholarAPI, ChatAgent
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from modules.pe import (
    SURVEY_OUTLINE_GENERATION,
    SUBSECTION_DRAFT,
    SUBSECTION_DRAFT_WITH_CODE,
    CODE_REPORT_PROMPT,
    SECTION_DRAFT,
    DRAFT_REFINEMENT,
    ERROR_FEEDBACK_PROMPT,
    DRAFT_REFINEMENT_IN_PARTS,
    SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT,
    SURVEY_OUTLINE_GENERATION_OUTLINE_DRAFT,
    SURVEY_CLAIM_TRACE_REPAIR,
    SECTION_REVISE,
    SECTION_REVIEW,
    SURVEY_OUTLINE_REPAIR,
    SURVEY_REVIEW,
    SURVEY_REVISE,
    DRAFT_REFINEMENT_SUBSECTION_IN_PARTS,
    CODE_REPORT_PROMPT_FOR_SECTION_REVIEWER,
    CODE_REPORT_PROMPT_FOR_SECTION_REVISER,
    CODE_REPORT_PROMPT_FOR_SURVEY_REVIEWER,
    CODE_REPORT_PROMPT_FOR_SURVEY_REVISER,
    EVIDENCE_BOUNDED_SECTION_QUALITY_REVIEW,
    EVIDENCE_BOUNDED_SECTION_QUALITY_REVISE,
)
from modules.refine_agent import (
    agentic_revise_survey_whole,
    agentic_revise_survey_in_parts,
    apply_revision_to_text,
    validate_revision_payload,
)
from typing import Any, Dict, List, Mapping, Sequence, Union
from utils.err_info import CumulativeErrorInfo
from utils.utils import extract_json
import textwrap
from tqdm import tqdm

import json
import re
import copy
import os
from difflib import SequenceMatcher
from pathlib import Path
from omegaconf import OmegaConf

from src.pipeline.survey_evidence_plan import (
    BACKGROUND_ONLY,
    EVIDENCE_BACKED_SYNTHESIS,
    EVIDENCE_GAP_REPORT,
    OUT_OF_SCOPE_OR_REJECTED,
    QUALIFIED_SYNTHESIS,
    SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
    build_survey_evidence_plan,
)
from src.pipeline.multimodal_evidence.contract import validate_multimodal_evidence
from src.pipeline.multimodal_evidence.safety import violates_noncausal_policy
from src.pipeline.multimodal_evidence.survey_integration import (
    LOCAL_DATA_OBSERVATION,
    enrich_multimodal_evidence,
    multimodal_trace_details,
)
from src.pipeline.paper_identity import canonical_paper_id, canonical_paper_ids
from src.pipeline.survey_handoff_persistence import publish_survey_run_artifacts


OUTLINE_EVIDENCE_PROMPT_SCHEMA_VERSION = "survey_sh_evidence_prompt_v1"


class OutlineGenerationError(RuntimeError):
    """Raised before an invalid or oversized outline can reach later stages."""


class SurveyGenerator:
    def __init__(self, config, work_analyzer, database):
        self.config = config
        self.logger = get_logger("SurveyGenerator")
        self.chat_agent = ChatAgent(config)
        self.work_analyzer = work_analyzer
        self.database = database
        self.use_title_in_draft = config.ModuleInfo.SurveyGenerator.use_title_in_draft
        self.refine_in_parts = config.ModuleInfo.SurveyGenerator.draft_refinement_in_parts
        self.omit_error_preserve_retry_time = config.ModuleInfo.SurveyGenerator.omit_error_preserve_retry_time
        self.include_initial_analysis = config.ModuleInfo.SurveyGenerator.include_initial_analysis
        self.include_relation_graph = config.ModuleInfo.SurveyGenerator.include_relation_graph
        self.include_relation_table = config.ModuleInfo.SurveyGenerator.include_relation_table
        self.refine_in_parts_mode = self.config.ModuleInfo.SurveyGenerator.refine_in_parts_mode
        self.outline_fast_mode = self.config.ModuleInfo.SurveyGenerator.outline_assign_fast_mode
        self.agentic_refine_section = self.config.ModuleInfo.SurveyGenerator.agentic_refine_section
        self.agentic_refine_survey = self.config.ModuleInfo.SurveyGenerator.agentic_refine_survey
        self.always_omit_error = self.config.ModuleInfo.SurveyGenerator.always_omit_error_in_draft_validation
        self.survey_evidence_plan = {}
        self.survey_claim_traceability_artifact = {}
        self.survey_outline_artifact = {}
        self.survey_multimodal_evidence = {}
        # This is prompt-local state. ``survey_evidence_plan`` stays complete
        # so its persisted JSON remains the audit artifact.
        self._outline_representative_paper_ids: list[str] = []

    @staticmethod
    def _as_mapping(value: Any) -> dict:
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _json_compatible(value: Any) -> Any:
        """Recursively convert OmegaConf containers before persisting JSON."""
        if OmegaConf.is_config(value):
            return SurveyGenerator._json_compatible(
                OmegaConf.to_container(value, resolve=True)
            )
        if isinstance(value, Mapping):
            return {
                str(key): SurveyGenerator._json_compatible(item)
                for key, item in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return [SurveyGenerator._json_compatible(item) for item in value]
        return value

    @staticmethod
    def _as_texts(value: Any) -> list[str]:
        values = value if isinstance(value, (list, tuple, set)) else [value]
        result = []
        seen = set()
        for raw in values:
            text = str(raw or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    @staticmethod
    def _as_paper_ids(value: Any) -> list[str]:
        """Return comparable canonical IDs without altering non-OpenAlex IDs."""

        return canonical_paper_ids(value)

    def _paper_role_constraints_by_id(
        self, entry: Mapping[str, Any] | None
    ) -> dict[str, list[dict[str, Any]]]:
        """Index role constraints by canonical paper ID.

        This keeps older persisted plans, which may use an OpenAlex URL as the
        mapping key, compatible with current ``W...`` cache and citation IDs.
        Multiple aliases for the same paper are merged rather than letting one
        silently overwrite the other.
        """

        normalized: dict[str, list[dict[str, Any]]] = {}
        for raw_paper_id, raw_constraints in self._as_mapping(
            self._as_mapping(entry).get("paper_role_constraints")
        ).items():
            paper_id = canonical_paper_id(raw_paper_id)
            if not paper_id or not isinstance(raw_constraints, Sequence) or isinstance(
                raw_constraints, (str, bytes)
            ):
                continue
            bucket = normalized.setdefault(paper_id, [])
            for raw_constraint in raw_constraints:
                if not isinstance(raw_constraint, Mapping):
                    continue
                constraint = self._as_mapping(raw_constraint)
                if constraint not in bucket:
                    bucket.append(constraint)
        return normalized

    def _survey_runtime_multimodal_evidence(self, collector: Any) -> dict[str, Any] | None:
        """Return only explicitly enabled, validated multimodal runtime evidence."""

        self.survey_multimodal_evidence = {}
        multimodal = getattr(getattr(self, "config", None), "multimodal_evidence", None)
        if not hasattr(multimodal, "get") or not bool(multimodal.get("enabled")):
            return None
        input_spec = multimodal.get("input_spec", {})
        if not isinstance(input_spec, Mapping) or not input_spec.get("records"):
            return None
        runtime_evidence = multimodal.get("runtime_evidence", {})
        if not isinstance(runtime_evidence, Mapping) or not runtime_evidence:
            return None
        try:
            evidence = validate_multimodal_evidence(runtime_evidence)
        except Exception as exc:
            raise ValueError("Invalid runtime multimodal evidence configuration.") from exc
        if evidence.get("perception", {}).get("mode") == "remote_perception" and not bool(
            multimodal.get("allow_remote_perception")
        ):
            raise ValueError(
                "Remote multimodal evidence requires the explicit allow_remote_perception gate."
            )
        data_artifact = getattr(collector, "data_anchored_subhypothesis_artifact", {})
        try:
            enriched = enrich_multimodal_evidence(
                evidence,
                data_anchored_subhypothesis_artifact=(
                    data_artifact if isinstance(data_artifact, Mapping) else None
                ),
            )
        except Exception as exc:
            raise ValueError("Unable to link multimodal evidence to data-anchored SH metadata.") from exc
        self.survey_multimodal_evidence = dict(enriched)
        return dict(enriched)

    def _survey_evidence_plan_sources(self):
        """Read only the current v1 SH artifacts needed before survey writing."""

        collector = getattr(self.work_analyzer, "work_collector", None)
        basic_info = getattr(self.config, "BasicInfo", None)
        provenance = getattr(collector, "sh_graph_provenance_artifact", {})
        retrieval = getattr(collector, "subhypothesis_retrieval_artifact", {})
        cluster_coverage = getattr(self.work_analyzer, "sh_cluster_coverage_artifact", {})
        if not cluster_coverage:
            cluster_coverage = getattr(collector, "sh_cluster_coverage_artifact", {})
        if basic_info is not None:
            if not provenance:
                provenance = getattr(basic_info, "sh_graph_provenance", {})
            if not retrieval:
                retrieval = getattr(basic_info, "subhypothesis_retrieval", {})
            if not cluster_coverage:
                cluster_coverage = getattr(basic_info, "sh_cluster_coverage", {})

        if not provenance and not retrieval and not cluster_coverage:
            return None
        generator_config = getattr(
            getattr(self.config, "ModuleInfo", None), "SurveyGenerator", None
        )
        max_writable_papers_per_sh = self._positive_int(
            getattr(generator_config, "writing_max_papers_per_sh", 20),
            20,
        )
        provenance = self._as_mapping(provenance)
        retrieval = self._as_mapping(retrieval)
        cluster_coverage = self._as_mapping(cluster_coverage)
        plan = self._as_mapping(retrieval.get("plan"))
        plan_context = self._as_mapping(plan.get("project_context"))
        project_id = str(provenance.get("project_id") or "").strip()
        fingerprint = str(provenance.get("project_context_fingerprint") or "")
        if (
            not project_id
            or not fingerprint
            or str(retrieval.get("project_id") or "").strip() != project_id
            or str(retrieval.get("project_context_fingerprint") or "").strip()
            != fingerprint
            or plan_context.get("project_context_fingerprint") != fingerprint
        ):
            raise ValueError("Survey evidence plan received mismatched SH provenance and retrieval artifacts.")
        contracts = plan.get("subhypotheses")
        if not isinstance(contracts, Sequence) or isinstance(contracts, (str, bytes)):
            raise ValueError("Survey evidence plan requires compiled SH contracts from the retrieval plan.")
        sources = {
            "provenance_artifact": provenance,
            "coverage_ledger": retrieval.get("evidence_coverage_ledger_final"),
            "cluster_coverage_artifact": cluster_coverage,
            "subhypothesis_contracts": list(contracts),
            "max_writable_papers_per_sh": max_writable_papers_per_sh,
        }
        multimodal_evidence = self._survey_runtime_multimodal_evidence(collector)
        if multimodal_evidence is not None:
            sources["multimodal_evidence"] = multimodal_evidence
        return sources

    def _store_survey_evidence_plan(self, plan: Mapping[str, Any]) -> None:
        self.survey_evidence_plan = dict(plan)
        basic_info = getattr(self.config, "BasicInfo", None)
        if basic_info is None:
            return
        try:
            basic_info.survey_evidence_plan = self.survey_evidence_plan
        except Exception:
            pass
        base_dir = str(getattr(basic_info, "base_dir", "") or "").strip()
        if not base_dir:
            return
        artifact_path = Path(base_dir) / "survey_evidence_plan.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(self.survey_evidence_plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            basic_info.survey_evidence_plan_artifact_path = str(artifact_path)
        except Exception:
            pass

    def prepare_survey_evidence_plan(self) -> dict:
        """Compile and persist the SH plan before any outline or prose LLM call."""

        existing = getattr(self, "survey_evidence_plan", {})
        if (
            isinstance(existing, Mapping)
            and existing.get("schema_version") == SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION
        ):
            return dict(existing)
        sources = self._survey_evidence_plan_sources()
        if sources is None:
            return {}
        plan = build_survey_evidence_plan(**sources)
        self._store_survey_evidence_plan(plan)
        modes = self._as_texts(
            [
                entry.get("allowed_writing_mode")
                for entry in plan.get("subhypotheses", [])
                if isinstance(entry, Mapping)
            ]
        )
        self.logger.info(
            "Compiled survey evidence plan before outline: SH=%s modes=%s.",
            len(plan.get("subhypotheses", [])),
            "|".join(modes),
        )
        return plan

    def _evidence_bounded_writing_enabled(self) -> bool:
        plan = getattr(self, "survey_evidence_plan", {})
        return bool(
            isinstance(plan, Mapping)
            and plan.get("schema_version") == SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION
            and plan.get("evidence_bounded_writing")
        )

    def _estimate_prompt_tokens(self, text: Any) -> int:
        """Estimate tokens even in lightweight tests without a real ChatAgent."""
        content = str(text or "")
        estimate = getattr(getattr(self, "chat_agent", None), "estimate_tokens", None)
        if callable(estimate):
            return max(0, int(estimate(content)))
        return max(0, math.ceil(len(content) / 4))

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _survey_evidence_plan_prompt_projection(self) -> dict[str, Any]:
        """Project the auditable SH plan into the small contract needed by LLMs.

        The full plan deliberately retains graph provenance for audit and claim
        validation. Passing every graph annotation to every writing prompt is
        both unnecessary and capable of crowding out the output schema. This
        projection retains only the SH slots, allowed papers, and constraints
        that can govern an actual writing decision.
        """
        plan = self._as_mapping(getattr(self, "survey_evidence_plan", {}))
        entries: list[dict[str, Any]] = []
        for raw_entry in plan.get("subhypotheses", []):
            if not isinstance(raw_entry, Mapping):
                continue
            entry = self._as_mapping(raw_entry)
            allowed_ids = self._as_paper_ids(
                [
                    *self._as_paper_ids(entry.get("evidence_paper_ids")),
                    *self._as_paper_ids(entry.get("qualified_paper_ids")),
                    *self._as_paper_ids(entry.get("context_paper_ids")),
                ]
            )
            raw_constraints = self._paper_role_constraints_by_id(entry)
            paper_constraints: dict[str, list[dict[str, Any]]] = {}
            for paper_id in allowed_ids:
                constraints = raw_constraints.get(paper_id, [])
                if not isinstance(constraints, Sequence) or isinstance(
                    constraints, (str, bytes)
                ):
                    continue
                compact_constraints = []
                for raw_constraint in constraints:
                    if not isinstance(raw_constraint, Mapping):
                        continue
                    constraint = self._as_mapping(raw_constraint)
                    compact_constraints.append(
                        {
                            "association_stage": str(
                                constraint.get("association_stage") or ""
                            ),
                            "evidence_use_mode": str(
                                constraint.get("evidence_use_mode") or ""
                            ),
                            "allowed_support_kinds": self._as_texts(
                                constraint.get("allowed_support_kinds")
                            ),
                            "semantic_claim_limits": self._as_texts(
                                constraint.get("semantic_claim_limits")
                            ),
                            "writing_direct_evidence_allowed": bool(
                                constraint.get("writing_direct_evidence_allowed")
                            ),
                        }
                    )
                if compact_constraints:
                    paper_constraints[paper_id] = compact_constraints

            slot_support: dict[str, dict[str, Any]] = {}
            for slot_name, raw_slot in self._as_mapping(
                entry.get("slot_support")
            ).items():
                slot = self._as_mapping(raw_slot)
                slot_support[str(slot_name)] = {
                    "expected_evidence_role": str(
                        slot.get("expected_evidence_role") or ""
                    ),
                    "evidence_paper_ids": self._as_paper_ids(
                        slot.get("evidence_paper_ids")
                    ),
                    "qualified_paper_ids": self._as_paper_ids(
                        slot.get("qualified_paper_ids")
                    ),
                    "background_paper_ids": self._as_paper_ids(
                        slot.get("background_paper_ids")
                    ),
                    "minimum_evidence": str(slot.get("minimum_evidence") or ""),
                }

            limitations = self._as_mapping(entry.get("limitations"))
            prompt_entry = {
                    "sub_hypothesis_id": str(
                        entry.get("sub_hypothesis_id") or ""
                    ),
                    "summary": str(entry.get("summary") or ""),
                    "question_kind": str(entry.get("question_kind") or ""),
                    "research_role": str(entry.get("research_role") or ""),
                    "required_slots": self._as_texts(entry.get("required_slots")),
                    "covered_slots": self._as_texts(entry.get("covered_slots")),
                    "background_only_slots": self._as_texts(
                        entry.get("background_only_slots")
                    ),
                    "missing_slots": self._as_texts(entry.get("missing_slots")),
                    "slot_support": slot_support,
                    "allowed_writing_mode": str(
                        entry.get("allowed_writing_mode") or ""
                    ),
                    "allowed_claim_modes": self._as_texts(
                        entry.get("allowed_claim_modes")
                    ),
                    "evidence_paper_ids": self._as_paper_ids(
                        entry.get("evidence_paper_ids")
                    ),
                    "qualified_paper_ids": self._as_paper_ids(
                        entry.get("qualified_paper_ids")
                    ),
                    "context_paper_ids": self._as_paper_ids(
                        entry.get("context_paper_ids")
                    ),
                    "challenge_paper_ids": self._as_paper_ids(
                        entry.get("challenge_paper_ids")
                    ),
                    "paper_role_constraints": paper_constraints,
                    "limitations": {
                        "blockers": self._as_texts(limitations.get("blockers")),
                        "scope_rejection_count": self._positive_int(
                            limitations.get("scope_rejection_count"), 0
                        ),
                    },
            }
            multimodal_projection = self._as_mapping(entry.get("multimodal_projection"))
            if multimodal_projection:
                prompt_entry["analysis_priority"] = str(
                    entry.get("analysis_priority") or ""
                )
                prompt_entry["must_cover"] = bool(entry.get("must_cover"))
                prompt_entry["multimodal_projection"] = multimodal_projection
            entries.append(prompt_entry)

        if any(entry.get("must_cover") for entry in entries):
            entries.sort(key=lambda entry: 0 if entry.get("must_cover") else 1)

        writing_rules = self._as_mapping(plan.get("writing_rules"))
        return {
            "schema_version": OUTLINE_EVIDENCE_PROMPT_SCHEMA_VERSION,
            "source_schema_version": str(plan.get("schema_version") or ""),
            "evidence_bounded_writing": True,
            "subhypotheses": entries,
            "writing_rules": {
                key: bool(writing_rules.get(key))
                for key in (
                    "all_subhypotheses_accounted_for",
                    "graph_expanded_candidates_are_not_evidence",
                    "complete_section_promoted_expanded_papers_may_be_used_only_by_their_own_sh_role",
                    "background_context_is_not_direct_evidence",
                    "partial_or_indirect_seed_contributions_require_qualified_synthesis",
                    "not_admissible_subhypotheses_cannot_receive_assertive_conclusions",
                    "claims_require_sh_slot_paper_trace",
                    "multimodal_observations_are_not_literature",
                    "data_anchored_subhypotheses_must_cover",
                )
                if key in writing_rules
            },
        }

    @staticmethod
    def _outline_summary_text(value: Any, max_characters: int = 700) -> str:
        """Return a short summary without serializing a raw whole-paper note."""

        candidates: list[Any] = []
        if isinstance(value, Mapping):
            for key in (
                "summary",
                "keynote_summary",
                "abstract_summary",
                "conclusion",
                "results",
            ):
                if value.get(key):
                    candidates.append(value.get(key))
            claims = value.get("claims")
            if isinstance(claims, Sequence) and not isinstance(claims, (str, bytes)):
                for claim in claims[:2]:
                    if isinstance(claim, Mapping):
                        candidates.append(
                            claim.get("claim")
                            or claim.get("summary")
                            or claim.get("evidence")
                        )
                    else:
                        candidates.append(claim)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            candidates.extend(value[:2])
        elif value:
            candidates.append(value)

        text = " ".join(
            str(candidate or "").strip()
            for candidate in candidates
            if str(candidate or "").strip()
        )
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= max_characters:
            return text
        return text[: max(1, max_characters - 1)].rstrip() + "…"

    def _outline_representative_paper_metadata(self, paper_id: str) -> tuple[str, str]:
        """Load only title plus a bounded keynote summary for an outline."""

        cache = getattr(self, "_outline_representative_metadata_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._outline_representative_metadata_cache = cache
        if paper_id in cache:
            return cache[paper_id]

        title = paper_id
        keynote_summary = ""
        analyzer = getattr(self, "work_analyzer", None)
        collector = getattr(analyzer, "work_collector", None)
        get_title = getattr(collector, "get_paper_title", None)
        if callable(get_title):
            try:
                title = str(get_title(paper_id) or paper_id).strip() or paper_id
            except Exception as exc:
                self.logger.warning(
                    "Unable to get title for outline representative %s: %s",
                    paper_id,
                    exc,
                )

        get_keynote = getattr(analyzer, "get_paper_keynote", None)
        if callable(get_keynote):
            try:
                keynote_summary = self._outline_summary_text(get_keynote(paper_id))
            except Exception as exc:
                self.logger.warning(
                    "Unable to get keynote for outline representative %s: %s",
                    paper_id,
                    exc,
                )

        cache[paper_id] = (title, keynote_summary)
        return cache[paper_id]

    def _outline_paper_brief(self, paper_id: str) -> str:
        """Format the only paper-level evidence text allowed in outline prompts."""

        title, keynote_summary = self._outline_representative_paper_metadata(paper_id)
        return (
            f"Paper ID: {paper_id}\n"
            f"Title: {title}\n"
            f"Keynote summary: {keynote_summary or 'No concise keynote available.'}\n\n"
        )

    def _qualified_limitation_summary(
        self,
        entry: Mapping[str, Any],
        paper_id: str,
        slot_names: Sequence[str],
    ) -> str:
        """Keep a qualified-evidence caveat without exposing raw constraints."""

        fragments: list[Any] = []
        slot_support = self._as_mapping(entry.get("slot_support"))
        for slot_name in slot_names:
            support = self._as_mapping(slot_support.get(slot_name))
            by_paper = self._as_mapping(support.get("qualified_paper_constraints"))
            for raw_paper_id, raw_constraints in by_paper.items():
                if canonical_paper_id(raw_paper_id) != paper_id:
                    continue
                constraints = (
                    raw_constraints
                    if isinstance(raw_constraints, Sequence)
                    and not isinstance(raw_constraints, (str, bytes))
                    else [raw_constraints]
                )
                for raw_constraint in constraints:
                    constraint = self._as_mapping(raw_constraint)
                    fragments.extend(
                        [
                            *self._as_texts(constraint.get("semantic_claim_limits")),
                            *self._as_texts(constraint.get("limitations")),
                            constraint.get("limitation"),
                        ]
                    )

        if not fragments:
            for raw_constraint in self._paper_role_constraints_by_id(entry).get(
                paper_id, []
            ):
                fragments.extend(
                    self._as_texts(
                        self._as_mapping(raw_constraint).get("semantic_claim_limits")
                    )
                )
        if not fragments:
            fragments.extend(
                self._as_texts(self._as_mapping(entry.get("limitations")).get("blockers"))
            )
        summary = self._outline_summary_text(fragments, max_characters=420)
        return summary or "Use this evidence only with its stated qualification."

    def _outline_evidence_plan_prompt_projection(
        self, representative_paper_ids: Sequence[Any]
    ) -> dict[str, Any]:
        """Build the representative-only SH contract used by outline prompts.

        The full plan remains the audit and claim-trace source. This projection
        intentionally excludes every unselected paper, rejected candidate,
        graph-expansion record, raw evidence path, and complete keynote.
        """

        plan = self._as_mapping(getattr(self, "survey_evidence_plan", {}))
        selected_ids = self._as_paper_ids(representative_paper_ids)
        selected_set = set(selected_ids)
        entries: list[dict[str, Any]] = []

        for raw_entry in plan.get("subhypotheses", []):
            if not isinstance(raw_entry, Mapping):
                continue
            entry = self._as_mapping(raw_entry)
            sub_hypothesis_id = str(entry.get("sub_hypothesis_id") or "").strip()
            slot_support = self._as_mapping(entry.get("slot_support"))
            evidence_by_paper_role: dict[tuple[str, str], list[str]] = {}
            writable_slots: list[str] = []
            qualified_slots: list[str] = []

            for raw_slot_name, raw_support in slot_support.items():
                slot_name = str(raw_slot_name or "").strip()
                if not slot_name:
                    continue
                support = self._as_mapping(raw_support)
                role_memberships = (
                    ("direct", self._as_paper_ids(support.get("evidence_paper_ids"))),
                    ("qualified", self._as_paper_ids(support.get("qualified_paper_ids"))),
                    ("background", self._as_paper_ids(support.get("background_paper_ids"))),
                )
                if any(paper_ids for _, paper_ids in role_memberships):
                    writable_slots.append(slot_name)
                if any(
                    role == "qualified" and paper_ids
                    for role, paper_ids in role_memberships
                ):
                    qualified_slots.append(slot_name)
                for evidence_role, paper_ids in role_memberships:
                    for paper_id in paper_ids:
                        if paper_id in selected_set:
                            evidence_by_paper_role.setdefault(
                                (paper_id, evidence_role), []
                            ).append(slot_name)

            represented_slots = {
                slot_name
                for slot_names in evidence_by_paper_role.values()
                for slot_name in slot_names
            }
            mode = str(entry.get("allowed_writing_mode") or "")
            required_covered_slots = [
                slot_name
                for slot_name in writable_slots
                if slot_name in self._as_texts(entry.get("covered_slots"))
                or slot_name in self._as_texts(entry.get("background_only_slots"))
            ]
            missing_representatives = [
                slot_name
                for slot_name in required_covered_slots
                if slot_name not in represented_slots
            ]
            # A representative set can legitimately omit a slot when the
            # ledger retained contextual support that did not survive into the
            # current outline input.  Do not let that prevent an otherwise
            # supported SH from reaching the outline model.  The compact plan
            # makes the omission an explicit evidence gap instead, so the
            # model may synthesize only represented evidence and must not
            # infer support for the missing slot.
            representative_evidence_gaps = []
            if selected_ids and missing_representatives:
                for slot_name in missing_representatives:
                    if slot_name == "comparable_endpoint":
                        instruction = (
                            "State explicitly that the selected evidence does not "
                            "support a comparable endpoint; do not draw a cross-model "
                            "endpoint comparison."
                        )
                    else:
                        instruction = (
                            "State explicitly that this slot lacks selected "
                            "representative evidence; do not make a substantive "
                            "claim about it."
                        )
                    representative_evidence_gaps.append(
                        {
                            "slot_name": slot_name,
                            "instruction": instruction,
                        }
                    )

            representative_evidence: list[dict[str, Any]] = []
            for paper_id in selected_ids:
                for evidence_role in ("direct", "qualified", "background"):
                    covered_slots = evidence_by_paper_role.get(
                        (paper_id, evidence_role), []
                    )
                    if not covered_slots:
                        continue
                    title, keynote_summary = self._outline_representative_paper_metadata(
                        paper_id
                    )
                    limitation_summary = ""
                    if evidence_role == "qualified":
                        limitation_summary = self._qualified_limitation_summary(
                            entry, paper_id, covered_slots
                        )
                    elif evidence_role == "background":
                        limitation_summary = (
                            "Background context only; do not state it as direct evidence."
                        )
                    representative_evidence.append(
                        {
                            "paper_id": paper_id,
                            "title": title,
                            "evidence_role": evidence_role,
                            "covered_slots": self._as_texts(covered_slots),
                            "limitation_summary": limitation_summary,
                            "keynote_summary": keynote_summary,
                        }
                    )

            if selected_ids and mode == QUALIFIED_SYNTHESIS and qualified_slots:
                qualified_items = [
                    item
                    for item in representative_evidence
                    if item["evidence_role"] == "qualified"
                ]
                if not qualified_items or any(
                    not item["limitation_summary"] for item in qualified_items
                ):
                    raise OutlineGenerationError(
                        "Qualified outline evidence requires a representative paper and "
                        f"limitation summary for {sub_hypothesis_id or 'an unnamed SH'}."
                    )

            prompt_entry = {
                    "sub_hypothesis_id": sub_hypothesis_id,
                    "summary": str(entry.get("summary") or ""),
                    "mode": mode,
                    "required_slots": self._as_texts(entry.get("required_slots")),
                    "covered_slots": self._as_texts(entry.get("covered_slots")),
                    "background_only_slots": self._as_texts(
                        entry.get("background_only_slots")
                    ),
                    "missing_slots": self._as_texts(entry.get("missing_slots")),
                    "representative_evidence": representative_evidence,
                    "representative_evidence_gaps": representative_evidence_gaps,
            }
            multimodal_projection = self._as_mapping(entry.get("multimodal_projection"))
            if multimodal_projection:
                prompt_entry["analysis_priority"] = str(
                    entry.get("analysis_priority") or ""
                )
                prompt_entry["must_cover"] = bool(entry.get("must_cover"))
                prompt_entry["allowed_claim_modes"] = self._as_texts(
                    entry.get("allowed_claim_modes")
                )
                prompt_entry["multimodal_projection"] = multimodal_projection
            entries.append(prompt_entry)

        if any(entry.get("must_cover") for entry in entries):
            entries.sort(key=lambda entry: 0 if entry.get("must_cover") else 1)

        writing_rules = self._as_mapping(plan.get("writing_rules"))
        derived_writing_rules = {
            "representative_evidence_gaps_must_be_reported_without_assertive_claims": True
        }
        if any(entry.get("must_cover") for entry in entries):
            derived_writing_rules.update(
                {
                    "multimodal_observations_are_not_literature": True,
                    "data_anchored_subhypotheses_must_cover": True,
                }
            )
        return {
            "schema_version": OUTLINE_EVIDENCE_PROMPT_SCHEMA_VERSION,
            "source_schema_version": str(plan.get("schema_version") or ""),
            "projection_scope": "outline_representative_evidence_only",
            "selected_representative_paper_ids": selected_ids,
            "evidence_bounded_writing": True,
            "subhypotheses": entries,
            "writing_rules": {
                key: bool(writing_rules.get(key))
                for key in (
                    "all_subhypotheses_accounted_for",
                    "background_context_is_not_direct_evidence",
                    "partial_or_indirect_seed_contributions_require_qualified_synthesis",
                    "not_admissible_subhypotheses_cannot_receive_assertive_conclusions",
                    "representative_evidence_gaps_must_be_reported_without_assertive_claims",
                    "multimodal_observations_are_not_literature",
                    "data_anchored_subhypotheses_must_cover",
                )
                if key in writing_rules
            }
            | derived_writing_rules,
        }

    def _survey_evidence_plan_prompt(
        self, representative_paper_ids: Sequence[Any] | None = None
    ) -> str:
        if not self._evidence_bounded_writing_enabled():
            return "No active SH evidence plan is available for this non-SH survey run."
        compact_plan = (
            self._outline_evidence_plan_prompt_projection(representative_paper_ids)
            if representative_paper_ids is not None
            else self._survey_evidence_plan_prompt_projection()
        )
        prompt = json.dumps(compact_plan, ensure_ascii=False, separators=(",", ":"))
        generator_config = self.config.ModuleInfo.SurveyGenerator
        max_tokens = self._positive_int(
            getattr(generator_config, "outline_evidence_plan_max_input_tokens", 100_000),
            100_000,
        )
        token_count = self._estimate_prompt_tokens(prompt)
        if token_count > max_tokens:
            raise OutlineGenerationError(
                "Compact survey evidence plan exceeds its prompt budget: "
                f"{token_count} > {max_tokens} tokens. The full plan remains "
                "available as an audit artifact; reduce allowed-paper constraints "
                "or increase outline_evidence_plan_max_input_tokens explicitly."
            )
        return prompt

    def _outline_input_token_budget(self) -> int:
        generator_config = self.config.ModuleInfo.SurveyGenerator
        api_info = self.config.APIInfo
        context_limit = self._positive_int(
            getattr(api_info, "llm_max_context_length", 0), 0
        )
        if context_limit <= 0:
            raise OutlineGenerationError("Outline generation requires llm_max_context_length.")
        output_reserve = self._positive_int(
            getattr(generator_config, "outline_max_output_tokens", 16_000), 16_000
        )
        overhead = self._positive_int(
            getattr(
                generator_config,
                "llm_max_context_overhead_length_outline_generation",
                10_000,
            ),
            10_000,
        )
        available = context_limit - output_reserve - overhead
        if available <= 0:
            raise OutlineGenerationError(
                "Outline context budget is non-positive after output reserve and overhead: "
                f"context={context_limit}, output={output_reserve}, overhead={overhead}."
            )
        configured = self._positive_int(
            getattr(generator_config, "outline_prompt_max_input_tokens", 160_000),
            160_000,
        )
        return min(configured, available)

    def _truncate_outline_component(
        self, label: str, text: Any, max_tokens: int
    ) -> str:
        """Trim a dynamic component, never the assembled prompt or its schema."""
        content = str(text or "")
        token_count = self._estimate_prompt_tokens(content)
        if token_count <= max_tokens:
            return content
        truncate = getattr(getattr(self, "chat_agent", None), "truncate_text", None)
        if callable(truncate):
            content = truncate(f"outline:{label}", content, max_tokens)
        else:
            upper_bound = max(1, int(len(content) * max_tokens / token_count))
            content = content[:upper_bound]
        while content and self._estimate_prompt_tokens(content) > max_tokens:
            content = content[: max(1, int(len(content) * 0.9))]
        self.logger.warning(
            "Capped outline prompt component '%s' from %s to %s tokens.",
            label,
            token_count,
            self._estimate_prompt_tokens(content),
        )
        return content

    def _build_outline_prompt(
        self,
        *,
        template: str,
        phase: str,
        paper_keynotes: Any,
        current_outline: Any,
        papers_analysis: Any,
        other_relevant_papers: Any,
        representative_paper_ids: Sequence[Any] | None = None,
    ) -> tuple[str, dict[str, int]]:
        """Build an outline prompt under explicit component and total budgets."""
        generator_config = self.config.ModuleInfo.SurveyGenerator
        components = {
            "survey_evidence_plan": self._survey_evidence_plan_prompt(
                representative_paper_ids=representative_paper_ids
            ),
            "outline_size_budget": self._outline_size_budget_prompt(),
            "current_outline": json.dumps(current_outline or {}, ensure_ascii=False),
            "paper_keynotes": str(paper_keynotes or ""),
            "papers_analysis": str(papers_analysis or ""),
            "other_relevant_papers": str(other_relevant_papers or ""),
        }
        component_limits = {
            "current_outline": self._positive_int(
                getattr(generator_config, "outline_current_outline_max_input_tokens", 20_000),
                20_000,
            ),
            "paper_keynotes": self._positive_int(
                getattr(generator_config, "outline_keynotes_max_input_tokens", 70_000),
                70_000,
            ),
            "papers_analysis": self._positive_int(
                getattr(generator_config, "outline_analysis_max_input_tokens", 12_000),
                12_000,
            ),
            "other_relevant_papers": self._positive_int(
                getattr(generator_config, "outline_rag_max_input_tokens", 12_000),
                12_000,
            ),
        }
        for name, limit in component_limits.items():
            components[name] = self._truncate_outline_component(
                name,
                components[name],
                limit,
            )

        prompt = template.format(**components)
        total_budget = self._outline_input_token_budget()
        token_breakdown = {
            name: self._estimate_prompt_tokens(value)
            for name, value in components.items()
        }
        token_breakdown["total"] = self._estimate_prompt_tokens(prompt)
        token_breakdown["budget"] = total_budget
        if token_breakdown["total"] > total_budget and components["other_relevant_papers"]:
            components["other_relevant_papers"] = ""
            prompt = template.format(**components)
            token_breakdown["other_relevant_papers"] = 0
            token_breakdown["total"] = self._estimate_prompt_tokens(prompt)
        if token_breakdown["total"] > total_budget:
            raise OutlineGenerationError(
                f"Outline {phase} prompt exceeds its preflight budget: "
                + ", ".join(
                    f"{name}={count}"
                    for name, count in token_breakdown.items()
                )
            )
        self.logger.info(
            "Outline %s prompt token budget: %s.",
            phase,
            ", ".join(f"{name}={count}" for name, count in token_breakdown.items()),
        )
        return prompt, token_breakdown

    def _outline_size_budget_prompt(self) -> str:
        """Describe a bounded survey shape instead of rewarding outline sprawl."""

        generator_config = self.config.ModuleInfo.SurveyGenerator
        target_words = self._positive_int(
            getattr(generator_config, "survey_target_words", 25_000), 25_000
        )
        max_words = max(
            target_words,
            self._positive_int(
                getattr(generator_config, "survey_max_words", 30_000), 30_000
            ),
        )
        target_sections = self._positive_int(
            getattr(generator_config, "outline_target_sections", 6), 6
        )
        min_sections = self._positive_int(
            getattr(generator_config, "outline_min_sections", 5), 5
        )
        max_sections = max(
            target_sections,
            self._positive_int(
                getattr(generator_config, "outline_max_sections", 7), 7
            ),
        )
        target_subsections = self._positive_int(
            getattr(
                generator_config, "outline_target_subsections_per_section", 3
            ),
            3,
        )
        max_subsections = max(
            target_subsections,
            self._positive_int(
                getattr(
                    generator_config, "outline_max_subsections_per_section", 3
                ),
                3,
            ),
        )
        return (
            f"Target a concise survey body of about {target_words} words and never "
            f"plan beyond {max_words} words. Use {min_sections}-{max_sections} "
            f"sections (target {target_sections}) and normally about "
            f"{target_subsections} subsections per section; never exceed "
            f"{max_subsections}. Merge adjacent topics instead of creating a "
            "section or subsection for every paper or SH."
        )

    def _outline_json_response_format(self) -> str | None:
        supports_format = getattr(self.chat_agent, "supports_response_format", None)
        if not callable(supports_format):
            return None
        try:
            return "json_object" if supports_format("json_object") else None
        except Exception as exc:
            self.logger.warning(
                "Unable to determine JSON-object support for outline generation: %s",
                exc,
            )
            return None

    def _outline_max_output_tokens(self) -> int:
        return self._positive_int(
            getattr(
                self.config.ModuleInfo.SurveyGenerator,
                "outline_max_output_tokens",
                4_096,
            ),
            4_096,
        )

    def _build_outline_repair_prompt(
        self,
        *,
        current_outline: Any,
        validation_error: Any,
        previous_response: Any,
    ) -> str:
        generator_config = self.config.ModuleInfo.SurveyGenerator
        repair_response_limit = self._positive_int(
            getattr(
                generator_config,
                "outline_repair_previous_response_max_input_tokens",
                8_000,
            ),
            8_000,
        )
        repair_outline_limit = self._positive_int(
            getattr(
                generator_config,
                "outline_repair_current_outline_max_input_tokens",
                8_000,
            ),
            8_000,
        )
        prompt = SURVEY_OUTLINE_REPAIR.format(
            validation_error=self._truncate_outline_component(
                "repair_error", validation_error, 1_000
            ),
            current_outline=self._truncate_outline_component(
                "repair_current_outline",
                json.dumps(current_outline or {}, ensure_ascii=False),
                repair_outline_limit,
            ),
            survey_evidence_plan=self._survey_evidence_plan_prompt(
                representative_paper_ids=getattr(
                    self, "_outline_representative_paper_ids", []
                )
            ),
            previous_response=self._truncate_outline_component(
                "repair_previous_response",
                previous_response,
                repair_response_limit,
            ),
        )
        token_count = self._estimate_prompt_tokens(prompt)
        budget = self._outline_input_token_budget()
        if token_count > budget:
            raise OutlineGenerationError(
                "Outline repair prompt exceeds its preflight budget: "
                f"{token_count} > {budget}."
            )
        return prompt

    def _request_outline_json(self, prompt: str) -> str:
        return self.chat_agent.remote_chat(
            text_content=prompt,
            temperature=self.config.ModuleInfo.SurveyGenerator.outline_generation_temperature,
            max_output_tokens=self._outline_max_output_tokens(),
            strict_input_budget=True,
            response_format=self._outline_json_response_format(),
        )

    def _require_assignable_outline(self, outline: Any) -> dict[str, Any]:
        valid, reason = self.validate_outline_format(outline)
        if not valid:
            raise OutlineGenerationError(
                "Cannot assign papers because draft outline is invalid: " + reason
            )
        normalized = dict(outline)
        if not normalized["sections"]:
            raise OutlineGenerationError(
                "Cannot assign papers because draft outline has no sections."
            )
        return normalized

    @staticmethod
    def _parse_outline_assignments(response: Any) -> list[dict[str, Any]]:
        """Read JSON-object assignment output, retaining legacy list compatibility."""
        payload = extract_json(response) if isinstance(response, str) else response
        if isinstance(payload, Mapping):
            assignments = payload.get("assignments")
        else:
            assignments = payload
        if not isinstance(assignments, list):
            raise ValueError("Outline assignment response must contain an 'assignments' list.")
        return [dict(item) for item in assignments if isinstance(item, Mapping)]

    def _permitted_evidence_plan_paper_ids(self) -> set[str]:
        if not self._evidence_bounded_writing_enabled():
            return set()
        return {
            paper_id
            for entry in self.survey_evidence_plan.get("subhypotheses", [])
            if isinstance(entry, Mapping)
            for paper_id in [
                *self._as_paper_ids(entry.get("evidence_paper_ids")),
                *self._as_paper_ids(entry.get("qualified_paper_ids")),
                *self._as_paper_ids(entry.get("context_paper_ids")),
            ]
        }

    def _bounded_writing_paper_ids(self, papers: Sequence[Any] | None) -> list[str]:
        """Keep only ledger-admitted direct/background work for SH-bound prompts."""

        paper_ids = self._as_paper_ids(papers)
        if not self._evidence_bounded_writing_enabled():
            return paper_ids
        permitted = self._permitted_evidence_plan_paper_ids()
        return [paper_id for paper_id in paper_ids if paper_id in permitted]

    @staticmethod
    def _append_unique(target: list[str], candidates: Sequence[Any], available: set[str]) -> None:
        """Append available paper IDs once, preserving evidence-plan order."""

        for paper_id in candidates:
            identifier = canonical_paper_id(paper_id)
            if identifier and identifier in available and identifier not in target:
                target.append(identifier)

    def _select_outline_representative_paper_ids(
        self, papers: Sequence[Any] | None
    ) -> list[str]:
        """Select a small SH-covering set for outline drafting.

        Drafting an outline needs contrasting representative evidence, not every
        paper that may later be assigned to a subsection.  The assignment phase
        still receives the full bounded paper set.  One paper is retained for
        every available evidence-plan slot before optional per-SH fill-up is
        applied, so the cap cannot silently drop an SH's only support.
        Qualified synthesis also retains one qualified representative so its
        required limitation reaches the outline prompt.
        """

        paper_ids = self._as_paper_ids(papers)
        if not paper_ids:
            return []

        generator_config = self.config.ModuleInfo.SurveyGenerator
        max_per_sh = self._positive_int(
            getattr(generator_config, "outline_representative_papers_per_sh", 4), 4
        )
        max_total = self._positive_int(
            getattr(generator_config, "outline_representative_max_papers", 30), 30
        )
        available = set(paper_ids)
        entries = [
            entry
            for entry in (self.survey_evidence_plan or {}).get("subhypotheses", [])
            if isinstance(entry, Mapping)
        ]

        # A legacy/non-SH run still gets a bounded outline input, albeit without
        # evidence-slot coverage semantics to guide the selection.
        if not entries:
            selected = paper_ids[:max_total]
            if len(selected) < len(paper_ids):
                self.logger.info(
                    "Outline representative selection (no SH plan): selected %s/%s papers.",
                    len(selected),
                    len(paper_ids),
                )
            return selected

        selected: list[str] = []
        selected_by_sh: dict[str, list[str]] = {}
        optional_by_sh: dict[str, list[str]] = {}
        include_context = bool(
            getattr(
                generator_config, "outline_representative_include_context_papers", True
            )
        )
        for entry in entries:
            sub_hypothesis_id = str(entry.get("sub_hypothesis_id") or "unknown")
            sh_selected: list[str] = []
            slot_support = entry.get("slot_support")
            mode = str(entry.get("allowed_writing_mode") or "")
            if mode == QUALIFIED_SYNTHESIS and isinstance(slot_support, Mapping):
                qualified_representative = next(
                    (
                        paper_id
                        for support in slot_support.values()
                        if isinstance(support, Mapping)
                        for paper_id in self._as_paper_ids(
                            support.get("qualified_paper_ids")
                        )
                        if paper_id in available
                    ),
                    "",
                )
                if qualified_representative:
                    sh_selected.append(qualified_representative)
            if isinstance(slot_support, Mapping):
                for support in slot_support.values():
                    if not isinstance(support, Mapping):
                        continue
                    # Direct support is preferred, then qualified support, then
                    # context used only to describe a documented limitation.
                    for key in (
                        "evidence_paper_ids",
                        "qualified_paper_ids",
                        "background_paper_ids",
                    ):
                        representative = next(
                            (
                                paper_id
                                for paper_id in self._as_paper_ids(support.get(key))
                                if paper_id in available and paper_id not in sh_selected
                            ),
                            "",
                        )
                        if representative:
                            sh_selected.append(representative)
                            break

            # First keep every slot representative globally.  These are never
            # displaced by a total cap, because that would make an SH invisible
            # in outline construction.
            self._append_unique(selected, sh_selected, available)
            selected_by_sh[sub_hypothesis_id] = sh_selected
            optional_by_sh[sub_hypothesis_id] = [
                *self._as_paper_ids(entry.get("evidence_paper_ids")),
                *self._as_paper_ids(entry.get("qualified_paper_ids")),
            ]
            if include_context:
                optional_by_sh[sub_hypothesis_id].extend(
                    self._as_paper_ids(entry.get("context_paper_ids"))
                )

        if len(selected) > max_total:
            self.logger.info(
                "Outline representative cap %s exceeded by %s mandatory SH-slot representatives.",
                max_total,
                len(selected),
            )

        # Only the optional comparison studies are constrained by total/per-SH
        # caps.  Round-robin selection avoids letting an early SH monopolize
        # the compact prompt.
        optional_added_by_sh = {sh_id: 0 for sh_id in selected_by_sh}
        made_progress = True
        while len(selected) < max_total and made_progress:
            made_progress = False
            for sub_hypothesis_id, candidates in optional_by_sh.items():
                if len(selected) >= max_total:
                    break
                if (
                    len(selected_by_sh[sub_hypothesis_id])
                    + optional_added_by_sh[sub_hypothesis_id]
                    >= max_per_sh
                ):
                    continue
                before = len(selected)
                self._append_unique(selected, candidates, available)
                # _append_unique can add every candidate, so retain only one
                # optional paper per SH per round for balanced coverage.
                if len(selected) > before + 1:
                    del selected[before + 1 :]
                if len(selected) > before:
                    optional_added_by_sh[sub_hypothesis_id] += 1
                    made_progress = True

        if not selected:
            selected = paper_ids[:max_total]
        self.logger.info(
            "Outline representative evidence selected %s/%s papers across %s SHs: %s",
            len(selected),
            len(paper_ids),
            len(selected_by_sh),
            "; ".join(
                f"{sh_id}={len(paper_ids_for_sh)}"
                for sh_id, paper_ids_for_sh in selected_by_sh.items()
            ),
        )
        return selected

    def _survey_length_budget(self, outline: Mapping[str, Any] | None = None) -> dict[str, int]:
        """Translate the whole-survey length contract into unit-level budgets."""

        generator_config = self.config.ModuleInfo.SurveyGenerator
        survey_target_words = self._positive_int(
            getattr(generator_config, "survey_target_words", 10_000), 10_000
        )
        survey_max_words = max(
            survey_target_words,
            self._positive_int(
                getattr(generator_config, "survey_max_words", 12_000), 12_000
            ),
        )
        sections = [
            section
            for section in (dict(outline or {}).get("sections") or [])
            if isinstance(section, Mapping)
        ]
        section_count = len(sections) or self._positive_int(
            getattr(generator_config, "outline_target_sections", 6), 6
        )
        subsection_count = sum(
            len(section.get("subsections") or []) for section in sections
        )
        if not subsection_count:
            subsection_count = section_count * self._positive_int(
                getattr(
                    generator_config, "outline_target_subsections_per_section", 3
                ),
                3,
            )

        preamble_target_words = self._positive_int(
            getattr(generator_config, "section_preamble_target_words", 250), 250
        )
        preamble_max_words = max(
            preamble_target_words,
            self._positive_int(
                getattr(generator_config, "section_preamble_max_words", 400), 400
            ),
        )
        configured_subsection_min = self._positive_int(
            getattr(generator_config, "subsection_target_min_words", 875), 875
        )
        configured_subsection_max = max(
            configured_subsection_min,
            self._positive_int(
                getattr(generator_config, "subsection_target_max_words", 1_500), 1_500
            ),
        )
        target_per_subsection = math.ceil(
            max(1, survey_target_words - section_count * preamble_target_words)
            / subsection_count
        )
        subsection_target_words = min(
            configured_subsection_max,
            max(configured_subsection_min, target_per_subsection),
        )
        max_per_subsection_from_total = max(
            1,
            (survey_max_words - section_count * preamble_max_words)
            // subsection_count,
        )
        subsection_max_words = min(
            configured_subsection_max,
            max_per_subsection_from_total,
        )
        # A malformed/oversized manually provided outline should be rejected by
        # outline validation.  Keep the budget internally consistent until then.
        subsection_target_words = min(
            subsection_target_words, subsection_max_words
        )
        subsection_target_citations = self._positive_int(
            getattr(generator_config, "subsection_target_citations", 3), 3
        )
        subsection_max_citations = max(
            subsection_target_citations,
            self._positive_int(
                getattr(generator_config, "subsection_max_citations", 5), 5
            ),
        )
        preamble_target_citations = self._positive_int(
            getattr(generator_config, "section_preamble_target_citations", 1), 1
        )
        preamble_max_citations = max(
            preamble_target_citations,
            self._positive_int(
                getattr(generator_config, "section_preamble_max_citations", 2), 2
            ),
        )
        return {
            "survey_target_words": survey_target_words,
            "survey_max_words": survey_max_words,
            "section_count": section_count,
            "subsection_count": subsection_count,
            "subsection_target_words": subsection_target_words,
            "subsection_max_words": subsection_max_words,
            "subsection_target_citations": subsection_target_citations,
            "subsection_max_citations": subsection_max_citations,
            "section_preamble_target_words": preamble_target_words,
            "section_preamble_max_words": preamble_max_words,
            "section_preamble_target_citations": preamble_target_citations,
            "section_preamble_max_citations": preamble_max_citations,
            "section_target_words": math.ceil(survey_target_words / section_count),
        }

    def _keep_revised_sections_within_budget(
        self,
        original_sections: Sequence[str],
        revised_sections: Sequence[str],
        outline: Mapping[str, Any] | None,
    ) -> list[str]:
        """Keep a concise valid draft if an unbounded revision expands a section.

        Revision is allowed to improve wording but must not quietly invalidate the
        total-survey contract.  Falling back to the already validated section is
        safer than truncating prose mid-argument.
        """

        budget = self._survey_length_budget(outline)
        section_cap = math.ceil(
            budget["survey_max_words"] / budget["section_count"]
        )
        bounded: list[str] = []
        for index, original in enumerate(original_sections):
            revised = revised_sections[index] if index < len(revised_sections) else original
            if len(str(revised).split()) > section_cap:
                self.logger.warning(
                    "Discarding overlong revision for section %s: %s > %s words; "
                    "keeping the validated pre-revision section.",
                    index + 1,
                    len(str(revised).split()),
                    section_cap,
                )
                bounded.append(original)
            else:
                bounded.append(revised)
        return bounded

    def _ensure_survey_body_within_budget(
        self, survey_text: str, outline: Mapping[str, Any] | None, stage: str
    ) -> None:
        budget = self._survey_length_budget(outline)
        word_count = len(str(survey_text or "").split())
        if word_count > budget["survey_max_words"]:
            raise ValueError(
                f"Survey {stage} exceeds the configured body-length budget: "
                f"{word_count} > {budget['survey_max_words']} words."
            )

    def _evidence_bounded_section_quality_settings(self) -> dict[str, Any]:
        """Read the non-blocking quality-pass controls with safe defaults."""

        generator_config = self.config.ModuleInfo.SurveyGenerator
        raw_enabled = getattr(
            generator_config, "evidence_bounded_section_quality_review_enabled", True
        )
        enabled = (
            raw_enabled.strip().casefold() not in {"false", "0", "no", "off"}
            if isinstance(raw_enabled, str)
            else bool(raw_enabled)
        )
        try:
            threshold = float(
                getattr(
                    generator_config,
                    "evidence_bounded_section_quality_score_threshold",
                    8.0,
                )
            )
        except (TypeError, ValueError):
            threshold = 8.0
        threshold = min(10.0, max(0.0, threshold))

        def nonnegative_int(name: str, default: int) -> int:
            try:
                return max(0, int(getattr(generator_config, name, default)))
            except (TypeError, ValueError):
                return default

        return {
            "enabled": enabled,
            "threshold": threshold,
            "max_improvements": nonnegative_int(
                "evidence_bounded_section_quality_max_improvements", 2
            ),
            "review_retry": max(
                1,
                nonnegative_int(
                    "evidence_bounded_section_quality_review_retry", 2
                ),
            ),
            "revise_retry": max(
                1,
                nonnegative_int(
                    "evidence_bounded_section_quality_revise_retry", 2
                ),
            ),
            "max_suggestions": max(
                1, self._positive_int(getattr(generator_config, "reviewer_max_suggestions", 5), 5)
            ),
        }

    def _evidence_bounded_section_allowed_paper_ids(
        self, section_outline: Mapping[str, Any] | None
    ) -> set[str]:
        """Return the evidence-plan papers assigned to one immutable section."""

        section = self._as_mapping(section_outline)
        candidates: list[str] = []
        for unit in [section, *(section.get("subsections") or [])]:
            if isinstance(unit, Mapping):
                candidates.extend(self._as_paper_ids(unit.get("papers_to_use")))
        permitted = self._permitted_evidence_plan_paper_ids()
        return {paper_id for paper_id in candidates if paper_id in permitted}

    @staticmethod
    def _section_heading_signature(section_text: str) -> list[str]:
        """Capture the immutable Markdown headings of a section."""

        return [
            re.sub(r"\s+", " ", line).strip()
            for line in str(section_text or "").splitlines()
            if re.match(r"^\s{0,3}#{1,6}\s+\S", line)
        ]

    def _evidence_bounded_section_cited_paper_ids(
        self, section_text: str
    ) -> tuple[list[str], list[str]]:
        """Resolve only the citations already visible in a bounded section."""

        if self.use_title_in_draft:
            valid, paper_ids, _titles, errors = self.extract_and_validate_titles_in_text(
                section_text
            )
            if not valid or errors:
                return [], self._as_texts(errors) or [
                    "one or more title citations could not be resolved"
                ]
            return self._as_paper_ids(paper_ids), []
        return self._as_paper_ids(self.get_unique_paper_ids_from_raw(section_text)), []

    def _review_evidence_bounded_section_quality(
        self,
        *,
        section_text: str,
        previous_section_text: str,
        next_section_text: str,
        section_outline: Mapping[str, Any],
        settings: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Score one section; errors are logged and remain non-blocking."""

        prompt = EVIDENCE_BOUNDED_SECTION_QUALITY_REVIEW.format(
            topic=self.config.BasicInfo.topic,
            max_suggestions=int(settings["max_suggestions"]),
            previous_section_text=previous_section_text or "(No previous section)",
            next_section_text=next_section_text or "(No next section)",
            section_text=section_text,
            section_outline=self._format_section_outline(section_outline),
        )
        generator_config = self.config.ModuleInfo.SurveyGenerator
        temperature = getattr(generator_config, "section_review_temperature", 0.2)
        for attempt in range(int(settings["review_retry"])):
            try:
                payload = extract_json(
                    self.chat_agent.remote_chat(
                        prompt,
                        temperature=temperature,
                        response_format="json_object",
                    )
                )
                if not isinstance(payload, Mapping):
                    raise ValueError("quality review response is not a JSON object")
                raw_scores = self._as_mapping(payload.get("scores"))
                scores: dict[str, float] = {}
                for dimension in ("readability", "scientific", "framework"):
                    raw_score = raw_scores.get(dimension)
                    if dimension == "scientific" and raw_score is None:
                        # Accept the old agentic-reviewer field while all new
                        # prompts and logs use the requested scientific label.
                        raw_score = raw_scores.get("depth")
                    if raw_score is None:
                        raise ValueError(f"quality review omitted '{dimension}' score")
                    score = float(raw_score)
                    if not math.isfinite(score):
                        raise ValueError(f"quality review has non-finite '{dimension}' score")
                    scores[dimension] = min(10.0, max(0.0, score))
                raw_suggestions = payload.get("suggestions", [])
                if not isinstance(raw_suggestions, list):
                    raise ValueError("quality review suggestions must be a list")
                suggestions = [
                    str(suggestion).strip()
                    for suggestion in raw_suggestions
                    if str(suggestion).strip()
                ][: int(settings["max_suggestions"])]
                return {"scores": scores, "suggestions": suggestions}
            except Exception as exc:
                self.logger.warning(
                    "Evidence-bounded quality review attempt %s/%s failed: %s",
                    attempt + 1,
                    settings["review_retry"],
                    exc,
                )
        return None

    def _revise_evidence_bounded_section_quality(
        self,
        *,
        section_text: str,
        section_outline: Mapping[str, Any],
        suggestions: Sequence[str],
        section_word_cap: int,
        settings: Mapping[str, Any],
    ) -> str | None:
        """Request a complete but citation-preserving bounded section revision."""

        prompt = EVIDENCE_BOUNDED_SECTION_QUALITY_REVISE.format(
            topic=self.config.BasicInfo.topic,
            section_outline=self._format_section_outline(section_outline),
            section_text=section_text,
            suggestions="\n".join(f"- {suggestion}" for suggestion in suggestions),
            section_word_cap=section_word_cap,
        )
        generator_config = self.config.ModuleInfo.SurveyGenerator
        temperature = getattr(generator_config, "section_revise_temperature", 0.2)
        for attempt in range(int(settings["revise_retry"])):
            try:
                payload = extract_json(
                    self.chat_agent.remote_chat(
                        prompt,
                        temperature=temperature if attempt == 0 else 0.1,
                        response_format="json_object",
                    )
                )
                revised = (
                    payload.get("revised_section") if isinstance(payload, Mapping) else None
                )
                if not isinstance(revised, str) or not revised.strip():
                    raise ValueError("quality revision must contain non-empty 'revised_section'")
                return revised.strip()
            except Exception as exc:
                self.logger.warning(
                    "Evidence-bounded quality revision attempt %s/%s failed: %s",
                    attempt + 1,
                    settings["revise_retry"],
                    exc,
                )
        return None

    def _validate_evidence_bounded_section_quality_revision(
        self,
        *,
        original_section: str,
        revised_section: str,
        allowed_paper_ids: set[str],
        section_word_cap: int,
    ) -> list[str]:
        """Reject unsafe quality rewrites while retaining the last valid draft."""

        errors: list[str] = []
        if self._section_heading_signature(revised_section) != self._section_heading_signature(
            original_section
        ):
            errors.append("section or subsection headings changed")
        if len(str(revised_section).split()) > section_word_cap:
            errors.append(
                f"section exceeds its word cap: {len(str(revised_section).split())} > {section_word_cap}"
            )

        original_ids, original_errors = self._evidence_bounded_section_cited_paper_ids(
            original_section
        )
        revised_ids, revised_errors = self._evidence_bounded_section_cited_paper_ids(
            revised_section
        )
        if original_errors:
            errors.extend(f"original citation invalid: {error}" for error in original_errors)
        if revised_errors:
            errors.extend(f"revised citation invalid: {error}" for error in revised_errors)
        if not original_errors and not revised_errors:
            if set(original_ids) != set(revised_ids):
                errors.append("citation paper set changed during quality revision")
            unauthorized = set(revised_ids) - allowed_paper_ids
            if unauthorized:
                errors.append(
                    "citation is outside this section's evidence-plan whitelist: "
                    + ", ".join(sorted(unauthorized))
                )
        return errors

    def _improve_evidence_bounded_sections(self, draft: dict) -> dict:
        """Run bounded quality improvement without making survey completion depend on it.

        Unlike the legacy free-form revisor, this path has no external RAG and
        accepts a rewritten section only after structural, citation, whitelist,
        and length checks.  Any review/revision failure leaves the last safe
        text in place and merely emits a warning.
        """

        if not self._evidence_bounded_writing_enabled():
            return draft
        settings = self._evidence_bounded_section_quality_settings()
        if not settings["enabled"]:
            self.logger.info("Evidence-bounded section quality review is disabled.")
            return draft
        if self._claim_trace_validation_enabled():
            self.logger.warning(
                "Skipping evidence-bounded section quality review because strict "
                "claim-trace validation is enabled and a prose rewrite would make "
                "the persisted claim text stale."
            )
            return draft

        outline = self._as_mapping(draft.get("outline"))
        sections = [str(section or "") for section in draft.get("section_drafts", [])]
        outline_sections = [
            self._as_mapping(section) for section in outline.get("sections", [])
        ]
        if not sections:
            return draft

        budget = self._survey_length_budget(outline)
        section_word_cap = math.ceil(
            budget["survey_max_words"] / max(1, budget["section_count"])
        )
        revised_sections = list(sections)
        for index, original_section in enumerate(sections):
            section_outline = (
                outline_sections[index] if index < len(outline_sections) else {}
            )
            allowed_paper_ids = self._evidence_bounded_section_allowed_paper_ids(
                section_outline
            )
            original_ids, original_citation_errors = (
                self._evidence_bounded_section_cited_paper_ids(original_section)
            )
            baseline_errors = [
                f"original citation invalid: {error}"
                for error in original_citation_errors
            ]
            baseline_unauthorized = set(original_ids) - allowed_paper_ids
            if baseline_unauthorized:
                baseline_errors.append(
                    "original citation is outside this section's evidence-plan "
                    "whitelist: " + ", ".join(sorted(baseline_unauthorized))
                )
            if baseline_errors:
                self.logger.warning(
                    "Skipping quality revision for section %s because its existing "
                    "citation boundary cannot be established: %s",
                    index + 1,
                    " | ".join(baseline_errors),
                )
                continue

            current_section = original_section
            accepted_improvements = 0
            for review_round in range(int(settings["max_improvements"]) + 1):
                review = self._review_evidence_bounded_section_quality(
                    section_text=current_section,
                    previous_section_text=sections[index - 1] if index else "",
                    next_section_text=(
                        sections[index + 1] if index + 1 < len(sections) else ""
                    ),
                    section_outline=section_outline,
                    settings=settings,
                )
                if review is None:
                    self.logger.warning(
                        "Section %s quality could not be scored; retaining its last "
                        "safe version without blocking the survey.",
                        index + 1,
                    )
                    break
                scores = review["scores"]
                self.logger.info(
                    "Evidence-bounded quality review for section %s, round %s/%s: %s",
                    index + 1,
                    review_round + 1,
                    int(settings["max_improvements"]) + 1,
                    scores,
                )
                low_dimensions = [
                    dimension
                    for dimension, score in scores.items()
                    if score < settings["threshold"]
                ]
                if not low_dimensions:
                    self.logger.info(
                        "Evidence-bounded section %s meets the quality target: %s",
                        index + 1,
                        scores,
                    )
                    break
                if review_round >= int(settings["max_improvements"]):
                    self.logger.warning(
                        "Section %s remains below the %.1f quality target after %s "
                        "accepted improvement(s), low dimensions=%s, scores=%s; "
                        "continuing without blocking the survey.",
                        index + 1,
                        settings["threshold"],
                        accepted_improvements,
                        ", ".join(low_dimensions),
                        scores,
                    )
                    break
                suggestions = review["suggestions"]
                if not suggestions:
                    self.logger.warning(
                        "Section %s is below the quality target but has no safe "
                        "revision suggestion; retaining its current version.",
                        index + 1,
                    )
                    break
                candidate = self._revise_evidence_bounded_section_quality(
                    section_text=current_section,
                    section_outline=section_outline,
                    suggestions=suggestions,
                    section_word_cap=section_word_cap,
                    settings=settings,
                )
                if candidate is None:
                    self.logger.warning(
                        "Section %s quality revision failed; retaining its last safe "
                        "version without blocking the survey.",
                        index + 1,
                    )
                    break
                revision_errors = self._validate_evidence_bounded_section_quality_revision(
                    original_section=original_section,
                    revised_section=candidate,
                    allowed_paper_ids=allowed_paper_ids,
                    section_word_cap=section_word_cap,
                )
                if revision_errors:
                    self.logger.warning(
                        "Discarding unsafe quality revision for section %s: %s. "
                        "Retaining its last safe version without blocking the survey.",
                        index + 1,
                        " | ".join(revision_errors),
                    )
                    break
                current_section = candidate
                accepted_improvements += 1
            revised_sections[index] = current_section

        title = draft.get("title", self.config.BasicInfo.topic + " Survey")
        def draft_text_for(candidate_sections: Sequence[str]) -> str:
            return str(title) + "\n\n" + "\n\n".join(candidate_sections)

        while (
            len(draft_text_for(revised_sections).split()) > budget["survey_max_words"]
        ):
            changed_index = next(
                (
                    index
                    for index in range(len(revised_sections) - 1, -1, -1)
                    if revised_sections[index] != sections[index]
                ),
                None,
            )
            if changed_index is None:
                break
            self.logger.warning(
                "Discarding quality revision for section %s to restore the total "
                "survey word budget.",
                changed_index + 1,
            )
            revised_sections[changed_index] = sections[changed_index]

        draft["section_drafts"] = revised_sections
        draft["full_draft"] = draft_text_for(revised_sections)
        return draft

    def _bounded_writing_analysis(self, intra_analysis_results, inter_analysis_results) -> str:
        """Do not pass unassessed graph/cluster analysis into bounded writing."""

        if self._evidence_bounded_writing_enabled():
            return ""
        return self.format_papers_analysis(intra_analysis_results, inter_analysis_results)

    def _bounded_writing_code_report(self, code_report: Any) -> str:
        """Code reports lack SH-slot evidence provenance and are excluded when bounded."""

        if self._evidence_bounded_writing_enabled():
            return ""
        return str(code_report or "")

    def _is_valid_outline_paper_id(self, paper_id: Any, papers: Sequence[Any]) -> bool:
        """Do not let the global graph bypass the plan-scoped outline allow-list."""

        identifier = canonical_paper_id(paper_id)
        if identifier in self._as_paper_ids(papers):
            return True
        if self._evidence_bounded_writing_enabled():
            return False
        graph_paper_ids = getattr(
            getattr(self.work_analyzer, "work_collector", None),
            "graph_paper_ids",
            set(),
        )
        return identifier in graph_paper_ids

    def _bound_outline_to_evidence_plan(self, outline: Mapping[str, Any] | None) -> dict:
        """Remove unassessed graph candidates from a SH-bound writing outline."""

        bounded = copy.deepcopy(dict(outline or {}))
        allowed_papers = self._permitted_evidence_plan_paper_ids()
        if not self._evidence_bounded_writing_enabled():
            return bounded
        for section in bounded.get("sections", []):
            if not isinstance(section, dict):
                continue
            for unit in [section, *section.get("subsections", [])]:
                if not isinstance(unit, dict):
                    continue
                unit["papers_to_use"] = [
                    paper_id
                    for paper_id in self._as_paper_ids(unit.get("papers_to_use"))
                    if paper_id in allowed_papers
                ]
        return bounded

    def _extract_claim_trace(self, response_text: Any) -> tuple[str, list[dict], list[str]]:
        """Separate mandatory JSON claim metadata from a bounded prose response."""

        text = str(response_text or "")
        if not self._evidence_bounded_writing_enabled():
            return text, [], []
        matches = list(
            re.finditer(
                r"\[\[SH_CLAIM_TRACE\]\]\s*(\{.*?\})\s*\[\[/SH_CLAIM_TRACE\]\]",
                text,
                flags=re.DOTALL,
            )
        )
        if len(matches) != 1:
            return text, [], ["Expected exactly one [[SH_CLAIM_TRACE]] JSON block."]
        match = matches[0]
        try:
            payload = json.loads(match.group(1))
        except (TypeError, ValueError, json.JSONDecodeError):
            return text, [], ["SH claim trace is not valid JSON."]
        claims = payload.get("claims") if isinstance(payload, Mapping) else None
        if not isinstance(claims, list):
            return text, [], ["SH claim trace must contain a claims list."]
        visible_text = (text[:match.start()] + text[match.end():]).strip()
        if text[match.end():].strip():
            return visible_text, [], ["SH claim trace must be the final response block."]
        return visible_text, [dict(item) for item in claims if isinstance(item, Mapping)], []

    @staticmethod
    def _normalize_claim_reference_text(text: Any) -> str:
        """Normalize harmless formatting differences without erasing citations."""

        normalized = str(text or "").replace("\u201c", '"').replace("\u201d", '"')
        normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
        normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
        normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
        # Claim metadata frequently differs only in terminal punctuation or a
        # clause separator.  These are presentation differences, not a change
        # to the citation-bearing statement.
        normalized = re.sub(r"[^\w\s<>]", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _visible_prose_sentences(visible_text: Any) -> list[str]:
        """Return stable, one-based trace candidates from reader-visible prose."""

        text = str(visible_text or "").strip()
        if not text:
            return []
        parts = re.split(
            r"(?<=[.!?\u3002\uff01\uff1f])(?:[\"'\u201d\u2019\)\]\uff09]*)\s+|\n+",
            text,
        )
        sentences = [part.strip() for part in parts if part and part.strip()]
        return sentences or [text]

    def _resolve_trace_claim_text(
        self,
        visible_text: str,
        claim: Mapping[str, Any],
    ) -> tuple[str, str]:
        """Map a trace reference to the exact reader-visible prose sentence.

        The evidence audit still records the real sentence, but the model is no
        longer required to copy it byte-for-byte.  A one-based sentence index,
        an unambiguous anchor, whitespace/punctuation-normalized text, or a
        high-similarity sentence can establish the mapping.
        """

        sentences = self._visible_prose_sentences(visible_text)
        if not sentences:
            return "", "claim reference cannot be resolved because the prose is empty."

        raw_text = str(claim.get("claim_text") or "").strip()
        raw_normalized = self._normalize_claim_reference_text(raw_text)
        anchor_normalized = self._normalize_claim_reference_text(
            claim.get("claim_anchor")
        )
        raw_index = claim.get("claim_index")
        claim_index = None
        if raw_index not in (None, ""):
            try:
                candidate_index = int(raw_index)
            except (TypeError, ValueError):
                return "", "claim_index must be a positive one-based sentence index."
            if candidate_index < 1 or candidate_index > len(sentences):
                return (
                    "",
                    f"claim_index {candidate_index} is outside the visible prose sentence range 1-{len(sentences)}.",
                )
            claim_index = candidate_index

        normalized_sentences = [
            self._normalize_claim_reference_text(sentence) for sentence in sentences
        ]

        # An explicit sentence index is the least ambiguous reference.  When
        # supplied, it deliberately wins over a lightly edited copied claim.
        if claim_index is not None:
            return sentences[claim_index - 1], ""

        if raw_normalized:
            exact_matches = [
                index
                for index, candidate in enumerate(normalized_sentences)
                if candidate == raw_normalized
                or raw_normalized in candidate
                or candidate in raw_normalized
            ]
            if len(exact_matches) == 1:
                return sentences[exact_matches[0]], ""

        if anchor_normalized:
            anchor_matches = [
                index
                for index, candidate in enumerate(normalized_sentences)
                if anchor_normalized in candidate
            ]
            if len(anchor_matches) == 1:
                return sentences[anchor_matches[0]], ""

        if raw_normalized:
            ranked = sorted(
                (
                    (
                        SequenceMatcher(None, raw_normalized, candidate).ratio(),
                        index,
                    )
                    for index, candidate in enumerate(normalized_sentences)
                ),
                reverse=True,
            )
            if ranked and ranked[0][0] >= 0.90 and (
                len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.03
            ):
                return sentences[ranked[0][1]], ""

        return (
            "",
            "claim reference must provide a valid claim_index, an unambiguous "
            "claim_anchor, or text that matches a visible prose sentence.",
        )

    def _normalize_and_derive_claim_trace(
        self,
        visible_text: str,
        claims: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Resolve prose references and derive plan-owned trace fields.

        ``support_kind``, ``evidence_role``, and qualified limitation slots are
        deterministic consequences of an admitted ``(SH, slot, paper)`` path.
        They are never trusted from free-form model output.
        """

        entries = {
            str(entry.get("sub_hypothesis_id") or ""): dict(entry)
            for entry in self.survey_evidence_plan.get("subhypotheses", [])
            if isinstance(entry, Mapping)
        }
        normalized_claims: list[dict[str, Any]] = []
        errors: list[str] = []

        for claim_index, raw_claim in enumerate(claims, start=1):
            claim = dict(raw_claim)
            prefix = f"claim {claim_index}"
            resolved_claim_text, reference_error = self._resolve_trace_claim_text(
                visible_text,
                claim,
            )
            if reference_error:
                errors.append(f"{prefix}: {reference_error}")
            else:
                claim["claim_text"] = resolved_claim_text

            raw_paths = claim.get("evidence_paths")
            normalized_paths: list[dict[str, Any]] = []
            derived_limitation_slots = self._as_texts(claim.get("limitation_slots"))
            if isinstance(raw_paths, list):
                for path_index, raw_path in enumerate(raw_paths, start=1):
                    if not isinstance(raw_path, Mapping):
                        errors.append(f"{prefix} path {path_index}: path must be a JSON object.")
                        continue
                    path = dict(raw_path)
                    path_prefix = f"{prefix} path {path_index}"
                    path_sh = str(path.get("sub_hypothesis_id") or "").strip()
                    slot_name = str(path.get("slot_name") or "").strip()
                    source_type = self._claim_trace_source_type(path)
                    if str(path.get("source_type") or "").strip():
                        path["source_type"] = source_type
                    if source_type == "multimodal_observation":
                        normalized_paths.append(path)
                        continue
                    paper_id = canonical_paper_id(path.get("paper_id"))
                    path["paper_id"] = paper_id
                    entry = entries.get(path_sh)
                    slot_support = self._as_mapping(
                        entry.get("slot_support") if entry else {}
                    )
                    support = self._as_mapping(slot_support.get(slot_name))
                    if not entry or not support or not paper_id:
                        normalized_paths.append(path)
                        continue

                    supported_kinds = []
                    if paper_id in set(
                        self._as_paper_ids(support.get("evidence_paper_ids"))
                    ):
                        supported_kinds.append("DIRECT_LEDGER_EVIDENCE")
                    if paper_id in set(
                        self._as_paper_ids(support.get("background_paper_ids"))
                    ):
                        supported_kinds.append("BACKGROUND_CONTEXT")
                    if paper_id in set(
                        self._as_paper_ids(support.get("qualified_paper_ids"))
                    ):
                        supported_kinds.append("QUALIFIED_SH_CONTRIBUTION")
                    if len(supported_kinds) != 1:
                        errors.append(
                            f"{path_prefix}: evidence plan cannot derive one unique support "
                            "kind for this SH, slot, and paper."
                        )
                    else:
                        path["support_kind"] = supported_kinds[0]
                        path["evidence_role"] = str(
                            support.get("expected_evidence_role") or ""
                        )
                        if supported_kinds[0] == "QUALIFIED_SH_CONTRIBUTION":
                            derived_limitation_slots.append(slot_name)
                    normalized_paths.append(path)
            claim["evidence_paths"] = normalized_paths
            claim["limitation_slots"] = self._as_texts(derived_limitation_slots)
            normalized_claims.append(claim)

        return normalized_claims, errors

    @staticmethod
    def _claim_trace_source_type(path: Mapping[str, Any]) -> str:
        source_type = str(path.get("source_type") or "").strip()
        if source_type:
            return source_type
        return "paper" if canonical_paper_id(path.get("paper_id")) else ""

    def _claim_trace_repair_context(self, visible_text: str) -> tuple[list[dict], list[dict]]:
        """Expose only plan-valid paths for citations already visible to readers."""

        if self.use_title_in_draft:
            _valid, cited_paper_ids, _titles, _invalid_titles = (
                self.extract_and_validate_titles_in_text(visible_text)
            )
        else:
            cited_paper_ids = self._as_paper_ids(
                self.get_unique_paper_ids_from_raw(visible_text)
            )
        cited = set(self._as_paper_ids(cited_paper_ids))
        admissible_paths: list[dict] = []
        contracts: list[dict] = []
        seen_paths: set[tuple[str, str, str]] = set()

        for raw_entry in self.survey_evidence_plan.get("subhypotheses", []):
            if not isinstance(raw_entry, Mapping):
                continue
            entry = dict(raw_entry)
            sh_id = str(entry.get("sub_hypothesis_id") or "").strip()
            if not sh_id:
                continue
            slot_support = self._as_mapping(entry.get("slot_support"))
            limited_slots = [
                *self._as_texts(entry.get("missing_slots")),
                *self._as_texts(entry.get("background_only_slots")),
                *[
                    slot_name
                    for slot_name, support in slot_support.items()
                    if self._as_texts(
                        self._as_mapping(support).get("qualified_paper_ids")
                    )
                ],
            ]
            contracts.append(
                {
                    "sub_hypothesis_id": sh_id,
                    "allowed_claim_modes": self._as_texts(
                        entry.get("allowed_claim_modes")
                    ),
                    "limitation_slots": self._as_texts(limited_slots),
                }
            )
            for slot_name, raw_support in slot_support.items():
                support = self._as_mapping(raw_support)
                for field_name in (
                    "evidence_paper_ids",
                    "qualified_paper_ids",
                    "background_paper_ids",
                ):
                    for paper_id in self._as_paper_ids(support.get(field_name)):
                        key = (sh_id, str(slot_name), paper_id)
                        if paper_id in cited and key not in seen_paths:
                            seen_paths.add(key)
                            admissible_paths.append(
                                {
                                    "source_type": "paper",
                                    "sub_hypothesis_id": sh_id,
                                    "slot_name": str(slot_name),
                                    "paper_id": paper_id,
                                }
                            )
            multimodal_projection = self._as_mapping(entry.get("multimodal_projection"))
            for observation_id in self._as_texts(
                multimodal_projection.get("observation_ids")
            ):
                key = (sh_id, "multimodal_observation", observation_id)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                admissible_paths.append(
                    {
                        "source_type": "multimodal_observation",
                        "sub_hypothesis_id": sh_id,
                        "observation_id": observation_id,
                    }
                )
        return admissible_paths, contracts

    def _claim_trace_repair_max_attempts(self) -> int:
        generator_config = getattr(
            getattr(self.config, "ModuleInfo", None), "SurveyGenerator", None
        )
        configured = self._positive_int(
            getattr(generator_config, "claim_trace_repair_max_attempts", 2), 2
        )
        return min(configured, 2)

    def _claim_trace_validation_enabled(self) -> bool:
        """Return whether machine-readable claim-trace checks are enforced.

        This is intentionally separate from evidence-bounded writing. A
        temporary operational bypass may keep the bounded evidence plan and
        reader-visible citation checks while allowing drafting to continue when
        the model cannot produce compliant trace metadata.
        """
        generator_config = getattr(
            getattr(self.config, "ModuleInfo", None), "SurveyGenerator", None
        )
        configured = getattr(
            generator_config, "claim_trace_validation_enabled", True
        )
        if isinstance(configured, str):
            return configured.strip().lower() not in {"false", "0", "no", "off"}
        return bool(configured)

    def _claim_trace_repair_max_output_tokens(self) -> int:
        generator_config = getattr(
            getattr(self.config, "ModuleInfo", None), "SurveyGenerator", None
        )
        return self._positive_int(
            getattr(generator_config, "claim_trace_repair_max_output_tokens", 2_048),
            2_048,
        )

    def _repair_claim_traces(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        stage: str,
    ) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[str]]]:
        """Repair only invalid trace metadata, preserving accepted visible prose."""

        pending = [dict(record) for record in records]
        repaired: dict[int, list[dict[str, Any]]] = {}
        failures: dict[int, list[str]] = {}
        for attempt in range(1, self._claim_trace_repair_max_attempts() + 1):
            if not pending:
                break
            prompts = []
            for record in pending:
                admissible_paths, contracts = self._claim_trace_repair_context(
                    str(record.get("visible_draft") or "")
                )
                prompts.append(
                    SURVEY_CLAIM_TRACE_REPAIR.format(
                        visible_prose=record.get("visible_draft") or "",
                        admissible_paths=json.dumps(
                            admissible_paths, ensure_ascii=False, indent=2
                        ),
                        subhypothesis_contracts=json.dumps(
                            contracts, ensure_ascii=False, indent=2
                        ),
                        validation_errors="\n".join(
                            self._as_texts(record.get("trace_errors"))[:8]
                        )[:2_000]
                        or "No parseable trace was returned.",
                    )
                )
            try:
                responses = self.chat_agent.batch_remote_chat(
                    prompts,
                    desc=f"Repairing {stage} claim traces (attempt {attempt}/2)",
                    temperature=0.0,
                    strict_input_budget=True,
                    max_output_tokens=self._claim_trace_repair_max_output_tokens(),
                    response_format=self._outline_json_response_format(),
                )
            except Exception as exc:
                self.logger.warning(
                    "Claim-trace repair request failed for %s attempt %s: %s",
                    stage,
                    attempt,
                    exc,
                )
                responses = [None] * len(pending)

            next_pending: list[dict] = []
            for record, response in zip(pending, responses):
                record_index = int(record["draft_index"])
                try:
                    payload = extract_json(response) if isinstance(response, str) else response
                    raw_claims = payload.get("claims") if isinstance(payload, Mapping) else None
                    if not isinstance(raw_claims, list):
                        raise ValueError("claim-trace repair response must contain a claims list.")
                    claims = [dict(item) for item in raw_claims if isinstance(item, Mapping)]
                    normalized_claims, normalization_errors = (
                        self._normalize_and_derive_claim_trace(
                            str(record.get("visible_draft") or ""),
                            claims,
                        )
                    )
                    trace_errors = [
                        *normalization_errors,
                        *self._validate_claim_trace(
                            str(record.get("visible_draft") or ""),
                            normalized_claims,
                        ),
                    ]
                    if trace_errors:
                        raise ValueError("; ".join(trace_errors[:8]))
                    repaired[record_index] = normalized_claims
                except Exception as exc:
                    record["trace_errors"] = [str(exc)]
                    next_pending.append(record)

            pending = next_pending

        for record in pending:
            failures[int(record["draft_index"])] = self._as_texts(
                record.get("trace_errors")
            ) or ["claim-trace repair returned no valid trace."]
        return repaired, failures

    def _validate_and_normalize_claim_trace(
        self,
        visible_text: str,
        claims: Sequence[Mapping[str, Any]],
        parse_errors: Sequence[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Return plan-derived trace data plus any remaining audit errors."""

        normalized_claims, normalization_errors = self._normalize_and_derive_claim_trace(
            visible_text,
            claims,
        )
        return normalized_claims, [
            *self._as_texts(parse_errors),
            *normalization_errors,
            *self._validate_claim_trace(visible_text, normalized_claims),
        ]

    def _claim_citation_paper_ids(self, claim_text: str) -> tuple[set[str], list[str]]:
        """Resolve the reader-visible citations contained in one claim sentence."""

        if not getattr(self, "use_title_in_draft", False):
            return set(
                self._as_paper_ids(self.get_unique_paper_ids_from_raw(claim_text))
            ), []
        valid, paper_ids, _titles, invalid_titles = self.extract_and_validate_titles_in_text(
            claim_text
        )
        if not valid:
            return set(paper_ids), [
                "claim citation title could not be resolved: " + title
                for title in invalid_titles
            ]
        return set(self._as_paper_ids(paper_ids)), []

    def _validate_claim_trace(self, visible_text: str, claims: Sequence[Mapping[str, Any]]) -> list[str]:
        """Validate exact claim -> SH -> slot -> paper paths, without legacy fallback."""

        if not self._evidence_bounded_writing_enabled():
            return []
        entries = {
            str(entry.get("sub_hypothesis_id") or ""): dict(entry)
            for entry in self.survey_evidence_plan.get("subhypotheses", [])
            if isinstance(entry, Mapping)
        }
        normalized_text = re.sub(r"\s+", " ", visible_text).strip().casefold()
        errors: list[str] = []
        if not claims:
            return ["Evidence-bounded writing requires at least one SH claim trace."]

        for index, raw_claim in enumerate(claims, start=1):
            claim = dict(raw_claim)
            claim_text = re.sub(r"\s+", " ", str(claim.get("claim_text") or "")).strip()
            sh_ids = self._as_texts(claim.get("sub_hypothesis_ids"))
            claim_mode = str(claim.get("claim_mode") or "").strip()
            raw_paths = claim.get("evidence_paths")
            paths = [dict(path) for path in raw_paths if isinstance(path, Mapping)] if isinstance(raw_paths, list) else []
            limitation_slots = self._as_texts(claim.get("limitation_slots"))
            prefix = f"claim {index}"

            if not claim_text or claim_text.casefold() not in normalized_text:
                errors.append(f"{prefix}: claim_text must be a verbatim sentence from the prose.")
            if not sh_ids or any(identifier not in entries for identifier in sh_ids):
                errors.append(f"{prefix}: unknown or missing sub_hypothesis_ids.")
                continue
            if any(
                claim_mode not in entries[identifier].get("allowed_claim_modes", [])
                for identifier in sh_ids
            ):
                errors.append(f"{prefix}: claim_mode is not allowed by the SH writing mode.")
                continue

            citation_paper_ids, citation_errors = self._claim_citation_paper_ids(claim_text)
            errors.extend(f"{prefix}: {error}" for error in citation_errors)
            limited_slots = {
                slot
                for identifier in sh_ids
                for slot in (
                    self._as_texts(entries[identifier].get("missing_slots"))
                    + self._as_texts(entries[identifier].get("background_only_slots"))
                    + [
                        slot_name
                        for slot_name, support in self._as_mapping(
                            entries[identifier].get("slot_support")
                        ).items()
                        if self._as_texts(
                            self._as_mapping(support).get("qualified_paper_ids")
                        )
                    ]
                )
            }
            if claim_mode in {EVIDENCE_GAP_REPORT, OUT_OF_SCOPE_OR_REJECTED}:
                if paths:
                    errors.append(f"{prefix}: gap/rejection reports must have empty evidence_paths.")
                if citation_paper_ids:
                    errors.append(f"{prefix}: gap/rejection reports cannot contain paper citations.")
                if not limitation_slots or not set(limitation_slots).issubset(limited_slots):
                    errors.append(f"{prefix}: gap/rejection reports require limited limitation_slots.")
                continue

            if not isinstance(raw_paths, list) or not paths:
                errors.append(f"{prefix}: non-gap claims require non-empty evidence_paths.")
                continue
            path_paper_ids = {
                canonical_paper_id(path.get("paper_id"))
                for path in paths
                if self._claim_trace_source_type(path) == "paper"
                and canonical_paper_id(path.get("paper_id"))
            }
            untraced_citations = citation_paper_ids - path_paper_ids
            if untraced_citations:
                errors.append(
                    f"{prefix}: every claim citation requires a matching evidence path: "
                    + ", ".join(sorted(untraced_citations))
                )
            paper_paths: list[dict[str, Any]] = []
            multimodal_paths: list[dict[str, Any]] = []
            for path_index, path in enumerate(paths, start=1):
                path_prefix = f"{prefix} path {path_index}"
                path_sh = str(path.get("sub_hypothesis_id") or "").strip()
                source_type = self._claim_trace_source_type(path)
                slot_name = str(path.get("slot_name") or "").strip()
                paper_id = canonical_paper_id(path.get("paper_id"))
                support_kind = str(path.get("support_kind") or "").strip()
                evidence_role = str(path.get("evidence_role") or "").strip()
                if path_sh not in sh_ids or path_sh not in entries:
                    errors.append(f"{path_prefix}: path must name one claim sub_hypothesis_id.")
                    continue
                if source_type == "multimodal_observation":
                    multimodal_paths.append(path)
                    unexpected_fields = set(path) - {
                        "source_type",
                        "sub_hypothesis_id",
                        "observation_id",
                    }
                    if unexpected_fields:
                        errors.append(
                            f"{path_prefix}: multimodal observation paths use only source_type, SH, and observation_id."
                        )
                    details = multimodal_trace_details(
                        entries[path_sh], path.get("observation_id")
                    )
                    if details is None:
                        errors.append(
                            f"{path_prefix}: observation_id is missing or does not belong to this data-anchored SH."
                        )
                    if self._multimodal_claim_is_overstrong(claim_text):
                        errors.append(
                            f"{path_prefix}: multimodal observation claims must not use causal, universal, or overstrong language."
                        )
                    if not self._is_bounded_multimodal_claim(claim_text, details):
                        errors.append(
                            f"{path_prefix}: multimodal observation claims must retain the supplied-data scope and claim limits."
                        )
                    continue
                if source_type != "paper":
                    errors.append(
                        f"{path_prefix}: source_type must be paper or multimodal_observation."
                    )
                    continue
                paper_paths.append(path)
                slot_support = self._as_mapping(entries[path_sh].get("slot_support"))
                support = self._as_mapping(slot_support.get(slot_name))
                if not support:
                    errors.append(f"{path_prefix}: slot_name is not declared for this SH.")
                    continue
                if evidence_role != str(support.get("expected_evidence_role") or ""):
                    errors.append(f"{path_prefix}: evidence_role does not match the ledger slot.")
                direct_ids = set(self._as_paper_ids(support.get("evidence_paper_ids")))
                background_ids = set(
                    self._as_paper_ids(support.get("background_paper_ids"))
                )
                qualified_ids = set(
                    self._as_paper_ids(support.get("qualified_paper_ids"))
                )
                raw_role_constraints = self._paper_role_constraints_by_id(
                    entries[path_sh]
                ).get(paper_id, [])
                role_constraints = [
                    self._as_mapping(constraint)
                    for constraint in raw_role_constraints
                    if isinstance(constraint, Mapping)
                ]
                if role_constraints and not any(
                    support_kind
                    in self._as_texts(constraint.get("allowed_support_kinds"))
                    for constraint in role_constraints
                ):
                    errors.append(
                        f"{path_prefix}: paper provenance role does not permit {support_kind}; "
                        "root lineage is not direct evidence."
                    )
                if paper_id in set(
                    self._as_paper_ids(entries[path_sh].get("forbidden_paper_ids"))
                ):
                    errors.append(
                        f"{path_prefix}: paper is a graph/holdout candidate and cannot support an SH claim."
                    )
                if support_kind == "DIRECT_LEDGER_EVIDENCE":
                    if paper_id not in direct_ids:
                        errors.append(f"{path_prefix}: paper does not directly cover this SH slot.")
                    if claim_mode not in {EVIDENCE_BACKED_SYNTHESIS, QUALIFIED_SYNTHESIS}:
                        errors.append(f"{path_prefix}: direct evidence is incompatible with claim_mode.")
                elif support_kind == "BACKGROUND_CONTEXT":
                    if paper_id not in background_ids:
                        errors.append(f"{path_prefix}: paper is not background context for this SH slot.")
                    if claim_mode not in {QUALIFIED_SYNTHESIS, BACKGROUND_ONLY}:
                        errors.append(f"{path_prefix}: background context cannot support this claim_mode.")
                elif support_kind == "QUALIFIED_SH_CONTRIBUTION":
                    if paper_id not in qualified_ids:
                        errors.append(
                            f"{path_prefix}: paper is not an explicit qualified contribution for this SH slot."
                        )
                    if claim_mode != QUALIFIED_SYNTHESIS:
                        errors.append(
                            f"{path_prefix}: qualified contribution requires QUALIFIED_SYNTHESIS."
                        )
                    if slot_name not in limitation_slots:
                        errors.append(
                            f"{path_prefix}: qualified contribution requires its slot in limitation_slots."
                        )
                else:
                    errors.append(
                        f"{path_prefix}: support_kind must be DIRECT_LEDGER_EVIDENCE, "
                        "BACKGROUND_CONTEXT, or QUALIFIED_SH_CONTRIBUTION."
                    )
                if paper_id and paper_id not in citation_paper_ids:
                    errors.append(f"{path_prefix}: paper_id must be cited in claim_text.")

            if claim_mode == LOCAL_DATA_OBSERVATION:
                if not multimodal_paths or paper_paths:
                    errors.append(
                        f"{prefix}: local-data observations require multimodal observation paths only."
                    )
                if citation_paper_ids:
                    errors.append(
                        f"{prefix}: local-data observations must not present their observation as a paper citation."
                    )
            if claim_mode == EVIDENCE_BACKED_SYNTHESIS and (
                not any(
                    str(path.get("support_kind") or "") == "DIRECT_LEDGER_EVIDENCE"
                    for path in paper_paths
                )
                or any(
                    str(path.get("support_kind") or "") != "DIRECT_LEDGER_EVIDENCE"
                    for path in paper_paths
                )
            ):
                errors.append(f"{prefix}: evidence-backed claims require direct paper paths.")
            if claim_mode == BACKGROUND_ONLY and (
                not paper_paths
                or any(
                    str(path.get("support_kind") or "") != "BACKGROUND_CONTEXT"
                    for path in paper_paths
                )
            ):
                errors.append(f"{prefix}: background-only claims require background paper paths.")
        return errors

    @staticmethod
    def _is_bounded_multimodal_claim(
        claim_text: str,
        details: Mapping[str, Any] | None,
    ) -> bool:
        if not details or not SurveyGenerator._as_texts(details.get("claim_limits")):
            return False
        normalized = re.sub(r"\s+", " ", str(claim_text or "")).casefold()
        scope_markers = (
            "provided data",
            "provided-data",
            "local data",
            "local observation",
            "representative",
            "bounded",
        )
        uncertainty_markers = (
            "compatible",
            "tentative",
            "may",
            "might",
            "could",
            "cannot distinguish",
            "does not establish",
        )
        return any(marker in normalized for marker in scope_markers) and any(
            marker in normalized for marker in uncertainty_markers
        )

    @staticmethod
    def _multimodal_claim_is_overstrong(claim_text: str) -> bool:
        if violates_noncausal_policy(claim_text):
            return True
        normalized = re.sub(r"\s+", " ", str(claim_text or "")).casefold()
        universal_markers = (
            "all samples",
            "every sample",
            "any sample",
            "across all",
            "in every",
            "generalizes",
            "generalizable",
            "universally",
            "universal",
            "always",
        )
        return any(marker in normalized for marker in universal_markers)

    def _store_claim_traceability(
        self,
        claims: Sequence[Mapping[str, Any]],
        *,
        validation_enabled: bool = True,
    ) -> None:
        if not self._evidence_bounded_writing_enabled():
            return
        artifact = {
            "schema_version": "survey_claim_traceability_v1",
            "project_id": self.survey_evidence_plan.get("project_id", ""),
            "project_context_fingerprint": self.survey_evidence_plan.get(
                "project_context_fingerprint", ""
            ),
            "evidence_plan_schema_version": SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
            "validation_enabled": validation_enabled,
            "claims": [dict(claim) for claim in claims],
        }
        self.survey_claim_traceability_artifact = artifact
        basic_info = getattr(self.config, "BasicInfo", None)
        if basic_info is None:
            return
        try:
            basic_info.survey_claim_traceability = artifact
        except Exception:
            pass
        base_dir = str(getattr(basic_info, "base_dir", "") or "").strip()
        if not base_dir:
            return
        artifact_path = Path(base_dir) / "survey_claim_traceability.json"
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            basic_info.survey_claim_traceability_artifact_path = str(artifact_path)
        except Exception:
            pass

    def _unaccounted_plan_subhypotheses(
        self,
        claims: Sequence[Mapping[str, Any]],
    ) -> list[str]:
        if not self._evidence_bounded_writing_enabled():
            return []
        required = {
            str(entry.get("sub_hypothesis_id") or "")
            for entry in self.survey_evidence_plan.get("subhypotheses", [])
            if isinstance(entry, Mapping)
        }
        observed = {
            identifier
            for claim in claims
            if isinstance(claim, Mapping)
            for identifier in self._as_texts(claim.get("sub_hypothesis_ids"))
        }
        return sorted(identifier for identifier in required if identifier and identifier not in observed)

    def format_papers_analysis(self, intra_analysis_results, inter_analysis_results, concise_mode = False):
        papers_analysis = ""

        # debug
        if self.include_relation_graph and not concise_mode:
            papers_analysis += self.work_analyzer.format_analysis_graph()
            self.logger.info("add relation graph in analysis")

        if self.include_relation_table:
            table =  self.work_analyzer.format_analysis_table()
            papers_analysis += table
            # if self.config.BasicInfo.debug:
            #     self.logger.info(f"Relation Table: {table}")
            self.logger.info("add relation table in analysis")

        if self.include_initial_analysis:
            for i, group in enumerate(intra_analysis_results):
                papers_analysis += f"Group {i+1} Analysis:\n"
                for j, q in enumerate(group):
                    papers_analysis += f"Question {j+1}: {q['question']}\nAnswer {j + 1}: {q['answer']}\nRelated Papers {j + 1}: {q['related_papers']}\n\n---\n"

            papers_analysis += (
                f"\n\nHigh-level Inter-Group Analysis:\n{inter_analysis_results}\n"
            )
            papers_analysis = papers_analysis.replace('#', '*')
        

        return papers_analysis

    def format_intra_papers_analysis(self, intra_analysis_results, inter_analysis_results, cluster_index):
        papers_analysis = ""
        group = intra_analysis_results[cluster_index]
        
        papers_analysis += f"Group {cluster_index+1} Analysis:\n"
        for j, q in enumerate(group):
            papers_analysis += f"Question {j+1}: {q['question']}\nAnswer {j + 1}: {q['answer']}\nRelated Papers {j + 1}: {q['related_papers']}\n\n---\n"

        return papers_analysis

    def generate_outline(
        self, intra_analysis_results, inter_analysis_results, papers, retry=1
    ):
        self.prepare_survey_evidence_plan()
        papers = self._bounded_writing_paper_ids(papers)
        if not self.config.ModuleInfo.SurveyGenerator.outline_generation_in_steps:
            outline = self.generate_outline_1_step(
                intra_analysis_results, inter_analysis_results, papers, retry
            )
        else:
            outline = self.generate_outline_in_steps(
                intra_analysis_results, inter_analysis_results, papers, retry
            )
        bounded_outline = self._bound_outline_to_evidence_plan(outline)
        # Retain the final, evidence-bounded outline for downstream optional
        # artifacts such as the post-save visual companion.
        self.survey_outline_artifact = self._json_compatible(bounded_outline)
        return bounded_outline

    def generate_outline_in_steps(
        self, intra_analysis_results, inter_analysis_results, papers, retry=1
    ):
        papers = self._bounded_writing_paper_ids(papers)
        outline = self.generate_outline_draft_outline(
            intra_analysis_results, inter_analysis_results, papers, retry
        )
        outline_with_paper_assignment = self.generate_outline_assign_papers(
            outline, intra_analysis_results, inter_analysis_results, papers, retry
        )
        return outline_with_paper_assignment

    def generate_outline_draft_outline(
        self, intra_analysis_results, inter_analysis_results, papers, retry=1
    ):
        papers = self._select_outline_representative_paper_ids(
            self._bounded_writing_paper_ids(papers)
        )
        self._outline_representative_paper_ids = list(papers)
        max_retry_in_loop = self.config.ModuleInfo.SurveyGenerator.outline_generation_draft_max_retry
        max_iterations = getattr(self.config.ModuleInfo.SurveyGenerator, 'outline_generation_draft_max_iterations', 10)
        empty_iteration = getattr(self.config.ModuleInfo.SurveyGenerator, 'outline_generation_draft_empty_keynotes_iteration', 1)

        papers_analysis = self._bounded_writing_analysis(
            intra_analysis_results, inter_analysis_results
        )
        outline = {}

        # iteratively generate outline
        num_batches = math.ceil(
            len(papers)
            / self.config.ModuleInfo.SurveyGenerator.outline_generation_draft_batch_size
        )
        
        # Set max_iterations to num_batches + 1 (for final empty iteration)
        max_iterations = min(num_batches + empty_iteration, max_iterations)
        if max_iterations < num_batches + empty_iteration:
            self.logger.warning(f"max_iterations ({max_iterations}) < num_batches ({num_batches}) + empty_iteration ({empty_iteration}), truncating {num_batches + empty_iteration - max_iterations} batch(es)...")

        # stop debugging prompt
        debug = False
        for iteration_idx in range(max_iterations):
            # Determine if this is the final empty iteration
            is_empty_iteration = (iteration_idx + empty_iteration >= max_iterations)
            
            if is_empty_iteration:
                # Final iteration with empty paper_keynotes
                err_info = CumulativeErrorInfo()
                self.logger.info(
                    f"Generating outline: final refinement iteration (no new papers)"
                )
                paper_keynotes = ""
            else:
                # Normal batch processing
                batch_idx = iteration_idx
                err_info = CumulativeErrorInfo()

                self.logger.info(
                    f"Generating outline: processing batch {batch_idx + 1} of {num_batches} (iteration {iteration_idx + 1}/{max_iterations})"
                )
                batch_papers = papers[
                    batch_idx
                    * self.config.ModuleInfo.SurveyGenerator.outline_generation_draft_batch_size : (
                        batch_idx + 1
                    )
                    * self.config.ModuleInfo.SurveyGenerator.outline_generation_draft_batch_size
                ]
                paper_keynotes = ""
                for paper_id in batch_papers:
                    try:
                        paper_keynotes += self._outline_paper_brief(paper_id)
                    except Exception as e:
                        self.logger.error(f"Failed to build outline brief for paper ID: {paper_id} in OUTLINE GENERATION DRAFT STEP with error {e}. Skipping this paper in OUTLINE GENERATION.")
                        continue

            query = (
                f"Current Outline Title: {outline.get('title', '')}\n"
                f"Current Outline Sections: {json.dumps(outline.get('sections', []))}"
            )
            other_relevant_papers = (
                ""
                if self._evidence_bounded_writing_enabled()
                or not self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG_in_outline
                else self.database.query_and_text(
                    query_text=query,
                    top_k=self.config.ModuleInfo.SurveyGenerator.outline_draft_RAG_topk,
                    include_paper_id=True,
                )
            )
            prompt, _ = self._build_outline_prompt(
                template=SURVEY_OUTLINE_GENERATION_OUTLINE_DRAFT,
                phase="draft",
                paper_keynotes=paper_keynotes,
                current_outline=outline,
                papers_analysis=papers_analysis,
                other_relevant_papers=other_relevant_papers,
                representative_paper_ids=papers,
            )

            if self.config.BasicInfo.debug and debug:
                self.logger.info(f"Outline draft generation prompt(debug mode, print the first prompt): {prompt}")
                debug = False

            last_error = ""
            last_response = ""
            for retry_time in range(max_retry_in_loop):
                valid = False
                try:
                    if self.config.BasicInfo.debug and retry_time > 0:
                        self.logger.info(f"Retry time {retry_time}, with cumulative error info: {err_info.get_errors_text()[:50]} in OUTLINE GENERATION-DRAFT")
                    request_prompt = (
                        prompt
                        if retry_time == 0
                        else self._build_outline_repair_prompt(
                            current_outline=outline,
                            validation_error=last_error or err_info.get_errors_text(),
                            previous_response=last_response,
                        )
                    )
                    renew_outline_raw = self._request_outline_json(request_prompt)
                    last_response = str(renew_outline_raw or "")
                    renew_outline = extract_json(renew_outline_raw)
                    valid, new_err, err_papers = self.validate_outline(intra_analysis_results, papers, renew_outline, format_only = True)
                    err_info.add_errors(new_err)
                    if not valid:
                        raise ValueError(f"{new_err}")
                except Exception as e:
                    last_error = str(e)
                    self.logger.warning(f"Outline validation failed for iteration {iteration_idx + 1}: {e} in OUTLINE GENERATION-DRAFT. Retrying this iteration for {retry_time + 1}...")
                    valid = False
                
                if valid:
                    outline = renew_outline
                    break

            if not valid:
                raise OutlineGenerationError(
                    "Outline draft generation exhausted retries for iteration "
                    f"{iteration_idx + 1}: {last_error or err_info.get_errors_text()}"
                )

        return outline


    def _validate_assignment(self, result, info_dict = None):
        error_conservatism_mode = info_dict.get("error_conservatism_mode", False)
        omit_error_preserve_retry_time = info_dict.get("omit_error_preserve_retry_time", 1)
        retry_time = info_dict.get("retry_time", 0)
        max_retry = info_dict.get("max_retry", 5)
        papers = info_dict.get("papers", [])

        omit_err = (retry_time + omit_error_preserve_retry_time >= max_retry and not error_conservatism_mode)

        papers_assignment = self._parse_outline_assignments(result)
        err_papers = []

        for paper in papers_assignment:
            # Validate paper_id
            if "paper_id" not in paper:
                if omit_err:
                    continue
                else:
                    raise ValueError(f"Paper Dict lack paper_id key in current provided paper in outline paper assignment")
            
            paper_id = paper.get("paper_id")
            
            # Validate paper_id is in valid papers
            if not self._is_valid_outline_paper_id(paper_id, papers):
                if omit_err:
                    err_papers.append(paper_id)
                else:
                    raise ValueError(f"Paper ID {paper_id} not in current provided papers in outline paper assignment")
            
            # Validate assignment key exists and is a dict
            if "assignment" not in paper:
                if omit_err:
                    err_papers.append(paper_id)
                    self.logger.warning(f"Omit Err mode. Paper {paper_id} lacks 'assignment' key, skipping this paper in OUTLINE GENERATION-ASSIGN")
                    continue
                else:
                    raise ValueError(f"Paper {paper_id} lacks 'assignment' key in outline paper assignment")
            
            assignment = paper.get("assignment")
            if not isinstance(assignment, dict):
                if omit_err:
                    err_papers.append(paper_id)
                    self.logger.warning(f"Omit Err mode. Paper {paper_id} 'assignment' is not a dict, skipping this paper in OUTLINE GENERATION-ASSIGN")
                    continue
                else:
                    raise ValueError(f"Paper {paper_id} 'assignment' is not a dict in outline paper assignment")
            
            # Validate assignment values are lists
            for assign_section, assign_subsections in assignment.items():
                if not isinstance(assign_subsections, list):
                    if omit_err:
                        err_papers.append(paper_id)
                        self.logger.warning(f"Omit Err mode. Paper {paper_id} assignment for section '{assign_section}' is not a list, skipping this paper in OUTLINE GENERATION-ASSIGN")
                        continue
                    else:
                        raise ValueError(f"Paper {paper_id} assignment for section '{assign_section}' is not a list in outline paper assignment")

        ## still err in last try, just delete errors rather than retry
        if omit_err and len(err_papers) > 0:
            self.logger.warning(f"max retry reached, deleting error papers{err_papers} directly and returning in OUTLINE GENERATION-ASSIGN")
            papers_assignment = [paper for paper in papers_assignment if paper.get("paper_id", "unknown") not in err_papers]


        result = json.dumps(papers_assignment)
        # Fixed: return (val, result) not (result, val)
        return True, result

    def generate_outline_assign_papers(
        self, outline, intra_analysis_results, inter_analysis_results, papers, retry=1
    ):
        papers = self._bounded_writing_paper_ids(papers)
        representative_paper_ids = self._as_paper_ids(
            getattr(self, "_outline_representative_paper_ids", [])
        )
        if not representative_paper_ids:
            representative_paper_ids = self._select_outline_representative_paper_ids(
                papers
            )
            self._outline_representative_paper_ids = list(representative_paper_ids)
        outline = self._require_assignable_outline(outline)
        max_retry_in_loop = self.config.ModuleInfo.SurveyGenerator.outline_generation_assign_max_retry
        self.logger.info(f"OUTLINE GENERATION ASSIGNMENT need to assign {len(papers)} papers")
        papers_analysis = self._bounded_writing_analysis(
            intra_analysis_results, inter_analysis_results
        )

        # step 1: initialize
        for section in outline["sections"]:
            section["papers_to_use"] = []
            for subsection in section.get("subsections", []):
                subsection["papers_to_use"] = []

        
        outline_with_paper_assignment = copy.deepcopy(outline)

        # step 2: cal batch
        num_batches = math.ceil(
            len(papers)
            / self.config.ModuleInfo.SurveyGenerator.outline_generation_assign_batch_size
        )

        prompts = []
        for batch_idx in range(num_batches):
            err_info = CumulativeErrorInfo()

            self.logger.info(
                f"Generating outline: processing batch {batch_idx + 1} of {num_batches}"
            )
            # step 3: chunk batch
            batch_papers = papers[
                batch_idx
                * self.config.ModuleInfo.SurveyGenerator.outline_generation_assign_batch_size : (
                    batch_idx + 1
                )
                * self.config.ModuleInfo.SurveyGenerator.outline_generation_assign_batch_size
            ]

            # step 4: build prompt
            paper_keynotes = ""
            for paper_id in batch_papers:
                try:
                    paper_keynotes += self._outline_paper_brief(paper_id)
                except Exception as e:
                    self.logger.error(f"Failed to build outline brief for paper ID: {paper_id} in OUTLINE GENERATION ASSIGNMENT with error {e}. Skipping this paper in OUTLINE GENERATION ASSIGNMENT.")

            query = (
                f"Current Outline Title: {outline.get('title', '')}\n"
                f"Current Outline Sections: {json.dumps(outline.get('sections', []))}"
            )
            other_relevant_papers = (
                ""
                if self._evidence_bounded_writing_enabled()
                or not self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG_in_outline
                else self.database.query_and_text(
                    query_text=query,
                    top_k=self.config.ModuleInfo.SurveyGenerator.outline_assign_RAG_topk,
                    include_paper_id=True,
                )
            )
            prompt, _ = self._build_outline_prompt(
                template=SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT,
                phase="assignment",
                paper_keynotes=paper_keynotes,
                current_outline=outline,
                papers_analysis="",
                other_relevant_papers=other_relevant_papers,
                representative_paper_ids=representative_paper_ids,
            )

            prompts.append(prompt)

            # if self.config.BasicInfo.debug:
            #     self.logger.info(f"Outline generation prompt : {prompt}")

            if self.outline_fast_mode:
                break
            

            valid = False
            # step 5: chat(fast mode will use batch chat out of loop)
            for retry_time in range(
                max_retry_in_loop
            ): 
                omit_err = (retry_time + self.omit_error_preserve_retry_time >= max_retry_in_loop and not self.config.BasicInfo.error_conservatism_mode)
                try:
                    if self.config.BasicInfo.debug and retry_time > 0:
                        self.logger.info(f"Retry time {retry_time} with cumulative error info: {err_info.get_errors_text()} in OUTLINE GENERATION-ASSIGN")

                    paper_assignment_raw = self._request_outline_json(
                        prompt if retry_time == 0 else prompt + ERROR_FEEDBACK_PROMPT.format(info = err_info.get_errors_text())
                    )
                    papers_assignment = self._parse_outline_assignments(
                        paper_assignment_raw
                    )

                    err_papers = []
                    # if self.config.BasicInfo.debug:
                    #     self.logger.info(f"Retry_condition: {retry_time + self.omit_error_preserve_retry_time >= max_retry_in_loop}, omit_enable_condition: {not self.config.BasicInfo.error_conservatism_mode}. Omit Err mode: {omit_err} in OUTLINE GENERATION-ASSIGN")


                    for paper in papers_assignment:
                        if "paper_id" not in paper:
                            if omit_err:
                                continue
                            else:
                                raise ValueError(f"Paper Dict lack paper_id key in current provided paper in outline paper assignment")
                        if not self._is_valid_outline_paper_id(paper["paper_id"], papers):
                            err_info.add_error(f"Paper ID {paper['paper_id']} not in current provided papers in paper assignment")
                            if omit_err:
                                err_papers.append(paper["paper_id"])
                            else:
                                raise ValueError(f"Paper ID {paper['paper_id']} not in current provided papers in outline paper assignment")

                    ## still err in last try, just delete errors rather than retry
                    if omit_err and len(err_papers) > 0:
                        self.logger.warning(f"max retry reached, deleting error papers{err_papers} directly and returning in OUTLINE GENERATION-ASSIGN")
                        papers_assignment = [paper for paper in papers_assignment if paper.get("paper_id", "unknown") not in err_papers]

                    outline_with_paper_assignment = self._assign_paper(papers_assignment, outline_with_paper_assignment, omit_err = omit_err)
                    
                    valid, new_err, err_papers = self.validate_outline(intra_analysis_results, papers, outline_with_paper_assignment, omit_err = omit_err)
                    err_info.add_errors(new_err)
                    
                    if omit_err:
                        if self.config.BasicInfo.debug:
                            self.logger.info(f"Omit Err mode, proceeding with valid outline even if errors exist in OUTLINE GENERATION-ASSIGN.")
                        valid = True
                    if not valid:
                        raise ValueError(f"{new_err}")
                        
                except Exception as e:
                    if omit_err:
                        valid = True
                    self.logger.warning(f"Outline validation failed for batch {batch_idx + 1}: {e} in OUTLINE GENERATION-ASSIGN. Retrying this batch for {retry_time + 1}...")
                    continue

                if valid:
                    break

            if not valid:
                raise ValueError("Invalid paper ID after maximum retries in loop.")
            
        if self.outline_fast_mode:
            info_dict = {
                "papers": papers,
                "error_conservatism_mode": self.config.BasicInfo.error_conservatism_mode,
                "omit_error_preserve_retry_time": self.omit_error_preserve_retry_time,
                "max_retry": self.config.ModuleInfo.SurveyGenerator.outline_generation_assign_max_retry,
            }
            self.logger.info("[OUTLINE FAST MODE DEBUG]Fast mode enabled, use batch_remote_chat to process outline assignement")
            results = self.chat_agent.batch_remote_chat_with_retry(prompts, 
                                                                   self._validate_assignment, 
                                                                   max_retry = self.config.ModuleInfo.SurveyGenerator.outline_generation_assign_max_retry,
                                                                   desc = "Generating batch chat result for outline assignment",
                                                                   # Fixed: removed negative sign from temperature
                                                                   temperature=self.config.ModuleInfo.SurveyGenerator.outline_generation_temperature,
                                                                   info_dict=info_dict,
                                                                   strict_input_budget=True,
                                                                   max_output_tokens=self._outline_max_output_tokens(),
                                                                   response_format=self._outline_json_response_format(),)

            omit_err = (self.omit_error_preserve_retry_time >= 1 and not self.config.BasicInfo.error_conservatism_mode)
            for result in results:
                papers_assignment = self._parse_outline_assignments(result)
                outline_with_paper_assignment = self._assign_paper(papers_assignment, outline_with_paper_assignment, omit_err = omit_err)

        return outline_with_paper_assignment

    def _assign_paper(self, paper_assignment, outline, omit_err = False):
        outline_with_paper_assignment = outline

        for paper in paper_assignment:
            paper_id = paper.get("paper_id")
            for assign_section, assign_subsections in paper.get("assignment").items():
                matched_section = False
                for section in outline_with_paper_assignment["sections"]:
                    if assign_section == section.get("title"):
                        matched_section = True
                        if paper_id not in section["papers_to_use"]:
                            section["papers_to_use"].append(paper_id)
                        for subsection_title in assign_subsections:
                            matched_subsection = False
                            for subsection in section.get("subsections", []):
                                if subsection_title == subsection.get("title"):
                                    matched_subsection = True
                                    if paper_id not in subsection["papers_to_use"]:
                                        subsection["papers_to_use"].append(paper_id)
                            if not matched_subsection:
                                if omit_err:
                                    self.logger.info(f"Omit Err mode. Subsection title {subsection_title} not found during paper assignment for paper ID {paper_id}, skipping this subsection assignment.")
                                    continue
                                raise ValueError(f"Subsection title {subsection_title} not found during paper assignment.")
                if not matched_section:
                    if omit_err:
                        self.logger.info(f"Omit Err mode. Section title {assign_section} not found during paper assignment for paper ID {paper_id}, skipping this section assignment.")
                        continue
                    raise ValueError(f"Section title {assign_section} not found during paper assignment.")

        return outline_with_paper_assignment

    def generate_outline_1_step(
        self, intra_analysis_results, inter_analysis_results, papers, retry=1
    ):
        papers = self._select_outline_representative_paper_ids(
            self._bounded_writing_paper_ids(papers)
        )
        self._outline_representative_paper_ids = list(papers)
        max_retry_in_loop = self.config.ModuleInfo.SurveyGenerator.outline_generation_max_retry_in_generation_loop
        max_retry_out_loop = self.config.ModuleInfo.SurveyGenerator.outline_generation_max_retry
        try:
            papers_analysis = self._bounded_writing_analysis(
                intra_analysis_results, inter_analysis_results
            )
            outline = {}

            # iteratively generate outline
            num_batches = math.ceil(
                len(papers)
                / self.config.ModuleInfo.SurveyGenerator.outline_generation_batch_size
            )
            for batch_idx in range(num_batches):
                err_info = CumulativeErrorInfo()

                self.logger.info(
                    f"Generating outline: processing batch {batch_idx + 1} of {num_batches}"
                )
                batch_papers = papers[
                    batch_idx
                    * self.config.ModuleInfo.SurveyGenerator.outline_generation_batch_size : (
                        batch_idx + 1
                    )
                    * self.config.ModuleInfo.SurveyGenerator.outline_generation_batch_size
                ]
                paper_keynotes = ""
                for paper_id in batch_papers:
                    try:
                        paper_keynotes += self._outline_paper_brief(paper_id)
                    except Exception as e:
                        self.logger.error(f"Failed to build outline brief for paper ID: {paper_id} in OUTLINE GENERATION with error {e}. Skipping this paper in OUTLINE GENERATION.")
                        continue

                query = (
                    f"Current Outline Title: {outline.get('title', '')}\n"
                    f"Current Outline Sections: {json.dumps(outline.get('sections', []))}"
                )
                other_relevant_papers = (
                    ""
                    if self._evidence_bounded_writing_enabled()
                    or not self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG_in_outline
                    else self.database.query_and_text(
                        query,
                        self.config.ModuleInfo.SurveyGenerator.outline_RAG_topk,
                    )
                )
                prompt, _ = self._build_outline_prompt(
                    template=SURVEY_OUTLINE_GENERATION,
                    phase="one_step",
                    paper_keynotes=paper_keynotes,
                    current_outline=outline,
                    papers_analysis=papers_analysis,
                    other_relevant_papers=other_relevant_papers,
                    representative_paper_ids=papers,
                )



                # if self.config.BasicInfo.debug:
                #     self.logger.info(f"Outline generation prompt : {prompt}")

                valid = False
                last_error = ""
                last_response = ""
                for retry_time in range(max_retry_in_loop):
                    try:
                        request_prompt = (
                            prompt
                            if retry_time == 0
                            else self._build_outline_repair_prompt(
                                current_outline=outline,
                                validation_error=last_error or err_info.get_errors_text(),
                                previous_response=last_response,
                            )
                        )
                        renew_outline_raw = self._request_outline_json(request_prompt)
                        last_response = str(renew_outline_raw or "")
                        renew_outline = extract_json(renew_outline_raw)

                        omit_error = (
                            retry_time + self.omit_error_preserve_retry_time
                            >= max_retry_in_loop
                            and retry + 1 == max_retry_out_loop
                            and not self.config.BasicInfo.error_conservatism_mode
                        )
                        valid, new_err, err_papers = self.validate_outline(
                            intra_analysis_results,
                            papers,
                            renew_outline,
                            omit_err=omit_error,
                        )
                        if valid:
                            outline = renew_outline
                            break
                        err_info.add_errors(new_err)
                        raise ValueError(str(new_err))
                    except Exception as exc:
                        last_error = str(exc)
                        self.logger.warning(
                            "Outline validation failed for batch %s. Retrying this batch for %s: %s",
                            batch_idx + 1,
                            retry_time + 1,
                            exc,
                        )
                        if self.config.BasicInfo.debug:
                            self.logger.warning(
                                "Batch cumulative error: %s", err_info.get_errors_text()
                            )
                if not valid:
                    raise OutlineGenerationError(
                        "Outline generation exhausted retries for batch "
                        f"{batch_idx + 1}: {last_error or err_info.get_errors_text()}"
                    )

            return self._require_assignable_outline(outline)
        except Exception as e:
            if (
                retry
                > self.config.ModuleInfo.SurveyGenerator.outline_generation_max_retry
            ):
                raise e
            if self.config.BasicInfo.debug:
                self.logger.error(
                    f"Outline generation failed on retry {retry} with error: {e}. Retrying..."
                )
            return self.generate_outline(
                intra_analysis_results,
                inter_analysis_results,
                papers,
                retry=retry + 1,
            )

    def validate_outline_format(self, outline):
        if not isinstance(outline, dict):
            return False, "Outline must be a dictionary."
        # if "title" not in outline or not isinstance(outline["title"], str):
        #     return False, "Outline must have a 'title' field of type string."
        if "sections" not in outline or not isinstance(outline["sections"], list):
            return False, "Outline must have a 'sections' field of type list."
        if not outline["sections"]:
            return False, "Outline must contain at least one section."
        generator_config = self.config.ModuleInfo.SurveyGenerator
        min_sections = self._positive_int(
            getattr(generator_config, "outline_min_sections", 1), 1
        )
        max_sections = max(
            min_sections,
            self._positive_int(
                getattr(generator_config, "outline_max_sections", 15), 15
            ),
        )
        if len(outline["sections"]) < min_sections:
            return False, f"Outline must contain at least {min_sections} sections."
        if len(outline["sections"]) > max_sections:
            return False, f"Outline must contain no more than {max_sections} sections."
        min_subsections = self._positive_int(
            getattr(generator_config, "outline_min_subsections_per_section", 1), 1
        )
        max_subsections = max(
            min_subsections,
            self._positive_int(
                getattr(
                    generator_config, "outline_max_subsections_per_section", 15
                ),
                15,
            ),
        )
        for section in outline["sections"]:
            if not isinstance(section, dict):
                return False, f"Each section must be a dictionary, got {type(section)}."
            if (
                "title" not in section
                or not isinstance(section["title"], str)
                or not section["title"].strip()
            ):
                return False, "Each section must have a non-empty 'title' string."
            if (
                "description" not in section
                or not isinstance(section["description"], str)
                or not section["description"].strip()
            ):
                return False, "Each section must have a non-empty 'description' string."
            if "subsections" not in section or not isinstance(section["subsections"], list):
                return False, f"Each section must have a 'subsections' field of type list."
            if not section["subsections"]:
                return False, "Each section must contain at least one subsection."
            if len(section["subsections"]) < min_subsections:
                return False, (
                    "Each section must contain at least "
                    f"{min_subsections} subsections."
                )
            if len(section["subsections"]) > max_subsections:
                return False, (
                    "Each section must contain no more than "
                    f"{max_subsections} subsections."
                )
            for subsection in section["subsections"]:
                if not isinstance(subsection, dict):
                    return False, f"Each subsection must be a dictionary, got {type(subsection)}."
                if (
                    "title" not in subsection
                    or not isinstance(subsection["title"], str)
                    or not subsection["title"].strip()
                ):
                    return False, "Each subsection must have a non-empty 'title' string."
                if (
                    "description" not in subsection
                    or not isinstance(subsection["description"], str)
                    or not subsection["description"].strip()
                ):
                    return False, "Each subsection must have a non-empty 'description' string."
        return True, ""

    def validate_outline(self, intra_analysis_results, papers, outline, format_only = False, omit_err = False):
        valid_papers = set()
        if (
            not self._evidence_bounded_writing_enabled()
            and self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG_in_outline
        ):
            valid_papers.update(self.database.valid_paper_ids)
        err_info = []
        valid = True
        err_papers = []

        if not self._evidence_bounded_writing_enabled():
            for group in intra_analysis_results:
                for q in group:
                    valid_papers.update(q["related_papers"])
                    # if self.config.BasicInfo.debug:
                    #     self.logger.info(f"Valid paper IDs from intra-analysis: {q['related_papers']}") # YZY DEBUG
        
        for paper_id in papers:
            valid_papers.add(paper_id)
        
        valid_format, err_format =  self.validate_outline_format(outline)

        if not valid_format:
            err_info.append(f"Outline format error: {err_format}\n")
            valid = False
            return valid, err_info, err_papers
        
        if format_only:
            return valid, err_info, err_papers

        paper_set = set()
        for section in outline.get("sections", []):
            paper_set.update(section.get("papers_to_use", []))

            err_papers_to_remove = []
            for paper_id in section.get("papers_to_use", []):
                # if self.config.BasicInfo.debug:
                #     self.logger.info(f"Validating paper ID: {paper_id} in OUTLINE GENERATION") # YZY DEBUG
                if paper_id not in valid_papers:
                    self.logger.error(
                        f"Paper ID {paper_id} in section '{section.get('title', '')}' is not in the valid papers set.\n"
                    )
                    if omit_err:
                        err_papers_to_remove.append(paper_id)
                        self.logger.info(f"Omit Err mode. Removed invalid paper ID {paper_id} from section '{section.get('title', '')}' due to omit_err=True.")
                    else:
                        err_papers.append(paper_id)
                        # raise ValueError("Invalid paper ID in outline section.")
                        err_info.append(f"Paper ID {paper_id} in section '{section.get('title', '')}' is not in the valid papers set.")
                        valid = False
            section["papers_to_use"] = [pid for pid in section.get("papers_to_use", []) if pid not in err_papers_to_remove]

            for subsection in section.get("subsections", []):
                paper_set.update(subsection.get("papers_to_use", []))

                err_papers_to_remove = []
                for paper_id in subsection.get("papers_to_use", []):
                    if paper_id not in valid_papers:
                        self.logger.error(
                            f"Paper ID {paper_id} in subsection '{subsection.get('title', '')}' is not in the valid papers set."
                        )
                        if omit_err:
                            err_papers_to_remove.append(paper_id)
                            self.logger.info(f"Omit Err mode. Removed invalid paper ID {paper_id} from subsection '{subsection.get('title', '')}' due to omit_err=True.")
                        else:
                            err_info.append(f"Paper ID {paper_id} in subsection '{subsection.get('title', '')}' is not in the valid papers set.\n")
                            err_papers.append(paper_id)
                            valid = False
                        # raise ValueError("Invalid paper ID in outline subsection.")
                subsection["papers_to_use"] = [pid for pid in subsection.get("papers_to_use", []) if pid not in err_papers_to_remove]
                        
        self.logger.info(f"A {valid} batch, reference paper num: {len(paper_set)}")
        if self.config.BasicInfo.debug:
            self.logger.info(f"Use papers: {paper_set}")

        if not valid:
            return False, err_info, err_papers

        return True, err_info, []

    def log_outline(
        self, outline, width=100, max_papers_display=100, desc_preview_len=None
    ):
        used_paper_ids = set()
        """
        Pretty-print outline to the logger.
        - width: wrap width for descriptions
        - max_papers_display: if many papers, only show this many then "..."
        - desc_preview_len: if set, truncate description to this many chars before wrapping
        """

        def format_desc(desc):
            if not desc:
                return ""
            if desc_preview_len is not None and len(desc) > desc_preview_len:
                desc = desc[:desc_preview_len].rstrip() + "..."
            return "\n".join(textwrap.wrap(desc, width=width))

        def format_papers(papers):
            if not papers:
                return ""
            if len(papers) > max_papers_display:
                shown = papers[:max_papers_display]
                return (
                    ", ".join(shown) + f", ...(+{len(papers)-max_papers_display} more)"
                )
            return ", ".join(papers)

        def print_section(sec, indent=0):
            prefix = " " * indent
            lines = []
            title = sec.get("title", "<no title>")
            lines.append(f"{prefix}- {title}")

            desc = sec.get("description", "")
            if desc:
                wrapped = format_desc(desc)
                # indent wrapped description one level further
                for dline in wrapped.splitlines():
                    lines.append(f"{prefix}  {dline}")

            papers = sec.get("papers_to_use", []) or sec.get("papers", [])
            if papers:
                lines.append(f"{prefix}  papers: {format_papers(papers)}")
                used_paper_ids.update(papers)

            # recurse subsections
            for sub in sec.get("subsections", []):
                lines.append(print_section(sub, indent + 2))

            return "\n".join(lines)

        # build full text
        out_lines = []
        out_lines.append("=== Generated Survey Outline ===")
        out_lines.append(f"Survey Title: {outline.get('title', '<no title>')}\n")

        for sec in outline.get("sections", []):
            out_lines.append(print_section(sec))
            out_lines.append("")  # blank line between top-level sections

        pretty = "\n".join(out_lines)
        self.logger.info(pretty)     
        self.logger.info(f"Total unique papers used in outline: {len(used_paper_ids)}")

    def build_prompt_with_truncation(self, template: str, papers_list: list[str], params: dict):
        paper_num = len(papers_list)
        papers = ""
        use_full_text = self.config.ModuleInfo.SurveyGenerator.use_full_text_in_survey_generation

        params_no_papers = dict(params)
        params_no_papers["papers"] = ""
        valid_paper_ids = []

        estimated_prompt_tokens = self.chat_agent.estimate_tokens(template.format(**params_no_papers))

        per_paper_allowd = (self.config.APIInfo.llm_max_context_length 
                        - self.config.ModuleInfo.SurveyGenerator.llm_max_context_overhead_length_generation
                        - estimated_prompt_tokens) // max(paper_num, 1)

        for paper_id in papers_list:
            try:
                title, abstract = self.work_analyzer.work_collector.get_paper_title_abstract(paper_id)
            except Exception as e:
                title, abstract = "", ""

            if use_full_text:
                try:
                    paper_raw_markdown = self.work_analyzer.work_collector.get_paper_raw_markdown(
                        paper_id
                    )
                except Exception as e:
                    if self.config.ModuleInfo.WorkAnalyzer.abstract_when_full_text_fail:
                        self.logger.info(f"Full text fetch failed for paper ID: {paper_id}: {e} in SURVEY DRAFT, using abstract instead.")
                        try:
                            paper_raw_markdown, _ = self.work_analyzer.work_collector.get_paper_title_abstract(
                                paper_id
                            )
                            paper_raw_markdown = str(paper_raw_markdown)
                        except Exception as e:
                            self.logger.error(f"Failed to get abstract for paper ID: {paper_id} in SURVEY DRAFT with error {e}. Skipping this paper in SURVEY DRAFT.")
                            continue
                    else:
                        self.logger.error(f"Failed to get content for paper ID: {paper_id} in SURVEY DRAFT. Skipping this paper in SURVEY DRAFT.")
                        continue
                if self.config.BasicInfo.debug:
                    self.logger.info(f"Original length of paper {paper_id} raw markdown: {len(paper_raw_markdown)} in SURVEY DRAFT")
                paper_raw_markdown = self.chat_agent.truncate_text(paper_id, paper_raw_markdown, per_paper_allowd)

                if self.use_title_in_draft:
                    self.logger.info(f"Using title for paper ID: {paper_id} in SURVEY DRAFT")
                    papers += (
                        f"Title: {title}\nRaw markdown: {paper_raw_markdown}\n\n"
                    )
                else:
                    papers += (
                        f"Paper ID: {paper_id}\nRaw markdown: {paper_raw_markdown}\n\n"
                    )
                valid_paper_ids.append(paper_id)

            else:
                if self.config.BasicInfo.debug:
                    self.logger.info(f"Using keynote for paper ID: {paper_id} in SURVEY DRAFT")
                try:
                    paper_keynote = self.work_analyzer.get_paper_keynote(
                        paper_id
                    )
                    paper_keynote = str(paper_keynote)
                except Exception as e:
                    self.logger.error(f"Failed to get keynote for paper ID: {paper_id} in SURVEY DRAFT with error {e}. Skipping this paper in SURVEY DRAFT.")
                    continue
                if self.config.BasicInfo.debug:
                    self.logger.info(f"Original length of paper {paper_id} paper keynote: {len(paper_keynote)} in SURVEY DRAFT")
                paper_keynote = self.chat_agent.truncate_text(paper_id, paper_keynote, per_paper_allowd)
                if self.use_title_in_draft:
                    papers += f"Title: {title}\nKeynote: {paper_keynote}\n\n"
                else:
                    papers += f"Paper ID: {paper_id}\nKeynote: {paper_keynote}\n\n"
                valid_paper_ids.append(paper_id)

        params["papers"] = papers
        prompt = template.format(**params)

        if self.config.BasicInfo.debug:
            self.logger.info(f"Built prompt with length {len(prompt)}")

        return prompt, valid_paper_ids

    def draft_survey(self, intra_analysis_results, inter_analysis_results, outline, code_report=None):
        self.prepare_survey_evidence_plan()
        outline = self._bound_outline_to_evidence_plan(outline)
        claim_trace_validation_enabled = self._claim_trace_validation_enabled()
        if (
            self._evidence_bounded_writing_enabled()
            and not claim_trace_validation_enabled
        ):
            self.logger.warning(
                "Claim-trace validation is temporarily disabled; preserving "
                "evidence-bounded prompts and visible citation validation, but "
                "skipping trace repair, provenance, support-kind, and "
                "claim-trace completeness gates."
            )
        length_budget = self._survey_length_budget(outline)
        self.logger.info(
            "Survey length budget: target=%s, max=%s, sections=%s, subsections=%s, "
            "subsection_target/max=%s/%s.",
            length_budget["survey_target_words"],
            length_budget["survey_max_words"],
            length_budget["section_count"],
            length_budget["subsection_count"],
            length_budget["subsection_target_words"],
            length_budget["subsection_max_words"],
        )
        relevant_analysis = self._bounded_writing_analysis(
            intra_analysis_results, inter_analysis_results
        )

        # Determine which template to use based on whether code_report is provided
        bounded_code_report = self._bounded_writing_code_report(code_report)
        use_code_template = bool(bounded_code_report)
        if use_code_template:
            self.logger.info("Code report provided. Using code-aware prompt template for subsection drafting.")
            code_report_prompt = CODE_REPORT_PROMPT.format(code_report=bounded_code_report)
        else:
            code_report_prompt = ""
            self.logger.info("No code report provided. Using standard prompt template for subsection drafting.")

        # step 1: subsection draft
        subsection_prompts = []
        subsection_locations = []
        subsection_claims_by_index = {}
        subsections_valid_paper_ids = []
        for section_index, section in enumerate(outline.get("sections", [])):
            for subsection_index, subsection in enumerate(section.get("subsections", [])):
                
                query = f"Title: {subsection.get('title', '')}\n Description: {subsection.get('description', '')}"
                other_paper_RAG_text = "" if self._evidence_bounded_writing_enabled() else self.database.query_and_text(query, self.config.ModuleInfo.SurveyGenerator.subsection_RAG_topk) if self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG else ""
                params_dict = {
                    "title": subsection.get("title", ""),
                    "description": subsection.get("description", ""),
                    "relevant_analysis": relevant_analysis,
                    "papers": "",
                    "other_relevant_papers": other_paper_RAG_text,
                    "subsection_target_words": length_budget["subsection_target_words"],
                    "subsection_max_words": length_budget["subsection_max_words"],
                    "subsection_target_citations": length_budget[
                        "subsection_target_citations"
                    ],
                    "subsection_max_citations": length_budget[
                        "subsection_max_citations"
                    ],
                    "survey_outline": json.dumps(outline, ensure_ascii=False),
                    "code_report_prompt": code_report_prompt,
                    "survey_evidence_plan": self._survey_evidence_plan_prompt(),
                    # "section_index": section_index + 1,
                    # "subsection_index": subsection_index + 1
                }

                # Use code-aware template if code_report is provided, otherwise use standard template
                template = SUBSECTION_DRAFT_WITH_CODE if use_code_template else SUBSECTION_DRAFT
                
                prompt, valid_paper_ids = self.build_prompt_with_truncation(
                                                                    template = template, 
                                                                    papers_list = [
                                                                        paper_id
                                                                        for paper_id in self._as_paper_ids(subsection.get("papers_to_use"))
                                                                        if not self._evidence_bounded_writing_enabled()
                                                                        or paper_id in self._permitted_evidence_plan_paper_ids()
                                                                    ],
                                                                    params = params_dict
                                                                )
                subsections_valid_paper_ids.extend(valid_paper_ids)

                subsection_prompts.append(prompt)
                subsection_locations.append((section_index, subsection_index))

                # self.logger.info(f"OUTLINEDEBUG: Built subsection draft prompt for section {section_index + 1} subsection {subsection_index + 1}: \n\n {prompt}")

        # if self.config.BasicInfo.debug:
        #     self.logger.info(f"subsection prompt example: {subsection_prompts[0] if subsection_prompts else 'No prompts generated'}")

        subsection_drafts = [""] * len(subsection_prompts)
        subsection_indices = list(range(len(subsection_prompts)))
        previous_err_infos = [CumulativeErrorInfo() for _ in range(len(subsection_prompts))]

        valid = False
        for try_time in range(self.config.ModuleInfo.SurveyGenerator.subsection_draft_max_retry):
            subsection_prompts_with_error = [subsection_prompts[i] + ERROR_FEEDBACK_PROMPT.format(info=previous_err_infos[i].get_errors_text()) 
                                                                        if len(previous_err_infos[i].get_errors_text()) > 1 else subsection_prompts[i] for i in range(len(subsection_prompts))]
            try:    
                response_drafts = self.chat_agent.batch_remote_chat(
                    subsection_prompts_with_error,
                    desc="Drafting survey subsections...",
                    temperature=self.config.ModuleInfo.SurveyGenerator.subsection_draft_temperature,
                )
            except Exception as e:
                self.logger.error(f"Failed to get subsection drafts from chat agent: {e} in SUBSECTION DRAFT. Retrying all subsections for {try_time + 1}...")
                continue
            err_prompts = []
            err_indices = []
            err_infos = []
            trace_repair_records = []

            for i, drafts in enumerate(response_drafts):
                allow_omit = (not self.config.BasicInfo.error_conservatism_mode) and (try_time + self.omit_error_preserve_retry_time >= self.config.ModuleInfo.SurveyGenerator.subsection_draft_max_retry)
                visible_draft, claim_trace, parse_errors = self._extract_claim_trace(drafts)
                if self.use_title_in_draft:
                    is_valid_subsection, info, cleaned_draft = self.validate_title_citation_draft(
                        visible_draft,
                        subsections_valid_paper_ids,
                        length_budget["subsection_target_words"],
                        max_words=length_budget["subsection_max_words"],
                        omit_error=allow_omit,
                    )
                else:
                    is_valid_subsection, info, cleaned_draft = self.validate_id_citation_draft(
                        visible_draft,
                        subsections_valid_paper_ids,
                        length_budget["subsection_target_words"],
                        max_words=length_budget["subsection_max_words"],
                        omit_error=allow_omit,
                    )
                if claim_trace_validation_enabled:
                    normalized_claim_trace, trace_errors = (
                        self._validate_and_normalize_claim_trace(
                            cleaned_draft,
                            claim_trace,
                            parse_errors,
                        )
                    )
                else:
                    normalized_claim_trace, trace_errors = [], []

                if not is_valid_subsection:
                    if trace_errors:
                        info = [*info, *trace_errors]
                    err_prompts.append(subsection_prompts[i])
                    err_indices.append(subsection_indices[i])
                    previous_err_infos[i].add_errors(info)
                    err_infos.append(previous_err_infos[i])

                    error_summary = " | ".join(self._as_texts(info)) or (
                        "validator returned no diagnostic"
                    )
                    if len(error_summary) > 1_000:
                        error_summary = error_summary[:997] + "..."
                    if self.config.BasicInfo.debug:
                        self.logger.info(f'cumulative error info for subsection index {subsection_indices[i]}: {previous_err_infos[i].get_errors_text()} in SUBSECTION DRAFT')
                    self.logger.warning(
                        "Subsection draft validation failed for subsection index "
                        f"{subsection_indices[i]}: {error_summary}. Retrying this "
                        f"subsection for {try_time + 1}..."
                    )
                elif trace_errors:
                    # The reader-visible subsection already satisfies citation
                    # and length checks.  Preserve it and repair only its
                    # metadata instead of regenerating a long passage.
                    trace_repair_records.append(
                        {
                            "draft_index": subsection_indices[i],
                            "visible_draft": cleaned_draft,
                            "trace_errors": trace_errors,
                        }
                    )
                else:
                    subsection_drafts[subsection_indices[i]] = cleaned_draft
                    subsection_claims_by_index[subsection_indices[i]] = normalized_claim_trace

            if trace_repair_records:
                repaired_traces, repair_failures = self._repair_claim_traces(
                    trace_repair_records,
                    stage="subsection",
                )
                for record in trace_repair_records:
                    draft_index = int(record["draft_index"])
                    if draft_index in repaired_traces:
                        subsection_drafts[draft_index] = str(record["visible_draft"])
                        subsection_claims_by_index[draft_index] = repaired_traces[
                            draft_index
                        ]
                if repair_failures:
                    details = "; ".join(
                        f"subsection {index}: {' | '.join(errors[:3])}"
                        for index, errors in sorted(repair_failures.items())
                    )
                    self.logger.error(
                        "Claim-trace repair exhausted without rewriting accepted subsection prose: %s",
                        details,
                    )
                    raise ValueError(
                        "Invalid subsection claim trace after metadata-only repair: "
                        + details
                    )
            
            if not err_prompts:
                valid = True
                break  # all valid
            else:
                subsection_prompts = err_prompts
                subsection_indices = err_indices
                if self.config.BasicInfo.debug:
                    self.logger.info(f"Retrying {len(err_prompts)} subsection drafts due to validation errors...")
                for i in range(len(subsection_prompts)):
                    subsection_prompts[i]
                previous_err_infos = err_infos

        if not valid:
            final_failure_details = []
            for draft_index, error_info in zip(
                subsection_indices, previous_err_infos
            ):
                errors = self._as_texts(error_info.get_errors())
                summary = " | ".join(errors) or "validator returned no diagnostic"
                if len(summary) > 1_000:
                    summary = summary[:997] + "..."
                final_failure_details.append(
                    f"subsection {draft_index}: {summary}"
                )
            details = "; ".join(final_failure_details)
            self.logger.error(
                "Some subsection drafts failed validation after maximum retries: "
                + details
            )
            raise ValueError(
                "Invalid subsection draft after maximum retries: " + details
            )

        if self.config.BasicInfo.debug:
            # self.logger.info(f"SUBSECTION DRAFTS: {subsection_drafts}")
            total_cites = 0
            for i, subsection_draft in enumerate(subsection_drafts):
                cites = self.count_unique_titles(subsection_draft)
                total_cites += cites
                self.logger.info(f"Subsection {i} citation num: {cites}")
            self.logger.info(f"Total citation num in subsection drafts: {total_cites}")

        # step 2: section draft
        section_prompts = []
        section_claims_by_index = {}
        sections_valid_ids = []
        sections_subsection_drafts = []
        idx = 0
        for section_index, section in enumerate(outline.get("sections", [])):
            valid_ids = []
            current_subsection_drafts = "\n\n"
            for i in range(len(section.get("subsections", []))):
                current_subsection_drafts += "#### " +section.get("subsections", [])[i].get("title", "") + "\n\n" + subsection_drafts[idx + i] + "\n\n"
            sections_subsection_drafts.append(current_subsection_drafts)
            idx += len(section.get("subsections", []))

            subsection_paper_ids = set()
            for subsection in section.get("subsections", []):
                subsection_paper_ids.update(subsection.get("papers_to_use", []))
                sections_valid_ids.extend(subsection.get("papers_to_use", []))

            papers = ""
            section_paper_ids = []
            for paper_id in section.get("papers_to_use", []):
                if paper_id in subsection_paper_ids:
                    continue  # already included in subsections
                section_paper_ids.append(paper_id)
                sections_valid_ids.append(paper_id)
            
            query = f"Title: {section.get('title', '')}\n Description: {section.get('description', '')}"
            other_paper_RAG_text = "" if self._evidence_bounded_writing_enabled() else self.database.query_and_text(query, self.config.ModuleInfo.SurveyGenerator.section_RAG_topk) if self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG else ""
            params_dict = {
                "title": section.get("title", ""),
                "description": section.get("description", ""),
                "subsection_drafts": current_subsection_drafts,
                "papers": "",
                "other_relevant_papers": other_paper_RAG_text,
                "section_target_words": length_budget["section_preamble_target_words"],
                "section_max_words": length_budget["section_preamble_max_words"],
                "section_target_citations": length_budget[
                    "section_preamble_target_citations"
                ],
                "section_max_citations": length_budget[
                    "section_preamble_max_citations"
                ],
                # "section_index": section_index + 1,
                "survey_outline": json.dumps(outline, ensure_ascii=False),
                "survey_evidence_plan": self._survey_evidence_plan_prompt(),
            }
            prompt, _ = self.build_prompt_with_truncation(
                template = SECTION_DRAFT,
                papers_list = [
                    paper_id
                    for paper_id in self._as_paper_ids(section_paper_ids)
                    if not self._evidence_bounded_writing_enabled()
                    or paper_id in self._permitted_evidence_plan_paper_ids()
                ],
                params = params_dict,
            )
            # self.logger.info(f"OUTLINEDEBUG: Section draft prompt for section index {section_index} before error feedback: \n\n {prompt}")

            section_prompts.append(prompt)

        # if self.config.BasicInfo.debug:
        #     self.logger.info(f"section prompt example: {section_prompts[0] if section_prompts else 'No prompts generated'}")
        
        section_drafts = [""] * len(section_prompts)
        section_indices = list(range(len(section_prompts)))
        previous_err_infos = [
            CumulativeErrorInfo() for _ in range(len(section_prompts))
        ]

        valid = True
        self.logger.info(f"Starting section draft with max_retry: {self.config.ModuleInfo.SurveyGenerator.section_draft_max_retry}, error_conservatism_mode: {self.config.BasicInfo.error_conservatism_mode}")
        for try_time in range(self.config.ModuleInfo.SurveyGenerator.section_draft_max_retry):
            section_prompts_with_error = [section_prompts[i] + ERROR_FEEDBACK_PROMPT.format(info=previous_err_infos[i].get_errors_text()) 
                                        if len(previous_err_infos[i].get_errors_text()) > 1 else section_prompts[i] for i in range(len(section_prompts))]

            try:
                response_drafts = self.chat_agent.batch_remote_chat(
                    section_prompts_with_error,
                    desc="Drafting survey sections...",
                    temperature=self.config.ModuleInfo.SurveyGenerator.section_draft_temperature,
                )
            except Exception as e:
                self.logger.error(f"Failed to get section drafts from chat agent: {e} in SECTION DRAFT. Retrying all sections for {try_time + 1}...")
                continue

            err_prompts = []
            err_indices = []
            err_infos = []
            trace_repair_records = []
            for i, drafts in enumerate(response_drafts):
                allow_omit = (not self.config.BasicInfo.error_conservatism_mode) and (try_time + self.omit_error_preserve_retry_time >= self.config.ModuleInfo.SurveyGenerator.section_draft_max_retry)
                visible_draft, claim_trace, parse_errors = self._extract_claim_trace(drafts)
                if self.use_title_in_draft:
                    is_valid_section, info, cleaned_draft = self.validate_title_citation_draft(
                        visible_draft,
                        sections_valid_ids,
                        length_budget["section_preamble_target_words"],
                        max_words=length_budget["section_preamble_max_words"],
                        omit_error=allow_omit,
                    )
                else:
                    is_valid_section, info,  cleaned_draft = self.validate_id_citation_draft(
                        visible_draft,
                        sections_valid_ids,
                        length_budget["section_preamble_target_words"],
                        max_words=length_budget["section_preamble_max_words"],
                        omit_error=allow_omit,
                    )
                if claim_trace_validation_enabled:
                    normalized_claim_trace, trace_errors = (
                        self._validate_and_normalize_claim_trace(
                            cleaned_draft,
                            claim_trace,
                            parse_errors,
                        )
                    )
                else:
                    normalized_claim_trace, trace_errors = [], []

                if not is_valid_section:
                    if trace_errors:
                        info = [*info, *trace_errors]
                    self.logger.warning(f"Section draft validation failed for section index {section_indices[i]}. Retrying this section for {try_time + 1}...")
                    err_prompts.append(section_prompts[i])
                    err_indices.append(section_indices[i])
                    previous_err_infos[i].add_errors(info)
                    if self.config.BasicInfo.debug:
                        self.logger.info(f'cumulative error info for section index {section_indices[i]}: {previous_err_infos[i].get_errors_text()} in SECTION DRAFT')
                    err_infos.append(previous_err_infos[i])
                    valid =False
                elif trace_errors:
                    trace_repair_records.append(
                        {
                            "draft_index": section_indices[i],
                            "visible_draft": cleaned_draft,
                            "trace_errors": trace_errors,
                        }
                    )
                else:
                    section_drafts[section_indices[i]] = cleaned_draft + sections_subsection_drafts[section_indices[i]]
                    section_claims_by_index[section_indices[i]] = normalized_claim_trace
                    self.logger.info(f"OUTLINEDEBUG: Section draft for index {section_indices[i]} valid, and updated with subsection drafts.")

            if trace_repair_records:
                repaired_traces, repair_failures = self._repair_claim_traces(
                    trace_repair_records,
                    stage="section",
                )
                for record in trace_repair_records:
                    draft_index = int(record["draft_index"])
                    if draft_index in repaired_traces:
                        section_drafts[draft_index] = (
                            str(record["visible_draft"])
                            + sections_subsection_drafts[draft_index]
                        )
                        section_claims_by_index[draft_index] = repaired_traces[
                            draft_index
                        ]
                if repair_failures:
                    details = "; ".join(
                        f"section {index}: {' | '.join(errors[:3])}"
                        for index, errors in sorted(repair_failures.items())
                    )
                    self.logger.error(
                        "Claim-trace repair exhausted without rewriting accepted section prose: %s",
                        details,
                    )
                    raise ValueError(
                        "Invalid section claim trace after metadata-only repair: "
                        + details
                    )

            if not err_prompts:
                valid = True
                break  # all valid
            else:
                section_prompts = err_prompts
                section_indices = err_indices
                previous_err_infos = err_infos
                self.logger.info(f"Retrying {len(err_prompts)} section drafts due to validation errors...")
        if not valid:
            self.logger.error("Some section drafts failed validation after maximum retries.")
            raise ValueError("Invalid section draft after maximum retries.")
            
        # if self.config.BasicInfo.debug:
        #     self.logger.info(f"SECTION DRAFTS: {section_drafts}")

        outcome_draft = outline.get("title", self.config.BasicInfo.topic + " Survey")+ "\n\n"+ "\n\n".join(section_drafts)
        outcome_word_count = len(outcome_draft.split())
        if outcome_word_count > length_budget["survey_max_words"]:
            raise ValueError(
                "Survey draft exceeds the configured total length budget: "
                f"{outcome_word_count} > {length_budget['survey_max_words']} words."
            )
        self.logger.info(f"OUTLINEDEBUG: Full draft before cleaning and refine: \n\n {outcome_draft}")

        if self.use_title_in_draft:
            self.logger.info(f"Total unique paper titles in correct format in Draft before cleaning and refine: {self.count_unique_titles(outcome_draft)}")
        else:
            self.logger.info(f"Total paper references in correct format in Draft before cleaning: {self.count_unique_paper_ids(outcome_draft)}")

        drafts = {
            "section_drafts": section_drafts,
            "full_draft": outcome_draft,
            "title": outline.get("title", self.config.BasicInfo.topic + " Survey"),
            "outline": outline
        }
        if self._evidence_bounded_writing_enabled():
            traceability = []
            for draft_index, claims in subsection_claims_by_index.items():
                section_index, subsection_index = subsection_locations[draft_index]
                for claim_index, claim in enumerate(claims, start=1):
                    traceability.append(
                        {
                            **dict(claim),
                            "claim_id": f"S{section_index + 1}.SS{subsection_index + 1}.C{claim_index}",
                            "draft_unit": "subsection",
                            "section_index": section_index + 1,
                            "subsection_index": subsection_index + 1,
                        }
                    )
            for section_index, claims in section_claims_by_index.items():
                for claim_index, claim in enumerate(claims, start=1):
                    traceability.append(
                        {
                            **dict(claim),
                            "claim_id": f"S{section_index + 1}.P.C{claim_index}",
                            "draft_unit": "section_preamble",
                            "section_index": section_index + 1,
                        }
                    )
            if claim_trace_validation_enabled:
                unaccounted = self._unaccounted_plan_subhypotheses(traceability)
                if unaccounted:
                    raise ValueError(
                        "Evidence-bounded survey draft does not account for every SH: "
                        + ", ".join(unaccounted)
                    )
            self._store_claim_traceability(
                traceability,
                validation_enabled=claim_trace_validation_enabled,
            )
            drafts["survey_evidence_plan"] = self.survey_evidence_plan
            drafts["claim_traceability"] = self.survey_claim_traceability_artifact
        return drafts
    
    def validate_id_citation_draft(
        self, section_draft, papers, least_words=0, max_words=None, omit_error=False
    ):
        if self.always_omit_error:
            omit_error = True
        if not isinstance(section_draft, str):
            return False, [f"draft context is {type(section_draft)}, not str"], section_draft

        valid = True
        citation_valid = True
        err_info = []

        if least_words and len(section_draft.split()) < least_words*self.config.ModuleInfo.SurveyGenerator.draft_length_relax_ratio:
            self.logger.info(
                f"Section draft too short: {len(section_draft.split())} words < {least_words}."
            )
            if omit_error:
                self.logger.info("Omitting draft length being too short error...")
            else:
                valid = False
                err_info.append(f"Section draft too short: {len(section_draft.split())} words < {least_words}.")

        if max_words and len(section_draft.split()) > max_words:
            valid = False
            err_info.append(
                f"Section draft too long: {len(section_draft.split())} words > {max_words}."
            )

        papers_set = set(papers)
        if self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG:
            papers_set.update(self.database.valid_paper_ids)
        err_papers = []
        paper_ids = list(self.get_unique_paper_ids_from_raw(section_draft))

        if '#' in section_draft:
            valid = False
            err_info.append("Draft contains '#' character, probably a wrong format.")
            self.logger.error(f"Draft contains '#' character, probably a wrong format in SUBSECTION DRAFT.")
            if omit_error:
                self.logger.info("Omitting draft containing '#' character error...")
                section_draft = section_draft.replace('#', '')

        for paper_id in paper_ids:
            if paper_id not in papers_set:
                self.logger.warning(f"Paper ID {paper_id} not found in papers set in SUBSECTION DRAFT VALIDATE.")
                err_info.append(f"Paper ID {paper_id} not found in papers set, probably a wrong paper_id.")
                valid = False
                citation_valid = False
                err_papers.append(paper_id)

        cleaned = section_draft
        if not valid and omit_error:
            if not citation_valid:
                cleaned = self._remove_err_paper_ids_from_text(section_draft, err_papers)
            valid = True

        return valid, err_info, cleaned

    def validate_title_citation_draft(
        self, section_draft, papers, least_words=0, max_words=None, omit_error=False
    ):
        if self.always_omit_error:
            omit_error = True
        # In SH-bounded writing, an unapproved title must force a retry.  Omitting
        # the validation error would leave a rendered citation that has no
        # admissible ledger path, even if its title resolves in the global database.
        if self._evidence_bounded_writing_enabled():
            omit_error = False
        if self.config.BasicInfo.debug:
            self.logger.info(f"Validating draft titles in DRAFT TITLE VALIDATE.")
        if not isinstance(section_draft, str):
            return False, [f"draft context is {type(section_draft)}, not str"], section_draft

        citation_valid = True
        err_info = []
        if least_words and len(section_draft.split()) < least_words*self.config.ModuleInfo.SurveyGenerator.draft_length_relax_ratio:
            self.logger.info(
                f"Draft too short for title validation: {len(section_draft.split())} words < {least_words}."
            )
            err_info.append(f"Draft too short for title validation: {len(section_draft.split())} words < {least_words}.")

        too_long = bool(max_words and len(section_draft.split()) > max_words)
        if too_long:
            err_info.append(
                f"Draft too long for title validation: {len(section_draft.split())} words > {max_words}."
            )

        papers_set = set(papers)
        if self.config.ModuleInfo.SurveyGenerator.include_other_relevant_papers_RAG:
            papers_set.update(self.database.valid_paper_ids)

        valid, paper_ids, titles, err_titles = self.extract_and_validate_titles_in_text(section_draft)
        if too_long:
            valid = False
        if not valid:
            citation_valid = False

        if self._evidence_bounded_writing_enabled():
            unauthorized_paper_ids = [
                paper_id for paper_id in paper_ids if paper_id not in papers_set
            ]
            if unauthorized_paper_ids:
                valid = False
                citation_valid = False
                err_info.append(
                    "Resolved title citations are outside the evidence-bounded "
                    "paper set: " + ", ".join(dict.fromkeys(unauthorized_paper_ids))
                )

        for err_paper_title in err_titles:
            err_info.append(f"Paper title '{err_paper_title}' not found in database, probably a wrong or incomplete title, or the paper is not in valid citation range.\n")

        if '#' in section_draft:
            valid = False
            err_info.append("Draft contains '#' character, probably a wrong format.")
            self.logger.error(f"Draft contains '#' character, probably a wrong format in SUBSECTION DRAFT.")
            if omit_error:
                self.logger.info("Omitting draft containing '#' character error...")
                section_draft = section_draft.replace('#', '')

        cleaned = section_draft
        if not valid and omit_error:
            if not citation_valid:
                cleaned = self._remove_err_paper_titles_from_text(section_draft, err_titles)
            valid = True

        return valid, err_info, cleaned

    def _remove_err_paper_ids_from_text(self, text: str, err_ids: list[str]) -> str:
        cleaned = text
        for pid in err_ids:
            pat = rf"<Paper ID:\s*{re.escape(pid)}\s*>|\(Paper ID:\s*{re.escape(pid)}\s*\)|<Paper\s*ID\s*:\s*{re.escape(pid)}\s*>|\(Paper\s*ID\s*{re.escape(pid)}\s*\)|<Paper\s*{re.escape(pid)}\s*>|\(Paper\s*{re.escape(pid)}\s*\)|{re.escape(pid)}|<Paper\s*<{re.escape(pid)}>\s*>"
            cleaned = re.sub(pat, "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    def _remove_err_paper_titles_from_text(self, text: str, err_titles: list[str]) -> str:
        cleaned = text
        for title in err_titles:
            # Remove the bracketed title citation, and any standalone title leftovers
            pat = rf"<\s*{re.escape(title)}\s*>|{re.escape(title)}"
            cleaned = re.sub(pat, "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    def _remove_papers_from_outline(self, outline: dict, err_ids: list[str]) -> dict:
        err_set = set(err_ids)
        for section in outline.get("sections", []) or []:
            section["papers_to_use"] = [p for p in section.get("papers_to_use", []) if p not in err_set]
            for subsection in section.get("subsections", []) or []:
                subsection["papers_to_use"] = [p for p in subsection.get("papers_to_use", []) if p not in err_set]
        return outline

    def review_section(self, section_text, previous_section_text=None, next_section_text=None, section_title = None, section_outline = None, code_report = None, env_report = None):
        self.logger.info("\n--- [Reviewer] analyzing text... ---")
        
        if self.config.ModuleInfo.SurveyGenerator.include_env_report and env_report:
            final_report = f"CODE REPORT: {code_report}\n\nENV REPORT: {env_report}\n\n"
        else:
            final_report = code_report

        if self.config.ModuleInfo.SurveyGenerator.include_code_report and final_report:
            additional_context = CODE_REPORT_PROMPT_FOR_SECTION_REVIEWER.format(code_report = final_report)
            self.logger.info(f"injecting code report to section reviewer: {additional_context[:1500]}")
        else:
            additional_context = "None"

        review_prompt = SECTION_REVIEW.format(
            topic = self.config.BasicInfo.topic,
            section_text=section_text,
            section_target_words = self._survey_length_budget()["section_target_words"],
            previous_section_text=previous_section_text or "",
            next_section_text=next_section_text or "",
            current_section_length = len(section_text.split()),
            section_title = section_title or "",
            section_outline = section_outline or "",
            additional_context = additional_context,
        )
        valid = False
        for _ in range(self.config.ModuleInfo.SurveyGenerator.section_review_retry):
            try:
                suggestions = extract_json(
                    self.chat_agent.remote_chat(
                        review_prompt,
                        temperature=self.config.ModuleInfo.SurveyGenerator.section_review_temperature,
                    )
                )
                valid = True
                break
            except Exception as e:
                self.logger.error(f"Section review failed with error {e}. Retrying...")
                continue

        if valid:
            print(f"   [Reviewer] Generated {len(suggestions)} suggestions.")
            return suggestions
        else:
            print("   [Reviewer] Failed to generate valid list.")
            raise ValueError("Invalid section review output.")

    def _apply_revision_to_text(self, original_text: str, revision_json: dict) -> str:
        new_text = apply_revision_to_text(original_text, revision_json)
        if self.config.BasicInfo.debug and new_text != original_text:
            old_str = revision_json["originalText"]
            new_str = revision_json["newText"]
            self.logger.info(f"OUTLINEREVISEDEBUG: text to be replaced: {old_str}\n")
            self.logger.info(f"OUTLINEREVISEDEBUG: new text: {new_str}\n")
            self.logger.info(f"   >>> Applied revision: Replaced {len(old_str)} chars with {len(new_str)} chars.")
        return new_text

    def revise_section(self, section_text, suggestion, section_title = None, section_outline = None, code_report = None, env_report = None):
        self.logger.info(f"\n--- [Reviser] processing suggestion: {suggestion}... ---")
        valid = False
        retry_feedback = ""
        for retry_time in range(self.config.ModuleInfo.SurveyGenerator.section_revise_retry):
            try:
                if self.config.ModuleInfo.SurveyGenerator.include_env_report and env_report:
                    final_report = f"CODE REPORT: {code_report}\n\nENV REPORT: {env_report}\n\n"
                else:
                    final_report = code_report

                if self.config.ModuleInfo.SurveyGenerator.include_code_report and final_report:
                    additional_context = CODE_REPORT_PROMPT_FOR_SECTION_REVISER.format(code_report = final_report)
                    self.logger.info(f"injecting code report to section revieser: {additional_context[:1500]}")
                else:
                    additional_context = "None"
                prompt = SECTION_REVISE.format(
                    section_title=section_title,
                    section_outline = section_outline or "",
                    topic=self.config.BasicInfo.topic, 
                    text=section_text,
                    citations=self.database.query_and_text(section_title or self.config.BasicInfo.topic, self.config.ModuleInfo.SurveyGenerator.section_revision_RAG_topk),
                    additional_context = additional_context,
                    reviewer_suggestion=suggestion
                )
                if retry_feedback:
                    prompt += (
                        "\n\nPrevious attempt was rejected for this reason:\n"
                        f"{retry_feedback}\n"
                        "Return a corrected JSON object that satisfies the output contract."
                    )

                parsed_json = extract_json(
                    self.chat_agent.remote_chat(
                        prompt,
                        temperature=(
                            self.config.ModuleInfo.SurveyGenerator.section_revise_temperature
                            if retry_time == 0 else 0.1
                        ),
                        response_format="json_object",
                    )
                )
                if not isinstance(parsed_json, dict):
                    raise ValueError("Parsed JSON is not a dict.")
                validate_revision_payload(section_text, parsed_json)
                valid = True
                break
            except Exception as e:
                retry_feedback = str(e)
                self.logger.error(
                    f"Section revision attempt {retry_time + 1}/"
                    f"{self.config.ModuleInfo.SurveyGenerator.section_revise_retry} failed "
                    f"for '{section_title}' using {self.chat_agent.model_name}: {e}"
                )
        
        if not valid:
            self.logger.error("Failed to generate valid revision after retries.")
            raise ValueError("Invalid section revision output.")

        if isinstance(parsed_json, dict):
            if parsed_json.get("action") == "done":
                if self.config.BasicInfo.debug:
                    self.logger.info("   [Reviser] Decided no change needed.")
                return section_text
            elif parsed_json.get("action") == "replace":
                if self.config.BasicInfo.debug:
                    self.logger.info("   [Reviser] Applying revision...")
                return self._apply_revision_to_text(section_text, parsed_json)
        else:
            raise ValueError("Parsed revision JSON is not a dict.")
        return section_text
    
    def _format_section_outline(self, section_outline, include_description = True):
        text = f"- Section title: {section_outline.get('title', '')}\n"
        if include_description:
            text += f"  Section description: {section_outline.get('description', '')}\n"
        for subsection in section_outline.get("subsections", []):
            text += f"  - Subsection title: {subsection.get('title', '')}\n"
            if include_description:
                text += f"    Subsection description: {subsection.get('description', '')}\n"
        return text

    def review_and_revise_section(self, current_text, previous_section_text=None, next_section_text=None, section_outline=None, code_report = None, env_report = None):
        MAX_OUTER_ITERATIONS = self.config.ModuleInfo.SurveyGenerator.max_review_revise_iterations
        for i in range(MAX_OUTER_ITERATIONS):
            self.logger.info(f"\n\n====== step 1.1 revise in parts: OUTER LOOP {i+1}/{MAX_OUTER_ITERATIONS} ======")
            
            try:
                suggestions = self.review_section(current_text, previous_section_text, next_section_text, section_outline.get("title", ""), self._format_section_outline(section_outline), code_report = code_report, env_report = env_report)
            except Exception as e:
                self.logger.error(f"Section review failed in OUTER LOOP {i+1} with error {e}. Exiting review and revise loop.")
                continue
            
            if not suggestions or len(suggestions) == 0:
                if (isinstance(suggestions, list) and len(suggestions) == 1 and suggestions[0].lower() == "done"):
                    self.logger.info("Reviewer indicates completion. Exiting.")
                    break
                elif isinstance(suggestions, str) and suggestions.lower() == "done":
                    self.logger.info("Reviewer indicates completion. Exiting.")
                    break
                else:
                    self.logger.info(f"Unexpected reviewer output type: {type(suggestions)} or empty suggestions.")
                    self.logger.info("No suggestions generated. Exiting.")
                    break

            self.logger.info(f"Starting to apply {len(suggestions)} suggestions...")
            for idx, sug in enumerate(suggestions):
                try:
                    new_text = self.revise_section(current_text, sug, section_title=section_outline.get("title", ""), section_outline = self._format_section_outline(section_outline, False), code_report = code_report, env_report = env_report)
                except Exception as e:
                    self.logger.error(f"Section revision failed for suggestion {idx+1} in OUTER LOOP {i+1} with error {e}. Skipping this suggestion.")
                    continue
                
                if new_text != current_text:
                    current_text = new_text
                else:
                    self.logger.info(f"   (Suggestion {idx+1} resulted in no change)")

            for _ in range(self.config.ModuleInfo.SurveyGenerator.no_suggestion_run_each_iteration):
                self.logger.info(f"\n--- step 1.2 NO SUGGESTION LOOP ---")
                try:
                    new_text = self.revise_section(current_text, "", section_title=section_outline.get("title", ""), code_report = code_report, env_report = env_report)
                except Exception as e:
                    self.logger.error(f"Section revision failed for suggestion {idx+1} in OUTER LOOP empty-suggest-modify with error {e}. Skipping this suggestion.")
                    continue
            
            self.logger.info(f"\n--- LOOP {i+1} REVISED FINISH --- \n")
            if self.config.BasicInfo.debug and (i + 1) % 5 == 0:
                self.logger.info(current_text)
            self.logger.info(f"\n--- End of OUTER LOOP {i+1} --- \n")
        if self.config.BasicInfo.debug:
            self.logger.info("\n\n=== Final Result ===")
            self.logger.info(current_text[:30])
        return current_text

    def review_and_revise_survey_in_parts(self, draft, outline, code_report = None, env_report = None):
        if self._evidence_bounded_writing_enabled():
            self.logger.info(
                "Skipping untraced review/revision for evidence-bounded survey writing."
            )
            return draft
        if not self.config.ModuleInfo.SurveyGenerator.enable_review_and_revise:
            self.logger.info("Review and revise module is disabled. Skipping...")
            return draft
        if self.agentic_refine_section:
            original_sections = list(draft.get("section_drafts", []) or [])
            revised_draft = agentic_revise_survey_in_parts(
                self,
                draft,
                outline,
                self.config.ModuleInfo.SurveyGenerator.max_review_revise_iterations,
                code_report,
            )
            revised_draft["section_drafts"] = self._keep_revised_sections_within_budget(
                original_sections,
                revised_draft.get("section_drafts", []) or [],
                outline,
            )
            revised_draft["full_draft"] = (
                outline.get("title", self.config.BasicInfo.topic + " Survey")
                + "\n\n"
                + "\n\n".join(revised_draft["section_drafts"])
            )
            self._ensure_survey_body_within_budget(
                revised_draft["full_draft"], outline, "section review/revision"
            )
            return revised_draft
        sections = draft.get("section_drafts", []) or []
        if len(sections) == 0:
            self.logger.error("No sections found in draft for review and revise.")
            raise ValueError("No sections in draft.")
        
        max_parallel = getattr(self.config.ModuleInfo.SurveyGenerator, 'revise_section_in_parallel', 1)
        
        if max_parallel <= 1:
            revised_sections = []
            for idx, section_text in enumerate(sections):
                self.logger.info(f"\n\n***** Reviewing and Revising Section {idx + 1}/{len(sections)}: {outline.get('sections', [])[idx].get('title', 'No Title')} *****")
                previous_section_text = sections[idx - 1] if idx > 0 else ""
                next_section_text = sections[idx + 1] if idx + 1 < len(sections) else ""
                revised_text = self.review_and_revise_section(
                    section_text,
                    previous_section_text=previous_section_text,
                    next_section_text=next_section_text,
                    section_outline=outline.get('sections', [])[idx],
                    code_report = code_report,
                    env_report = env_report
                )
                revised_sections.append(revised_text)
        else:
            max_parallel = min(max_parallel, len(sections))
            self.logger.info(f"\n\n***** Processing {len(sections)} sections in parallel (max {max_parallel} workers) *****")
            
            def revise_section_with_context(idx):
                section_text = sections[idx]
                self.logger.info(f"Reviewing and Revising Section {idx + 1}/{len(sections)}: {outline.get('sections', [])[idx].get('title', 'No Title')}")
                previous_section_text = sections[idx - 1] if idx > 0 else ""
                next_section_text = sections[idx + 1] if idx + 1 < len(sections) else ""
                
                return self.review_and_revise_section(
                    section_text,
                    previous_section_text=previous_section_text,
                    next_section_text=next_section_text,
                    section_outline=outline.get('sections', [])[idx],
                    code_report = code_report,
                    env_report = env_report
                )
            
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                future_to_idx = {executor.submit(revise_section_with_context, idx): idx for idx in range(len(sections))}
                revised_sections = [None] * len(sections)
                
                for future in tqdm(as_completed(future_to_idx), total=len(sections), desc="Revising sections in parallel", unit="section"):
                    idx = future_to_idx[future]
                    try:
                        revised_sections[idx] = future.result()
                    except Exception as exc:
                        self.logger.error(f"Section {idx} generated an exception: {exc}")
                        revised_sections[idx] = sections[idx]

        # if self.config.BasicInfo.debug:
        #     self.logger.info("\n\n=== Revised Sections ===")
        #     with open("./revised_sections_debug.txt", "w", encoding="utf-8") as f:
        #         for idx, sec in enumerate(revised_sections):
        #             f.write("\n")
        #             f.write(sec)

        revised_sections = self._keep_revised_sections_within_budget(
            sections, revised_sections, outline
        )
        draft['section_drafts'] = revised_sections
        draft["full_draft"] = outline.get("title", self.config.BasicInfo.topic + " Survey") + "\n\n" + "\n\n".join(revised_sections)
        self._ensure_survey_body_within_budget(
            draft["full_draft"], outline, "section review/revision"
        )

        return draft

    def revise_survey(self, survey, outline, suggestion, code_report=None, env_report = None):
        self.logger.info(f"\n--- [Reviser] processing suggestion: {suggestion}... ---")
        valid = False
        retry_feedback = ""
        for retry_time in range(self.config.ModuleInfo.SurveyGenerator.section_revise_retry):
            try:
                if self.config.ModuleInfo.SurveyGenerator.include_env_report and env_report:
                    final_report = f"CODE REPORT: {code_report}\n\nENV REPORT: {env_report}\n\n"
                else:
                    final_report = code_report

                if self.config.ModuleInfo.SurveyGenerator.include_code_report and final_report:
                    additional_context = CODE_REPORT_PROMPT_FOR_SURVEY_REVISER.format(code_report = final_report)
                    self.logger.info(f"injecting code report to survey reviser: {additional_context[:500]}")
                else:
                    additional_context = "None"
                    
                prompt = SURVEY_REVISE.format(
                    topic=self.config.BasicInfo.topic,
                    survey_outline = self._format_survey_outline(outline, False) or "",
                    survey=survey,
                    reviewer_suggestion=suggestion,
                    additional_context = additional_context,
                )
                if retry_feedback:
                    prompt += (
                        "\n\nPrevious attempt was rejected for this reason:\n"
                        f"{retry_feedback}\n"
                        "Return a corrected JSON object that satisfies the output contract."
                    )

                parsed_json = extract_json(
                    self.chat_agent.remote_chat(
                        prompt,
                        temperature=(
                            self.config.ModuleInfo.SurveyGenerator.section_revise_temperature
                            if retry_time == 0 else 0.1
                        ),
                        response_format="json_object",
                    )
                )
                if not isinstance(parsed_json, dict):
                    raise ValueError("Parsed JSON is not a dict.")
                validate_revision_payload(survey, parsed_json)
                valid = True
                break
            except Exception as e:
                retry_feedback = str(e)
                self.logger.error(
                    f"Survey revision attempt {retry_time + 1}/"
                    f"{self.config.ModuleInfo.SurveyGenerator.section_revise_retry} failed "
                    f"using {self.chat_agent.model_name}: {e}"
                )
        
        if not valid:
            self.logger.error("Failed to generate valid revision after retries.")
            raise ValueError("Invalid section revision output.")

        if isinstance(parsed_json, dict):
            if parsed_json.get("action") == "done":
                if self.config.BasicInfo.debug:
                    self.logger.info("   [Reviser] Decided no change needed.")
                return survey
            elif parsed_json.get("action") == "replace":
                if self.config.BasicInfo.debug:
                    self.logger.info("   [Reviser] Applying revision...")
                return self._apply_revision_to_text(survey, parsed_json)
        else:
            raise ValueError("Parsed revision JSON is not a dict.")
        return survey
    
    def _format_survey_outline(self, outline, include_description = True):
        text = ""
        for section_outline in outline.get("sections"):
            text += f"- Section title: {section_outline.get('title', '')}\n"
            if include_description:
                text += f"  Section description: {section_outline.get('description', '')}\n"
            for subsection in section_outline.get("subsections", []):
                text += f"  - Subsection title: {subsection.get('title', '')}\n"
                if include_description:
                    text += f"    Subsection description: {subsection.get('description', '')}\n"
        return text

    def review_survey(self, survey, survey_outline = None, code_report=None, env_report = None):
        self.logger.info("\n--- [Reviewer] analyzing text... ---")
        if self.config.ModuleInfo.SurveyGenerator.include_env_report and env_report:
            final_report = f"CODE REPORT: {code_report}\n\nENV REPORT: {env_report}\n\n"
        else:
            final_report = code_report
        if self.config.ModuleInfo.SurveyGenerator.include_code_report and final_report:
            additional_context = CODE_REPORT_PROMPT_FOR_SURVEY_REVIEWER.format(code_report = final_report)
            self.logger.info(f"injecting code report to survey reviewer: {additional_context[:1500]}")
        else:
            additional_context = "None"

        review_prompt = SURVEY_REVIEW.format(
            topic = self.config.BasicInfo.topic,
            survey=survey,
            survey_outline = self._format_survey_outline(survey_outline, False),
            additional_context = additional_context,
        )
        valid = False
        for _ in range(self.config.ModuleInfo.SurveyGenerator.section_review_retry):
            try:
                suggestions = extract_json(
                    self.chat_agent.remote_chat(
                        review_prompt,
                        temperature=self.config.ModuleInfo.SurveyGenerator.section_review_temperature,
                    )
                )
                valid = True
                break
            except Exception as e:
                self.logger.error(f"Section review failed with error {e}. Retrying...")
                continue

        if valid:
            print(f"   [Reviewer] Generated {len(suggestions)} suggestions.")
            return suggestions
        else:
            print("   [Reviewer] Failed to generate valid list.")
            raise ValueError("Invalid section review output.")

    def review_and_revise_survey(self, survey, outline, code_report=None, env_report = None):
        if self._evidence_bounded_writing_enabled():
            self.logger.info(
                "Skipping untraced whole-survey review/revision for evidence-bounded writing."
            )
            return survey
        MAX_WHOLE_SURVEY_ITERATION = self.config.ModuleInfo.SurveyGenerator.review_and_revise_whole_survey_max_iteration
        if self.agentic_refine_survey:
            return agentic_revise_survey_whole(self, survey, outline, MAX_WHOLE_SURVEY_ITERATION, code_report)
        for i in range(MAX_WHOLE_SURVEY_ITERATION):
            self.logger.info(f"\n\n====== step 2 revise whole survey: OUTER LOOP {i+1}/{MAX_WHOLE_SURVEY_ITERATION} ======")
            
            try:
                suggestions = self.review_survey(survey, outline, code_report=code_report, env_report = env_report)
            except Exception as e:
                self.logger.error(f"Survey review failed in OUTER LOOP {i+1} with error {e}. Exiting review and revise loop.")
                continue
            
            suggestions = suggestions[:self.config.ModuleInfo.SurveyGenerator.reviewer_max_suggestions]
            if not suggestions or len(suggestions) == 0:
                if (isinstance(suggestions, list) and len(suggestions) == 1 and suggestions[0].lower() == "done"):
                    self.logger.info("Reviewer indicates completion. Exiting.")
                    break
                elif isinstance(suggestions, str) and suggestions.lower() == "done":
                    self.logger.info("Reviewer indicates completion. Exiting.")
                    break
                else:
                    self.logger.info(f"Unexpected reviewer output type: {type(suggestions)} or empty suggestions.")
                    self.logger.info("No suggestions generated. Exiting.")
                    break

            self.logger.info(f"Starting to apply {len(suggestions)} suggestions...")
            for idx, sug in enumerate(suggestions):
                try:
                    new_survey = self.revise_survey(survey, outline, sug, code_report=code_report, env_report = env_report)
                except Exception as e:
                    self.logger.error(f"Section revision failed for suggestion {idx+1} in OUTER LOOP {i+1} with error {e}. Skipping this suggestion.")
                    continue
                
                if new_survey != survey:
                    survey = new_survey
                else:
                    self.logger.info(f"   (Suggestion {idx+1} resulted in no change)")
            
            self.logger.info(f"\n--- LOOP {i+1} REVISED FINISH --- \n")
            # if self.config.BasicInfo.debug and (i + 1) % 5 == 0:
            #     self.logger.info(survey)
            self.logger.info(f"\n--- End of OUTER LOOP {i+1} --- \n")
        # if self.config.BasicInfo.debug:
        #     self.logger.info("\n\n=== Final Result ===")
        #     self.logger.info(survey)
        return survey



    def _format_full_survey_text_from_drafts(self, draft):
        sections = draft.get("section_drafts", []) or []

        def _parse_heading(line: str):
            """Return cleaned title if the line looks like a markdown heading."""
            match = re.match(r"^\s*(#+)\s*(.*?)\s*(#*)\s*$", line)
            if not match:
                return None
            # Drop trailing # and surrounding whitespace to isolate the title text.
            title = re.sub(r"#+$", "", match.group(2) or "").strip()
            # Remove any leading numeric index like "1." or "1.2" that may already be present.
            title = re.sub(r"^\d+(?:\.\d+)*\s*[\.|\-|\)]?\s*", "", title)
            return title if title else None

        formatted_sections = []

        for sec_idx, raw_section in enumerate(sections, start=1):
            if self.config.BasicInfo.debug:
                self.logger.info(f"------RAW SECTION {sec_idx}------")
                ## assign section titles
                raw_section = "##" + draft["outline"].get("sections", [])[sec_idx - 1].get("title", "") + "\n" + raw_section
                self.logger.info(raw_section)
                self.logger.info("----------------------------------")
            lines = (raw_section or "").splitlines()
            new_lines: list[str] = []
            saw_section_heading = False
            sub_idx = 0
            last_added_heading = None  # Track the last added heading to detect duplicates

            for line in lines:
                # if self.config.BasicInfo.debug:
                #     self.logger.info(f"ORIGINAL LINE: {line}")
                title = _parse_heading(line)
                if title:
                    if not saw_section_heading:
                        saw_section_heading = True
                        outline_title = draft["outline"].get("sections", [])[sec_idx - 1].get("title", "")
                        if self.config.BasicInfo.debug:
                            self.logger.info(f"outline title: {outline_title} - title: {title}")
                        if outline_title != "" and outline_title != title:
                            self.logger.warning("section title not same! use outline result")
                            title = outline_title
                        new_lines.append(f"## {sec_idx}. {title}")
                        last_added_heading = ("section", sec_idx, title)
                        if self.config.BasicInfo.debug:
                            self.logger.info(f"Extract Section Title: ## {sec_idx}. {title}")
                    else:
                        # Check for duplicate subsection title (exact match)
                        is_duplicate = False
                        
                        if last_added_heading and last_added_heading[0] == "subsection":
                            if title == last_added_heading[2]:
                                is_duplicate = True
                                if self.config.BasicInfo.debug:
                                    self.logger.info(f"Skipping duplicate subsection title: {title}")
                        
                        if not is_duplicate:
                            sub_idx += 1
                            new_lines.append(f"### {sec_idx}.{sub_idx}. {title}")
                            last_added_heading = ("subsection", sec_idx, title)
                            if self.config.BasicInfo.debug:
                                self.logger.info(f"Extract Subsection {sub_idx} Title: ### {sec_idx}.{sub_idx}. {title}")
                        # If duplicate, skip adding this heading but still track it
                    continue

                new_lines.append(line)
                # Reset last_added_heading when we add content (not a heading)
                last_added_heading = None

            # Post-process to add blank lines before subsection headings for better readability
            final_lines: list[str] = []
            for i, line in enumerate(new_lines):
                # Check if this line is a subsection heading (starts with ###)
                if re.match(r'^\s*###\s+\d+\.\d+', line):
                    # Add a blank line before subsection heading if not already present
                    if final_lines and final_lines[-1].strip() != '':
                        final_lines.append('')
                final_lines.append(line)
            new_lines = final_lines

            if not saw_section_heading:
                # Fallback: treat the first non-empty line as the section title; everything else stays as content.
                self.logger.warning(f"No section heading found in section {sec_idx}, using fallback title.")
                fallback_title = f"Section {sec_idx}"
                for idx, line in enumerate(new_lines):
                    if line.strip():
                        fallback_title = re.sub(r"#+$", "", line).strip("# ") or fallback_title
                        new_lines.pop(idx)
                        break
                new_lines.insert(0, f"## {sec_idx}. {fallback_title}\n")

            formatted_sections.append("\n".join(new_lines).strip())

        return f"# {draft.get('title', self.config.BasicInfo.topic + ' Survey')}" + "\n\n" +"\n\n".join(formatted_sections)

    def _validate_refinement_result(self, result: str, info_dict: dict = None) -> tuple:
        """Validation function for refinement results. Checks if result is non-empty and not an error message."""
        if result is None:
            raise ValueError("Result is None")
        if not isinstance(result, str):
            raise ValueError(f"Result is not a string, got {type(result)}")
        if len(result.strip()) == 0:
            raise ValueError("Result is empty")
        # Check if the result looks like an error/explanation instead of refined content
        result_lower = result.strip().lower()
        if result_lower.startswith("the draft text is empty") or result_lower.startswith("the user wants me to refine"):
            raise ValueError(f"Result appears to be an explanation rather than refined content: {result[:100]}...")
        return True, result

    def _finalize_evidence_bounded_draft(self, draft):
        """Format citations without permitting an untraced whole-survey rewrite."""

        survey = self._format_full_survey_text_from_drafts(draft)
        self._ensure_survey_body_within_budget(
            survey, draft.get("outline"), "evidence-bounded finalization"
        )
        survey, references, _correct_titles, _err_titles = self.extract_and_process_citations(
            survey
        )
        reference_text = "References:\n"
        for index, paper_id in tqdm(enumerate(references)):
            try:
                reference_text += f"{index + 1}. {self.work_analyzer.generate_mla(paper_id)}\n"
            except Exception as exc:
                self.logger.error(
                    "Failed to generate reference for evidence-bounded paper %s: %s",
                    paper_id,
                    exc,
                )
                reference_text += f"{index + 1}. unknown citation\n"
        return survey + "\n\n" + reference_text, references

    def refine_draft(self, draft, code_report = None, env_report = None):
        if self._evidence_bounded_writing_enabled():
            self.logger.info(
                "Running non-blocking, citation-preserving quality review for "
                "evidence-bounded sections before finalization."
            )
            draft = self._improve_evidence_bounded_sections(draft)
            return self._finalize_evidence_bounded_draft(draft)
        # Optional: first refine each section independently with local context, keeping <title> citations.
        draft_text = draft["full_draft"]
        for section in draft.get("section_drafts", []) or []:
            if self.config.BasicInfo.debug:
                self.logger.info(f"OUTLINEDEBUG: Section draft before refinement: \n\n {section}\n")
                self.logger.info(f"Section draft word count: {len(section.split())}\n")
        if self.refine_in_parts:
            sections = draft.get("section_drafts", []) or []
            if self.refine_in_parts_mode == 0: # no refinement
                refined_sections = sections
            if self.refine_in_parts_mode == 1: # trivial refinement: can modify subsection title
                refined_sections = []
                for idx, section_text in enumerate(sections):
                    prev_text = sections[idx - 1] if idx > 0 else ""
                    next_text = sections[idx + 1] if idx + 1 < len(sections) else ""
                    part_prompt = DRAFT_REFINEMENT_IN_PARTS.format(
                        title = draft["outline"]["sections"][idx].get("title", ""),
                        previous_text=prev_text,
                        next_text=next_text,
                        draft_text=section_text
                    )
                    part_raw = None
                    for retry_time in range(5):
                        try:
                            part_raw = self.chat_agent.remote_chat(
                                part_prompt,
                                temperature=self.config.ModuleInfo.SurveyGenerator.draft_refinement_temperature,
                            )
                            break
                        except Exception as e:
                            self.logger.error(
                                f"Section {idx} refinement failed on retry {retry_time} with error: {e}. Retrying..."
                            )
                            continue
                    if part_raw is None:
                        raise RuntimeError(
                            f"Section {idx} refinement failed after all retries."
                        )
                    refined_sections.append(
                        part_raw
                    )
            if self.refine_in_parts_mode == 2: # advanced refinement: refinement in subsection unit
                subsection_pattern = re.compile(r"(####\s*(.+?))\n", re.IGNORECASE)

                # Split each section into (preamble, [(heading, body), ...])
                # preamble = text before the first #### — kept as-is, NOT refined
                all_section_preambles: list[str] = []
                all_section_chunks: list[list[tuple[str, str]]] = []  # per section: [(heading, body), ...]
                for sec_idx, section_text in enumerate(sections):
                    self.logger.info(f"[REFINE SPLIT DEBUG]: orginal text: \n{section_text}\n")
                    parts = subsection_pattern.split(section_text)
                    # parts layout from re.split with 2 groups:
                    # [pre_text, full_match_0, title_0, body_0, full_match_1, title_1, body_1, ...]
                    preamble = parts[0]  # text before first #### — not refined
                    self.logger.info(f"[REFINE SPLIT DEBUG]: preamble: \n{preamble}")
                    chunks: list[tuple[str, str]] = []
                    i = 1
                    while i + 2 <= len(parts):
                        heading = parts[i].rstrip("\n")   # e.g. "#### 2.1 Background"
                        body    = parts[i + 2] if i + 2 < len(parts) else ""
                        self.logger.info(f"[REFINE SPLIT DEBUG]: heading: \n{heading}")
                        self.logger.info(f"[REFINE SPLIT DEBUG]: body: \n{body}\n\n")
                        
                        # Additional check: if body is only whitespace or very short, log it
                        body_stripped = body.strip()
                        if len(body_stripped) < 10:  # Very short body might be problematic
                            self.logger.warning(f"[SPLIT DEBUG] Section {sec_idx} subsection '{heading}' has short body (len={len(body_stripped)}): '{body_stripped[:100]}...'")
                        
                        chunks.append((heading, body))
                        i += 3
                    all_section_preambles.append(preamble)
                    all_section_chunks.append(chunks)

                # Check if fast mode is enabled
                refine_fast_mode = getattr(self.config.ModuleInfo.SurveyGenerator, 'refine_in_parts_fast_mode', True)
                
                if refine_fast_mode:
                    # Fast mode: collect all prompts, batch them together, then reassemble by section
                    self.logger.info(f"[mode=2 fast] Collecting all subsection prompts across all sections...")
                    
                    # Collect all prompts with their section/subsection indices
                    all_prompts: list[str] = []
                    prompt_info: list[tuple[int, int, str, str]] = []  # (sec_idx, chunk_idx, heading, original_body)
                    
                    for sec_idx, chunks in enumerate(all_section_chunks):
                        section_title = draft["outline"]["sections"][sec_idx].get("title", "")
                        prev_section_text = sections[sec_idx - 1] if sec_idx > 0 else all_section_preambles[sec_idx]
                        next_section_text = sections[sec_idx + 1] if sec_idx + 1 < len(sections) else ""
                        
                        for chunk_idx, (heading, body) in enumerate(chunks):
                            # Skip empty body - use original content directly
                            if not body.strip():
                                self.logger.warning(f"[mode=2 fast] Section {sec_idx} subsection '{heading}' has empty body, using original content.")
                                prompt_info.append((sec_idx, chunk_idx, heading, body))
                                all_prompts.append(None)  # Placeholder - will use original body
                                continue
                            
                            prev_body = chunks[chunk_idx - 1][1] if chunk_idx > 0 else prev_section_text
                            next_body = chunks[chunk_idx + 1][1] if chunk_idx + 1 < len(chunks) else next_section_text
                            prompt = DRAFT_REFINEMENT_SUBSECTION_IN_PARTS.format(
                                topic=self.config.BasicInfo.topic,
                                subsection_title=heading,
                                section_title=section_title,
                                previous_text=prev_body,
                                next_text=next_body,
                                draft_text=body,
                            )
                            prompt_info.append((sec_idx, chunk_idx, heading, body))
                            all_prompts.append(prompt)
                    
                    # Separate valid prompts from placeholders
                    valid_prompt_indices = [i for i, p in enumerate(all_prompts) if p is not None]
                    valid_prompts = [all_prompts[i] for i in valid_prompt_indices]
                    
                    if valid_prompts:
                        self.logger.info(f"[mode=2 fast] Batching {len(valid_prompts)} prompts for batch_remote_chat_with_retry...")
                        
                        try:
                            results = self.chat_agent.batch_remote_chat_with_retry(
                                valid_prompts,
                                validate_fn=self._validate_refinement_result,
                                max_retry=self.config.ModuleInfo.SurveyGenerator.draft_refinement_max_retry or 7,
                                desc="[mode=2 fast] Refining all subsections...",
                                temperature=self.config.ModuleInfo.SurveyGenerator.draft_refinement_temperature,
                            )
                        except Exception as e:
                            self.logger.error(f"[mode=2 fast] batch_remote_chat_with_retry failed: {e}. Falling back to original content.")
                            results = [None] * len(valid_prompts)
                        
                        # Map results back to all_prompts indices
                        refined_results = [None] * len(all_prompts)
                        for local_idx, global_idx in enumerate(valid_prompt_indices):
                            refined_results[global_idx] = results[local_idx]
                    else:
                        refined_results = [None] * len(all_prompts)
                    
                    # Reassemble sections from results
                    refined_sections = []
                    for sec_idx, chunks in enumerate(all_section_chunks):
                        if not chunks:
                            self.logger.info(f"[mode=2 fast] Section {sec_idx} has no subsections, keeping as-is.")
                            # for debug
                            self.logger.info(f"[mode=2 fast] Section {sec_idx} has no subsections: {sections[sec_idx]}")
                            refined_sections.append(sections[sec_idx])
                            continue
                        
                        subsections: list[str] = []
                        preamble = all_section_preambles[sec_idx]
                        if preamble:
                            subsections.append(preamble)
                        
                        for chunk_idx, (heading, original_body) in enumerate(chunks):
                            # Find this subsection's result
                            global_idx = None
                            for i, (s_idx, c_idx, h, b) in enumerate(prompt_info):
                                if s_idx == sec_idx and c_idx == chunk_idx:
                                    global_idx = i
                                    break
                            
                            if global_idx is not None and refined_results[global_idx] is not None:
                                refined_body = refined_results[global_idx]
                            else:
                                # Use original body if refinement failed or was skipped
                                refined_body = original_body
                                self.logger.info(f"[mode=2 fast] Section {sec_idx} subsection {chunk_idx} using original body (refinement failed/skipped).")
                            
                            subsections.append(f"{heading}\n{refined_body}")
                        
                        refined_sections.append("\n".join(subsections))
                        self.logger.info(f"[mode=2 fast] Section {sec_idx} reassembled with {len(chunks)} subsections.")
                
                else:
                    # Normal mode: process section by section (original behavior)
                    refined_sections = []
                    for sec_idx, chunks in enumerate(all_section_chunks):
                        section_title = draft["outline"]["sections"][sec_idx].get("title", "")
                        prev_section_text = sections[sec_idx - 1] if sec_idx > 0 else all_section_preambles[sec_idx]
                        next_section_text = sections[sec_idx + 1] if sec_idx + 1 < len(sections) else ""

                        if not chunks:
                            # No subsections found — keep section as-is
                            self.logger.info(f"[mode=2] Section {sec_idx} has no subsections, skipping refinement.")
                            refined_sections.append(sections[sec_idx])
                            continue

                        # Build prompts only for the named subsection chunks (preamble excluded)
                        sec_prompts: list[str] = []
                        sec_chunk_info: list[tuple[str, str]] = []  # (heading, original_body)
                        
                        for chunk_idx, (heading, body) in enumerate(chunks):
                            # Skip empty body - use original content directly
                            if not body.strip():
                                self.logger.info(f"[mode=2] Section {sec_idx} subsection {chunk_idx} has empty body, skipping refinement.")
                                sec_prompts.append(None)  # Placeholder
                                sec_chunk_info.append((heading, body))
                                continue
                            
                            prev_body = chunks[chunk_idx - 1][1] if chunk_idx > 0 else prev_section_text
                            next_body = chunks[chunk_idx + 1][1] if chunk_idx + 1 < len(chunks) else next_section_text
                            prompt = DRAFT_REFINEMENT_SUBSECTION_IN_PARTS.format(
                                topic=self.config.BasicInfo.topic,
                                subsection_title=heading,
                                section_title=section_title,
                                previous_text=prev_body,
                                next_text=next_body,
                                draft_text=body,
                            )
                            sec_prompts.append(prompt)
                            sec_chunk_info.append((heading, body))

                        # Separate valid prompts from placeholders
                        valid_prompt_indices = [i for i, p in enumerate(sec_prompts) if p is not None]
                        valid_prompts = [sec_prompts[i] for i in valid_prompt_indices]
                        
                        if not valid_prompts:
                            # All chunks were empty, use original section
                            self.logger.info(f"[mode=2] Section {sec_idx} all subsections empty, keeping as-is.")
                            refined_sections.append(sections[sec_idx])
                            continue

                        self.logger.info(f"[mode=2] Section {sec_idx}: refining {len(valid_prompts)} subsections via batch_remote_chat_with_retry...")
                        
                        try:
                            results = self.chat_agent.batch_remote_chat_with_retry(
                                valid_prompts,
                                validate_fn=self._validate_refinement_result,
                                max_retry=self.config.ModuleInfo.SurveyGenerator.draft_refinement_max_retry or 5,
                                desc=f"[Section {sec_idx}] Refining subsections...",
                                temperature=self.config.ModuleInfo.SurveyGenerator.draft_refinement_temperature,
                            )
                        except Exception as e:
                            self.logger.error(f"[mode=2] Section {sec_idx} batch_remote_chat_with_retry failed: {e}. Using original content.")
                            results = [None] * len(valid_prompts)
                        
                        # Map results back to all chunk indices
                        refined_bodies: list[str | None] = [None] * len(sec_prompts)
                        for local_idx, global_idx in enumerate(valid_prompt_indices):
                            refined_bodies[global_idx] = results[local_idx]
                        
                        # Fall back to original body for any that failed
                        for idx, (heading, original_body) in enumerate(sec_chunk_info):
                            if refined_bodies[idx] is None:
                                self.logger.warning(f"[mode=2] Section {sec_idx} subsection {idx} refinement failed. Using original body.")
                                refined_bodies[idx] = original_body

                        # Reassemble: preamble (unchanged) + refined subsections
                        subsections: list[str] = []
                        preamble = all_section_preambles[sec_idx]
                        if preamble:
                            subsections.append(preamble)
                        for idx, (heading, _original_body) in enumerate(sec_chunk_info):
                            subsections.append(f"{heading}\n{refined_bodies[idx]}")
                            self.logger.info(f"======= refinement debug for Section {sec_idx} Subsection {idx} #### {heading} =======")
                        refined_sections.append("\n".join(subsections))

            refined_sections = self._keep_revised_sections_within_budget(
                sections, refined_sections, draft.get("outline")
            )
            draft['section_drafts'] = refined_sections

            survey = self._format_full_survey_text_from_drafts(draft)

            if self.config.ModuleInfo.SurveyGenerator.review_and_revise_whole_survey_in_refinement:
                survey = self.review_and_revise_survey(survey, draft["outline"], code_report=code_report, env_report = env_report)

            if len(survey.split()) > self._survey_length_budget(
                draft.get("outline")
            )["survey_max_words"]:
                self.logger.warning(
                    "Discarding overlong whole-survey refinement; restoring the "
                    "section-budgeted draft."
                )
                survey = self._format_full_survey_text_from_drafts(draft)

            self._test_valid_citation_threshold(survey)

            survey, references, correct_titles, err_titles = self.extract_and_process_citations(survey)

            if self.config.BasicInfo.debug:
                self.logger.info(f"correct citationnum {len(correct_titles)}")
                self.logger.info(f"err citationnum {len(err_titles)}")
                self.logger.info(f"valid ratio: {len(correct_titles)/(len(correct_titles)+len(err_titles)) if (len(correct_titles)+len(err_titles))>0 else 0}")

            if self.config.BasicInfo.debug:
                self.logger.info(f"Total unique paper titles in correct format in Draft after refining in parts: {len(set(correct_titles))}")

        else:
            prompt = DRAFT_REFINEMENT.format(draft_text=draft_text)
            output = None
            for retry_time in range(5):
                try:
                    output_raw = self.chat_agent.remote_chat(
                        prompt,
                        temperature=self.config.ModuleInfo.SurveyGenerator.draft_refinement_temperature,
                    )
                    output = extract_json(output_raw)
                    break
                except Exception as e:
                    self.logger.error(
                        f"Draft refinement failed on retry {retry_time} with error: {e}. Retrying..."
                    )
                    continue

            if output is None:
                raise RuntimeError("Draft refinement failed after all retries.")

            survey = output.get("refined_survey", draft_text)

            if self.config.ModuleInfo.SurveyGenerator.review_and_revise_whole_survey_in_refinement:
                survey = self.review_and_revise_survey(survey, draft["outline"], code_report=code_report, env_report = env_report)

            if len(survey.split()) > self._survey_length_budget(
                draft.get("outline")
            )["survey_max_words"]:
                self.logger.warning(
                    "Discarding overlong whole-survey refinement; restoring the "
                    "section-budgeted draft."
                )
                survey = draft_text

            references = output.get("references", [])

        self._ensure_survey_body_within_budget(
            survey, draft.get("outline"), "final refinement"
        )
        self.logger.info(f"Total references found: {len(references)}. Generating...")
        reference = "References:\n"
        for index, paper_id in tqdm(enumerate(references)):
            # self.logger.info(f" Generating reference for paper ID: {paper_id}") # YZY DEBUG
            # if self.use_title_in_draft:
            #     # resolve title to paper id
            #     try:
            #         resolved_paper_id, _, _ = self.database.resolve_title_to_paper_id(paper_id)
            #         paper_id = resolved_paper_id
            #         if self.config.BasicInfo.debug:
            #             self.logger.info(f"Resolved title '{paper_id}' to paper ID '{resolved_paper_id}' in REFERENCE GENERATION.")
            #     except ValueError:
            #         self.logger.error(f"Title '{paper_id}' could not be resolved to a paper ID in REFERENCE GENERATION. Skipping this reference.")
            #         continue
            try:
                reference += f"{index + 1}. {self.work_analyzer.generate_mla(paper_id)}\n"
            except Exception as e:
                self.logger.error(f"Failed to generate reference for paper ID: {paper_id} with error {e}. Skipping this reference.")
                reference += f"{index + 1}. unknown citation\n"

        return survey + "\n\n" + reference, references

    def save_survey(self, final_survey, references):
        save_path = self.config.BasicInfo.save_path
        save_json_path = self.config.BasicInfo.save_json_path
        topic = getattr(self.config.BasicInfo, "topic", "survey")
        research_run_id = str(
            getattr(self.config.BasicInfo, "survey_run_id", "") or ""
        ).strip()
        raw_research_context = getattr(self.config.BasicInfo, "research_context", {})
        raw_subhypothesis_retrieval = getattr(
            self.config.BasicInfo,
            "subhypothesis_retrieval",
            {},
        )
        raw_subhypothesis_decomposition = getattr(
            self.config.BasicInfo,
            "subhypothesis_decomposition",
            {},
        )
        raw_survey_evidence_plan = getattr(self, "survey_evidence_plan", None) or getattr(
            self.config.BasicInfo, "survey_evidence_plan", {}
        )
        raw_claim_traceability = getattr(
            self,
            "survey_claim_traceability_artifact",
            getattr(self.config.BasicInfo, "survey_claim_traceability", {}),
        )
        raw_survey_outline = getattr(
            self,
            "survey_outline_artifact",
            getattr(self.config.BasicInfo, "survey_outline", {}),
        )
        active_collector = getattr(
            getattr(self, "work_analyzer", None), "work_collector", None
        )
        raw_multimodal_evidence = self._survey_runtime_multimodal_evidence(
            active_collector
        )
        try:
            research_context = self._json_compatible(raw_research_context or {})
        except (TypeError, ValueError):
            research_context = {}
        try:
            subhypothesis_retrieval = self._json_compatible(
                raw_subhypothesis_retrieval or {}
            )
        except (TypeError, ValueError):
            subhypothesis_retrieval = {}
        try:
            subhypothesis_decomposition = self._json_compatible(
                raw_subhypothesis_decomposition or {}
            )
        except (TypeError, ValueError):
            subhypothesis_decomposition = {}
        try:
            survey_evidence_plan = self._json_compatible(raw_survey_evidence_plan or {})
        except (TypeError, ValueError):
            survey_evidence_plan = {}
        try:
            claim_traceability = self._json_compatible(raw_claim_traceability or {})
        except (TypeError, ValueError):
            claim_traceability = {}
        try:
            survey_outline = self._json_compatible(raw_survey_outline or {})
        except (TypeError, ValueError):
            survey_outline = {}
        try:
            multimodal_evidence = (
                validate_multimodal_evidence(
                    self._json_compatible(raw_multimodal_evidence)
                )
                if raw_multimodal_evidence
                else None
            )
        except Exception as exc:
            raise ValueError("Survey cannot publish invalid multimodal evidence.") from exc

        if self.config.BasicInfo.debug:
            self.logger.info(f"\n--------------------------")
            self.logger.info(f"final survey:{final_survey}")
            self.logger.info(f"--------------------------\n")
        if self.config.BasicInfo.debug:
            self.logger.info(f"Saving final survey to {save_path}...")
        if self.config.BasicInfo.debug:
            self.logger.info(f"Saving final survey JSON to {save_json_path}...")
        survey_payload = self._json_compatible(
            {
                "topic": topic,
                "topic_slug": os.path.basename(os.path.dirname(save_json_path)),
                "research_run_id": research_run_id
                or os.path.basename(os.path.dirname(save_json_path)),
                "project_domain": {
                    "declared_domain": research_context.get("declared_domain", ""),
                    "domain": research_context.get("domain", ""),
                    "research_domains": research_context.get("research_domains", []),
                    "domain_resolution_source": research_context.get(
                        "domain_resolution_source", ""
                    ),
                    "requires_human_confirmation": bool(
                        research_context.get("requires_human_confirmation")
                    ),
                },
                "research_context": research_context,
                "subhypothesis_decomposition": subhypothesis_decomposition,
                "subhypothesis_retrieval": subhypothesis_retrieval,
                "survey_evidence_plan": survey_evidence_plan,
                "claim_traceability": claim_traceability,
                "survey_outline": survey_outline,
                "paper": final_survey,
                "references": references,
            }
        )
        base_dir = Path(
            str(getattr(self.config.BasicInfo, "base_dir", "") or "")
            or Path(save_json_path).parent
        )

        gap_papers: list[dict[str, Any]] = []
        work_analyzer = getattr(self, "work_analyzer", None)
        reference_graph = getattr(work_analyzer, "reference_graph", None)
        if reference_graph is None:
            reference_graph = getattr(
                getattr(work_analyzer, "work_collector", None),
                "reference_graph",
                None,
            )
        for paper_id in self._as_paper_ids(references)[:40]:
            node = {}
            if reference_graph is not None:
                try:
                    node = dict(reference_graph.nodes.get(paper_id, {}))
                except (AttributeError, TypeError):
                    node = {}
            if node:
                gap_papers.append({"paper_id": paper_id, **node})

        chat_agent = getattr(self, "chat_agent", None)

        def gap_llm_call(prompt: str) -> str:
            try:
                return chat_agent.remote_chat(prompt, temperature=0.1)
            except Exception as exc:
                self.logger.warning(
                    "Gap extraction/adjudication LLM failed; retaining deterministic Gap Ledger only: %s",
                    exc,
                )
                return '{"candidates": [], "decisions": []}'

        publication_arguments = {
            "base_dir": base_dir,
            "topic": topic,
            "survey_run_id": research_run_id or base_dir.name,
            "final_survey": final_survey,
            "survey_payload": survey_payload,
            "survey_outline": survey_outline,
            "project_context": research_context,
            "evidence_plan": survey_evidence_plan,
            "claim_traceability": claim_traceability,
            "gap_llm_call": gap_llm_call if chat_agent is not None else None,
            "gap_papers": gap_papers,
        }
        if multimodal_evidence is not None:
            publication_arguments["multimodal_evidence"] = multimodal_evidence
        publication = publish_survey_run_artifacts(
            **publication_arguments,
        )
        save_path = publication["artifacts"]["survey_markdown"]
        save_json_path = publication["artifacts"]["survey_json"]
        survey_outline_path = Path(publication["artifacts"]["survey_outline"])
        saved_artifacts = {
            "survey_markdown_path": str(Path(save_path)),
            "survey_json_path": str(Path(save_json_path)),
            "survey_outline_path": str(survey_outline_path),
            "output_dir": str(Path(save_path).parent),
            "survey_manifest_path": publication["manifest_path"],
            "survey_manifest_status": publication["status"],
            "survey_gap_ledger_path": publication["gap_ledger_path"],
            "survey_idea_handoff_path": publication["idea_handoff_path"],
        }
        if "multimodal_evidence" in publication["artifacts"]:
            saved_artifacts["multimodal_evidence_path"] = publication["artifacts"][
                "multimodal_evidence"
            ]

        # Visual enhancement is intentionally post-save and fail-open.  The
        # canonical evidence-bounded survey remains available even if a remote
        # image provider or optional visual QA service is unavailable.
        try:
            from modules.survey_visualizer import SurveyVisualizer

            visual_result = SurveyVisualizer(
                self.config,
                self.chat_agent,
                self.logger,
            ).run(
                final_survey,
                survey_path=save_path,
                references=references,
                evidence_plan=survey_evidence_plan,
                outline=getattr(self, "survey_outline_artifact", {}),
                claim_traceability=claim_traceability,
            )
            saved_artifacts["survey_visualization"] = visual_result
        except Exception as exc:
            self.logger.warning(
                "Survey visualisation failed after saving the canonical survey; "
                "continuing without visual companion: %s",
                exc,
            )
            saved_artifacts["survey_visualization"] = {
                "status": "failed_open",
                "error": str(exc),
            }
        return saved_artifacts

    def count_unique_paper_ids(self, text: str) -> int:
        return len(self.get_unique_paper_ids_from_raw(text))

    def count_unique_titles(self, text: str) -> int:
        _, _, titles, _ = self.extract_and_validate_titles_in_text(text)
        unique_titles = set(titles)
        return len(unique_titles)

    def get_unique_paper_ids_from_raw(self, text: str):
        pattern = re.compile(
            r"<Paper ID:\s*([^\s>]+)\s*>"
            r"|\(Paper ID:\s*([^\s\)]+)\s*\)"
            r"|<Paper\s*ID\s*:\s*([^\s>]+)\s*>"
            r"|\(Paper\s*ID\s*([^\s\)]+)\s*\)"
            r"|<Paper\s*([^\s>]+)\s*>"
            r"|\(Paper\s*([^\s\)]+)\s*\)"
            r"|<Paper\s*<\s*([^\s>]+)\s*>\s*>"
            r"|<Paper ID:\s*([^>]+?)\s*>",  # e.g., '<Paper ID: 2408.08464, Paper ID: 2406.09324>'",
            flags=re.IGNORECASE,
        )

        matches = pattern.findall(text or "")
        ids = set()
        ordered_ids = []
        for m in matches:
            raw = next((grp for grp in m if grp), "").strip()
            if not raw:
                continue
            # handle combined forms like "2408.08464, Paper ID: 2406.09324"
            parts = [p.strip() for p in re.split(r",|\band\b", raw) if p.strip()]
            for p in parts:
                # remove leading 'Paper ID:' if present
                p = re.sub(r"^(?i:paper\s*id:?)\s*", "", p).strip()
                if p not in ids:
                    ids.add(p)
                    ordered_ids.append(p)
        return ordered_ids

    @staticmethod
    def _openalex_citation_paper_id(citation_token: Any) -> str:
        """Return a canonical OpenAlex ID when a title citation contains one.

        Title-mode drafting prefers ``<paper title>`` citations, but models
        sometimes emit a permitted OpenAlex identifier as ``<W123>`` or
        ``<Paper ID: W123>``. Treat those forms as IDs rather than attempting a
        title-similarity lookup. Authorization remains the responsibility of
        the existing subsection/section paper-set validation.
        """
        text = str(citation_token or "").strip()
        text = re.sub(r"^(?i:paper\s*id)\s*:\s*", "", text)
        paper_id = canonical_paper_id(text)
        return paper_id if re.fullmatch(r"W\d+", paper_id) else ""

    def extract_and_validate_titles_in_text(self, text: str):
        """Extract titles inside '<...>' and validate each whole bracketed chunk as one citation.
        Splitting by comma risks breaking titles that contain commas, so treat the entire content as a single title.
        """
        if not isinstance(text, str):
            return False, []

        matches = re.findall(r"<([^<>]+)>", text or "")
        err_titles = []
        paper_ids = []
        titles = []

        for raw in matches:
            title = raw.strip()
            if not title:
                continue
            paper_id = self._openalex_citation_paper_id(title)
            if paper_id:
                paper_ids.append(paper_id)
                titles.append(title)
                continue
            try:
                paper_id, matched_title, _ = self.database.resolve_title_to_paper_id(
                                                                title_text = title,
                                                                min_title_similarity = self.config.ModuleInfo.SurveyGenerator.valid_title_min_similarity)
            except ValueError:
                err_titles.append(title)
                if self.config.BasicInfo.debug:
                    self.logger.warning(
                        f"Title '{title}' could not be resolved to a paper ID in VALIDATE TITLES."
                    )
                continue

            # if self.config.BasicInfo.debug:
            #     self.logger.info(
            #         f"Title '{title}' resolved to paper ID '{paper_id}' with matched title '{matched_title}' in VALIDATE TITLES."
            #     )
            paper_ids.append(paper_id)
            titles.append(matched_title)

        return len(err_titles) == 0, paper_ids, titles, err_titles

    def extract_and_process_citations(self, text: str):
        """Normalize citations, order references, and convert to numbered brackets."""
        if not isinstance(text, str):
            self.logger.error("Input text to EXTRACT AND PROCESS CITATIONS is not a string in EXTRACT AND PROCESS CITATIONS.")
            return "", [], [], []

        ordered_paper_ids: list[str] = []
        paper_id_to_index: dict[str, int] = {}
        normalized_parts: list[str] = []
        last_idx = 0

        valid_titles: list[str] = []
        err_titles: list[str] = []

        for match in re.finditer(r"<([^<>]+)>", text):
            normalized_parts.append(text[last_idx:match.start()])
            title = match.group(1).strip()
            last_idx = match.end()
            if not title:
                continue

            paper_id = self._openalex_citation_paper_id(title)
            if paper_id:
                valid_titles.append(title)
            else:
                try:
                    paper_id, _matched_title, _ = self.database.resolve_title_to_paper_id(
                        title_text=title,
                        min_title_similarity=self.config.ModuleInfo.SurveyGenerator.valid_title_min_similarity,
                    )
                    valid_titles.append(title)
                except ValueError:
                    if getattr(self.config, 'AblationInfo', None) and getattr(self.config.AblationInfo, 'survey_generator_disabled', False):
                        self.logger.info(f"Ablation mode: Using title as paper_id for '{title}'")
                        paper_id = title
                    else:
                        err_titles.append(title)
                        if self.config.BasicInfo.debug:
                            self.logger.warning(f"Title '{title}' could not be resolved. Removing citation.")
                        continue

            if paper_id not in paper_id_to_index:
                ordered_paper_ids.append(paper_id)
                paper_id_to_index[paper_id] = len(ordered_paper_ids)

            normalized_parts.append(f"[{paper_id_to_index[paper_id]}]")

        normalized_parts.append(text[last_idx:])
        processed_text = "".join(normalized_parts)

        return processed_text, ordered_paper_ids, valid_titles, err_titles

    def _test_valid_citation_threshold(self, text: str):
        self.logger.info("Testing valid citation thresholds from 0.1-0.9 and test valid ratio...")
        self.logger.info(f"Total extracted titles: {len(re.findall(r'<([^<>]+)>', text))}")
        self.logger.info(f"------------------------------------------------------------")
        threshold = 0.0
        while threshold < 1.0:

            valid_titles: list[str] = []
            err_titles: list[str] = []
            
            for match in re.finditer(r"<([^<>]+)>", text):
                title = match.group(1).strip()
                if not title:
                    continue

                try:
                    paper_id, matched_title, _ = self.database.resolve_title_to_paper_id(
                        title_text=title,
                        min_title_similarity=threshold,
                    )
                    valid_titles.append(title)
                except ValueError:
                    err_titles.append(title)
                    if self.config.BasicInfo.debug:
                        self.logger.warning(f"Title '{title}' could not be resolved. Removing citation.")
                    continue
            valid_ratio = len(valid_titles) / (len(valid_titles) + len(err_titles)) if (len(valid_titles) + len(err_titles)) > 0 else 0
            self.logger.info(f"At threshold {threshold}, valid titles: {len(valid_titles)}, err titles: {len(err_titles)}, valid ratio: {valid_ratio}")
            threshold += 0.1

        self.logger.info(f"------------------------------------------------------------")

        return 
