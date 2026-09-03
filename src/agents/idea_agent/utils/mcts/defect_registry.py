"""Canonical defect registry shared by MCTS evaluation and skill selection."""

from __future__ import annotations

from typing import Dict, Optional, Set


DEFECT_REGISTRY: Dict[str, str] = {
    # mechanism-first innovation
    "stagnant_novelty": (
        "The idea lacks a genuinely new mechanism; contributions feel incremental "
        "or re-package known techniques without a clear novel insight."
    ),
    "unclear_mechanism": (
        "The core mechanism is vaguely described or under-specified, making it "
        "hard to reproduce, reason about, or evaluate the contribution."
    ),
    "validation_gap": (
        "The validation plan is missing key ablations, stress tests, or fair "
        "comparisons needed to support the claims."
    ),
    # domain-neutral scientific reasoning and evidence defects
    "unsupported_causal_link": (
        "The proposal claims a causal or mechanistic link that is not supported "
        "by the stated intervention, observation, proof, or evidence."
    ),
    "unresolved_alternative_explanation": (
        "A competing explanation remains plausible and the proposed evidence does "
        "not distinguish it from the preferred mechanism."
    ),
    "missing_comparator": (
        "No adequate control, counterfactual, reference case, or competing condition "
        "is specified for interpreting the claimed effect."
    ),
    "measurement_construct_mismatch": (
        "The observable, assay, endpoint, or characterization does not validly "
        "represent the construct or mechanism being claimed."
    ),
    "missing_boundary_condition": (
        "The proposal does not state the regime, population, scale, assumptions, "
        "or operating conditions where the claim holds or fails."
    ),
    "nonidentifiable_mechanism": (
        "The proposed mechanism cannot be distinguished from plausible alternatives "
        "with the stated data, experiment, observation, or proof."
    ),
    "confounding_or_selection_bias": (
        "Confounding, selection, sampling, or allocation bias can explain the "
        "observed relation and is not adequately controlled."
    ),
    "invalid_generalization": (
        "The conclusion is extended beyond the supported object, sample, regime, "
        "scale, domain, or formal validity conditions."
    ),
    "claim_overreach": (
        "The wording claims more causal, universal, predictive, or mechanistic "
        "strength than the evidence and validation can justify."
    ),
    "insufficient_reproducibility": (
        "The intervention, measurement, derivation, protocol, or conditions are "
        "not specified well enough for an independent reproduction."
    ),
    "missing_assumption": (
        "A formal or scientific assumption required for the stated relation is "
        "implicit, incomplete, or inconsistent."
    ),
    "missing_counterexample": (
        "The proposal lacks a counterexample, limiting case, or failure probe that "
        "could expose the boundary of the claim."
    ),
    "proof_gap": (
        "A required proof, derivation, construction, or verification step is "
        "missing or does not establish the stated conclusion."
    ),
    # alternative-path-contrast
    "brittle_single_path": (
        "The method assumes one dominant operating regime and lacks a structured "
        "fallback or contrastive treatment for rare regimes, failures, or recovery."
    ),
    "rare_regime_failure": (
        "Behavior under boundary conditions, overload, adversarial inputs, or "
        "other rare regimes is weak or unexamined."
    ),
    "weak_fallback_behavior": (
        "Fallback, recovery, or degraded-mode behavior is missing, underspecified, "
        "or ineffective when the primary path breaks down."
    ),
    # modular architecture
    "feature_dumping": (
        "Multiple components or features are added simultaneously without "
        "individual justification, making ablation or attribution impossible."
    ),
    "monolithic_design": (
        "Core responsibilities are trapped inside a single tightly coupled block, "
        "resisting modular analysis, replacement, or incremental improvement."
    ),
    "harder_to_ablate": (
        "Design choices make it difficult to isolate the effect of any single "
        "component through controlled ablation studies."
    ),
    # coordination across scales or layers
    "scale_mismatch": (
        "The solution operates at one scale, layer, or tier while the problem "
        "requires coordination across multiple scales or granularities."
    ),
    "coordination_failure": (
        "Multiple subsystems, branches, or layers fail to maintain a coherent "
        "decision rule, causing conflicts, redundancy, or information loss."
    ),
    "latency_bottleneck": (
        "A component, synchronization point, or coordination rule introduces "
        "unacceptable latency or throughput collapse."
    ),
    # hierarchical decomposition
    "responsibility_entanglement": (
        "Planning, control, execution, or analysis responsibilities are tangled "
        "together instead of being separated into explicit layers or roles."
    ),
    # feedback and adaptation
    "silent_failure": (
        "The system produces wrong or degraded outputs without exposing enough "
        "signal for downstream detection or correction."
    ),
    "drift": (
        "Performance degrades over time or across regimes as workloads, data, or "
        "operating conditions shift away from the design assumptions."
    ),
    "open_loop_fragility": (
        "The system acts in an open-loop manner and cannot adapt when outcomes, "
        "errors, or environment conditions change."
    ),
    # theory-guided reformulation
    "theory_gap": (
        "The approach lacks grounding in a transferable principle, invariant, or "
        "formal lens that could justify the mechanism design."
    ),
    "weak_generalization": (
        "Evidence that the approach transfers across domains, workloads, "
        "distributions, or operating regimes is insufficient or absent."
    ),
    # speculative execution
    "over_conservative_execution": (
        "The system pays full serialization, synchronization, or safety cost on "
        "every path because it lacks a principled optimistic fast path."
    ),
    "rollback_blindspot": (
        "The design lacks explicit detection, rollback, or repair when optimistic "
        "actions misfire or speculative assumptions are violated."
    ),
    # default fallback used when no context-specific defect is identified
    "unexplored_gap": (
        "No specific defect has been identified yet; the idea space is still "
        "being explored and requires targeted analysis."
    ),
}


