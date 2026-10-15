from copy import deepcopy
import json
from threading import Barrier

from test_formal_contracts_v2 import formal_plan
from test_definition_evidence_retrieval import resolution
from src.agents.experiment_design_agent.formal_object_registry import (
    adapt_group_delta, build_registry, commit_group_delta, inspect_dependency_graph,
    project_group_context, registry_cache_context, rewrite_record_symbols,
    rewrite_live_references, repair_dependency_cycles,
)
from src.agents.experiment_design_agent.formal_dependency import dependency_ids, related_context_ids
from src.agents.experiment_design_agent.formal_definition_resolver import FormalDefinitionResolver
from src.agents.experiment_design_agent.formal_reasoning_planner import FormalReasoningPlanner
from src.agents.experiment_design_agent.formal_plan_recovery import recover_formal_plan
from src.agents.experiment_design_agent.formal_skeleton_batches import dependency_batch, namespace_skeleton_response


def definition(identifier, symbol="x", **updates):
    record = deepcopy(formal_plan()["definitions"][0])
    record.update(definition_id=identifier, symbol=symbol, expression_latex=f"{symbol} \\in \\mathbb R")
    record.update(updates)
    return record


def request_payload(prompt):
    return json.loads(prompt.split("INPUT_JSON:\n", 1)[1])


def test_equal_objects_merge_and_rewrite_all_consumers():
    base = {"definitions": [definition("D1")]}
    incoming = {"definitions": [definition("local", "cost")],
                "model_relations": [{"relation_id": "R", "statement": "cost is positive",
                                      "depends_on": ["local"], "formal_expression": {"symbol": "cost"}}],
                "proof_attempts": [{"attempt_id": "attempt", "target_id": "P",
                                    "steps": [{"step_id": "S", "premises": ["local"],
                                               "derived_statement": "cost >= 0"}]}]}
    merged, rewritten, redirects = commit_group_delta(base, incoming, group_id="G2")
    assert len(merged["definitions"]) == 1
    assert redirects["local"] == "D1"
    assert merged["model_relations"][0]["depends_on"] == ["D1"]
    assert merged["model_relations"][0]["formal_expression"] == {"symbol": "x"}
    assert rewritten["proof_attempts"][0]["steps"][0]["premises"] == ["D1"]
    assert rewritten["proof_attempts"][0]["steps"][0]["derived_statement"] == "x >= 0"
    assert "local" in merged["object_registry"]["objects"]["D1"]["id_aliases"]


def test_colliding_local_id_does_not_redirect_existing_consumers():
    base = {"definitions": [definition("D1")],
            "model_relations": [{"relation_id": "old", "depends_on": ["D1"]}]}
    incoming = {"definitions": [definition("D1", unit="seconds", statement="A time interval")],
                "model_relations": [{"relation_id": "new", "depends_on": ["D1"]}]}
    merged, _, redirects = commit_group_delta(base, incoming, group_id="G2")
    assert redirects["D1"] == "G2_D1"
    assert merged["model_relations"][0]["depends_on"] == ["D1"]
    assert merged["model_relations"][1]["depends_on"] == ["G2_D1"]
    assert "D1" not in merged["object_registry"]["aliases"]


def test_same_symbol_different_conditions_remain_independent():
    base = {"definitions": [definition("D1", conditions=["large systems"])]}
    merged, _, _ = commit_group_delta(base, {"definitions": [definition("D2", conditions=["small systems"])]}, group_id="G2")
    assert len(merged["definitions"]) == 2
    assert merged["definitions"][0]["conditions"] == ["large systems"]
    assert merged["definitions"][1]["conditions"] == ["small systems"]


