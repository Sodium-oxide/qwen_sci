ROOT_DOMAIN_CLASSIFICATION_PROMPT = """
You classify the home research discipline of the ROOT idea in a memory-guided MCTS run.

Choose only from this natural-science and engineering allowlist. Each line shows
the canonical key, human label, and provider-native discovery categories:
{discipline_catalog}

Selection rules:
1. Classify the ROOT idea's home discipline, not an inspiration discipline.
2. Select at most two canonical keys from the catalog.
3. Human, social-science, business, law, education, history, and philosophy-only
   topics are out of scope. Do not map them to computer science.
4. If evidence is insufficient, return unresolved and no discipline keys.
5. If two natural-science disciplines are genuinely central, return ambiguous;
   otherwise return resolved with one primary key and optional adjacent keys.

== Topic ==
{topic}

== Root idea snapshot ==
{root_idea}

== Return STRICT JSON ==
{{
  "status": "resolved | ambiguous | unresolved | out_of_scope",
  "primary_discipline": "canonical_key_or_empty",
  "adjacent_disciplines": ["optional_canonical_key"],
  "confidence": 0.0,
  "matched_terms": ["short evidence phrase"],
  "reasoning": "brief explanation"
}}
"""
