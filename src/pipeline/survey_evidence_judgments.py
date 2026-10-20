"""Separate discovery, local support, target validation and ranking judgments.

These are semantic model judgments, not keyword tests. Older responses retain
their score semantics; missing new fields do not become negative findings.
"""

from collections.abc import Mapping


BOUNDARY_VALUES = {
    "discovery_relevance": {"relevant", "irrelevant", "unknown"},
    "local_contribution": {"supported", "identity_only", "none", "unknown"},
    "target_validation": {"direct", "indirect", "not_reported", "unknown"},
    "ranking_evidence": {"sufficient", "insufficient", "not_applicable", "unknown"},
    "exclusion_basis": {"explicit_criterion", "irrelevant", "insufficient_evidence", "none", "unknown"},
}


def normalize_evidence_boundaries(raw, diagnostic=None, **context):
    if raw is not None and not isinstance(raw, Mapping) and diagnostic is not None:
        diagnostic.unresolved("evidence_boundaries", "expected_object", raw, **context)
    raw = raw if isinstance(raw, Mapping) else {}
    result = {key: raw.get(key) if isinstance(raw.get(key), str) and raw[key] in values else "unknown"
              for key, values in BOUNDARY_VALUES.items()}
    if diagnostic is not None:
        for key, values in BOUNDARY_VALUES.items():
            value = raw.get(key)
            if value is not None and (not isinstance(value, str) or value not in values):
                diagnostic.unresolved("evidence_boundaries." + key, "unknown_boundary_status", value, **context)
    gaps = raw.get("validation_gaps", [])
    if isinstance(gaps, str):
        gaps = [gaps]
        if diagnostic is not None:
            diagnostic.recovered("evidence_boundaries.validation_gaps", "string_to_list")
    elif not isinstance(gaps, list) and diagnostic is not None:
        diagnostic.unresolved("evidence_boundaries.validation_gaps", "expected_string_list", gaps, **context)
    result["validation_gaps"] = list(dict.fromkeys(value.strip() for value in gaps
        if isinstance(value, str) and value.strip())) if isinstance(gaps, list) else []
    # An explicit evidence shortage cannot also establish scientific irrelevance.
    if result["exclusion_basis"] == "insufficient_evidence" and result["discovery_relevance"] == "irrelevant":
        result["discovery_relevance"] = "unknown"
    return result


def evidence_boundaries(assessment):
    return normalize_evidence_boundaries(assessment.get("evidence_boundaries"))


def semantic_boundary_fields(assessment):
    """Reconcile a declared evidence shortage without interpreting reason text."""
    if "evidence_boundaries" not in assessment:
        return {}
    boundaries = evidence_boundaries(assessment)
    fields = {"evidence_boundaries": boundaries}
    if boundaries["exclusion_basis"] in {"none", "insufficient_evidence"} and assessment.get("explicit_exclusion_matches"):
        fields.update(explicit_exclusion_matches=[], explicit_exclusion_matches_raw=assessment["explicit_exclusion_matches"])
    if assessment.get("overall_relation") == "irrelevant" and (
        boundaries["discovery_relevance"] == "relevant" or boundaries["exclusion_basis"] == "insufficient_evidence"):
        fields.update(overall_relation="uncertain", overall_relation_raw="irrelevant")
    return fields


def assessment_is_irrelevant(assessment):
    boundaries = evidence_boundaries(assessment)
    if boundaries["exclusion_basis"] == "insufficient_evidence":
        return False
    if boundaries["exclusion_basis"] == "irrelevant":
        return True
    if boundaries["discovery_relevance"] != "unknown":
        return boundaries["discovery_relevance"] == "irrelevant"
    if boundaries["local_contribution"] in {"supported", "identity_only"}:
        return False
    if assessment.get("overall_relation") == "irrelevant":
        return True
    if "evidence_boundaries" in assessment:
        # An unknown structured judgment must not become irrelevance by score.
        return False
    value = assessment.get("semantic_relevance_score")
    return type(value) is int and value <= 1


def assessment_is_excluded(assessment):
    boundaries = evidence_boundaries(assessment)
    if boundaries["exclusion_basis"] in {"none", "insufficient_evidence", "irrelevant"}:
        return False
    return bool(assessment.get("explicit_exclusion_matches"))