def test_global_symbol_rename_preserves_quantifiers_local_bindings_and_audit():
    record = {"quantifiers": [{"symbol": "x"}],
              "conclusion_expression": {"symbol": "x"},
              "predicate_expression": {"symbol": "y"},
              "raw_json": "x y",
              "local_bindings": {"z": {"symbol": "z"}}}
    rewrite_record_symbols(record, {"x": "xx", "y": "yy", "z": "zz"})
    assert record["quantifiers"][0]["symbol"] == "x"
    assert record["conclusion_expression"] == {"symbol": "x"}
    assert record["predicate_expression"] == {"symbol": "yy"}
    assert record["local_bindings"] == {"z": {"symbol": "z"}}
    assert record["raw_json"] == "x y"
    nested = {"formal_expression": {"op": "forall", "symbols": ["x"], "args": [{"symbol": "x"}, {"symbol": "y"}]}}
    rewrite_record_symbols(nested, {"x": "xx", "y": "yy"})
    assert nested["formal_expression"]["args"] == [{"symbol": "x"}, {"symbol": "yy"}]


def test_proof_steps_inherit_target_bound_symbols():
    plan = formal_plan()
    renamed = rewrite_live_references(plan, {}, symbol_renames={"P1": {"x": "y"}})
    assert renamed["proof_attempts"][0]["steps"][0]["derived_statement"] == "x >= 0"


def test_dependency_graph_reports_real_scc_missing_refs_and_affected_targets():
    plan = {"definitions": [definition("D1", depends_on=["D2", "absent"]),
                            definition("D2", depends_on=["D1"])],
            "propositions": [{"proposition_id": "P", "premises": ["D1"]}],
            "proof_attempts": [{"attempt_id": "PR", "target_id": "P",
                                "steps": [{"step_id": "S", "premises": ["unknown_premise"]}]}]}
    diagnostics = inspect_dependency_graph(plan)
    assert diagnostics["cyclic_component_count"] == 1
    assert diagnostics["cyclic_components"] == [["D1", "D2"]]
    assert diagnostics["cycle_paths"] == [["D1", "D2", "D1"]]
    assert diagnostics["missing_definition_reference_count"] == 1
    assert diagnostics["missing_premise_reference_count"] == 1
    assert diagnostics["affected_target_ids"] == ["P"]


def test_related_symbols_do_not_create_structural_dependencies():
    plan = {"schema_version": "formal_reasoning_plan_v2", "definitions": [definition("D1")]}
    record = {"formal_expression": {"symbol": "x"}, "variable_references": ["V1"]}
    assert dependency_ids(record, plan) == set()
    assert related_context_ids(record, plan) == {"D1"}
    record["object_bindings"] = {"x": "D1"}
    assert dependency_ids(record, plan) == {"D1"}
    record = {"quantifiers": [{"symbol": "x"}], "formal_expression": {"symbol": "x"}}
    assert related_context_ids(record, plan) == set()


def test_registry_projection_and_cache_ignore_unrelated_object_updates():
    payload = {"definitions": [definition("D1")]}
    payload["object_registry"] = build_registry(payload)
    before = project_group_context(payload["object_registry"], ["D1"], group_id="G1")
    payload["definitions"].append(definition("D2", "time", unit="seconds"))
    payload["object_registry"] = build_registry(payload)
    after = project_group_context(payload["object_registry"], ["D1"], group_id="G1")
    assert len(after["catalog"]) == 2
    assert registry_cache_context(before) == registry_cache_context(after)
    payload["definitions"][0]["conditions"] = ["new condition"]
    payload["object_registry"] = build_registry(payload)
    changed = project_group_context(payload["object_registry"], ["D1"], group_id="G1")
    assert changed["read_versions"]["D1"] > before["read_versions"]["D1"]


def test_incremental_adapter_and_namespace_are_idempotent():
    response = {"object_delta": {"new_objects": [{"collection": "definitions", "record": definition("SG2_D")}],
                                  "reused_object_ids": ["D1"]}}
    adapted = adapt_group_delta(response)
    assert adapted["definitions"][0]["definition_id"] == "SG2_D"
    once = namespace_skeleton_response(adapted, "SG2", {"D1"})
    assert namespace_skeleton_response(once, "SG2", {"D1"}) == once
    assert once["definitions"][0]["definition_id"] == "SG2_D"


def test_external_dependency_distinguishes_omitted_and_missing():
    payload = {"definitions": [definition("D1", depends_on=["D2", "unknown"]), definition("D2")], "model_relations": []}
    batch = dependency_batch(payload, ["D1"], max_definitions=1)
    external = {item["record_id"]: item for item in batch["external_dependencies"]}
    assert external["D2"]["exists_in_registry"] is True
    assert external["unknown"]["status"] == "missing"


