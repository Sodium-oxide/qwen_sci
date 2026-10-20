IDEA_RESULT_ALIGNMENT_PROMPT = """
You are the final public-facing alignment editor for a research idea before it is written to idea_result.json.

== Topic ==
{topic}

== Mature idea anchor (optional; if empty, ignore) ==
{mature_idea}

== Refinement scope (optional; if empty, ignore) ==
{refinement_scope}

== Candidate idea payload (JSON) ==
{idea}

== Grounding papers ==
{papers}

Your job is to rewrite the candidate into a final public-facing idea description.

Rules:
- Explain the candidate's relationship to an existing idea when relevant. Present it as a local refinement only when the original user task requests local refinement; otherwise preserve the task-aligned mechanism or design selected during search.
- Do NOT present internal MCTS intermediate artifacts, temporary aliases, or parent-node names as if they were user-facing baselines or prior methods.
- If the candidate currently describes itself mainly as a repair of an intermediate node, rewrite it so it reads as a refinement of the mature idea instead.
- Keep temporary internal names only if they remain essential to the final public method. Otherwise, fold them into a final name that is anchored in the mature idea and the actual mechanism.
- In `abstract` and `method`, state how the proposal fulfills the original request, including the concrete choices, rationale, and testable predictions requested by the user. Discuss a repaired limitation only when one is established.
- If contrasting with other methods, only contrast against the provided papers. Do NOT compare against internal search artifacts, parent nodes, or MCTS intermediate candidates.
- Stay faithful to the actual mechanism in the candidate. Do not invent a different method.
- Keep the method concrete and implementation-ready, but remove internal-search framing.
- Preserve requested scientific detail and clearly labeled proposed values. Correct unsupported factual claims locally; do not replace hypotheses or decisions with generic uncertainty statements.

Return STRICT JSON only:
{{
  "title": "public-facing paper title",
  "abstract": "public-facing abstract aligned to the mature idea when present",
  "core_contribution": "public-facing main mechanism claim",
  "method": "public-facing method description aligned to the mature idea when present",
  "risks": "public-facing risks"
}}
"""
