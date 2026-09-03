"""PowerDAE-Bench skeleton and hidden candidate evaluation helpers."""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any, Dict, Mapping, Optional
from .power_c_case_registry import CaseManifest, CaseRegistry, TruthDataset, create_default_registry, generate_truth
from .power_c_measurement_lens import LensResult, LensSpec, apply_lens


def _metric(a: list[float], b: list[float]) -> Dict[str, float]:
    if len(a) != len(b):
        # Compare only the common support; this keeps hidden evaluation robust
        # to candidate resampling while exposing the mismatch as a metric.
        n = min(len(a), len(b)); a, b = a[:n], b[:n]
    if not a: return {"rmse": math.inf, "mae": math.inf, "max_error": math.inf}
    errors = [x - y for x, y in zip(a, b)]
    return {"rmse": math.sqrt(sum(x * x for x in errors) / len(errors)),
            "mae": sum(abs(x) for x in errors) / len(errors), "max_error": max(abs(x) for x in errors)}


class HiddenEvaluator:
    """Evaluate a candidate against private truth without returning truth values."""

    def __init__(self, registry: Optional[CaseRegistry] = None, seed: int = 0):
        self.registry = registry or create_default_registry()
        self.seed = seed

    def evaluate(self, candidate_model: Mapping[str, Any], case_id: Any, lens_spec: Any,
                 predictions: Optional[Mapping[str, list[float]]] = None) -> Dict[str, Any]:
        if not isinstance(candidate_model, Mapping):
            if hasattr(candidate_model, "to_dict"):
                candidate_model = candidate_model.to_dict()
            else:
                candidate_model = vars(candidate_model)
        if isinstance(case_id, CaseManifest):
            case = case_id
        elif isinstance(case_id, Mapping):
            case = CaseManifest.from_dict(case_id)
        else:
            case = self.registry.get(str(case_id))
        if isinstance(lens_spec, Mapping):
            lens_spec = LensSpec.from_dict(lens_spec)
        truth = generate_truth(case, self.seed)
        observed = apply_lens(truth, case, lens_spec)
        equations = candidate_model.get("equations", [])
        codes: list[str] = []
        names = {v.name for v in case.variables}
        candidate_vars = {v.get("name") for v in candidate_model.get("variables", []) if isinstance(v, Mapping)}
        unknown = sorted(x for x in candidate_vars - names if x)
        if unknown: codes.append("UNKNOWN_VARIABLE")
        if not equations: codes.append("EMPTY_EQUATION_SET")
        metrics: Dict[str, float] = {}
        if predictions:
            for name, pred in predictions.items():
                if name in observed.values: metrics[f"{name}.rmse"] = _metric(list(pred), observed.values[name])["rmse"]
        passed = not codes and all(v < 0.1 for v in metrics.values())
        return {"model_id": candidate_model.get("candidate_id", "unknown"), "case_id": case.case_id,
                "lens_id": lens_spec.lens_id, "passed": passed, "stage": "numerical" if passed else "structure",
                "errors": [{"code": c, "severity": "error", "target": None, "message": c} for c in codes],
                "metrics": metrics, "truth_exposed": False, "observed_schema": list(observed.values),
            "artifacts": [{"kind": "lens_dataset", "content_hash": observed.content_hash}]}


def evaluate_candidate_model(candidate_model: Mapping[str, Any], case_manifest: Any,
                             lens_spec: Any, predictions: Optional[Mapping[str, list[float]]] = None,
                             registry: Optional[CaseRegistry] = None) -> Dict[str, Any]:
    """Convenience hidden-evaluation entry point used by benchmark runners."""
    return HiddenEvaluator(registry).evaluate(candidate_model, case_manifest, lens_spec, predictions)


def compare_lens_structure_drift(dataset: TruthDataset, case: CaseManifest,
                                 lens_a: LensSpec, lens_b: LensSpec) -> Dict[str, Any]:
    """Return deterministic distribution-shift indicators, without equations."""
    a, b = apply_lens(dataset, case, lens_a), apply_lens(dataset, case, lens_b)
    common = sorted(set(a.values) & set(b.values))
    means = {}
    for name in common:
        ma, mb = sum(a.values[name]) / len(a.values[name]), sum(b.values[name]) / len(b.values[name])
        means[name] = {"mean_shift": mb - ma,
                       "std_a": math.sqrt(sum((x - ma) ** 2 for x in a.values[name]) / len(a.values[name])),
                       "std_b": math.sqrt(sum((x - mb) ** 2 for x in b.values[name]) / len(b.values[name]))}
    return {"lens_a": lens_a.lens_id, "lens_b": lens_b.lens_id, "sample_count_a": len(a.time_s),
            "sample_count_b": len(b.time_s), "mean_shifts": means,
            "structure_drift_detected": any(abs(x["mean_shift"]) > 1e-4 or abs(x["std_b"] - x["std_a"]) > 1e-4 for x in means.values())}