def test_recovery_retains_missing_dependencies_and_propagates_to_target():
    plan = formal_plan()
    plan["definitions"][0]["depends_on"] = ["missing_definition"]
    plan["propositions"][0]["premises"].append("D1")
    recovered = recover_formal_plan(plan)
    assert recovered["definitions"][0]["depends_on"] == ["missing_definition"]
    assert recovered["definitions"][0]["dependency_health"] == "missing"
    assert recovered["object_registry_diagnostics"]["missing_definition_reference_count"] == 1
    assert recovered["object_registry_diagnostics"]["affected_target_ids"] == ["P1"]


def test_bounded_cycle_review_can_repair_or_keep_implicit_draft():
    plan = {"definitions": [definition("D1", depends_on=["D2"]), definition("D2", depends_on=["D1"])]}
    calls = []
    def callback(prompt, **_kwargs):
        request = request_payload(prompt)
        calls.append(request)
        return {"repairs": [{"record_id": "D1", "fields": {"depends_on": []}}]}
    repaired = repair_dependency_cycles(plan, llm_call=callback)
    assert len(calls) == 1
    assert repaired["object_registry_diagnostics"]["cyclic_component_count"] == 0
    kept = repair_dependency_cycles(plan, llm_call=lambda *_args, **_kwargs: {})
    assert kept["object_registry_diagnostics"]["cyclic_component_count"] == 1
    assert kept["definitions"][0]["depends_on"] == ["D2"]


def test_resolver_next_wave_reads_committed_shared_definition(tmp_path):
    seen = []
    variables = {"variables": [{"variable_id": "V1", "name": "shared"},
                                {"variable_id": "V2", "name": "dependent", "depends_on": ["V1"]}]}
    def callback(prompt, **_kwargs):
        request = request_payload(prompt)
        seen.append(request)
        variable_id = request["variable_claim_model"]["variables"][0]["variable_id"]
        if variable_id == "V2":
            records = request["mathematical_object_context"]["full_records"]
            assert any(record.get("definition_id") == "D1" and record.get("definition_status") == "specified" for record in records)
        return resolution(variable_id, "shared" if variable_id == "V1" else "dependent", request["assigned_definition_ids"][variable_id])
    result = FormalDefinitionResolver().resolve({}, {}, variables, {}, llm_call=callback,
                                                settings={"variables_per_group": 1, "max_supplement_rounds": 0})
    assert len(seen) == 2
    assert result["object_registry"]["objects"]["D1"]["owner_group"] == "G1"
    assert result["object_registry"]["objects"]["D2"]["owner_group"] == "G2"


def test_skeleton_parallel_generation_commits_in_group_order_and_updates_next_wave(tmp_path):
    barrier = Barrier(2)
    payload = {"definitions": [definition(f"D{number}", f"x{number}", variable_references=[])
                               for number in range(1, 4)], "model_relations": [], "unknown_items": []}
    contexts = {}
    def callback(prompt, **_kwargs):
        request = request_payload(prompt)
        group = request["mathematical_object_context"]["group_id"]
        contexts[group] = request["mathematical_object_context"]
        if group in {"SG1", "SG2"}:
            barrier.wait(timeout=5)
        return {"assumptions": [{"assumption_id": "A", "statement": group, "status": "candidate_formalization"}]}
    planner = FormalReasoningPlanner()
    result, _ = planner._generate_skeleton_batches({}, {}, {"variables": [], "claims": []}, payload,
                                                    {"evidence_cards": []}, llm_call=callback, logger=None, brief_id="test",
                                                    planner_settings={"skeleton_max_definitions_per_group": 1, "parallel_workers": 2})
    assert [item["assumption_id"] for item in result["assumptions"]] == ["SG1_A", "SG2_A", "SG3_A"]
    assert {item["canonical_id"] for item in contexts["SG3"]["catalog"]} >= {"SG1_A", "SG2_A"}


