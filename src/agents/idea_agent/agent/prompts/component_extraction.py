COMPONENT_EXTRACTION_PROMPT = """
You are an expert research scientist. Given a mature research idea and a fixed scientific intervention profile, extract its key domain-native research components.

Each component should be a concise name (2-5 words, snake_case) representing a distinct scientific object, mechanism, intervention, process, relation, measurement, proof object, data step, or evaluation protocol described in the idea.

== Mature Idea ==
{mature_idea}

== Topic ==
{topic}

== Fixed scientific intervention profile ==
{scientific_intervention_profile}

== Previous idea component inventory (reuse these exact names whenever the revised idea still contains the same component role) ==
{prior_components}

== Latest component decisions from re_analysis_replan ==
{component_decisions}

Return STRICT JSON (no Markdown wrapping):
{{
  "components": ["component_name_1", "component_name_2", ...],
  "component_explanations": {{
    "component_name_1": "Short explanation of the role this component plays in the idea.",
    "component_name_2": "Short explanation of the role this component plays in the idea."
  }}
}}

== Rules (Strict) ==
-  Extract at least 1 and at most 5 components.
-  Each component must be a distinct, non-overlapping part of the idea's scientific object, intervention, mechanism, or methodology.
-  Use short, descriptive snake_case names. Examples are profile-native roles such as "controllable_process", "causal_mediator", "measurement_endpoint", or "proof_obligation"; choose concrete names from the idea rather than copying these examples.
-  Do NOT include generic placeholders such as "unnamed_object" or "generic_process" — be specific to this idea.
-  Do not invent profile objects merely because the discipline is unresolved; use the selected profile's object, intervention, mechanism, observable, comparator, and boundary roles instead.
-  If the revised mature idea keeps or strengthens a prior component, reuse the exact prior component name instead of inventing a synonym.
-  Component explanations may change; name reuse matters more than explanation reuse.
-  If a component is genuinely replaced with a different mechanism, create a new name only when the functional role has materially changed.
-  Prefer the smallest stable rename set: reuse old names wherever reasonable, introduce new names only for genuinely new components.
-  Order objects by their importance to the central claim (most claim-critical first).
"""


def render_component_extraction_prompt(profile_id: str = "") -> str:
    """Render extraction wording without computational vocabulary for non-CS profiles."""

    prompt = COMPONENT_EXTRACTION_PROMPT
    if str(profile_id or "").strip().lower() == "computational_algorithmic":
        return prompt
    replacements = {
        "Each component should be a concise name": "Each scientific object should be a concise name",
        "Previous idea component inventory (reuse these exact names whenever the revised idea still contains the same component role)": "Previous scientific-object inventory (reuse these exact names whenever the revised idea still contains the same role)",
        '"components": ["component_name_1", "component_name_2", ...],': '"components": ["scientific_object_1", "scientific_object_2", ...],',
        "Each component must be a distinct, non-overlapping part": "Each scientific object must be a distinct, non-overlapping part",
        "If a component is genuinely replaced with a different mechanism, create a new name": "If a scientific object is genuinely replaced with a different mechanism, create a new name",
        "If the revised mature idea keeps or strengthens a prior component, reuse the exact prior component name": "If the revised mature idea keeps or strengthens a prior scientific object, reuse the exact prior name",
        "Component explanations may change; name reuse matters more than explanation reuse.": "Scientific-object explanations may change; name reuse matters more than explanation reuse.",
        "Prefer the smallest stable rename set": "Prefer the smallest stable scientific-object rename set",
    }
    for source, target in replacements.items():
        prompt = prompt.replace(source, target)
    return prompt
