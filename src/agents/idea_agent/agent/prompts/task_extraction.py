"""Task extraction is independent of title/seed interpretation."""

TASK_EXTRACTION_PROMPT = """
Extract the user's task contract from the original request below. Return strict JSON.
Do not use literature, infer new prohibitions, or turn review concerns into requirements.
task_mode is an advisory preference: idea_generation, idea_refinement, or protocol_design.
A task can include several activities; preserve every explicit deliverable regardless of mode.
For each item use an exact source_quote and an acceptance_description that operationalizes it.
Use [] only after checking that the request has no items of that kind.
Return extraction_status complete only after checking the whole request; otherwise partial.
Schema:
{{"task_mode": "...", "task_mode_source_quote": "...", "extraction_status": "complete|partial",
  "required_deliverables": [{{"source_quote": "...", "acceptance_description": "..."}}],
  "user_constraints": [{{"source_quote": "...", "acceptance_description": "..."}}],
  "problem_premises": [{{"source_quote": "...", "acceptance_description": "..."}}]}}
Original request:
{original_request}
"""