def test_proof_supporting_objects_share_registry_and_rewrite_step_references():
    plan = formal_plan()
    response = {"definitions": [definition("local", "scalar")],
                "proof_attempts": [{"attempt_id": "PR2", "target_id": "P1",
                                    "steps": [{"step_id": "S2", "premises": ["local"], "derived_statement": "scalar >= 0",
                                               "rule_or_lemma": "Order", "status": "proposed"}], "final_step_id": "S2"}]}
    FormalReasoningPlanner._merge_target_response(plan, response, {"P1"}, group_id="TP1")
    assert len(plan["definitions"]) == 1
    assert plan["proof_attempts"][-1]["steps"][0]["premises"] == ["D1"]
    assert plan["object_registry"]["group_aliases"]["TP1"]["local"] == "D1"


def test_object_bindings_are_rewritten_with_aliases():
    base = {"definitions": [definition("D1")]}
    incoming = {"definitions": [definition("local", "quantity")],
                "model_relations": [{"relation_id": "R", "object_bindings": {"quantity": "local"},
                                      "formal_expression": {"symbol": "quantity"}}]}
    merged, _, _ = commit_group_delta(base, incoming, group_id="G2")
    relation = merged["model_relations"][0]
    assert relation["object_bindings"] == {"x": "D1"}
    assert relation["formal_expression"] == {"symbol": "x"}


def test_explicit_owned_update_changes_existing_identity_and_all_live_users():
    base = formal_plan()
    base["definitions"][0]["audit_refs"] = ["original"]
    base["assumptions"][0]["depends_on"] = ["D1"]
    base["assumptions"][0]["object_bindings"] = {"x": "D1"}
    base["object_registry"] = build_registry(base)
    base["object_registry"]["objects"]["D1"]["owner_group"] = "G1"
    update = definition("D1", "y", audit_refs=["updated"])
    merged, _, _ = commit_group_delta(base, {"object_delta": {"updated_objects": [
        {"collection": "definitions", "record": update},
    ]}}, group_id="G1")
    assert len(merged["definitions"]) == 1
    assert merged["definitions"][0]["symbol"] == "y"
    assert set(merged["definitions"][0]["audit_refs"]) == {"original", "updated"}
    assert merged["assumptions"][0]["object_bindings"] == {"y": "D1"}
    assert merged["assumptions"][0]["predicate_expression"]["args"][0] == {"symbol": "y"}
    assert merged["propositions"][0]["conclusion_expression"]["args"][0] == {"symbol": "x"}
    assert merged["object_registry"]["objects"]["D1"]["symbol_aliases"] == ["x"]


def test_equivalent_merge_preserves_both_audit_refs():
    base = {"definitions": [definition("D1", audit_refs=["first"])]}
    merged, _, _ = commit_group_delta(base, {"definitions": [definition("second", audit_refs=["second"])]}, group_id="G2")
    assert merged["definitions"][0]["audit_refs"] == ["first", "second"]


def test_proposed_alias_merges_existing_records_and_rewrites_global_consumers():
    base = {"definitions": [definition("D1", variable_references=["V1"]),
                            definition("D2", "quantity", variable_references=["V2"])],
            "model_relations": [{"relation_id": "R", "depends_on": ["D2"],
                                  "formal_expression": {"symbol": "quantity"}, "object_bindings": {"quantity": "D2"}}]}
    merged, _, _ = commit_group_delta(base, {"object_delta": {"proposed_aliases": [
        {"alias_id": "D2", "canonical_id": "D1", "reason": "Both variables denote the same mathematical quantity"},
    ]}}, group_id="G2", llm_call=lambda *_args, **_kwargs: {
        "decision": "merge", "reason": "Both variables denote the same mathematical quantity"})
    assert len(merged["definitions"]) == 1
    assert merged["definitions"][0]["variable_references"] == ["V1", "V2"]
    assert merged["model_relations"][0]["depends_on"] == ["D1"]
    assert merged["model_relations"][0]["formal_expression"] == {"symbol": "x"}
    assert merged["model_relations"][0]["object_bindings"] == {"x": "D1"}


