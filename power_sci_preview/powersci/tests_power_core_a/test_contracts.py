from __future__ import annotations

from pathlib import Path
import json

import pytest

from power_core_a.errors import ContractValidationError
from power_core_a.schema_registry import SchemaRegistry
from power_core_a.semantic_validation import validate_case_against_equation_ir


FIXTURES = Path(__file__).resolve().parents[1] / "examples_power_core_a" / "b0"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_all_schema_documents_are_valid_draft_2020_12() -> None:
    result = SchemaRegistry().validate_schema_catalog()
    assert result["valid"] is True
    assert result["count"] == 20


@pytest.mark.parametrize(
    ("schema", "filename"),
    [
        ("ResearchBrief", "research_brief.json"),
        ("EquationIR", "equation_ir.json"),
        ("CaseManifest", "case_manifest.json"),
        ("LensSpec", "lens_spec.json"),
        ("ValidationReport", "validation_report.json"),
    ],
)
def test_b0_contract_fixtures_validate(schema: str, filename: str) -> None:
    assert SchemaRegistry().validate(schema, load(filename))["schema_version"]


def test_contracts_reject_unknown_fields() -> None:
    brief = load("research_brief.json")
    brief["arbitrary_payload"] = {}
    with pytest.raises(ContractValidationError, match="Additional properties"):
        SchemaRegistry().validate("ResearchBrief", brief)


def test_equation_ir_rejects_unknown_variable_reference() -> None:
    equation = load("equation_ir.json")
    equation["equations"][0]["residual"]["arguments"][1]["arguments"][1]["variable_id"] = "missing_speed"
    with pytest.raises(ContractValidationError, match="unknown variable_id"):
        SchemaRegistry().validate("EquationIR", equation)


def test_lens_rejects_noncontiguous_transform_order() -> None:
    lens = load("lens_spec.json")
    lens["transforms"][0]["order"] = 2
    with pytest.raises(ContractValidationError, match="contiguous"):
        SchemaRegistry().validate("LensSpec", lens)


def test_validation_pass_cannot_hide_errors() -> None:
    report = load("validation_report.json")
    report["errors"].append(
        {
            "schema_version": "structured_error_v1",
            "code": "STRUCTURE_INVALID",
            "severity": "ERROR",
            "message": "test",
            "field_path": "/equations/0",
            "recoverable": False,
            "origin_module": "M02"
        }
    )
    with pytest.raises(ContractValidationError, match="PASS requires"):
        SchemaRegistry().validate("ValidationReport", report)


def test_case_and_equation_cross_contract_units_must_match() -> None:
    case = load("case_manifest.json")
    equation = load("equation_ir.json")
    case["initial_conditions"][0]["unit"] = "degree"
    with pytest.raises(ContractValidationError, match="unit differs"):
        validate_case_against_equation_ir(case, equation)
