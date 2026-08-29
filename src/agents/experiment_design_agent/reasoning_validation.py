"""Local semantic checks for variable, proof, and counterexample artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _required(payload: Mapping[str, Any], keys: Sequence[str], prefix: str) -> list[str]:
    return [f"{prefix}_missing:{key}" for key in keys if key not in payload]


def _unique_ids(records: Sequence[Mapping[str, Any]], key: str, prefix: str) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        identifier = str(record.get(key) or "").strip()
        if not identifier:
            errors.append(f"{prefix}[{index}]_missing:{key}")
        elif identifier in seen:
            errors.append(f"{prefix}_duplicate:{identifier}")
        else:
            seen.add(identifier)
    return errors


def _verified_markers(value: Any, path: str = "$") -> list[str]:
    """Reject execution/proof claims that this design-only layer cannot establish."""

    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if str(key).casefold() in {"status", "validity", "verification_status"}:
                normalized = str(item or "").casefold().strip()
                if normalized in {"verified", "machine_checked", "valid_counterexample", "executed"}:
                    errors.append(f"{item_path}_cannot_claim_{normalized}_in_design_only_mode")
            errors.extend(_verified_markers(item, item_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            errors.extend(_verified_markers(item, f"{path}[{index}]"))
    return errors


_VARIABLE_ROLES = {
    "independent",
    "dependent",
    "control",
    "confounder",
    "moderator",
    "blocking_or_exclusion",
    "formal_parameter",
    "domain_variable",
    "latent_construct",
    "assumption_predicate",
}
_VARIABLE_STATUSES = {
    "candidate_extracted",
    "user_declared",
    "needs_formal_definition",
    "needs_human_input",
    "evidence_backed",
}


def validate_variable_claim_model(payload: Any) -> list[str]:
    model = _mapping(payload)
    errors = _required(model, ("schema_version", "claims", "variables", "unknown_items", "status"), "variable_claim_model")
    if model.get("schema_version") != "variable_claim_model_v1":
        errors.append("variable_claim_model_invalid_schema_version")
    claims = _records(model.get("claims"))
    variables = _records(model.get("variables"))
    errors.extend(_unique_ids(claims, "claim_id", "variable_claim_model.claims"))
    errors.extend(_unique_ids(variables, "variable_id", "variable_claim_model.variables"))
    claim_ids = {str(item.get("claim_id") or "").strip() for item in claims}
    for index, claim in enumerate(claims):
        for key in ("claim_id", "statement", "scope", "assumption_ids", "falsifier_ids", "hypothesis_links", "status"):
            if key not in claim:
                errors.append(f"variable_claim_model.claims[{index}]_missing:{key}")
        for link in list(claim.get("assumption_ids") or []) + list(claim.get("falsifier_ids") or []):
            if not str(link).strip():
                errors.append(f"variable_claim_model.claims[{index}]_contains_empty_reference")
    for index, variable in enumerate(variables):
        for key in (
            "variable_id",
            "name",
            "role",
            "formal_or_empirical",
            "construct",
            "observable",
            "operational_definition",
            "unit_or_domain",
            "hypothesis_links",
            "claim_links",
            "source_path",
            "status",
        ):
            if key not in variable:
                errors.append(f"variable_claim_model.variables[{index}]_missing:{key}")
        if variable.get("role") not in _VARIABLE_ROLES:
            errors.append(f"variable_claim_model.variables[{index}]_invalid_role")
        if variable.get("status") not in _VARIABLE_STATUSES:
            errors.append(f"variable_claim_model.variables[{index}]_invalid_status")
        if not isinstance(variable.get("operational_definition"), Mapping):
            errors.append(f"variable_claim_model.variables[{index}]_operational_definition_not_object")
        if not isinstance(variable.get("unit_or_domain"), Mapping):
            errors.append(f"variable_claim_model.variables[{index}]_unit_or_domain_not_object")
        for link in variable.get("claim_links") or []:
            if str(link).strip() not in claim_ids:
                errors.append(f"variable_claim_model.variables[{index}]_unknown_claim_link:{link}")
    if not isinstance(model.get("unknown_items"), list):
        errors.append("variable_claim_model_unknown_items_not_array")
    return errors


_FORMAL_REASONING_APPLICABILITIES = {
    "formal_theory",
    "empirical_component",
    "not_applicable",
}
_ASSUMPTION_STATUSES = {
    "candidate_formalization",
    "user_declared",
    "needs_human_input",
    "unresolved",
}
_DEFINITION_STATUSES = {
    "candidate_formalization",
    "needs_human_input",
    "unresolved",
}
_DEFINITION_SCHEMA_FIELDS = frozenset(
    {
        "definition_id",
        "symbol",
        "statement",
        "domain",
        "codomain",
        "variable_references",
        "source_path",
        "status",
    }
)
_PROPOSITION_STATUSES = {"candidate_formalization", "unresolved"}
_PROOF_OBLIGATION_STATUSES = {"unresolved", "needs_human_input"}
_DERIVATION_STEP_STATUSES = {"proposed", "unverified", "needs_human_input"}
_FORWARD_DERIVATION_STATUSES = {"unverified", "unresolved", "not_applicable"}
_FORMAL_REASONING_PLAN_STATUSES = {
    "unverified",
    "requires_human_review",
    "not_applicable",
}


def validate_formal_reasoning_plan(
    payload: Any,
    *,
    variable_claim_model: Mapping[str, Any] | None = None,
) -> list[str]:
    plan = _mapping(payload)
    errors = _required(
        plan,
        (
            "schema_version",
            "applicability",
            "assumptions",
            "definitions",
            "propositions",
            "proof_obligations",
            "forward_derivation",
            "unknown_items",
            "status",
        ),
        "formal_reasoning_plan",
    )
    if plan.get("schema_version") != "formal_reasoning_plan_v1":
        errors.append("formal_reasoning_plan_invalid_schema_version")
    if plan.get("applicability") not in _FORMAL_REASONING_APPLICABILITIES:
        errors.append("formal_reasoning_plan_invalid_applicability")
    if plan.get("status") not in _FORMAL_REASONING_PLAN_STATUSES:
        errors.append("formal_reasoning_plan_invalid_status")
    if plan.get("applicability") == "not_applicable":
        if not isinstance(plan.get("unknown_items"), list):
            errors.append("formal_reasoning_plan_unknown_items_not_array")
        return errors
    assumptions = _records(plan.get("assumptions"))
    definitions = _records(plan.get("definitions"))
    propositions = _records(plan.get("propositions"))
    obligations = _records(plan.get("proof_obligations"))
    errors.extend(_unique_ids(assumptions, "assumption_id", "formal_reasoning_plan.assumptions"))
    errors.extend(_unique_ids(definitions, "definition_id", "formal_reasoning_plan.definitions"))
    errors.extend(_unique_ids(propositions, "proposition_id", "formal_reasoning_plan.propositions"))
    errors.extend(_unique_ids(obligations, "obligation_id", "formal_reasoning_plan.proof_obligations"))
    for prefix, records, keys, allowed_statuses in (
        (
            "assumptions",
            assumptions,
            (
                "assumption_id",
                "statement",
                "predicate",
                "scope",
                "satisfaction_test",
                "symbol_references",
                "variable_references",
                "source_path",
                "status",
            ),
            _ASSUMPTION_STATUSES,
        ),
        (
            "definitions",
            definitions,
            (
                "definition_id",
                "symbol",
                "statement",
                "domain",
                "codomain",
                "variable_references",
                "source_path",
                "status",
            ),
            _DEFINITION_STATUSES,
        ),
        (
            "propositions",
            propositions,
            (
                "proposition_id",
                "statement",
                "premises",
                "conclusion",
                "scope",
                "symbol_references",
                "variable_references",
                "status",
            ),
            _PROPOSITION_STATUSES,
        ),
        (
            "proof_obligations",
            obligations,
            (
                "obligation_id",
                "target",
                "dependencies",
                "symbol_references",
                "variable_references",
                "status",
            ),
            _PROOF_OBLIGATION_STATUSES,
        ),
    ):
        for index, record in enumerate(records):
            for key in keys:
                if key not in record:
                    errors.append(f"formal_reasoning_plan.{prefix}[{index}]_missing:{key}")
            if record.get("status") not in allowed_statuses:
                errors.append(f"formal_reasoning_plan.{prefix}[{index}]_invalid_status")
            if prefix == "definitions":
                for field, value in record.items():
                    if (
                        field.endswith("_references")
                        and field not in _DEFINITION_SCHEMA_FIELDS
                        and isinstance(value, list)
                    ):
                        errors.append(
                            f"formal_reasoning_plan.definitions[{index}]_unsupported_reference_array:{field}"
                        )
    derivation = _mapping(plan.get("forward_derivation"))
    errors.extend(
        _required(
            derivation,
            ("steps", "target_proposition_id", "final_conclusion_step", "final_conclusion", "status"),
            "formal_reasoning_plan.forward_derivation",
        )
    )
    if derivation.get("status") not in _FORWARD_DERIVATION_STATUSES:
        errors.append("formal_reasoning_plan.forward_derivation_invalid_status")
    steps = _records(derivation.get("steps"))
    errors.extend(_unique_ids(steps, "step_id", "formal_reasoning_plan.forward_derivation.steps"))
    declared_ids = {
        str(item.get(identifier) or "").strip()
        for records, identifier in (
            (assumptions, "assumption_id"),
            (definitions, "definition_id"),
            (propositions, "proposition_id"),
            (obligations, "obligation_id"),
        )
        for item in records
        if str(item.get(identifier) or "").strip()
    }
    definition_by_symbol: dict[str, Mapping[str, Any]] = {}
    for index, definition in enumerate(definitions):
        symbol = str(definition.get("symbol") or "").strip()
        if not symbol:
            continue
        if symbol in definition_by_symbol:
            errors.append(f"formal_reasoning_plan.definitions_duplicate_symbol:{symbol}")
            continue
        definition_by_symbol[symbol] = definition
    declared_variable_ids: set[str] | None = None
    if variable_claim_model is not None:
        declared_variable_ids = {
            str(item.get("variable_id") or "").strip()
            for item in _records(_mapping(variable_claim_model).get("variables"))
            if str(item.get("variable_id") or "").strip()
        }

    def validate_variable_references(prefix: str, index: int, record: Mapping[str, Any]) -> None:
        references = record.get("variable_references")
        if not isinstance(references, list):
            errors.append(f"formal_reasoning_plan.{prefix}[{index}]_variable_references_not_array")
            return
        if declared_variable_ids is None:
            return
        for variable_id in references:
            normalized = str(variable_id or "").strip()
            if normalized not in declared_variable_ids:
                errors.append(f"formal_reasoning_plan.{prefix}[{index}]_unknown_variable_id:{normalized}")

    def validate_symbol_references(prefix: str, index: int, record: Mapping[str, Any]) -> None:
        references = record.get("symbol_references")
        if not isinstance(references, list):
            errors.append(f"formal_reasoning_plan.{prefix}[{index}]_symbol_references_not_array")
            return
        for symbol in references:
            normalized = str(symbol or "").strip()
            definition = definition_by_symbol.get(normalized)
            if definition is None:
                errors.append(f"formal_reasoning_plan.{prefix}[{index}]_undefined_symbol:{normalized}")
                continue
            if declared_variable_ids is not None and normalized in declared_variable_ids:
                definition_variables = definition.get("variable_references")
                if not isinstance(definition_variables, list) or normalized not in {
                    str(variable_id or "").strip()
                    for variable_id in definition_variables
                }:
                    errors.append(
                        f"formal_reasoning_plan.{prefix}[{index}]_variable_id_symbol_requires_linked_definition:{normalized}"
                    )

    for index, definition in enumerate(definitions):
        validate_variable_references("definitions", index, definition)
    for prefix, records in (
        ("assumptions", assumptions),
        ("propositions", propositions),
        ("proof_obligations", obligations),
    ):
        for index, record in enumerate(records):
            validate_symbol_references(prefix, index, record)
            validate_variable_references(prefix, index, record)
    prior_steps: set[str] = set()
    for index, step in enumerate(steps):
        for key in (
            "step_id",
            "premises",
            "symbol_references",
            "variable_references",
            "rule_or_lemma",
            "derived_statement",
            "status",
        ):
            if key not in step:
                errors.append(f"formal_reasoning_plan.forward_derivation.steps[{index}]_missing:{key}")
        if step.get("status") not in _DERIVATION_STEP_STATUSES:
            errors.append(f"formal_reasoning_plan.forward_derivation.steps[{index}]_invalid_status")
        for premise in step.get("premises") or []:
            premise_id = str(premise).strip()
            if premise_id not in declared_ids and premise_id not in prior_steps:
                errors.append(f"formal_reasoning_plan.forward_derivation.steps[{index}]_unknown_or_future_premise:{premise_id}")
        validate_symbol_references("forward_derivation.steps", index, step)
        validate_variable_references("forward_derivation.steps", index, step)
        step_id = str(step.get("step_id") or "").strip()
        if step_id:
            prior_steps.add(step_id)
    final_step = str(derivation.get("final_conclusion_step") or "").strip()
    if final_step and final_step not in prior_steps:
        errors.append(f"formal_reasoning_plan_forward_final_step_unknown:{final_step}")
    target_proposition_id = str(derivation.get("target_proposition_id") or "").strip()
    proposition_by_id = {
        str(item.get("proposition_id") or "").strip(): item
        for item in propositions
        if str(item.get("proposition_id") or "").strip()
    }
    if target_proposition_id and target_proposition_id not in proposition_by_id:
        errors.append(f"formal_reasoning_plan_target_proposition_unknown:{target_proposition_id}")
    if (
        plan.get("applicability") == "formal_theory"
        and plan.get("status") != "requires_human_review"
        and not propositions
    ):
        errors.append("formal_reasoning_plan_formal_theory_requires_proposition")
    if not isinstance(plan.get("unknown_items"), list):
        errors.append("formal_reasoning_plan_unknown_items_not_array")
    return errors


_COUNTEREXAMPLE_VALIDITIES = {
    "candidate_counterexample",
    "assumptions_not_satisfied",
    "conclusion_not_refuted",
    "boundary_case",
    "unverified",
}


def validate_counterexample_analysis(payload: Any) -> list[str]:
    analysis = _mapping(payload)
    errors = _required(
        analysis,
        (
            "schema_version",
            "applicability",
            "target_claim_id",
            "negated_conclusion",
            "search_domain",
            "candidate_counterexamples",
            "exhaustiveness",
            "status",
            "limitations",
            "unknown_items",
        ),
        "counterexample_analysis",
    )
    if analysis.get("schema_version") != "counterexample_analysis_v1":
        errors.append("counterexample_analysis_invalid_schema_version")
    candidates = _records(analysis.get("candidate_counterexamples"))
    errors.extend(_unique_ids(candidates, "counterexample_id", "counterexample_analysis.candidates"))
    for index, candidate in enumerate(candidates):
        for key in ("counterexample_id", "witness", "assumption_checks", "conclusion_check", "validity", "search_method", "limitations"):
            if key not in candidate:
                errors.append(f"counterexample_analysis.candidates[{index}]_missing:{key}")
        if candidate.get("validity") not in _COUNTEREXAMPLE_VALIDITIES:
            errors.append(f"counterexample_analysis.candidates[{index}]_invalid_validity")
        checks = _records(candidate.get("assumption_checks"))
        errors.extend(_unique_ids(checks, "assumption_id", f"counterexample_analysis.candidates[{index}].assumption_checks"))
        for check_index, check in enumerate(checks):
            for key in ("assumption_id", "check", "result", "evidence"):
                if key not in check:
                    errors.append(f"counterexample_analysis.candidates[{index}].assumption_checks[{check_index}]_missing:{key}")
            if check.get("result") not in {"true", "false", "unknown"}:
                errors.append(f"counterexample_analysis.candidates[{index}].assumption_checks[{check_index}]_invalid_result")
        conclusion_check = _mapping(candidate.get("conclusion_check"))
        for key in ("negated_conclusion", "result", "evidence"):
            if key not in conclusion_check:
                errors.append(f"counterexample_analysis.candidates[{index}].conclusion_check_missing:{key}")
        if conclusion_check.get("result") not in {"true", "false", "unknown"}:
            errors.append(f"counterexample_analysis.candidates[{index}]_invalid_conclusion_result")
        if candidate.get("validity") == "valid_counterexample":
            errors.append(f"counterexample_analysis.candidates[{index}]_cannot_claim_verified_counterexample")
        if candidate.get("validity") == "candidate_counterexample":
            if not checks or any(check.get("result") != "true" for check in checks):
                errors.append(f"counterexample_analysis.candidates[{index}]_candidate_does_not_satisfy_all_assumptions")
            if conclusion_check.get("result") != "true":
                errors.append(f"counterexample_analysis.candidates[{index}]_candidate_does_not_refute_conclusion")
        if (
            candidate.get("validity") == "candidate_counterexample"
            and all(check.get("result") == "true" for check in checks)
            and conclusion_check.get("result") == "true"
        ):
            errors.append(f"counterexample_analysis.candidates[{index}]_must_be_unverified_when_only_proposed")
    if not isinstance(analysis.get("limitations"), list):
        errors.append("counterexample_analysis_limitations_not_array")
    if not isinstance(analysis.get("unknown_items"), list):
        errors.append("counterexample_analysis_unknown_items_not_array")
    exhaustiveness = _mapping(analysis.get("exhaustiveness"))
    if exhaustiveness.get("is_exhaustive") is True:
        errors.append("counterexample_analysis_finite_or_llm_search_cannot_prove_exhaustiveness")
    return errors


def validate_reasoning_artifacts(
    *,
    variable_claim_model: Mapping[str, Any] | None,
    formal_reasoning_plan: Mapping[str, Any] | None,
    counterexample_analysis: Mapping[str, Any] | None,
    design: Mapping[str, Any] | None = None,
    template_composition: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    errors.extend(_verified_markers(variable_claim_model, "variable_claim_model"))
    errors.extend(_verified_markers(formal_reasoning_plan, "formal_reasoning_plan"))
    errors.extend(_verified_markers(counterexample_analysis, "counterexample_analysis"))
    if variable_claim_model is not None:
        errors.extend(validate_variable_claim_model(variable_claim_model))
    if formal_reasoning_plan is not None:
        errors.extend(
            validate_formal_reasoning_plan(
                formal_reasoning_plan,
                variable_claim_model=variable_claim_model,
            )
        )
    if counterexample_analysis is not None:
        errors.extend(validate_counterexample_analysis(counterexample_analysis))
    template = _mapping(template_composition)
    formal = _mapping(formal_reasoning_plan)
    counterexamples = _mapping(counterexample_analysis)
    formal_batch_unavailable = (
        formal.get("applicability") == "formal_theory"
        and formal.get("status") == "requires_human_review"
    )
    if formal.get("applicability") == "formal_theory" and not formal_batch_unavailable:
        propositions = _records(formal.get("propositions"))
        proposition_ids = {
            str(item.get("proposition_id") or "").strip()
            for item in propositions
            if str(item.get("proposition_id") or "").strip()
        }
        target_claim_id = str(counterexamples.get("target_claim_id") or "").strip()
        if target_claim_id not in proposition_ids:
            errors.append("counterexample_analysis_target_claim_must_reference_formal_proposition")
        if counterexamples.get("applicability") == "empirical_consistency":
            errors.append("formal_theorem_and_empirical_consistency_must_remain_separate")
        declared_assumptions = {
            str(item.get("assumption_id") or "").strip()
            for item in _records(formal.get("assumptions"))
            if str(item.get("assumption_id") or "").strip()
        }
        for index, candidate in enumerate(_records(counterexamples.get("candidate_counterexamples"))):
            checked_assumptions = {
                str(item.get("assumption_id") or "").strip()
                for item in _records(candidate.get("assumption_checks"))
            }
            if checked_assumptions != declared_assumptions:
                errors.append(f"counterexample_analysis.candidates[{index}]_must_check_every_declared_assumption")
    if formal.get("applicability") == "empirical_component" and counterexamples.get("applicability") == "formal_theory":
        errors.append("empirical_component_cannot_be_labeled_as_formal_counterexample_analysis")
    research = _mapping(design)
    if design is not None and template.get("template_id") == "mathematics_theory" and template.get("submode") != "physical_validation":
        field_statuses = _mapping(research.get("field_statuses"))
        for field in ("source", "eligibility_criteria", "sample_size_or_power_basis"):
            if field_statuses.get(f"sampling_and_eligibility.{field}") != "not_applicable":
                errors.append(f"formal_theory_sampling_must_be_not_applicable:{field}")
    return errors
