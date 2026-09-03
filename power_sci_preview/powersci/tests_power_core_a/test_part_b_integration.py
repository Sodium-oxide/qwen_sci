from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from power_core_a.errors import ContractValidationError, InvalidStateTransition
from power_core_a.integrations.part_b_adapter import b_candidate_to_contract, build_validation_report_v2
from power_core_a.schema_registry import SchemaRegistry
from power_core_a.validation_workflow import run_part_b_candidate_validation


@dataclass(frozen=True)
class VariableRef:
    name: str
    alias: str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class ParameterRef:
    name: str
    value: float | int | str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class EquationNode:
    kind: str
    lhs: str
    rhs: str
    unit: str | None = None
    expression: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateModel:
    candidate_id: str
    model_name: str
    equations: list[EquationNode]
    variables: list[VariableRef] = field(default_factory=list)
    parameters: list[ParameterRef] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    target: str | None = None
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    model_name: str
    passed: bool
    stage: str
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def _b_candidate() -> CandidateModel:
    return CandidateModel(
        candidate_id="smib-known-001", model_name="SMIB classical model",
        variables=[
            VariableRef("delta", unit="rad"), VariableRef("omega", unit="pu"),
            VariableRef("Pm", unit="pu"), VariableRef("Pe", unit="pu"),
        ],
        parameters=[
            ParameterRef("H", 3.5, "s"), ParameterRef("D", 0.1, "pu"),
            ParameterRef("omega_b", 377.0, "rad/s"),
        ],
        equations=[
            EquationNode("ode", "d(delta)/dt", "omega_b * (omega - 1)", "rad/s"),
            EquationNode("ode", "d(omega)/dt", "(Pm - Pe - D*(omega - 1))/(2*H)", "pu/s"),
            EquationNode("algebraic", "0", "Pe - Pm", "pu"),
        ],
    )


def _semantics() -> dict:
    return {
        "delta": {"coordinate": "rotor_angle", "reference_mode": "ABSOLUTE", "nominal_value": 0.0},
        "omega": {"coordinate": "rotor_speed", "reference_mode": "ABSOLUTE", "nominal_value": 1.0},
        "Pm": {"coordinate": "generator_power", "reference_mode": "NOT_APPLICABLE"},
        "Pe": {"coordinate": "generator_power", "reference_mode": "NOT_APPLICABLE"},
    }


def _contract() -> dict:
    return b_candidate_to_contract(
        _b_candidate(), variable_semantics=_semantics(), source="KNOWN_STRUCTURE_FIT",
        created_at="2026-08-26T08:00:00Z", producer="M10",
        fit_metadata={"method": "known-structure-fit", "random_seed": 7},
    )


def _fixture(name: str) -> dict:
    path = Path(__file__).parents[1] / "examples_power_core_a" / "b0" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_b_candidate_boundary_requires_explicit_speed_reference() -> None:
    semantics = _semantics()
    del semantics["omega"]
    with pytest.raises(ContractValidationError, match="omega"):
        b_candidate_to_contract(
            _b_candidate(), variable_semantics=semantics, source="KNOWN_STRUCTURE_FIT",
            created_at="2026-08-26T08:00:00Z",
        )


def test_physical_failure_is_a_structured_v3_hard_reject() -> None:
    raw = ValidationReport(
        model_name="SMIB classical model", passed=False, stage="physical",
        errors=[ValidationError("POWER_BALANCE_VIOLATION", "power mismatch", "eq-003", {"mismatch": 0.2})],
        metrics={"power_balance_error": 0.2},
    )
    report = build_validation_report_v2(
        raw, run_id="run-smib-001", candidate_contract=_contract(),
        case_manifest=_fixture("case_manifest.json"), lens_spec=_fixture("lens_spec.json"),
        created_at="2026-08-26T08:00:00Z",
    )
    assert report["verdict"] == "HARD_REJECT"
    assert [row["status"] for row in report["checks"]] == ["PASS", "NOT_RUN", "FAIL"]
    assert report["errors"][0]["code"] == "POWER_BALANCE_VIOLATION"


def test_workflow_builds_real_b_objects_and_resumes_without_second_call(tmp_path: Path) -> None:
    calls = {"count": 0}

    def validate_candidate_model(candidate, **kwargs):
        calls["count"] += 1
        assert isinstance(candidate, CandidateModel)
        assert candidate.variables[1].name == "omega"
        assert candidate.metadata == {}
        return ValidationReport(candidate.model_name, True, "physical", metrics={"power_balance_error": 0.0})

    api = SimpleNamespace(
        VariableRef=VariableRef, ParameterRef=ParameterRef, EquationNode=EquationNode,
        CandidateModel=CandidateModel, validate_candidate_model=validate_candidate_model,
        __version__="test-double-for-part-b-2026-08-26",
    )
    kwargs = dict(
        store_root=tmp_path / "store", run_id="run-smib-001", current_state="PROTOCOL_FROZEN",
        candidate_contract=_contract(), case_manifest=_fixture("case_manifest.json"),
        lens_spec=_fixture("lens_spec.json"), part_b_api=api, created_at="2026-08-26T08:00:00Z",
    )
    first = run_part_b_candidate_validation(**kwargs)
    second = run_part_b_candidate_validation(**kwargs)
    assert first["verdict"] == "PASS"
    assert first["resumed"] is False and second["resumed"] is True
    assert calls["count"] == 1
    payload = json.loads((tmp_path / "store" / first["validation_report"]["relative_path"]).read_text(encoding="utf-8"))
    SchemaRegistry().validate("ValidationReportV2", payload)


def test_validation_cannot_run_before_protocol_freeze(tmp_path: Path) -> None:
    with pytest.raises(InvalidStateTransition):
        run_part_b_candidate_validation(
            store_root=tmp_path, run_id="run-smib-001", current_state="CASE_BOUND",
            candidate_contract=_contract(), case_manifest=_fixture("case_manifest.json"),
            lens_spec=_fixture("lens_spec.json"), part_b_api=SimpleNamespace(),
            created_at="2026-08-26T08:00:00Z",
        )