def test_pair_review_merges_different_wording_and_is_cached(tmp_path):
    base = {"definitions": [definition("D1")]}
    incoming = {"definitions": [definition("local", statement="A scalar ranging over the reals")]}
    calls = []
    def callback(prompt, **_kwargs):
        request = request_payload(prompt)
        assert len(request["objects"]) == 2
        assert len(request["consumers"]) <= 8
        calls.append(request)
        return {"decision": "merge", "reason": "Equivalent scalar domains"}
    settings = {"enabled": True, "root": str(tmp_path)}
    first, _, _ = commit_group_delta(base, incoming, group_id="G2", llm_call=callback, checkpoint=settings)
    second, _, _ = commit_group_delta(base, incoming, group_id="G2", llm_call=callback, checkpoint=settings)
    assert len(calls) == 1
    assert first["definitions"] == second["definitions"]
    assert len(first["definitions"]) == 1


def test_pair_review_applies_scoped_revision_patch():
    base = {"definitions": [definition("D1")]}
    incoming = {"definitions": [definition("local", statement="An alternative wording")],
                "model_relations": [{"relation_id": "R", "depends_on": ["local"]}]}
    def callback(prompt, **_kwargs):
        pair = request_payload(prompt)
        candidate = pair["objects"][1]["definition_id"]
        return {"decision": "revise", "reason": "Normalize the same scalar definition",
                "patch": {"repairs": [{"record_id": candidate, "fields": {"statement": "A real scalar"}}]}}
    merged, _, _ = commit_group_delta(base, incoming, group_id="G2", llm_call=callback)
    assert len(merged["definitions"]) == 1
    assert merged["model_relations"][0]["depends_on"] == ["D1"]


def test_generation_and_proof_caches_replay_through_registry(tmp_path):
    plan = formal_plan()
    skeleton = deepcopy(plan)
    skeleton["proof_attempts"] = []
    calls = []
    def callback(prompt, **_kwargs):
        calls.append(prompt)
        if "skeleton stage" in prompt:
            return skeleton
        return {"target_results": [{"target_id": "P1", "proof_attempts": plan["proof_attempts"]}]}
    planner = FormalReasoningPlanner()
    settings = {"checkpoint": {"enabled": True, "root": str(tmp_path)}, "cache_identity": {"model": "test"}}
    kwargs = {"formal_inputs": {"definitions": plan["definitions"], "model_relations": [], "unknown_items": []},
              "planner_settings": settings, "llm_call": callback}
    first = planner.plan({}, {}, {"variables": [{"variable_id": "V1"}]}, **kwargs)
    second = planner.plan({}, {}, {"variables": [{"variable_id": "V1"}]}, **kwargs)
    assert len(calls) == 2
    assert first["definitions"] == second["definitions"]
    assert first["proof_attempts"] == second["proof_attempts"]
    assert list(tmp_path.glob("objects/skeleton_group_commits/*.json"))
    commits = list(tmp_path.glob("objects/target_group_commits/*.json"))
    assert commits
    stored = json.loads(commits[0].read_text(encoding="utf-8"))
    assert "D1" in stored["payload"]["read_versions"]
    assert stored["payload"]["proof_attempts"][0]["target_id"] == "P1"


def test_unresolved_cycle_review_is_cached_and_remains_a_draft(tmp_path):
    plan = {"definitions": [definition("D1", depends_on=["D2"]), definition("D2", depends_on=["D1"])]}
    calls = []
    def callback(*_args, **_kwargs):
        calls.append(True)
        return {"repairs": [], "reason": "Keep as an implicit construction to study"}
    settings = {"enabled": True, "root": str(tmp_path)}
    first = repair_dependency_cycles(plan, llm_call=callback, checkpoint=settings)
    second = repair_dependency_cycles(plan, llm_call=callback, checkpoint=settings)
    assert len(calls) == 1
    assert first["definitions"] == second["definitions"]
    assert second["object_registry_diagnostics"]["cyclic_component_count"] == 1


