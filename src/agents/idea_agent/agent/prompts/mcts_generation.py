from __future__ import annotations

from typing import Optional

from src.agents.idea_agent.agent.prompts.prompt_modes import (
    is_conceptual_surprise_mode,
)


MCTS_IDEA_GENERATION_PROMPT = """
You control the expansion step of a memory-guided MCTS that iteratively rewrites research ideas.
Your mission is to surface strong, non-incremental research concepts rather than incremental fixes. The output is a scientific hypothesis contract, not an implementation-only module proposal.
- Bold, profile-compatible scientific interventions beat small wrapper or reporting tweaks.
- At least one child must import an idea from another discipline or evidence contract and tag it "moonshot".
- If you absolutely must float an incremental safeguard, tag it "incremental" and state why it is only a stop-gap.
- A protocol, dataset, measurement method, or other design may be the primary deliverable when the original user task requests it or the scientific profile makes it central.

- Topic context: {topic}
- Direction mode: {direction_mode}
- Direction summary: {direction_summary}
- Taste guidance (soft preference only): {taste_guidance}
- Target gap IDs: {target_gap_ids}
- Resolved scientific profile ID: {profile_id}
- Fixed scientific intervention profile:
{scientific_intervention_profile}
- Profile-native scientific object schema:
{profile_native_object_schema}
- Gap-to-hypothesis seeds:
{gap_seed_context}
- Current focus node summary:
{current_summary}
- Literature context synthesized from the latest downloaded papers:
{paper_context}

Retrieved natural-language memory (field knowledge, anti-patterns, fix routines):
{memory_bundle}

You must expand this node by applying the provided edit operators exactly once per child.
Operators (choose one per idea, never invent new ones):
{edit_operators}

Global constraints (NEVER violate):
{constraints}

Return up to {max_children} mutually distinct child ideas. Each child must:
1. Address a user-required scientific decision or an evidenced defect. Do not invent a defect when the task can be fulfilled without one.
2. Document which operator was used and why it repairs the defect without triggering anti-patterns (no feature dumping, use an appropriate comparator/control, expose failure modes, and respect profile-relevant limits).
3. Provide a structured idea payload with the required research sections plus risk surface tags.
4. Reference the memory snippet IDs you actually used (if no relevant memory fits, return an empty list but explain in rationale).
5. Introduce one concrete scientific intervention compatible with the fixed profile. It may be a manipulable condition, mechanism-discriminating relation, measurement mapping, boundary condition, formal assumption/derivation/counterexample, intervention, or domain-native algorithmic mechanism. Training signals and model objectives are primary only when the profile and topic make them central.
6. Reference supplied target gap IDs only when the child addresses those gaps; an empty list is valid. If a seed is provisional or exploratory, keep the claim correspondingly qualified.
7. Prefer the **mechanism-commit-innovation** operator whenever it is applicable. If you choose a different operator, explicitly justify why mechanism-commit is unsuitable for that child and how the chosen edit fits the profile's contribution modes.
8. Explain how the idea fulfills the original user task and why its mechanism or design is useful.
9. Include user-requested design decisions and testable predictions, with rationale and validation criteria. Label proposed values and predictions; never invent observed results. Leave routine execution to Experiment Agent unless the user explicitly requests that detail.

STRICT OUTPUT: valid JSON with the following schema (do not wrap in Markdown):
{{
  "children": [
    {{
      "operator": "operator_name_from_list",
      "direction_mode": "exact direction mode supplied above",
      "target_defects": ["string"],
      "contribution_mode": "one allowed mode from the fixed profile",
      "scientific_object": {{
          "object_type": "profile-native object type",
          "target_object": "specific object, population, process, relation, or formal entity"
      }},
      "central_hypothesis": "falsifiable claim or relation",
      "intervention_or_transformation": "what is changed, assumed, constructed, or compared",
      "expected_mechanism": "why the intervention should change the target",
      "discriminating_observation": "observation, control, proof, counterexample, or comparison that separates explanations",
      "boundary_or_failure_condition": "where the claim should hold, fail, or become unsafe",
      "claim_scope": "the narrowest population, regime, object, relation, or assumption covered by the claim",
      "assumptions": ["assumption or transfer limit"],
      "target_gap_ids": ["gap_id"],
      "gap_alignment": ["how the candidate addresses each target gap"],
      "evidence_requirement": "observation, contrast, proof, or measurement needed to distinguish the claim",
      "evidence_basis": ["supplied Survey anchor, evidence role, or memory basis"],
      "title": "concise title",
      "abstract": "≤120 words abstract",
      "core_contribution": "focused statement of the new insight",
      "method": "key methodology steps",
      "risks": "dominant risks or failure modes being tracked",
      "tags": ["k1","k2"],
      "memory_refs": ["Field#1","Recipe#2"],
      "anti_pattern_checks": {{
          "scope_control": "how the idea avoids feature dumping",
          "fair_baseline": "describe a fair comparator or reference relation without an execution protocol",
          "failure_reporting": "how failure modes will be surfaced"
      }},
      "rationale": "2 sentences on how the operator resolves the defect while respecting guardrails"
    }}
  ]
}}

Never invent data that contradicts the retrieved memory or operators. Keep children orthogonal.
"""


CONCEPTUAL_SURPRISE_MCTS_IDEA_GENERATION_PROMPT = MCTS_IDEA_GENERATION_PROMPT.replace(
    "5. Introduce one concrete scientific intervention compatible with the fixed profile.",
    "5. For each child, first sharpen one local scientific thesis within the user's task: repair a weak assumption, "
    "propose a better principle, or reframe the parent idea on the same method axis when that axis is user-constrained. "
    "The concrete mechanism should realize that conceptual move rather than replace it. "
    "Introduce one concrete scientific intervention compatible with the fixed profile.",
).replace(
    '"core_contribution": "focused statement of the new insight",',
    '"core_contribution": "focused statement of the new thesis, principle, reframing, or mechanism insight",',
).replace(
    '"method": "key methodology steps",',
    '"method": "start with the conceptual move being realized, then give key methodology steps",',
)


def get_mcts_generation_prompt(
    mode: Optional[str] = None,
    *,
    profile_id: Optional[str] = None,
) -> str:
    prompt = (
        CONCEPTUAL_SURPRISE_MCTS_IDEA_GENERATION_PROMPT
        if is_conceptual_surprise_mode(mode)
        else MCTS_IDEA_GENERATION_PROMPT
    )
    if str(profile_id or "").strip().lower() != "computational_algorithmic":
        prompt = prompt.replace(
            "or domain-native algorithmic mechanism",
            "or domain-native scientific mechanism",
        ).replace(
            "Training signals and model objectives are primary only when the profile and topic make them central.",
            "Use only the profile-native evidence and contribution modes supplied above.",
        )
    return prompt
