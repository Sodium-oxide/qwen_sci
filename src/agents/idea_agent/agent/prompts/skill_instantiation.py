from __future__ import annotations

from typing import Optional

from src.agents.idea_agent.agent.prompts.prompt_modes import (
    is_conceptual_surprise_mode,
)


_BASE_HARD_TASKS = (
    'Replace every generic placeholder in the compiled edit plan with a specific, topic-relevant scientific object, role, mechanism, process, relation, or method name compatible with the fixed profile and its scientific_object_schema.',
    'Use the profile-native object and operation vocabulary directly. For non-computational profiles, do not translate an intervention, measurement, proof obligation, process, or boundary into a software module, interface, data-flow, or benchmark by default.',
    'Write a concrete title, abstract, core contribution, method, risks, and rationale as if drafting a real paper, while also completing the scientific hypothesis contract below.',
    'Keep the instantiated idea consistent with the compiled edit plan structure: preserve the same component-edit count and the same operator types.',
    'Make the method concrete enough to execute, observe, derive, or reproduce, and make the link from the instantiated intervention to the target defects explicit.',
    'If a mature idea is provided, treat it as the anchor: refine it directly, keep the title/abstract/method framed as a refinement of that mature idea, and do not drift into an unrelated direction or temporary internal search alias.',
    'Provide a "component_mapping" for every generic template name that literally appears in the compiled edit plan. The mapped names are scientific objects even when the legacy operation says COMPONENT. For REWIRE/REPLACE targets that refer to existing parent components, map them to the actual parent component name. For ADD_COMPONENT, give a concrete name that reflects its profile-native role.',
    'Keep "component_mapping" minimal and bounded to names that literally appear in the compiled edit plan. Also provide aligned "edit_reasons" and "component_role_explanations" for those mapped components.',
    'Complete contribution_mode, scientific_object, central_hypothesis, intervention_or_transformation, expected_mechanism, discriminating_observation, boundary_or_failure_condition, and evidence_requirement using the fixed profile. These fields must describe the science even when the legacy edit operator says COMPONENT.',
    'For non-computational profiles, missing loss, optimizer, dataset, encoder, training signal, or benchmark is not an innovation or completeness defect. Use synthesis, processing, intervention, cohort, endpoint, assumption, proof, observation, design, or safety evidence as appropriate instead.',
    'Stay inside the fixed root domain(s) and refinement scope above. If `skill_name` is `mechanism-commit-innovation` and the parent idea is not already centered on threshold/control logic, do not realize the edit as thresholding, gating, suppression, or quota adjustment.',
)

_BASE_HEURISTICS = (
    'Use additional retrieved references and skill-specific mechanism references only to ground mechanism choices or failure-mode checks. If a reference is cross-domain, transfer only the useful mechanism or invariant, not the paper-specific packaging or names.',
    'Treat the taste guidance above as a soft preference only. It must not override the compiled edit plan, target defects, validation protocols, or guardrails.',
    'If the mature idea or parent idea is training-free or inference-time only, preserve that character when possible. If you introduce new training, explicitly justify why the training shift is necessary and central.',
    'Prefer direct profile-native mechanism, relation, intervention, measurement, proof, design, or update-rule repairs over audit, guardrail, controller, or wrapper-heavy realizations. Validation and support steps should stay secondary unless the profile identifies validation itself as the scientific bottleneck.',
)

_CONCEPTUAL_SURPRISE_HEURISTICS = (
    'Use additional retrieved references and skill-specific mechanism references only to ground mechanism choices or failure-mode checks. If a reference is cross-domain, transfer only the useful mechanism or invariant, not the paper-specific packaging or names.',
    'Treat the taste guidance above as a soft preference only. It must not override the compiled edit plan, target defects, validation protocols, or guardrails.',
    'If the mature idea or parent idea is training-free or inference-time only, preserve that character when possible. If you introduce new training, explicitly justify why the training shift is necessary and central.',
    'Treat the contribution as a local conceptual repair of the parent idea, not merely a new module insertion. Keep it thesis-preserving; in `abstract`, lead with the repaired thesis; in `core_contribution`, state the principle or invariant; in `method`, separate the conceptual move from the concrete mechanism realization.',
)