def test_alias_with_incompatible_variables_requires_pair_review():
    base = {"definitions": [definition("D1", variable_references=["V1"]),
                            definition("D2", "y", variable_references=["V2"])]}
    calls = []
    def callback(prompt, **_kwargs):
        calls.append(request_payload(prompt))
        return {"decision": "distinct", "reason": "Variables have different physical meanings"}
    merged, _, _ = commit_group_delta(base, {"proposed_aliases": [
        {"alias_id": "D2", "canonical_id": "D1", "reason": "Similar descriptions"}]}, llm_call=callback)
    assert len(calls) == 1
    assert len(merged["definitions"]) == 2


def test_proof_alias_cannot_remove_protected_target():
    plan = formal_plan()
    plan["forward_derivation"] = {"steps": []}
    second = deepcopy(plan["propositions"][0])
    second["proposition_id"] = "P2"
    plan["propositions"].append(second)
    attempt = deepcopy(plan["proof_attempts"][0])
    attempt.update(attempt_id="PR2", target_id="P2")
    FormalReasoningPlanner._merge_target_response(plan, {
        "proposed_aliases": [{"alias_id": "P2", "canonical_id": "P1", "reason": "Identical statements"}],
        "target_results": [{"target_id": "P2", "proof_attempts": [attempt]}],
    }, {"P2"}, group_id="TP2")
    assert {record["proposition_id"] for record in plan["propositions"]} == {"P1", "P2"}
    assert any(record["target_id"] == "P2" for record in plan["proof_attempts"])


def test_step_diagnostics_inherit_quantifiers_and_local_bindings():
    plan = {"definitions": [definition("D1"), definition("D2", unit="seconds", statement="Time")],
            "propositions": [{"proposition_id": "P", "quantifiers": [{"symbol": "x"}]}],
            "forward_derivation": {"target_proposition_id": "P", "steps": [
                {"step_id": "S1", "local_bindings": {"z": "temporary"}},
                {"step_id": "S2", "symbol_references": ["x", "z"], "derived_expression": {"symbol": "x"}},
            ]}}
    diagnostic = inspect_dependency_graph(plan)
    assert diagnostic["ambiguous_symbol_bindings"] == []
    assert diagnostic["affected_target_ids"] == []
    plan["forward_derivation"]["steps"][1]["premises"] = ["missing"]
    assert inspect_dependency_graph(plan)["affected_target_ids"] == ["P"]


def test_global_assumptions_are_read_and_affect_target_diagnostics():
    plan = {"assumptions": [{"assumption_id": "A", "is_global": True, "depends_on": ["missing"]}],
            "propositions": [{"proposition_id": "P"}]}
    context = project_group_context(build_registry(plan), ["P"])
    assert set(context["read_versions"]) == {"P", "A"}
    assert context["missing_references"] == ["missing"]
    assert inspect_dependency_graph(plan)["affected_target_ids"] == ["P"]


def test_duplicate_symbol_normalization_uses_explicit_binding():
    from src.agents.experiment_design_agent.formal_reconciliation import normalize_duplicate_definitions
    plan = {"definitions": [definition("D1"), definition("D2", unit="seconds", statement="Time")],
            "model_relations": [{"relation_id": "R", "object_bindings": {"x": "D2"},
                                  "formal_expression": {"symbol": "x"}}]}
    result = normalize_duplicate_definitions(plan)
    assert result["model_relations"][0]["formal_expression"] == {"symbol": "x__D2"}
    assert result["model_relations"][0]["object_bindings"] == {"x__D2": "D2"}
    assert not result["model_relations"][0].get("dependency_health")


def test_resolver_delta_is_normalized_once_and_rewrites_expression_refs():
    auxiliary = definition("aux", "t", statement="A time interval", unit="seconds", variable_references=[])
    auxiliary["conditions"] = "t >= 0"
    payload = resolution()
    payload["object_delta"] = {"new_objects": [{"collection": "definitions", "record": auxiliary}]}
    payload["model_relations"] = [{"relation_id": "R", "depends_on": ["aux"],
                                  "object_bindings": {"t": "aux"}, "formal_expression": {"ref": "aux"}}]
    result = FormalDefinitionResolver().resolve({}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=lambda *_args, **_kwargs: payload, settings={"max_supplement_rounds": 0})
    assert {record["definition_id"] for record in result["definitions"]} == {"D1", "G1_aux"}
    assert next(record for record in result["definitions"] if record["definition_id"] == "G1_aux")["conditions"] == ["t >= 0"]
    assert result["model_relations"][0]["object_bindings"] == {"t": "G1_aux"}
    assert result["model_relations"][0]["formal_expression"] == {"ref": "G1_aux"}
    assert result["object_registry_diagnostics"]["missing_premise_reference_count"] == 0
    assert result["object_registry"]["group_aliases"]["G1"]["aux"] == "G1_aux"
    assert adapt_group_delta(adapt_group_delta(payload)) == adapt_group_delta(payload)


