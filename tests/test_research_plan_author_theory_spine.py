from __future__ import annotations

from copy import deepcopy
import json

from src.agents.research_plan_author.authoring_blueprint import (
    argument_ledger_context_for_section,
    build_authoring_argument_ledger,
    build_authoring_blueprint_skeleton,
)
from src.agents.research_plan_author.section_composer import (
    SectionComposer,
    build_section_composer_prompt,
    validate_section_output,
)
from src.agents.research_plan_author.section_router import route_author_sections
from src.agents.research_plan_author.theory_spine import (
    THEORY_SPINE_SCHEMA_VERSION,
    build_theory_spine,
    validate_theory_spine,
)


def _routing(template_family: str = "mathematics_theory") -> dict:
    route_ids = (
        "formal_problem_and_hypotheses",
        "definitions_and_propositions",
        "forward_derivation_and_counterexamples",
        "expected_outcomes",
        "risk_limitations_and_review",
    )
    return {
        "template_family": template_family,
        "routes": [
            {
                "section_id": section_id,
                "title": section_id.replace("_", " ").title(),
                "applicability": "required",
                "allowed_claim_kinds": [],
            }
            for section_id in route_ids
        ],
    }


def _preparation() -> dict:
    return {
        "source_design_id": "theory-design",
        "source_bundle": {
            "author_context": {
                "formal_reasoning": {
                    "definitions": [
                        {
                            "definition_id": "D4",
                            "status": "needs_human_input",
                            "symbol_references": ["C"],
                            "variable_references": ["V6"],
                        }
                    ],
                    "assumptions": [
                        {
                            "assumption_id": "A5",
                            "status": "user_declared",
                            "symbol_references": ["theta"],
                            "variable_references": ["V5"],
                        }
                    ],
                    "propositions": [
                        {
                            "proposition_id": "P2",
                            "status": "candidate_formalization",
                            "symbol_references": ["C"],
                            "variable_references": ["V6"],
                        },
                        {
                            "proposition_id": "P1",
                            "status": "candidate_formalization",
                            "symbol_references": ["theta"],
                            "variable_references": ["V5"],
                        },
                    ],
                    "proof_obligations": [
                        {
                            "obligation_id": "PO2",
                            "status": "unresolved",
                            "symbol_references": ["C"],
                            "variable_references": ["V6"],
                        },
                        {
                            "obligation_id": "PO1",
                            "status": "unresolved",
                            "symbol_references": ["theta"],
                            "variable_references": ["V5"],
                        },
                    ],
                    "forward_derivation": {
                        "steps": [
                            {
                                "step_id": "S2",
                                "status": "unverified",
                                "symbol_references": ["C"],
                                "variable_references": ["V6"],
                            },
                            {
                                "step_id": "S1",
                                "status": "proposed",
                                "symbol_references": ["theta"],
                                "variable_references": ["V5"],
                            },
                        ]
                    },
                },
                "counterexample_analysis": {
                    "target_claim_id": "P2",
                    "candidate_counterexamples": [
                        {"counterexample_id": "CE2", "validity": "assumptions_not_satisfied"},
                        {"counterexample_id": "CE1", "validity": "boundary_case"},
                    ],
                },
                "outcome_branches": [
                    {"branch_id": "partial_or_heterogeneous"},
                    {"branch_id": "uninformative_or_invalid"},
                    {"branch_id": "null_or_contradictory"},
                ],
                "unknown_items": [
                    {"field_path": "proof_obligations.PO1", "status": "needs_human_input"},
                    {"field_path": "definitions.D4", "status": "needs_human_input"},
                ],
            }
        },
    }


def _source_registry() -> dict:
    return {
        "unknown_items": [
            {
                "source_item_id": "unknown-po1",
                "original_item": {"field_path": "proof_obligations.PO1", "status": "needs_human_input"},
            },
            {
                "source_item_id": "unknown-d4",
                "original_item": {"field_path": "definitions.D4", "status": "needs_human_input"},
            },
        ],
        "review_items": [],
    }