def has_local_contribution(assessment, *, threshold=3):
    if assessment.get("assessment_status") != "assessed" or not assessment.get("evidence_spans"):
        return False
    if assessment_is_irrelevant(assessment) or assessment_is_excluded(assessment):
        return False
    local = evidence_boundaries(assessment)["local_contribution"]
    if local != "unknown":
        return local == "supported"
    value = assessment.get("semantic_relevance_score")
    return type(value) is int and value >= threshold


def project_is_excluded(project):
    basis = project.get("exclusion_basis", "unknown")
    if not isinstance(basis, str):
        basis = "unknown"
    if basis in {"none", "insufficient_evidence"}:
        return False
    if basis in {"explicit_criterion", "irrelevant"}:
        return bool(project.get("excluded") or project.get("violated_exclusions"))
    # A legacy declaration with no usable source assessment is unconfirmed.
    if project.get("assessment_status") in {"uncertain", "assessment_unavailable"}:
        return False
    return bool(project.get("excluded") or project.get("violated_exclusions"))


def candidate_discovery_status(item, project_score, sh_score):
    boundaries = evidence_boundaries(item)
    value = 20 * (0.6 * project_score + 0.4 * sh_score)
    if boundaries["discovery_relevance"] == "irrelevant" or boundaries["exclusion_basis"] == "irrelevant":
        return "irrelevant", value
    if ("evidence_boundaries" not in item
        and boundaries["discovery_relevance"] == "unknown"
        and boundaries["exclusion_basis"] != "insufficient_evidence"
        and boundaries["local_contribution"] not in {"supported", "identity_only"}
        and max(project_score, sh_score) <= 1):
        return "irrelevant", value
    # Scores prioritize bounded investigation. They do not prove target efficacy.
    return ("relevant" if value >= 70 else "exploratory"), value


def contribution_failure(assessment):
    if assessment.get("assessment_status") != "assessed":
        return "assessment_unavailable"
    boundaries = evidence_boundaries(assessment)
    if assessment_is_excluded(assessment):
        return "explicit_exclusion"
    if assessment_is_irrelevant(assessment):
        return "irrelevant"
    if not assessment.get("evidence_spans"):
        return "missing_evidence_spans"
    if has_local_contribution(assessment):
        return "local_contribution"
    if boundaries["local_contribution"] == "identity_only":
        return "identity_only"
    if boundaries["local_contribution"] == "none":
        return "no_local_contribution"
    return "insufficient_evidence"


def needs_local_contribution_review(paper, assessment):
    from .source_context import has_source_content

    boundaries = evidence_boundaries(assessment)
    return (assessment.get("assessment_status") == "assessed"
        and boundaries["local_contribution"] in {"none", "identity_only", "unknown"}
        and boundaries["target_validation"] in {"indirect", "not_reported"}
        and not project_is_excluded(paper.get("project_relevance", {}))
        and not assessment_is_excluded(assessment) and not assessment_is_irrelevant(assessment)
        and has_source_content(paper)
        and any(span.get("source") in {"abstract", "source_excerpt"} and span.get("text")
                for span in assessment.get("evidence_spans", []) if isinstance(span, Mapping)))


def failure_guidance(failure):
    guidance = {
        "identity_only": ("broaden_context", ["preserve_candidate_identity", "seek_local_method_or_mechanism_evidence", "use_justified_source_system"]),
        "no_local_contribution": ("broaden_context", ["seek_source_system_contribution", "separate_local_support_from_target_validation", "record_target_validation_condition"]),
        "missing_evidence_spans": ("broaden_context", ["seek_source_evidence", "complete_local_contribution_assessment"]),
        "target_validation_gap": ("broaden_context", ["preserve_candidate_identity", "relax_exact_target_to_source_system", "record_target_validation_condition"]),
        "ranking_evidence_gap": ("compare_alternative", ["preserve_candidate_identity", "seek_comparable_endpoint_or_comparator", "record_unresolved_ranking_requirements"]),
        "insufficient_evidence": ("broaden_context", ["preserve_candidate_identity", "seek_missing_local_contribution", "separate_discovery_from_validation_requirements"]),
        "irrelevant": ("narrow_scope", ["restore_identifying_context", "remove_ambiguous_terms"]),
        "explicit_exclusion": ("narrow_scope", ["respect_explicit_exclusion", "seek_eligible_sources"]),
    }
    action, priorities = guidance[failure]
    return {"reason": failure, "preferred_action": action, "priority_order": priorities,
            "preserve_candidate": failure not in {"irrelevant", "explicit_exclusion"},
            "scientific_absence_established": False}