def test_bad_operations_preserve_valid_objects():
    incoming = {"definitions": None, "assumptions": [{"assumption_id": "A"}],
                "updated_objects": [{"collection": "definitions", "record": {"definition_id": ["bad"]}}],
                "proposed_aliases": [{"alias_id": "bad", "canonical_id": ["bad"]}]}
    merged, _, _ = commit_group_delta({}, incoming, group_id="G1")
    assert merged["assumptions"][0]["assumption_id"] == "G1_A"
    assert merged["unknown_items"]


def test_resolver_raw_diagnostics_preserve_pre_normalization_duplicate_ids(tmp_path):
    candidate = resolution()
    candidate["definitions"].extend([definition("aux", variable_references=[]),
                                     definition("aux", "t", unit="seconds", variable_references=[])])
    candidate["model_relations"] = [{"relation_id": "R", "depends_on": ["absent"]}]
    arguments = {"settings": {"max_supplement_rounds": 0, "checkpoint": {"enabled": True, "root": str(tmp_path)}}}
    result = FormalDefinitionResolver().resolve({}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=lambda *_args, **_kwargs: candidate, **arguments)
    raw = result["object_registry_audit"][0]["raw_diagnostics"]
    assert raw["duplicate_ids"] == ["aux"]
    assert raw["missing_definition_reference_count"] == 1
    assert raw["missing_definition_references"][0]["missing_id"] == "absent"
    assert raw["supplement_round"] == 0
    assert result["object_registry_diagnostics"]["duplicate_ids"] == []
    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("Cached diagnostics must not require a new LLM response")
    replay = FormalDefinitionResolver().resolve({}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=unexpected_request, **arguments)
    assert replay["object_registry_audit"][0]["raw_group_diagnostics"] == result["object_registry_audit"][0]["raw_group_diagnostics"]


def test_skeleton_cache_reuses_existing_group_after_unrelated_append(tmp_path):
    calls = []
    planner = FormalReasoningPlanner()
    settings = {"checkpoint": {"enabled": True, "root": str(tmp_path)},
                "skeleton_max_definitions_per_group": 1, "parallel_workers": 1}
    def callback(prompt, **_kwargs):
        request = request_payload(prompt)
        calls.append(request["root_ids"])
        return {"assumptions": []}
    inputs = {"definitions": [definition("D1")], "model_relations": [], "unknown_items": []}
    arguments = {"llm_call": callback, "logger": None, "brief_id": "test", "planner_settings": settings}
    planner._generate_skeleton_batches({}, {}, {"variables": [], "claims": []}, inputs,
                                       {"evidence_cards": []}, **arguments)
    inputs["definitions"].append(definition("D2", "y", statement="Independent quantity", variable_references=[]))
    planner._generate_skeleton_batches({}, {}, {"variables": [], "claims": []}, inputs,
                                       {"evidence_cards": []}, **arguments)
    assert calls == [["D1"], ["D2"]]


def test_resolver_raw_diagnostics_recognize_objects_in_global_catalog():
    variables = {"variables": [{"variable_id": "V1"}, {"variable_id": "V2"}]}
    def callback(prompt, **_kwargs):
        request = request_payload(prompt)
        variable_id = request["variable_claim_model"]["variables"][0]["variable_id"]
        candidate = resolution(variable_id, variable_id, request["assigned_definition_ids"][variable_id])
        if variable_id == "V1":
            candidate["definitions"][0]["depends_on"] = ["D2"]
        return candidate
    result = FormalDefinitionResolver().resolve({}, {}, variables, {}, llm_call=callback,
        settings={"variables_per_group": 1, "max_supplement_rounds": 0})
    assert result["object_registry_audit"][0]["raw_diagnostics"]["missing_definition_reference_count"] == 0
    assert result["object_registry_diagnostics"]["missing_definition_reference_count"] == 0