def test_theory_spine_is_stable_and_references_only_frozen_records() -> None:
    preparation = _preparation()
    routing = _routing()
    registry = _source_registry()
    spine = build_theory_spine(preparation, routing=routing, source_registry=registry)

    reordered = deepcopy(preparation)
    formal = reordered["source_bundle"]["author_context"]["formal_reasoning"]
    for collection in ("definitions", "assumptions", "propositions", "proof_obligations"):
        formal[collection].reverse()
    formal["forward_derivation"]["steps"].reverse()
    reordered["source_bundle"]["author_context"]["counterexample_analysis"]["candidate_counterexamples"].reverse()
    reordered["source_bundle"]["author_context"]["outcome_branches"].reverse()
    assert spine == build_theory_spine(reordered, routing=routing, source_registry=_source_registry())
    assert spine["schema_version"] == THEORY_SPINE_SCHEMA_VERSION
    assert not validate_theory_spine(spine, preparation=preparation, source_registry=registry)

    formal_ids = {"A5", "D4", "P1", "P2", "PO1", "PO2", "S1", "S2"}
    counterexample_ids = {"CE1", "CE2"}
    outcome_ids = {"partial_or_heterogeneous", "uninformative_or_invalid", "null_or_contradictory"}
    unknown_ids = {"unknown-po1", "unknown-d4"}
    for collection in ("lemma_units", "proof_obligations", "falsifiers", "decision_branches"):
        for unit in spine[collection]:
            assert set(unit.get("source_formal_reference_ids", [])) <= formal_ids
            assert set(unit.get("required_formal_reference_ids", [])) <= formal_ids
            assert set(unit.get("target_formal_reference_ids", [])) <= formal_ids
            assert set(unit.get("source_counterexample_ids", [])) <= counterexample_ids
            assert set(unit.get("source_outcome_branch_ids", [])) <= outcome_ids
            assert set(unit.get("source_unknown_item_ids", [])) <= unknown_ids
    local_ids = {
        *(unit["lemma_id"] for unit in spine["lemma_units"]),
        *(unit["proof_obligation_id"] for unit in spine["proof_obligations"]),
        *(unit["falsifier_id"] for unit in spine["falsifiers"]),
        *(unit["branch_id"] for unit in spine["decision_branches"]),
    }
    assert local_ids.isdisjoint(formal_ids | counterexample_ids | outcome_ids | unknown_ids)
    assert [unit["display_label"] for unit in spine["lemma_units"]] == ["L1", "L2", "L3", "L4"]
    assert [unit["display_label"] for unit in spine["proof_obligations"]] == ["PO1", "PO2"]


def test_theory_spine_turns_missing_inputs_into_procedural_no_information_branches() -> None:
    preparation = _preparation()
    spine = build_theory_spine(preparation, routing=_routing(), source_registry=_source_registry())

    branches = {branch["branch_id"]: branch for branch in spine["decision_branches"]}
    assert branches["TS-BR-D4-NO_INFORMATION"] == {
        "branch_id": "TS-BR-D4-NO_INFORMATION",
        "display_label": "No-information: D4",
        "branch_kind": "no_information",
        "source_formal_reference_ids": ["D4"],
        "source_counterexample_ids": [],
        "source_outcome_branch_ids": ["uninformative_or_invalid"],
        "source_unknown_item_ids": ["unknown-d4"],
        "status": "no_information",
        "conclusion_policy": "withhold_theorem_status_update",
        "next_action": "resolve_or_review_upstream_input",
    }
    assert branches["TS-BR-PO1-NO_INFORMATION"]["source_unknown_item_ids"] == ["unknown-po1"]
    assert {record["classification"] for record in spine["falsifiers"]} == {
        "scope_delimiter",
        "assumptions_not_satisfied",
    }
    assert all(record["classification"] != "would_falsify" for record in spine["falsifiers"])
    assert all(record["source_formal_reference_ids"] for record in spine["proof_obligations"])


def test_theory_spine_integrates_with_blueprint_ledger_without_expanding_non_theory_templates() -> None:
    preparation = _preparation()
    routing = _routing()
    preparation["theory_spine"] = build_theory_spine(
        preparation,
        routing=routing,
        source_registry=_source_registry(),
    )
    blueprint = build_authoring_blueprint_skeleton(preparation, routing)
    ledger = build_authoring_argument_ledger(
        preparation,
        routing=routing,
        source_registry=_source_registry(),
    )
    definitions_context = argument_ledger_context_for_section(
        ledger,
        section_id="definitions_and_propositions",
    )
    assert blueprint["theory_spine"] == preparation["theory_spine"]
    assert definitions_context["theory_spine"]["enabled"] is True
    assert definitions_context["theory_spine"]["proof_obligations"]
    assert definitions_context["theory_spine"]["decision_branches"]

    non_theory = build_theory_spine(preparation, routing=_routing("computational_digital"), source_registry=_source_registry())
    assert non_theory == {
        "schema_version": THEORY_SPINE_SCHEMA_VERSION,
        "template_family": "computational_digital",
        "enabled": False,
        "compiler_status": "not_applicable",
        "lemma_units": [],
        "proof_obligations": [],
        "falsifiers": [],
        "decision_branches": [],
    }