DEFECT_PROFILE_PRIORITIES: Dict[str, tuple[str, ...]] = {
    "computational_algorithmic": (
        "feature_dumping",
        "latency_bottleneck",
        "weak_fallback_behavior",
        "monolithic_design",
        "stagnant_novelty",
    ),
    "physical_materials_chemical": (
        "measurement_construct_mismatch",
        "unsupported_causal_link",
        "missing_boundary_condition",
        "insufficient_reproducibility",
    ),
    "life_molecular_mechanistic": (
        "unsupported_causal_link",
        "missing_comparator",
        "measurement_construct_mismatch",
        "missing_boundary_condition",
        "confounding_or_selection_bias",
    ),
    "clinical_health": (
        "missing_comparator",
        "confounding_or_selection_bias",
        "invalid_generalization",
        "claim_overreach",
        "measurement_construct_mismatch",
        "missing_boundary_condition",
    ),
    "earth_environment_agro": (
        "unsupported_causal_link",
        "missing_boundary_condition",
        "measurement_construct_mismatch",
        "invalid_generalization",
    ),
    "energy_engineering_systems": (
        "unsupported_causal_link",
        "missing_boundary_condition",
        "insufficient_reproducibility",
        "invalid_generalization",
    ),
    "formal_theoretical": (
        "missing_assumption",
        "proof_gap",
        "missing_counterexample",
        "nonidentifiable_mechanism",
        "invalid_generalization",
    ),
    "generic_scientific": (
        "unsupported_causal_link",
        "unresolved_alternative_explanation",
        "missing_comparator",
        "missing_boundary_condition",
        "claim_overreach",
    ),
}