def _numbered_lines(lines: tuple[str, ...]) -> str:
    return "\n".join(f"{idx}. {line}" for idx, line in enumerate(lines, start=1))


def _build_output_schema(*, conceptual_surprise: bool) -> str:
    abstract_desc = "≤150 words abstract describing the concrete contribution"
    core_contribution_desc = "one focused statement of the new insight/mechanism"
    method_desc = (
        "concrete methodology steps using the concrete names defined for the compiled edit-plan placeholders "
        "in your component_mapping and the allowed native operations. Only a computational profile should mention standard losses, optimizers, datasets, encoders, or training contracts; other profiles should use their native evidence terms. "
        "routines in prose without adding them to component_mapping unless they literally appear in the compiled edit plan."
    )
    rationale_desc = (
        "2-3 sentences on how this skill application resolves the target defects. "
        "If you introduced new training into a training-free parent idea, explicitly justify why that shift is necessary."
    )

    if conceptual_surprise:
        abstract_desc += ". The opening sentence should state the scientific thesis or conceptual repair; later sentences can explain the mechanism vehicle."
        core_contribution_desc = (
            "one focused statement of the thesis, principle, invariant, or conceptual repair being introduced; "
            "not just a module name"
        )
        method_desc = (
            "start by naming the conceptual move being realized, then give concrete methodology steps using the "
            "concrete names defined for the compiled edit-plan placeholders in your component_mapping. You may "
            "mention computational losses, optimizers, datasets, encoders, or helper routines only when the fixed profile makes them central; otherwise use profile-native evidence without adding "
            "them to component_mapping unless they literally appear in the compiled edit plan."
        )
        rationale_desc = (
            "2-3 sentences on how this skill application resolves the target defects and sharpens the parent idea's thesis. "
            "If you introduced new training into a training-free parent idea, explicitly justify why that shift is necessary."
        )

    return "\n".join(
        [
            "Return STRICT JSON (no Markdown wrapping):",
            "{{",
            '  "title": "concise, specific paper title using the concrete component names",',
            f'  "abstract": "{abstract_desc}",',
            f'  "core_contribution": "{core_contribution_desc}",',
            f'  "method": "{method_desc}",',
            '  "risks": "concrete failure modes and mitigation strategies",',
            f'  "rationale": "{rationale_desc}",',
            '  "contribution_mode": "one allowed profile contribution mode",',
            '  "scientific_object": {{',
            '      "object_type": "profile-native object type",',
            '      "target_object": "specific object, population, process, relation, or formal entity"',
            "    }},",
            '  "central_hypothesis": "falsifiable claim or relation",',
            '  "intervention_or_transformation": "what is changed, assumed, constructed, or compared",',
            '  "expected_mechanism": "why the intervention should change the target",',
            '  "discriminating_observation": "observation, control, proof, counterexample, or comparison that separates explanations",',
            '  "boundary_or_failure_condition": "where the claim should hold, fail, or become unsafe",',
            '  "evidence_requirement": "minimum evidence needed to support the claim",',
            '  "component_mapping": {{',
            '      "generic_template_name_1": "concrete_topic_specific_name_1",',
            '      "generic_template_name_2": "concrete_topic_specific_name_2"',
            "    }},",
            '  "component_role_explanations": {{',
            '      "concrete_topic_specific_name_1": "Specific scientific role in the intervention...",',
            '      "concrete_topic_specific_name_2": "Specific scientific role in the intervention..."',
            "    }},",
            '  "edit_reasons": [',
            '      "Reason 1: Why generic_template_1 fixes Target Defect X...",',
            '      "Reason 2: Why generic_template_2 is needed for the validation..."',
            "    ]",
            "}}",
        ]
    )


