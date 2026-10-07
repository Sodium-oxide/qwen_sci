import json

from src.agents.experiment_design_agent.formal_definition_resolver import FormalDefinitionResolver


def test_compact_definition_wire_format_is_enriched_deterministically():
    def callback(prompt, **_kwargs):
        assert "object_kind" in prompt
        assert "exactly `primitive`" in prompt
        assert "relation `status` must be exactly `candidate_formalization`" in prompt
        assert "`unresolved`; `origin`" in prompt
        assert "verification_readiness" in prompt
        request = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])
        assert "condition_expressions" not in request["definition_fields"]
        assert "depends_on" not in request["definition_fields"]
        assert "verification_readiness" not in request["definition_fields"]
        assert "variable_dependency_registry" not in request["definition_fields"]
        return {
            "wire_format": "formal_definition_wire_v1",
            "schema_version": "formal_definition_resolution_v1",
            "definitions": [{
                "definition_id": "D1",
                "symbol": "x",
                "statement": "A real scalar",
                "object_kind": "primitive",
                "domain": "R",
                "codomain": "R",
                "unit": "dimensionless",
                "origin": "modeling_convention",
                "source_refs": [],
                "variable_references": ["V1"],
                "conditions": [{
                    "text": "x is positive",
                    "formal_expression": {
                        "op": "gt",
                        "args": [{"symbol": "x"}, {"number": "0"}],
                    },
                }],
            }],
            "model_relations": [],
            "unknown_items": [],
        }

    result = FormalDefinitionResolver().resolve(
        {}, {}, {"variables": [{"variable_id": "V1"}]}, {},
        llm_call=callback, settings={"max_supplement_rounds": 0},
    )

    definition = result["definitions"][0]
    assert definition["conditions"] == ["x is positive"]
    assert definition["condition_expressions"][0]["op"] == "gt"
    assert definition["definition_status"] == "specified"
    assert definition["verification_readiness"] == "requires_encoding"
    assert definition["symbol_references"] == []
    assert "wire_format" not in result
    assert result["variable_dependency_registry"][0]["record_id"] == "D1"