# Profile-native defects are mapped onto the existing skill vocabulary so
# legacy skill files remain readable while profile-aware selection can still
# reward the right intervention family.
PROFILE_DEFECT_SKILL_MATCHES: Dict[str, Dict[str, tuple[str, ...]]] = {
    "computational_algorithmic": {},
    "physical_materials_chemical": {
        "measurement_construct_mismatch": ("mechanism-commit-innovation", "feedback-closed-loop"),
        "unsupported_causal_link": ("mechanism-commit-innovation", "alternative-path-contrast"),
        "missing_boundary_condition": ("alternative-path-contrast", "feedback-closed-loop"),
        "insufficient_reproducibility": ("mechanism-commit-innovation", "feedback-closed-loop"),
    },
    "life_molecular_mechanistic": {
        "unsupported_causal_link": ("mechanism-commit-innovation", "alternative-path-contrast"),
        "missing_comparator": ("alternative-path-contrast",),
        "measurement_construct_mismatch": ("mechanism-commit-innovation", "feedback-closed-loop"),
        "missing_boundary_condition": ("alternative-path-contrast", "feedback-closed-loop"),
        "confounding_or_selection_bias": ("alternative-path-contrast",),
    },
    "clinical_health": {
        "missing_comparator": ("alternative-path-contrast",),
        "confounding_or_selection_bias": ("alternative-path-contrast",),
        "invalid_generalization": ("alternative-path-contrast", "theory-transfer-injection"),
        "claim_overreach": ("alternative-path-contrast",),
        "measurement_construct_mismatch": ("mechanism-commit-innovation", "feedback-closed-loop"),
        "missing_boundary_condition": ("alternative-path-contrast", "feedback-closed-loop"),
    },
    "earth_environment_agro": {
        "unsupported_causal_link": ("mechanism-commit-innovation", "alternative-path-contrast"),
        "missing_boundary_condition": ("alternative-path-contrast", "feedback-closed-loop"),
        "measurement_construct_mismatch": ("mechanism-commit-innovation", "feedback-closed-loop"),
        "invalid_generalization": ("alternative-path-contrast", "theory-transfer-injection"),
    },
    "energy_engineering_systems": {
        "unsupported_causal_link": ("mechanism-commit-innovation", "alternative-path-contrast"),
        "missing_boundary_condition": ("alternative-path-contrast", "feedback-closed-loop"),
        "insufficient_reproducibility": ("mechanism-commit-innovation", "feedback-closed-loop"),
        "invalid_generalization": ("alternative-path-contrast", "theory-transfer-injection"),
    },
    "formal_theoretical": {
        "missing_assumption": ("mechanism-commit-innovation", "theory-transfer-injection"),
        "proof_gap": ("theory-transfer-injection",),
        "missing_counterexample": ("alternative-path-contrast",),
        "nonidentifiable_mechanism": ("alternative-path-contrast", "theory-transfer-injection"),
        "invalid_generalization": ("alternative-path-contrast", "theory-transfer-injection"),
    },
    "generic_scientific": {
        "unsupported_causal_link": ("mechanism-commit-innovation", "alternative-path-contrast"),
        "unresolved_alternative_explanation": ("alternative-path-contrast", "theory-transfer-injection"),
        "missing_comparator": ("alternative-path-contrast",),
        "missing_boundary_condition": ("alternative-path-contrast", "feedback-closed-loop"),
        "claim_overreach": ("alternative-path-contrast",),
    },
}


def profile_skill_defect_tags(profile_id: Optional[str], skill_name: str) -> Set[str]:
    """Return profile-native defects that a legacy skill can remediate."""

    profile_key = str(profile_id or "generic_scientific").strip().lower()
    profile_matches = PROFILE_DEFECT_SKILL_MATCHES.get(profile_key, {})
    priority_tags = set(DEFECT_PROFILE_PRIORITIES.get(profile_key, ()))
    if priority_tags:
        profile_matches = {
            defect: skill_names
            for defect, skill_names in profile_matches.items()
            if defect in priority_tags
        }
    skill_key = str(skill_name or "").strip()
    return {
        defect
        for defect, skill_names in profile_matches.items()
        if skill_key in skill_names
    }


def format_defect_registry(profile_id: Optional[str] = None) -> str:
    """Return a prompt-friendly listing of canonical defect tags."""
    profile_key = str(profile_id or "").strip()
    priority_tags = set(DEFECT_PROFILE_PRIORITIES.get(profile_key, ()))
    header = "Canonical defect tag registry (use ONLY these tags in detected_defects):"
    if profile_key:
        header += f"\nProfile priority: {profile_key}"
    lines = [header]
    for tag, desc in DEFECT_REGISTRY.items():
        priority = " [profile-priority]" if tag in priority_tags else ""
        lines.append(f"  - {tag}{priority}: {desc}")
    return "\n".join(lines)
