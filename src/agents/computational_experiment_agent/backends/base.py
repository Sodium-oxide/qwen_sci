"""Common backend parsing with no trusted statuses accepted from generated code."""

from pathlib import Path
from typing import Protocol

from ..artifacts import read_json, safe_path
from ..contracts import CapabilityReport


class ExperimentBackend(Protocol):
    backend_id: str
    def uses_generated_code(self, plan: dict) -> bool: ...
    def validate(self, plan: dict) -> list[str]: ...
    def files(self, plan: dict) -> dict[str, str]: ...
    def parse(self, execution: dict) -> dict: ...


class PythonProjectBackend:
    backend_id = "python_project"

    def uses_generated_code(self, plan: dict) -> bool:
        return self.backend_id == "python_project"

    def generation_guidance(self, plan: dict) -> str:
        return "Implement the declared model and produce raw observations for host diagnostics."

    def validate(self, plan: dict) -> list[str]:
        errors = []
        for endpoint in plan["endpoints"]:
            binding = endpoint.get("observation_binding", {})
            if not binding:
                errors.append("python_endpoint_requires_observation_binding:" + endpoint["metric_id"])
            elif binding["source_key"] in {"metrics", "checks", "validation_status", "hypothesis_relation", "execution_status"}:
                errors.append("endpoint_cannot_bind_to_derived_metrics_or_status")
        return errors

    def files(self, plan: dict) -> dict[str, str]:
        return {}

    def probe(self, runtime, environment_id: str) -> CapabilityReport:
        return runtime.probe(environment_id)

    def parse(self, execution: dict) -> dict:
        if execution["status"] != "COMPLETED":
            return {}
        root = Path(execution["output_dir"]) / "raw"
        value = read_json(safe_path(root, "observations.json"))
        if any(field in value for field in ("validation_status", "hypothesis_relation", "execution_status")):
            raise ValueError("program_cannot_assert_trusted_status")
        return value
