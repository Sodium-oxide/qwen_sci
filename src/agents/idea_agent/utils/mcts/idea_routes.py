"""Generic route policies used to cross mature-idea seeds with search strategies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class IdeaRoutePolicy:
    route_id: str
    label: str
    required_structural_change: str
    forbidden_reuse: str
    allowed_object_transformations: str
    mechanism_constraints: str
    retrieval_mode: str
    risk_budget: str
    falsifier_requirement: str
    minimum_divergence: str
    legacy_mode: str

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


IDEA_ROUTE_POLICIES: List[IdeaRoutePolicy] = [
    IdeaRoutePolicy(
        "premise_inversion", "Premise inversion", "Invert or relax one defining premise",
        "Do not merely restate the seed conclusion", "Keep the object unless inversion requires a boundary change",
        "State the inverted premise and its causal consequence", "counterfactual_and_constraint", "high",
        "Name a result that would falsify the inverted premise", "premise_or_assumption", "moonshot_inventor",
    ),
    IdeaRoutePolicy(
        "object_substitution", "Object substitution", "Replace the primary scientific object or level of description",
        "Do not preserve the seed object as the only active object", "Permit adjacent object, scale, or representation substitution",
        "Explain the mapping from old object to new object", "analogy_and_transfer", "medium",
        "Specify an object-level discriminating observation", "scientific_object", "bridge_builder",
    ),
    IdeaRoutePolicy(
        "mechanism_replacement", "Mechanism replacement", "Replace the causal or formal mechanism",
        "Do not reuse the seed mechanism under synonymous terminology", "Object may remain fixed",
        "Use a genuinely different causal relation or derivation", "mechanism_first", "high",
        "Provide a mechanism-specific failure prediction", "mechanism_or_relation", "steady_engineer",
    ),
    IdeaRoutePolicy(
        "representation_shift", "Representation shift", "Change the formal representation or explanatory level",
        "Do not claim notation changes are mechanism changes", "Allow representation, state space, or scale changes",
        "Show what invariant and what new relation the representation exposes", "cross_representation", "medium",
        "Give an invariant-based falsifier", "representation", "ambitious_realist",
    ),
    IdeaRoutePolicy(
        "verification_reversal", "Verification reversal", "Use an observable or test outcome to back-infer the mechanism",
        "Do not turn instrumentation alone into the contribution", "Object follows the evidence pathway",
        "Derive competing mechanism predictions before selecting one", "evidence_to_hypothesis", "medium",
        "Require a pre-registered discriminating outcome", "falsifier_or_prediction", "evidence_first",
    ),
]

IDEA_ROUTE_POLICY_MAP = {policy.route_id: policy for policy in IDEA_ROUTE_POLICIES}

