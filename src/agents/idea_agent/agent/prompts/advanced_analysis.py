ADVANCED_ANALYSIS_PROMPT_SURVEY_LED_WITH_PAPERS = """
You are the research designer preparing a concrete, task-aligned proposal on "{topic}".

== Mature idea (optional; if empty, ignore) ==
{mature_idea}

== Mature idea source ==
{mature_idea_source}

== Refinement scope (optional; if empty, ignore) ==
{refinement_scope}

== Refinement scope source ==
{refinement_scope_source}

You have:
(1) Survey contents (evidence and literature coverage; the original user task defines the objective):
{survey_contents}

(2) Curated cited-paper capsules derived from survey keynotes (source-specific evidence, methods, and implementation details):
{papers}

(3) Experiment findings extracted from raw ablation results (OPTIONAL; use only if present):
{experiment_findings}

Core principles:
- The original user request defines the research object, goal, explicit restrictions, and deliverables.
  Survey and papers supply evidence and methods; their coverage does not limit what the user may ask you to design.
- Follow the task mode: `idea_refinement` makes scoped improvements to an existing idea;
  `idea_generation` explores distinct mechanisms within the task; `protocol_design` makes concrete design decisions
  and supplies the requested methodological detail. An existing seed alone does not require minimal edits.
- A refinement_scope is a hard boundary only when its source is `config_explicit`, `input_explicit`,
  `user_explicit`, or `explicit`. Inferred and analysis-generated scopes are revisable suggestions.
- Separate literature facts, user premises, proposed design choices, hypotheses, predictions, and observed results.
  State proposed choices and testable predictions concretely, with rationale and a validation path.
  Missing direct validation is a reason to test a hypothesis, not to omit a requested candidate or design choice.
- Preserve exact source identifiers and reported values. Never invent evidence, observed results, or citations.
  A missing cached source is a retrieval need, not evidence that the scientific relation is unresolved.
- List only problems, counterexamples, and gaps supported by the supplied material. Empty lists are valid.
  Use papers to extend an incomplete Survey when doing so serves the original task.
- When the user explicitly requests local refinement, preserve the stated edit boundary and justified existing choices.
  For other tasks, compare alternatives and select a useful mechanism or protocol without imposing a minimal-patch rule.

Before answering:
1) Recover the user-required decisions and deliverables from the original task contract.
2) Identify useful method families, established evidence, user premises, and specific retrieval needs.
3) Produce a search-ready root proposal with concrete choices, rationale, and alternatives within the user task.
4) State discriminating observations and validation targets. Include execution detail when requested by the user;
   otherwise leave routine execution to Experiment Agent. Keep unresolved details local to the affected choice.

Return STRICT JSON (no prose, no Markdown) with the schema:
{{
  "key_methods": ["relevant method family"],
  "field_consensus": [],
  "existing_problems": [],
  "evaluation_gaps": [
    {{
      "gap": "an evidenced measurement blind spot; return an empty evaluation_gaps list if none is established",
      "why_it_matters": "impact on validating the mechanism bottleneck or proposed patch",
      "validation_expectation": "what the validation setup must include to measure that mechanism credibly"
    }}
  ],
  "future_directions": [],
  "preserve_current_idea": {{
    "keep_original": false,
    "reason": "why preserving the existing idea fulfills an explicit refinement request; otherwise empty"
  }},
  "mature_ideas": [
    {{
      "idea_id": "stable identifier",
      "title": "independent mature idea title",
      "hypothesis": "central hypothesis",
      "scientific_object": "object or process",
      "mechanism": "causal or formal mechanism",
      "assumptions": ["..."],
      "evidence_basis": [],
      "target_gap_ids": [],
      "refinement_scope": "proposed scientific focus, revisable unless explicitly constrained by the user",
      "falsifier": "result that would refute the idea",
      "counterexamples": [],
      "retrieval_queries": [],
      "mechanism_chain": ["object -> mechanism -> observable consequence"],
      "validation_targets": ["testable target"],
      "anchor_policy": "scoped_survey_anchor|reframe_without_default_problem_anchor",
      "maturity_status": "mature|provisional",
      "idea_source": "user_input|survey_gap|prior_candidate|experiment_feedback|problem_reframing|adversarial_generation|cross_domain_transfer",
      "lineage": "where this idea came from",
      "independence_rationale": "structural difference from other mature ideas"
    }}
  ],
  "grounded_mature_idea": "3-6 sentences describing a concrete task-aligned proposal, distinguishing evidence from explicit assumptions and predictions",
  "grounded_refinement_scope": "optional proposed focus; may be empty and never creates a user restriction",
  "root_idea": {{
    "title": "one concrete task-aligned root proposal title",
    "abstract": "the proposal, its purpose, and the proposed mechanism or protocol",
    "core_contribution": "the scientific hypothesis, mechanism, or design contribution requested by the user",
    "method": "concrete choices, rationale, alternatives, and task-required implementation details; label proposed values and predictions",
    "risks": "main scientific/engineering risks",
    "target_defects": [],
    "rationale": "how the proposal fulfills the original request and why its decisions are scientifically useful",
    "supporting_papers": []
  }},
  "divergent_idea_seeds": [
    {{
      "title": "short memorable name",
      "hypothesis": "a useful alternative within the user's task",
      "why_it_is_not_incremental": "the substantive difference, or empty when inapplicable",
      "method_sketch": "concrete alternative mechanism or design",
      "evaluation_plan": "protocol/stress-test to validate the patch",
      "risk": "dominant scientific or engineering risk",
      "supporting_papers": ["SURVEY_ANCHOR:...", "PAPER_ANCHOR:..."]
    }}
  ],
  "cross_domain_inspiration": [
    {{
      "source_field": "e.g., control theory, neuroscience",
      "transferable_mechanism": "the mechanism or method borrowed",
      "application_hook": "how it serves the user's objective within explicit task constraints"
    }}
  ],
  "tldr": "≤50 word synthesis of the proposal and its task-relevant decisions"
}}

== Rules (Strict) ==
- Always output exactly one `root_idea`; it must be concrete enough to act as the MCTS root node.
- `root_idea` must answer the original task. An evidenced problem may motivate it, but a new problem is not required.
- Preserve user-explicit constraints. Use proposed scopes as focus suggestions, not hard prohibitions.
- `divergent_idea_seeds` are optional alternatives; each must serve the original task and describe a concrete mechanism or decision.
- `mature_ideas` may contain multiple structurally independent mature seeds. Do not create title-only variants; distinguish object, assumptions, mechanism, intervention, representation, target gaps, or falsifier.
- Mature ideas may come from `user_input`, `survey_gap`, `prior_candidate`, `experiment_feedback`, `problem_reframing`, `adversarial_generation`, or `cross_domain_transfer`; preserve the exact source and a structured lineage record for each mature idea. Do not collapse these sources into generic `survey`, `history`, or `generated` labels.
- Keep problem-reframing or adversarial records as formal exploratory/provisional ideas when they challenge the default problem definition; do not discard them solely for lower feasibility.
- Facts and citations must match the supplied source. Hypotheses and design choices may extend beyond established findings
  when clearly labeled and accompanied by reasoning and a validation path.
- Return empty lists for absent consensus, established problems, counterexamples, unnecessary retrieval queries, or gap IDs.
- Cite only supplied anchors or exact source quotations; never invent an anchor, paper ID, or a literature gap.
- Keep the JSON valid and free of commentary.
"""

