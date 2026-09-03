"""Versioned benchmark cases and deterministic truth trajectories.

Cases are intentionally represented as JSON-compatible dataclasses.  Truth
equations are kept in this module and are never returned by the hidden
evaluator; consumers receive trajectories and physical metadata instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class VariableSpec:
    name: str
    unit: str
    coordinate: str
    role: str = "state"
    reference_mode: str = "NOT_APPLICABLE"
    nominal_value: Optional[float] = None
    normalization: str = "physical"
    sampling_rate_hz: float = 100.0

    def __post_init__(self) -> None:
        if self.reference_mode not in {"ABSOLUTE", "DEVIATION", "NOT_APPLICABLE"}:
            raise ValueError("reference_mode must be ABSOLUTE, DEVIATION, or NOT_APPLICABLE")
        if self.reference_mode == "ABSOLUTE" and self.nominal_value is None:
            raise ValueError("ABSOLUTE variables require nominal_value")

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in {
            "name": self.name, "unit": self.unit, "coordinate": self.coordinate,
            "role": self.role, "reference_mode": self.reference_mode,
            "nominal_value": self.nominal_value, "normalization": self.normalization,
            "sampling_rate_hz": self.sampling_rate_hz,
        }.items() if v is not None}


@dataclass(frozen=True)
class ResourceRef:
    path: str
    kind: str
    sha256: str

    def to_dict(self) -> Dict[str, str]:
        return {"path": self.path, "kind": self.kind, "sha256": self.sha256}


@dataclass
class CaseManifest:
    case_id: str
    case_type: str
    system_name: str
    version: str
    base: Dict[str, float]
    time_domain: Dict[str, float]
    variables: list[VariableSpec]
    parameters: Dict[str, float] = field(default_factory=dict)
    events: list[Dict[str, Any]] = field(default_factory=list)
    resources: list[ResourceRef] = field(default_factory=list)
    expected_checks: list[str] = field(default_factory=lambda: ["power_balance", "algebraic_closure"])
    parameter_bounds: Dict[str, Sequence[float]] = field(default_factory=dict)
    files: Dict[str, str] = field(default_factory=dict)
    schema_version: str = "case_manifest_v2"

    def __post_init__(self) -> None:
        if self.case_type not in {"B0", "B1", "B2"}:
            raise ValueError("case_type must be B0, B1, or B2")
        start, stop = self.time_domain["start_s"], self.time_domain["stop_s"]
        if stop <= start:
            raise ValueError("time_domain stop_s must be greater than start_s")
        for event in self.events:
            if not start <= float(event["time_s"]) <= stop:
                raise ValueError("event time must lie within time_domain")

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict(include_hash=False))

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "schema_version": self.schema_version, "case_id": self.case_id,
            "case_type": self.case_type, "system_name": self.system_name,
            "version": self.version, "base": self.base, "time_domain": self.time_domain,
            "variables": [v.to_dict() for v in self.variables], "parameters": self.parameters,
            "events": self.events, "resources": [r.to_dict() for r in self.resources],
            "files": self.files,
            "expected_checks": self.expected_checks, "parameter_bounds": self.parameter_bounds,
        }
        if include_hash:
            result["content_hash"] = self.content_hash
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseManifest":
        resources = [ResourceRef(**r) for r in data.get("resources", [])]
        variables = [VariableSpec(**v) for v in data["variables"]]
        values = {k: data[k] for k in ("case_id", "case_type", "system_name", "version", "base", "time_domain")}
        values.update(variables=variables, parameters=data.get("parameters", {}), events=data.get("events", []),
                      resources=resources, expected_checks=data.get("expected_checks", []),
                      parameter_bounds=data.get("parameter_bounds", {}), files=data.get("files", {}),
                      schema_version=data.get("schema_version", "case_manifest_v2"))
        return cls(**values)


# Explicit versioned aliases used by the A-part public contract.
CaseManifestV2 = CaseManifest


@dataclass
class TruthDataset:
    case_id: str
    time_s: list[float]
    values: Dict[str, list[float]]
    variable_metadata: Dict[str, Dict[str, Any]]
    source: str = "synthetic_deterministic"
    seed: int = 0
    dataset_version: str = "truth_v1"

    @property
    def content_hash(self) -> str:
        return _hash(self.to_dict(include_hash=False))

    def to_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        out = {"dataset_version": self.dataset_version, "case_id": self.case_id,
               "time_s": self.time_s, "values": self.values,
               "variable_metadata": self.variable_metadata, "source": self.source, "seed": self.seed}
        if include_hash:
            out["content_hash"] = self.content_hash
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TruthDataset":
        return cls(case_id=data["case_id"], time_s=list(data["time_s"]), values={k: list(v) for k, v in data["values"].items()},
                   variable_metadata=dict(data["variable_metadata"]), source=data.get("source", "unknown"),
                   seed=int(data.get("seed", 0)), dataset_version=data.get("dataset_version", "truth_v1"))


class CaseRegistry:
    """In-memory registry with immutable-by-version case lookup."""

    def __init__(self, cases: Optional[Iterable[CaseManifest]] = None):
        self._cases: Dict[str, CaseManifest] = {}
        for case in cases or (): self.register(case)

    def register(self, case: CaseManifest) -> None:
        key = f"{case.case_id}@{case.version}"
        if key in self._cases and self._cases[key].content_hash != case.content_hash:
            raise ValueError(f"case version already registered with different content: {key}")
        self._cases[key] = case

    def get(self, case_id: str, version: Optional[str] = None) -> CaseManifest:
        if version is not None: return self._cases[f"{case_id}@{version}"]
        matches = [c for c in self._cases.values() if c.case_id == case_id]
        if not matches: raise KeyError(case_id)
        return sorted(matches, key=lambda c: c.version)[-1]

    def list(self) -> list[CaseManifest]: return list(self._cases.values())


def _common(case_id: str, case_type: str, system: str, variables: list[VariableSpec], parameters: Dict[str, float], bounds: Dict[str, Sequence[float]]) -> CaseManifest:
    manifest_stub = {"case_id": case_id, "case_type": case_type, "system_name": system, "version": "1.0.0",
        "variables": [v.to_dict() for v in variables], "parameters": parameters}
    resources = [ResourceRef(f"builtin://{case_id}/truth", "truth_data", _hash(manifest_stub))]
    return CaseManifest(case_id=case_id, case_type=case_type, system_name=system, version="1.0.0",
        base={"s_base_mva": 100.0, "v_base_kv": 230.0, "frequency_hz": 60.0, "omega_base_rad_s": 2 * math.pi * 60},
        time_domain={"start_s": 0.0, "stop_s": 10.0, "step_s": 0.01}, variables=variables,
        parameters=parameters, parameter_bounds=bounds, resources=resources,
        files={"truth_data": f"cases/{case_id}/1.0.0/truth_data.json", "metadata": f"cases/{case_id}/1.0.0/metadata.json"})


def build_b0_case() -> CaseManifest:
    variables = [VariableSpec("x", "pu", "b0_state", "state", "DEVIATION", 0.0),
                 VariableSpec("v", "pu/s", "b0_state", "state", "DEVIATION", 0.0)]
    return _common("B0_swing_v1", "B0", "single_machine_swing", variables,
                   {"damping": 0.12, "stiffness": 1.0}, {"damping": (0.0, 2.0), "stiffness": (0.1, 5.0)})


def build_b1_smib_case() -> CaseManifest:
    variables = [VariableSpec("delta", "rad", "generator_g1", "state", "DEVIATION", 0.0),
                 VariableSpec("omega", "pu", "generator_g1", "state", "ABSOLUTE", 1.0),
                 VariableSpec("Pe", "pu", "generator_g1", "algebraic", "NOT_APPLICABLE"),
                 VariableSpec("Pm", "pu", "generator_g1", "input", "NOT_APPLICABLE")]
    return _common("B1_SMIB_v1", "B1", "SMIB", variables,
                   {"H": 3.5, "D": 0.1, "Pm": 0.8, "E": 1.1, "V": 1.0, "X": 0.6, "delta0": 0.45},
                   {"H": (0.5, 20.0), "D": (0.0, 5.0), "Pm": (0.0, 2.0), "E": (0.5, 2.0), "V": (0.5, 1.5), "X": (0.05, 3.0)})


def build_b2_ieee9_case() -> CaseManifest:
    variables: list[VariableSpec] = []
    for i in range(1, 4):
        variables += [VariableSpec(f"delta_g{i}", "rad", f"generator_g{i}", "state", "DEVIATION", 0.0),
                      VariableSpec(f"omega_g{i}", "pu", f"generator_g{i}", "state", "ABSOLUTE", 1.0)]
    for bus in range(1, 10):
        variables += [VariableSpec(f"Vm_bus{bus}", "pu", f"bus_{bus}", "algebraic", "ABSOLUTE", 1.0),
                      VariableSpec(f"Va_bus{bus}", "rad", f"bus_{bus}", "algebraic", "DEVIATION", 0.0)]
    return _common("B2_IEEE9_v1", "B2", "IEEE_9_bus", variables,
                   {"H_g1": 3.5, "H_g2": 4.0, "H_g3": 3.0, "D_g1": 0.1, "D_g2": 0.1, "D_g3": 0.1},
                   {"H_g1": (0.5, 20), "H_g2": (0.5, 20), "H_g3": (0.5, 20), "D_g1": (0, 5), "D_g2": (0, 5), "D_g3": (0, 5)})


def generate_truth(case: CaseManifest, seed: int = 0) -> TruthDataset:
    n = int(round((case.time_domain["stop_s"] - case.time_domain["start_s"]) / case.time_domain["step_s"])) + 1
    t = [case.time_domain["start_s"] + i * case.time_domain["step_s"] for i in range(n)]
    p = case.parameters
    values: Dict[str, list[float]] = {}
    if case.case_type == "B0":
        values["x"] = [0.2 * math.exp(-p["damping"] * ti / 2) * math.sin(ti) for ti in t]
        values["v"] = [0.2 * math.exp(-p["damping"] * ti / 2) * (math.cos(ti) - p["damping"] * math.sin(ti) / 2) for ti in t]
    elif case.case_type == "B1":
        d0, amp = p["delta0"], 0.08
        values["delta"] = [d0 + amp * math.exp(-p["D"] * ti / (4 * p["H"])) * math.sin(2 * math.pi * 0.8 * ti) for ti in t]
        values["omega"] = [1.0 + amp * 0.02 * math.exp(-p["D"] * ti / (4 * p["H"])) * math.cos(2 * math.pi * 0.8 * ti) for ti in t]
        values["Pe"] = [p["E"] * p["V"] / p["X"] * math.sin(d) for d in values["delta"]]
        values["Pm"] = [p["Pm"] for _ in t]
    else:
        for i in range(1, 4):
            values[f"delta_g{i}"] = [0.1 * i + 0.03 * math.exp(-0.04 * ti) * math.sin(0.7 * ti + i) for ti in t]
            values[f"omega_g{i}"] = [1.0 + 0.003 * math.exp(-0.04 * ti) * math.cos(0.7 * ti + i) for ti in t]
        for bus in range(1, 10):
            values[f"Vm_bus{bus}"] = [1.0 - 0.01 * (bus % 3) + 0.002 * math.sin(0.3 * ti + bus) for ti in t]
            values[f"Va_bus{bus}"] = [0.01 * math.sin(0.2 * ti + bus / 3) for ti in t]
    metadata = {v.name: v.to_dict() for v in case.variables}
    return TruthDataset(case.case_id, t, values, metadata, seed=seed)


def create_default_registry() -> CaseRegistry:
    return CaseRegistry([build_b0_case(), build_b1_smib_case(), build_b2_ieee9_case()])


def generate_b0_truth(case: Optional[CaseManifest] = None, seed: int = 0) -> TruthDataset:
    return generate_truth(case or build_b0_case(), seed)


def generate_b1_truth(case: Optional[CaseManifest] = None, seed: int = 0) -> TruthDataset:
    return generate_truth(case or build_b1_smib_case(), seed)


def generate_b2_truth(case: Optional[CaseManifest] = None, seed: int = 0) -> TruthDataset:
    return generate_truth(case or build_b2_ieee9_case(), seed)


def save_case_bundle(root: str | Path, case: CaseManifest, truth: Optional[TruthDataset] = None) -> Dict[str, str]:
    """Persist a reproducible case bundle without overwriting a prior version."""
    root_path = Path(root) / case.case_id / case.version
    root_path.mkdir(parents=True, exist_ok=True)
    truth = truth or generate_truth(case)
    manifest_path, truth_path = root_path / "case_manifest.json", root_path / "truth.json"
    if manifest_path.exists() or truth_path.exists():
        # Existing content is safe to reuse only when it is byte-for-byte equivalent.
        for path, payload in ((manifest_path, case.to_dict()), (truth_path, truth.to_dict())):
            if path.exists() and path.read_text(encoding="utf-8") != json.dumps(payload, indent=2, sort_keys=True):
                raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    manifest_path.write_text(json.dumps(case.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    truth_path.write_text(json.dumps(truth.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return {"case_manifest": str(manifest_path), "truth_data": str(truth_path),
            "case_hash": case.content_hash, "truth_hash": truth.content_hash}