def test_related_context_never_supplies_proof_constraints_or_blocks_target():
    from src.agents.experiment_design_agent.formal_verification import build_verification_task, run_verification_task
    plan = formal_plan()
    plan["assumptions"] = []
    plan["proof_attempts"] = []
    plan["propositions"][0].update(premises=[], variable_references=["V1"])
    plan["definitions"][0].update(conditions=["x > 0"],
        condition_expressions=[{"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]}])
    task = build_verification_task(plan, "P1", "z3")
    assert task["constraints"] == [{"bool": True}]
    assert "D1" in task["input_snapshot"]
    assert run_verification_task(task)["result"] == "failed"
    plan["definitions"][0]["dependency_health"] = "cyclic"
    assert not build_verification_task(plan, "P1", "z3")["blockers"]


def test_pair_revision_cannot_change_protected_target():
    plan = formal_plan()
    plan["propositions"][0]["depends_on"] = ["D1"]
    original = deepcopy(plan["propositions"])
    def callback(*_args, **_kwargs):
        return {"decision": "revise", "reason": "Proposed target change",
                "patch": {"repairs": [{"record_id": "P1", "fields": {"statement": "Different target"}}]}}
    FormalReasoningPlanner._merge_supporting_records(plan,
        {"definitions": [definition("aux", statement="Alternative scalar description")]},
        group_id="TP1", llm_call=callback)
    assert plan["propositions"] == original


def test_conflicting_group_local_aliases_have_no_global_redirect():
    first, _, _ = commit_group_delta({}, {"definitions": [definition("G1_aux", unit="seconds", statement="Time")],
        "local_object_aliases": {"aux": "G1_aux"}}, group_id="G1")
    second, _, _ = commit_group_delta(first,
        {"definitions": [definition("G2_aux", unit="joules", statement="Energy")],
         "local_object_aliases": {"aux": "G2_aux"}}, group_id="G2")
    assert second["object_registry"]["group_aliases"]["G1"]["aux"] == "G1_aux"
    assert second["object_registry"]["group_aliases"]["G2"]["aux"] == "G2_aux"
    assert "aux" not in second["object_registry"]["aliases"]


def test_explicit_lemma_instantiation_is_a_dependency_and_reports_missing():
    plan = {"definitions": [definition("D1")],
            "lemmas": [{"lemma_id": "L", "depends_on": ["D1"]}],
            "propositions": [{"proposition_id": "P", "lemma_instantiations": [{"lemma_id": "L"}]}]}
    assert dependency_ids(plan["propositions"][0], {**plan, "schema_version": "formal_reasoning_plan_v2"}) == {"L"}
    assert set(project_group_context(build_registry(plan), ["P"])["read_versions"]) == {"P", "L", "D1"}
    plan["lemmas"][0]["depends_on"] = ["P"]
    assert inspect_dependency_graph(plan)["cyclic_components"] == [["L", "P"]]
    plan["lemmas"] = []
    diagnostic = inspect_dependency_graph(plan)
    assert diagnostic["missing_premise_references"][0]["missing_id"] == "L"
    assert diagnostic["affected_target_ids"] == ["P"]


def test_explicit_reference_variants_follow_canonical_redirects():
    record = {"conclusion_expression": {"lemma_ref": "old_lemma", "assumption_ref": "old_assumption",
                                        "premise_ref": "old_premise", "definition_ref": "old_definition"},
              "lemma_instantiations": [{"lemma_id": "old_lemma"}]}
    redirects = {"old_lemma": "L", "old_assumption": "A", "old_premise": "P", "old_definition": "D"}
    rewritten = rewrite_live_references(record, redirects)
    from src.agents.experiment_design_agent.formal_dependency import declared_dependencies
    assert declared_dependencies(rewritten) == {"L", "A", "P", "D"}
    assert rewritten["lemma_instantiations"][0]["lemma_id"] == "L"