def test_theory_spine_rejects_forged_reverse_references_even_without_unknown_items() -> None:
    preparation = _preparation()
    preparation["source_bundle"]["author_context"]["unknown_items"] = []
    registry = {"unknown_items": [], "review_items": []}
    spine = build_theory_spine(preparation, routing=_routing(), source_registry=registry)
    malformed = deepcopy(spine)
    malformed["lemma_units"][0]["premise_ids"].append("forged-formal")
    malformed["lemma_units"][0]["proof_obligation_ids"].append("forged-local-po")
    malformed["proof_obligations"][0]["related_lemma_ids"].append("forged-local-lemma")
    malformed["decision_branches"][0]["source_unknown_item_ids"] = ["forged-source-item"]
    errors = validate_theory_spine(malformed, preparation=preparation, source_registry=registry)
    assert any("premise_ids contains an unknown formal reference" in error for error in errors)
    assert any("proof_obligation_ids contains an unknown local proof obligation" in error for error in errors)
    assert any("related_lemma_ids contains an unknown local lemma" in error for error in errors)
    assert any("source_unknown_item_ids contains an unknown source item" in error for error in errors)


def test_theory_spine_records_missing_derivation_input_without_blocking_preparation() -> None:
    preparation = _preparation()
    formal = preparation["source_bundle"]["author_context"]["formal_reasoning"]
    formal["propositions"] = []
    formal["forward_derivation"]["steps"] = []
    formal["proof_obligations"] = []
    preparation["source_bundle"]["author_context"]["unknown_items"] = []
    registry = {"unknown_items": [], "review_items": []}

    spine = build_theory_spine(preparation, routing=_routing(), source_registry=registry)

    assert spine["enabled"] is True
    assert spine["compiler_status"] == "no_auditable_lemma_input"
    assert spine["lemma_units"] == []
    assert spine["decision_branches"][-1]["branch_id"] == "TS-BR-MISSING-DERIVATION-INPUT-NO_INFORMATION"
    assert spine["decision_branches"][-1]["conclusion_policy"] == "withhold_theorem_status_update"
    assert not validate_theory_spine(spine, preparation=preparation, source_registry=registry)