def _build_skill_instantiation_prompt(*, conceptual_surprise: bool) -> str:
    heuristics = (
        _CONCEPTUAL_SURPRISE_HEURISTICS
        if conceptual_surprise
        else _BASE_HEURISTICS
    )
    return "\n".join(
        [
            "You are an expert research scientist instantiating a structured skill-based edit plan into a concrete research idea.",
            "",
            "Given a compiled edit plan (skill + atomic component edits + validation protocols), your job is to fill in the concrete, topic-specific content for each field.",
            "",
            "== Context ==",
            "Topic: {topic}",
            "Fixed root domains for this MCTS run: {root_domains}",
            "Fixed scientific intervention profile:",
            "{scientific_intervention_profile}",
            "Refinement scope: {refinement_scope}",
            "Taste guidance (soft preference only): {taste_guidance}",
            "Mature idea (ANCHOR): {mature_idea}",
            "Parent idea: {parent_summary}",
            "Parent scientific objects (legacy component field in the current idea): {parent_components}",
            "Literature context: {paper_context}",
            "Memory bundle: {memory_bundle}",
            "Skill-specific mechanism references: {skill_references}",
            "{additional_retrieval_context}",
            "",
            "== Compiled Edit Plan ==",
            "Skill: {skill_name}",
            "Objective: {plan_objective}",
            "Target defects: {target_defects}",
            "Component/object edits (legacy atomic blueprint, already compiled; placeholders must be mapped using the profile-native scientific object schema):",
            "{component_edits}",
            "Validation protocols:",
            "{validation_protocols}",
            "Guardrails: {guardrails}",
            "",
            "== Hard Constraints ==",
            "Satisfy all of the following:",
            _numbered_lines(_BASE_HARD_TASKS),
            "",
            "== Heuristics ==",
            "When multiple outputs satisfy the hard constraints, prefer the following:",
            _numbered_lines(heuristics),
            "",
            _build_output_schema(conceptual_surprise=conceptual_surprise),
            "",
        ]
    )


SKILL_INSTANTIATION_PROMPT = _build_skill_instantiation_prompt(
    conceptual_surprise=False
)

CONCEPTUAL_SURPRISE_SKILL_INSTANTIATION_PROMPT = _build_skill_instantiation_prompt(
    conceptual_surprise=True
)


def get_skill_instantiation_prompt(
    mode: Optional[str] = None,
    *,
    profile_id: Optional[str] = None,
) -> str:
    prompt = (
        CONCEPTUAL_SURPRISE_SKILL_INSTANTIATION_PROMPT
        if is_conceptual_surprise_mode(mode)
        else SKILL_INSTANTIATION_PROMPT
    )
    normalized_profile = str(profile_id or "").strip().lower()
    if normalized_profile and normalized_profile != "computational_algorithmic":
        replacements = {
            "Parent scientific objects (legacy component field in the current idea):": "Parent scientific objects:",
            "Component/object edits (legacy atomic blueprint, already compiled; placeholders must be mapped using the profile-native scientific object schema):": "Profile-native scientific object edits (already compiled; placeholders must be mapped using the selected object schema):",
            "component edit count": "scientific-object edit count",
            "Only a computational profile should mention standard losses, optimizers, datasets, encoders, or training contracts; other profiles should use their native evidence terms.": "Use the fixed profile's native evidence terms and do not add an unrelated optimization or training contract.",
            "You may mention computational losses, optimizers, datasets, encoders, or helper routines only when the fixed profile makes them central; otherwise use profile-native evidence without adding": "Use profile-native evidence and helper routines only when the fixed profile makes them central; otherwise do not add",
            "For non-computational profiles, missing loss, optimizer, dataset, encoder, training signal, or benchmark is not an innovation or completeness defect. Use synthesis, processing, intervention, cohort, endpoint, assumption, proof, observation, design, or safety evidence as appropriate instead.": "For non-computational profiles, judge completeness from the selected object, intervention, mechanism, observation, proof, design, or safety evidence rather than an optimization contract.",
        }
        for source, target in replacements.items():
            prompt = prompt.replace(source, target)
    return prompt
