SCIENTIFIC_MATERIALIZATION_PROMPT = """
You are materializing a research idea into a profile-aware scientific specification.

== Topic ==
{topic}

== Fixed scientific intervention profile ==
{scientific_intervention_profile}

== Scientific object schema ==
{scientific_object_schema}

== Idea ==
Title: {idea_title}
Abstract: {idea_abstract}
Core contribution: {idea_core_contribution}
Method: {idea_method}
Components and roles: {idea}

Return STRICT JSON only:
{{
  "scientific_spec": {{
    "schema_version": "scientific_materialization_v1",
    "profile_id": "profile id copied from the fixed profile",
    "spec_type": "profile-native specification type",
    "contribution_mode": "allowed contribution mode",
    "object_type": "profile-native object type",
    "target_object": "specific target object, population, process, relation, or formal entity",
    "intervention_or_transformation": "what is changed, assumed, constructed, or compared",
    "mechanism_or_relation": "mechanism, causal relation, derivation, or design rule",
    "evidence_obligation": "minimum evidence, control, proof, comparator, or observation",
    "boundary_condition": "validity, failure, safety, transfer, or regime boundary",
    "measurement_or_observation": "observable, endpoint, characterization, proof check, or readout",
    "steps": ["profile-native step 1", "profile-native step 2"]
  }},
  "legacy_algorithm": []
}}

Rules:
- The fixed profile controls the schema and vocabulary. Do not emit an algorithm specification for a non-computational profile.
- For a computational_algorithmic profile, `legacy_algorithm` may contain the existing algorithm schema with name/input/output/pipeline.
- For all other profiles, keep `legacy_algorithm` an empty list and put the complete result in `scientific_spec`.
- Do not turn a material process, clinical intervention, environmental observation, engineering operation, or formal proof obligation into a module, training objective, benchmark, or pipeline.
- Every field must be concrete and traceable to the idea; do not invent data or unsupported evidence.
"""