# Backward-compatible alias expected by prompt registry/imports.
ADVANCED_ANALYSIS_PROMPT = ADVANCED_ANALYSIS_PROMPT_SURVEY_LED_WITH_PAPERS


def render_advanced_analysis_prompt(prompt: str, profile_id: str | None = None) -> str:
    """Keep the pre-MCTS survey analysis in the selected scientific vocabulary."""

    if str(profile_id or "").strip().lower() == "computational_algorithmic":
        return prompt
    replacements = {
        "method clusters + unresolved mechanism bottlenecks + evaluation blind spots": "scientific object/process clusters + unresolved mechanism bottlenecks + evidence blind spots",
        "supervision/training signals": "evidence, observations, or operating conditions",
        "implementation constraints or operating assumptions": "implementation, intervention, measurement, or operating assumptions",
        "gate/router/controller/monitor style patches": "generic wrapper or decision-layer patches",
        "gate/router/controller/monitor": "generic wrapper or decision-layer",
        "gate/router/controller": "generic decision layer",
        "gate/threshold/router": "generic decision layer",
        "gate-like control logic": "generic decision logic",
        "threshold/budget": "decision-layer/resource",
        "gating/routing/control logic": "generic decision logic",
        "gate, router, controller, monitor, or threshold": "generic decision or audit layer",
        "threshold policy": "decision policy",
        "trainable controller": "fitted or control layer",
        "auxiliary loss": "auxiliary fitting criterion",
        "learned module": "fitted component",
        "fine-tuning": "additional optimization",
        "fine tuning": "additional optimization",
        "representation": "scientific object description",
        "task-solving mechanism": "scientific mechanism",
        "update rule, objective, representation, or training contract": "process rule, causal relation, measurement construct, assumption, or evidence contract",
        "objective, representation, update contract, or training contract": "process rule, causal relation, measurement construct, assumption, or evidence contract",
        "objective, representation, or training contract": "process rule, causal relation, measurement construct, or evidence contract",
        "new training stage, trainable controller, auxiliary loss, fine-tuning loop, or learned module": "unrelated optimization stage, control wrapper, or auxiliary computational layer",
        "training-free or inference-time": "non-learning, observation-only, or intervention-only",
        "training-free": "non-learning",
        "optimization or calibration-free": "non-learning",
        "training-free ideas": "non-learning or intervention-only ideas",
        "training-free local repairs": "profile-native local repairs",
        "modules/objective/training contract": "objects/processes/relations/evidence contract",
        "modules/objective/update contract": "objects/processes/relations/evidence contract",
        "modules/objective": "objects/processes/relations",
        "learned controller": "generic control wrapper",
        "fine-tuning machinery": "unrelated optimization machinery",
        "representation change": "object or relation change",
        "update rule": "process or causal rule",
        "training contract": "evidence contract",
        "training signals": "evidence or operating signals",
        "training": "optimization or calibration",
        "supervision": "evidence or observation",
        "modules": "scientific objects",
        "objective": "claim or process target",
    }
    for source, target in replacements.items():
        prompt = prompt.replace(source, target)
    return prompt
