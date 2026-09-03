"""Executable smoke test for project C.

Run from the repository root with ``python -m part_c_xtl.power_c_selfcheck``.
"""
from __future__ import annotations

from . import (
    HiddenEvaluator,
    apply_lens,
    build_b1_smib_case,
    compare_lens_structure_drift,
    create_default_registry,
    fisher_identifiability,
    generate_truth,
    high_quality_lens,
    noisy_low_rate_lens,
    pmu_lens,
)


def run() -> dict[str, bool]:
    registry = create_default_registry()
    assert {c.case_type for c in registry.list()} == {"B0", "B1", "B2"}
    case = build_b1_smib_case()
    truth = generate_truth(case, seed=11)
    high = apply_lens(truth, case, high_quality_lens())
    pmu = apply_lens(truth, case, pmu_lens())
    noisy_a = apply_lens(truth, case, noisy_low_rate_lens(seed=11))
    noisy_b = apply_lens(truth, case, noisy_low_rate_lens(seed=11))
    assert high.content_hash != pmu.content_hash != noisy_a.content_hash
    assert noisy_a.content_hash == noisy_b.content_hash
    assert high.variable_metadata["omega"]["reference_mode"] == "ABSOLUTE"
    assert compare_lens_structure_drift(truth, case, high_quality_lens(), noisy_low_rate_lens())["structure_drift_detected"]
    assert fisher_identifiability([[1.0, 0.0], [0.0, 1.0]]).passed
    assert not fisher_identifiability([[1.0, 2.0], [2.0, 4.0]]).passed
    report = HiddenEvaluator(registry).evaluate(
        {"candidate_id": "selfcheck", "variables": [{"name": "unknown"}], "equations": []},
        case, high_quality_lens())
    assert {e["code"] for e in report["errors"]} == {"UNKNOWN_VARIABLE", "EMPTY_EQUATION_SET"}
    assert report["truth_exposed"] is False
    return {"case_registry": True, "lens_determinism": True, "identifiability": True, "hidden_evaluator": True}


if __name__ == "__main__":
    results = run()
    for name, passed in results.items():
        print(f"[{name}] {'PASS' if passed else 'FAIL'}")
    print("C_PART_SELFCHECK PASS")