def test_theory_routes_consume_compiled_units_in_lemmas_and_decision_matrices() -> None:
    preparation = _preparation()
    preparation["source_bundle"]["author_context"]["provenance"] = {
        "discipline_ids": ["26"],
        "template_id": "mathematics_theory",
    }
    routing = route_author_sections(preparation["source_bundle"]["author_context"])
    registry = _source_registry()
    preparation["theory_spine"] = build_theory_spine(
        preparation,
        routing=routing,
        source_registry=registry,
    )
    blueprint = build_authoring_blueprint_skeleton(preparation, routing)
    blueprint["argument_ledger"] = build_authoring_argument_ledger(
        preparation,
        routing=routing,
        source_registry=registry,
    )
    theory_references_by_section = {
        reference["section_id"]: reference
        for reference in blueprint["argument_ledger"]["theory_spine"]["section_unit_references"]
    }
    blueprint_sections_by_id = {section["section_id"]: section for section in blueprint["sections"]}
    for section_id, section in blueprint_sections_by_id.items():
        section["theory_unit_references"] = deepcopy(theory_references_by_section[section_id])
    routes_by_id = {route["section_id"]: route for route in routing["routes"]}

    def claim(claim_id: str, kind: str, formal_reference_id: str) -> dict:
        return {
            "claim_id": claim_id,
            "claim_kind": kind,
            "statement": "The proposal records a bounded theoretical relation.",
            "qualification": "proposed",
            "source_ids": [],
            "evidence_card_ids": [],
            "survey_anchor_ids": [],
            "formal_reference_ids": [formal_reference_id],
            "outcome_branch_ids": [],
            "citation_keys": [],
        }

    def response_for(route: dict, prompt_payload: dict) -> dict:
        context = prompt_payload["section_argument_context"]["theory_spine"]
        lemma_ids = [record["lemma_id"] for record in context["lemma_units"]]
        proof_ids = [record["proof_obligation_id"] for record in context["proof_obligations"]]
        falsifier_ids = [record["falsifier_id"] for record in context["falsifiers"]]
        branch_ids = [record["branch_id"] for record in context["decision_branches"]]
        section_id = route["section_id"]
        if section_id == "formal_problem_and_hypotheses":
            primary_claim = claim("formal-claim", "formal_proposition", "P1")
            blocks = [
                {"block_id": "domain", "kind": "definition", "text": "The candidate theorem is restricted to the declared domain.", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "premises", "kind": "list", "text": "- Retain the declared premise set.\n- Keep the conclusion conditional.", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "relation", "kind": "equation", "text": r"F = G", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "entry-lemma", "kind": "lemma", "text": "Lemma L1 (Candidate): the stated premise has the proposed role in the theorem entry condition.", "claim_ids": [primary_claim["claim_id"]], "reference_block_ids": ["relation"], "theory_unit_ids": [*lemma_ids, *proof_ids]},
                {"block_id": "candidate", "kind": "proposition", "text": "The candidate conclusion remains unverified until its registered proof obligations close.", "claim_ids": [primary_claim["claim_id"]], "reference_block_ids": ["relation"]},
            ]
        elif section_id == "definitions_and_propositions":
            primary_claim = claim("definition-claim", "formal_definition", "D4")
            blocks = [
                {"block_id": "ledger", "kind": "definition", "text": "The definition ledger retains supplied symbols and their declared status.", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "assumptions", "kind": "list", "text": "- Use each supplied premise only within its stated domain.\n- Route unresolved inputs to their proof obligations.", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "relation", "kind": "equation", "text": r"C \geq C_{\mathrm{threshold}}", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "lemma-registry", "kind": "lemma", "text": "Lemma registry (Candidate): the listed units are audit labels for supplied formal records.", "claim_ids": [primary_claim["claim_id"]], "reference_block_ids": ["relation"], "theory_unit_ids": lemma_ids},
                {"block_id": "obligation", "kind": "proposition", "text": "Each registered proof obligation remains unverified until its required input is available.", "claim_ids": [primary_claim["claim_id"]], "reference_block_ids": ["relation"], "theory_unit_ids": proof_ids},
                {"block_id": "dependency-matrix", "kind": "table", "text": "Dependency | Affected lemma | Status | Branch | Next action\nPO1 | L1 | Unverified | No-information | Resolve the supplied input\nD4 | L2 | Candidate | No-information | Review the definition", "claim_ids": [primary_claim["claim_id"]], "theory_unit_ids": [*proof_ids, *branch_ids]},
            ]
        else:
            primary_claim = claim("derivation-claim", "forward_derivation", "S1")
            counterexample_claim = claim("counterexample-claim", "counterexample_plan", "P2")
            blocks = [
                {"block_id": "setup", "kind": "definition", "text": "The derivation consumes only the supplied candidate premises.", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "premises", "kind": "list", "text": "- Preserve the declared scope.\n- Do not update theorem status when a dependency is unavailable.", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "relation", "kind": "equation", "text": r"\theta \leq 0", "claim_ids": [primary_claim["claim_id"]]},
                {"block_id": "derivation-lemma", "kind": "lemma", "text": "Lemma L3 (Unverified): the supplied derivation step is conditional on its registered premises.", "claim_ids": [primary_claim["claim_id"]], "reference_block_ids": ["relation"], "theory_unit_ids": lemma_ids},
                {"block_id": "obligation", "kind": "proposition", "text": "The derivation remains unverified pending the linked proof obligations.", "claim_ids": [primary_claim["claim_id"]], "reference_block_ids": ["relation"], "theory_unit_ids": proof_ids},
                {"block_id": "falsifier-matrix", "kind": "table", "text": "Target lemma | Classification | No-information condition | Response\nL3 | Scope delimiter | Premise fails | Record the boundary\nL4 | Assumptions not satisfied | PO remains open | Withhold theorem-status update", "claim_ids": [counterexample_claim["claim_id"]], "theory_unit_ids": [*falsifier_ids, *branch_ids]},
            ]
        return {
            "schema_version": "research_plan_section_v1",
            "language": "en",
            "section_id": section_id,
            "title": route["title"],
            "applicability": route["applicability"],
            "blocks": blocks,
            "claim_provenance": [primary_claim] if section_id != "forward_derivation_and_counterexamples" else [primary_claim, counterexample_claim],
            "open_items": [],
            "review_items": [],
        }

    expected_roles = {
        "formal_problem_and_hypotheses": "candidate_theorem_entry",
        "definitions_and_propositions": "theory_control_panel",
        "forward_derivation_and_counterexamples": "derivation_and_falsification",
    }
    for section_id, expected_role in expected_roles.items():
        route = routes_by_id[section_id]
        blueprint_section = blueprint_sections_by_id[section_id]
        prompt = build_section_composer_prompt(preparation, blueprint, route, blueprint_section, registry)
        prompt_payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
        assert route["theory_role"] == expected_role
        assert prompt_payload["theory_writing_role"] == expected_role
        assert prompt_payload["section_argument_context"]["theory_spine"]["enabled"] is True
        assert prompt_payload["theory_artifact_quota"]["theory_spine_enabled"] is True
        candidate = response_for(route, prompt_payload)
        assert validate_section_output(
            candidate,
            route=route,
            blueprint_section=blueprint_section,
            preparation=preparation,
            source_registry=registry,
        ) == []
        section, audit = SectionComposer().compose(
            preparation,
            blueprint=blueprint,
            route=route,
            blueprint_section=blueprint_section,
            source_registry=registry,
            llm_call=lambda _prompt, **_kwargs: deepcopy(candidate),
        )
        assert any(block["kind"] == "lemma" for block in section["blocks"])
        assert audit is None
        foreign_ids = [
            unit_id
            for unit_id in (
                *(unit["lemma_id"] for unit in preparation["theory_spine"]["lemma_units"]),
                *(unit["proof_obligation_id"] for unit in preparation["theory_spine"]["proof_obligations"]),
                *(unit["falsifier_id"] for unit in preparation["theory_spine"]["falsifiers"]),
                *(unit["branch_id"] for unit in preparation["theory_spine"]["decision_branches"]),
            )
            if unit_id not in {
                unit_id
                for field_name in ("lemma_ids", "proof_obligation_ids", "falsifier_ids", "decision_branch_ids")
                for unit_id in blueprint_section["theory_unit_references"][field_name]
            }
        ]
        if foreign_ids:
            out_of_slice = deepcopy(candidate)
            out_of_slice["blocks"][0]["theory_unit_ids"] = [foreign_ids[0]]
            assert any(
                "is not one of" in error
                for error in validate_section_output(
                    out_of_slice,
                    route=route,
                    blueprint_section=blueprint_section,
                    preparation=preparation,
                    source_registry=registry,
                )
            )
        leaked_identifier = deepcopy(candidate)
        leaked_identifier["blocks"][0]["text"] += " TS-L-1"
        normalized, _audit = SectionComposer().compose(
            preparation,
            blueprint=blueprint,
            route=route,
            blueprint_section=blueprint_section,
            source_registry=registry,
            llm_call=lambda _prompt, **_kwargs: deepcopy(leaked_identifier),
        )
        assert "TS-L-1" not in normalized["blocks"][0]["text"]
        assert "L1" in normalized["blocks"][0]["text"]


def test_theory_role_activates_the_quota_for_discipline_31() -> None:
    preparation = _preparation()
    author_context = preparation["source_bundle"]["author_context"]
    author_context["provenance"] = {"discipline_ids": ["31"]}
    author_context["selected_direction"] = {
        "title": "A formal theorem with a counterexample boundary",
        "central_hypothesis": "The proposed derivation has a conditional theorem path.",
    }
    routing = route_author_sections(author_context)
    assert routing["template_family"] == "mathematics_theory"
    preparation["theory_spine"] = build_theory_spine(
        preparation,
        routing=routing,
        source_registry=_source_registry(),
    )
    ledger = build_authoring_argument_ledger(
        preparation,
        routing=routing,
        source_registry=_source_registry(),
    )
    route = next(route for route in routing["routes"] if route["section_id"] == "formal_problem_and_hypotheses")
    references = next(
        reference
        for reference in ledger["theory_spine"]["section_unit_references"]
        if reference["section_id"] == route["section_id"]
    )
    prompt = build_section_composer_prompt(
        preparation,
        {"argument_ledger": ledger},
        route,
        {"theory_unit_references": references},
        {"allowed_source_ids": [], "allowed_survey_anchor_ids": [], "evidence_cards_by_id": {}, "citation_registry": []},
    )
    assert json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])["theory_artifact_quota"] is not None
