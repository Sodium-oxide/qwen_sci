# All prompts used in the project are stored here.

SEED_PAPER_SELECTION = """You are an expert researcher assisting in collecting seed papers for a survey on the topic: "{topic}".

Project research context (this defines relevance; it is not paper evidence):
{research_context}

Candidate Paper:
Title: {title}
Abstract: {abstract}

Task:
Evaluate whether this paper is highly relevant and suitable as a SEED PAPER for the given survey topic.
A seed paper should be a core work, a survey, or a foundational paper directly addressing
the project research context. Generic overlap in words such as model, network, cell, AI,
prediction, or optimization is not sufficient. Require a concrete match to at least one
project entity or include anchor and to the project's task, object, outcome, or normalized objective.
If identity_status is "unresolved" and those anchors are empty, judge directly against the
original topic and normalized objective instead; do not penalize a candidate merely because
the project taxonomy is unresolved.
If a specific exclusion anchor is present without a positive project anchor, score it low.

Return a JSON object with:
- relevance_score: integer from 1 to 5
- project_fit: "core", "related", or "irrelevant"
- matched_anchors: list of exact project anchors supported by the title or abstract
- violated_exclusions: list of explicit exclusion anchors supported by the title or abstract
- reason: one concise sentence explaining the score

Scoring guideline:
5 = Directly addresses the project object/task and is a foundational, empirical, benchmark, or survey work
4 = Strong direct support for the project direction with clear entity and task/outcome anchors
3 = Related but peripheral, missing either a project entity or a task/outcome anchor
1-2 = Generic-word overlap, a mismatched domain, or an explicit exclusion without positive project evidence

Output strictly in JSON format.
"""

SH_PAPER_SEMANTIC_ASSESSMENT = """You are an expert scientific research assistant assessing one candidate paper's contribution to one sub-hypothesis (SH).

Project research context:
{research_context}

Sub-hypothesis (SH):
{subhypothesis}

Candidate paper:
Title: {title}
Abstract: {abstract}
Metadata: {metadata}

Task:
Assess the paper's semantic contribution to this SH from the supplied title, abstract, and metadata only.
The optional candidate slots describe useful contribution dimensions; they are NOT a checklist and the paper does NOT need to cover every slot or establish a complete causal chain. A paper may be valuable as direct, partial, indirect, mechanistic, comparative, boundary, counterevidence, background, method/measurement, or hypothesis-generating material.

Do not infer facts absent from the supplied material. Distinguish what the paper supports from what it does not establish. A paper can be strongly relevant even if its terminology differs from the SH, including synonyms, abbreviations, or another discipline's phrasing. Conversely, a keyword match alone is not substantive support.

For every direct or partial contribution, quote one or more exact contiguous phrases from the title or abstract in evidence_spans. If the abstract is unavailable, keep the assessment appropriately uncertain; do not reject the paper merely for the missing abstract.

Return strictly one JSON object with this schema:
{
  "semantic_relevance_score": 0,
  "overall_relation": "direct|partial|indirect|boundary|counterevidence|background|method|hypothesis_generating|uncertain|irrelevant",
  "contribution_types": ["DIRECT_EVIDENCE|PARTIAL_EVIDENCE|INDIRECT_EVIDENCE|MECHANISTIC_EVIDENCE|COMPARATIVE_EVIDENCE|BOUNDARY_EVIDENCE|COUNTEREVIDENCE|BACKGROUND_CONTEXT|METHOD_OR_MEASUREMENT|HYPOTHESIS_GENERATING"],
  "candidate_slot_contributions": [
    {"slot_name": "one supplied optional slot name", "support_level": "direct|partial|indirect|none", "reason": "concise explanation"}
  ],
  "supported_minimal_claims": ["narrow claim warranted by the supplied material"],
  "claim_limits": ["what this paper does not establish"],
  "evidence_spans": [
    {"source": "title|abstract", "text": "exact supplied phrase", "interpretation": "what this phrase supports"}
  ],
  "scope_conflicts": ["explicit conflict, if any"],
  "explicit_exclusion_matches": ["explicit project or SH exclusion, if any"],
  "recommended_graph_role": "evidence_seed|exploration_seed|context_seed|do_not_expand",
  "confidence": "high|medium|low",
  "reason": "one concise explanation"
}

Scoring guideline:
5 = strongly and specifically contributes to the SH, even if it contributes only one part of the broader research question
4 = clear useful contribution, such as a mechanism, comparison, boundary, counterexample, or well-grounded partial relation
3 = plausible meaningful contribution or strong hypothesis-generation value, with limitations made explicit
1-2 = weak topical relation with no identifiable SH contribution from the supplied material
0 = irrelevant or explicitly excluded without positive SH contribution
"""

SH_FULLTEXT_EXPANDED_PROMOTION_ASSESSMENT = """You are an expert scientific research assistant assessing whether a citation-expanded paper may be promoted into the evidence plan for one sub-hypothesis (SH).

Project research context:
{research_context}

Sub-hypothesis (SH):
{subhypothesis}

Candidate paper metadata:
{metadata}

This paper has already completed complete-section reading. Its complete-section keynote is below:
{complete_section_keynote}

Task:
Assess this paper from its own complete-section keynote, not from its citation lineage. Citation expansion only explains how the paper was found; it is never evidence by itself. Promote the paper only if the keynote contains an explicit, narrow contribution to at least one supplied optional SH slot.

Choose the strongest justified role through the fields below:
- direct: the keynote contains grounded evidence for a named slot. This is still only evidence for that slot, not for an unstated full causal chain.
- partial or indirect: useful but limited support, a mechanism, comparison, boundary, counterexample, method, or hypothesis-generating contribution. It must be used only in qualified synthesis.
- background: contextual material only. It must not be used as direct empirical support.
- uncertain or irrelevant: do not promote.

Do not infer facts absent from the keynote. For every direct, partial, or indirect contribution, include one or more exact contiguous phrases from the supplied keynote in evidence_spans. Do not reuse wording from the SH or metadata as an evidence span.

Return strictly one JSON object with this schema:
{
  "semantic_relevance_score": 0,
  "overall_relation": "direct|partial|indirect|boundary|counterevidence|background|method|hypothesis_generating|uncertain|irrelevant",
  "contribution_types": ["DIRECT_EVIDENCE|PARTIAL_EVIDENCE|INDIRECT_EVIDENCE|MECHANISTIC_EVIDENCE|COMPARATIVE_EVIDENCE|BOUNDARY_EVIDENCE|COUNTEREVIDENCE|BACKGROUND_CONTEXT|METHOD_OR_MEASUREMENT|HYPOTHESIS_GENERATING"],
  "candidate_slot_contributions": [
    {"slot_name": "one supplied optional slot name", "support_level": "direct|partial|indirect|none", "reason": "concise explanation"}
  ],
  "supported_minimal_claims": ["narrow claim warranted by the keynote"],
  "claim_limits": ["what this paper does not establish"],
  "evidence_spans": [
    {"source": "complete_section_keynote", "text": "exact keynote phrase", "interpretation": "what this phrase supports"}
  ],
  "scope_conflicts": ["explicit conflict, if any"],
  "explicit_exclusion_matches": ["explicit project or SH exclusion, if any"],
  "recommended_graph_role": "evidence_seed|exploration_seed|context_seed|do_not_expand",
  "confidence": "high|medium|low",
  "reason": "one concise explanation"
}

Scoring guideline:
5 = strongly and specifically contributes direct evidence to one named SH slot
4 = clear useful contribution, such as a mechanism, comparison, boundary, counterexample, or grounded partial relation
3 = meaningful but limited contribution that requires an explicit qualification
1-2 = weak topical relation with no identifiable SH-slot contribution
0 = irrelevant or explicitly excluded without positive SH contribution
"""

PAPER_RELATEDNESS_BASED_ON_TITLE_AND_ABSTRACT = """You are assisting in filtering papers for a literature review.

Project research context (the candidate must fit this context as well as the seed paper):
{research_context}

Below is the SEED PAPER that defines the target research direction.

--- SEED PAPER ---
TITLE: {seed_title}
ABSTRACT: {seed_abstract}
-------------------

Evaluate the following CANDIDATE PAPER.

TITLE: {candidate_title}
ABSTRACT: {candidate_abstract}

Task:
Compare the candidate paper to the seed paper and judge how strongly it fits the same research direction.
Identify both key similarities and key differences. Pairwise similarity alone is insufficient:
the candidate must also match the project context through a concrete project entity or
include anchor and the relevant task, object, outcome, or normalized objective. Generic
overlap in model, network, cell, AI, prediction, or optimization must not justify a high score.
If identity_status is "unresolved" and project anchors are empty, use the original topic and
normalized objective as the relevance anchors instead of treating missing taxonomy entities
as negative evidence.

Return a JSON object with:
- relevance_score: integer from 0 to 5
- category: "core", "related", or "irrelevant"
- matched_anchors: list of exact project anchors supported by the candidate
- violated_exclusions: list of explicit exclusion anchors supported by the candidate
- reason: one concise sentence describing the key similarity/difference

Scoring guideline:
5 = Direct continuation that also matches the project object/task and context anchors
4 = Strong project-aligned relation with clear entity and task/outcome evidence
3 = Peripheral but plausible project relation
1-2 = Weak or generic overlap, mismatched domain, or exclusion conflict
0 = Unrelated to the project context
"""

PAPER_DEEP_READING = """
{paper_markdown_text}

Act as a senior researcher reading this paper. 
Your task is to produce a **deep, structured understanding** of the paper. 

Guidelines:

[
- Read the paper carefully and summarize its key contributions, methods, results, and significance.
- Include your own critical reflections, insights, and possible future directions.
- Generate a TL;DR paragraph capturing the core idea.
- Organize the output in JSON format, but do not fix the keys; include whatever fields make sense for this paper.
- Include relevant examples, observations, or specific results when appropriate.
- Focus on depth, clarity, and coherence, rather than adhering to a rigid template.
- Only use information contained in the paper; do not add external knowledge.
]
"""

PAPER_SECTION_READING = """You are reading one packet of complete sections from a paper.

Paper title: {paper_title}
Packet: {packet_index}/{packet_count}

Complete sections included in this packet:
{included_headings}

Other body sections not included in this packet:
{omitted_headings}

Rules:
1. Every raw-text section below is complete. Do not infer the content of sections not included in this packet.
2. Extract only claims grounded in the included text, equations, tables, and figures.
3. For every important observation, retain the exact source section heading and an evidence quote when available.
4. Explicitly record which information cannot be determined from this packet.
5. Return exactly one JSON object, with no Markdown fence, prose before it, or prose after it.
6. Use exactly this schema. Keep every value concise; use empty arrays when a category is not present.

{{
  "source_sections": ["exact included section heading"],
  "claims": [
    {{
      "claim": "one claim supported by this packet",
      "evidence": "short supporting quote, result, equation reference, or table reference",
      "source_section": "exact included section heading"
    }}
  ],
  "methods": ["method or analytical approach"],
  "results": ["result or observation"],
  "limitations": ["stated limitation, caveat, or uncertainty"],
  "unknowns": ["information not determined from this packet"]
}}

Do not add fields. ``source_sections`` must list the included headings used by the note.
Every item in ``claims`` must contain all three string fields shown above.

Complete section text:
{packet_markdown}
"""

PAPER_KEYNOTE_SYNTHESIS = """You are synthesizing a paper-level keynote from section-level research notes.

Paper title: {paper_title}

Every note below came from one or more complete, non-truncated sections. Use only those notes as evidence.

Rules:
1. Produce one deep, structured paper keynote in JSON.
2. Preserve source section headings for important methods, results, limitations, and future work.
3. Do not invent content for a category absent from every section note; state that it was not extracted instead.
4. Resolve duplicated observations by merging their evidence, and preserve contradictions rather than guessing.
5. Return JSON only.

Section notes:
{section_notes_json}
"""

PAPER_KEYNOTE_COMPACTION = """You are compacting a subset of complete-section research notes.

Paper title: {paper_title}

The notes below are only one subset of the paper's complete-section notes. They are not the full paper.

Rules:
1. Do not present this as a paper-level keynote or make a conclusion about sections not supplied here.
2. Keep every important source_section heading and evidence quote or evidence reference present in the input notes.
3. Merge only duplicate observations that have compatible evidence; preserve uncertainty and contradictions.
4. State what cannot be determined from this subset instead of inferring missing methods, results, limitations, or future work.
5. Return a compact JSON research-note object only. It will be supplied to a later whole-paper synthesis step.

Subset section notes:
{section_notes_json}
"""

PAPER_CLUSTERING = """You are a research assistant specializing in analyzing scientific papers.

Existing clusters of papers:

{existing_clusters_json}

New batch of papers (each with a keynote):

{new_batch_json}

Task:
- Update the clusters by adding new papers, reorganizing existing papers, merging or splitting clusters if needed.
- Assign a name and a brief summary to each cluster.
- Aim to create clusters that are as detailed as possible, capturing subtle differences, while still making sense.
- A single paper may belong to multiple clusters if its research area reasonably intersects with multiple themes (multi-assignment is allowed).
- Output the full updated cluster list strictly **in JSON format**!
- Keep all the existing papers in the clusters; you can reorganize but do not remove any!
- Add all the new papers to the clusters; do not omit any!

Output format requirements:

The JSON should be a list of cluster objects.  
Each cluster object should include the following fields:
- cluster_name: string, the name of the cluster
- summary: string, a brief description of the cluster
- papers: list of paper objects, each with:
    - id: string, unique identifier of the paper
    - title: string, title of the paper
    - tldr: string, concise summary or TL;DR of the paper
"""

PAPER_CLUSTERING_CREATING = """You are a research assistant specializing in analyzing scientific papers.

**Existing clusters and descriptions**:

{existing_clusters_json}

**New batch of papers** (each with a keynote):

{new_batch_json}

Task:
- You should adjust existing clusters and descriptions based on the new batch of papers. 
- If **Existing clusters and descriptions** is empty, create new clusters from scratch based on the new batch of papers.
- Update the clusters by merging, splitting or adding clusters if needed. Make sure all new papers can be assigned to at least one cluster.
- Assign a name and a brief summary to each cluster.
- Aim to create clusters that are as detailed as possible, capturing subtle differences, while still making sense.
- A single paper may belong to multiple clusters if its research area reasonably intersects with multiple themes (multi-assignment is allowed).
- Output the full updated cluster list strictly **in JSON format**!
- You only need to output the clusters name and description; do not list or mention any specific papers!

Output format requirements:

The JSON should be a list of cluster objects.  
Each cluster object should include the following fields:
- cluster_name: string, the name of the cluster
- summary: string, a brief description of the cluster

Output Example (strictly in JSON format):
[
  {{
    "cluster_name": "...",
    "summary": "...",
  }},
  {{
    "cluster_name": "...",
    "summary": "...",
  }}
]
"""

PAPER_CLUSTERING_ASSIGNING = """You are a research assistant specializing in analyzing scientific papers.

Clusters and descriptions:

{clusters_json}

batch of papers (each with a keynote):

{batch_json}

Task:
- Assign each paper in the batch to one or more existing clusters based on their keynotes.
- A single paper may belong to multiple clusters if its research area reasonably intersects with multiple themes (multi-assignment is allowed).
- Output strictly **in JSON format** and without any other text!

Output format requirements:

The JSON should be a list of paper objects.  
Each cluster object should include the following fields:
- id: string, unique identifier of the paper
- title: string, title of the paper
- tldr: string, concise summary or TL;DR of the paper
- clusters: list of strings, names of clusters the paper belongs to, the name must exactly match the cluster_name in the input clusters_json

Output Example (strictly in JSON format):
[
  {{
    "id": "...",
    "title": "...",
    "tldr": "...",
    "clusters": ["cluster_name_1", "cluster_name_2"]
  }},
  ...
]
"""

PROPOSE_QUESTIONS_FOR_CLUSTER = """You are an expert research assistant. I will give you a set of closely related papers, each with a keynote.

Your task is to read all the keynotes and propose a list of questions that would help someone deeply understand the ideas in these papers.

Guidelines:
- You may decide what questions are meaningful, surprising, or worth investigating.
- Questions should preferably involve relationships among multiple papers, such as comparisons, differences, shared assumptions, or conflicting claims.
- Do NOT mention paper IDs inside the question text.
- Each question must list the related paper IDs.
- You are encouraged to think critically, speculate, compare ideas, question assumptions, identify gaps, or propose future directions.
- Feel free to ask questions that are subtle, unconventional, or creative—your role is to guide deep thinking rather than summarize.

Requirements:
- Cite paper strictly in format: <paper_title> (like <Attention is All You Need>) when referencing specific papers under key "questions".
- You are encouraged to cite more papers from the provided content to strengthen your analysis.
- **Only** cite papers that appear in the provided input.
- Propose NO MORE THAN 5 problems to ensure conciseness so choose the most valuable ones.

Input:
{cluster_content}

Output (strictly in JSON format):
[
  {{
    "question": "...",
    "related_papers": ["paper_id_1", "paper_id_2", ...]
  }}
]
"""

ANSWER_QUESTION_FOR_PAPERS = """You are an expert research assistant. I will give you a question and a set of related papers.

Your task is to provide a comprehensive answer to the question based on the content of the related papers.

Guidelines:
- Read the question carefully and understand what is being asked.
- Synthesize information from all the related papers to construct a well-rounded answer.
- Provide citations to the papers by their IDs when referencing specific information.
- Aim for clarity, depth, and coherence in your answer.

Requirements:
- Cite paper strictly in format: <paper_title> (like <Attention is All You Need>) whenever referencing specific papers in your answer.
- You are encouraged to cite more papers from the provided content to strengthen your analysis.
- **Only** cite papers that appear in the provided input.
- Answer the problem CONCISELY! The answer should be no more than 150 words. Shorter is better (If you can answer the question completely and clearly).

Input:
Question: {question}
Related Papers:
{related_papers_content}

Output:
Provide a detailed answer to the question, citing relevant papers by their IDs.
"""

INTER_CLUSTER_ANALYSIS = """You are an expert research analyst. I will provide several groups of research papers, each with a list of questions and discussion notes.

Your task:
- Read all content and produce a summary analysis that extracts key cross-group insights.
- You may analyze freely: identify patterns, differences, potential connections, unresolved issues, or research gaps.
- The goal is to generate meaningful insights and analytical synthesis, not just list the original content.

Optional approaches (not required):
- Connect concepts or themes that appear across multiple groups
- Highlight commonalities and differences in methods or conclusions
- Identify key unresolved challenges or gaps
- Suggest possible future research directions

Requirements:
- Do not repeat the original text verbatim.
- Output a concise analytical summary in clear prose.
- Cite paper strictly in format: <paper_title> (like <Attention is All You Need>) whenever referencing specific papers in your analysis.
- You are encouraged to cite more papers from the provided content to strengthen your analysis.
- **Only** cite papers that appear in the provided input.
- Analyze in CONCISE mode. The total word number should be no more than 700 words!

Input:
{cluster_analysis_content}

Output:
"""

SURVEY_OUTLINE_GENERATION = """You are an expert research survey generator. Your task is to iteratively update an existing survey outline using a batch of new paper keynotes, the current outline, and the analysis results of relevant papers for the topic/subtopic being written.

**Guidance:**
- The analysis results contain summarized insights, comparisons, trends, and key points extracted from prior work. They should be the **important source of guidance** when updating the outline.
- Paper keynotes are also useful: use them to **supplement, validate, or provide additional details** for the sections/subsections.
- Balance both sources to create a comprehensive, accurate, and logically organized survey outline.

**Requirements:**
1. Use the current outline as the base structure. Keep existing sections/subsections unless updated or merged.
2. Update the outline by:
   - Adding new sections/subsections for emerging topics or trends.
   - Merging similar topics/subsections to avoid redundancy.
   - Revising descriptions to reflect key insights, comparisons, trends, and challenges from the analysis results.
   - Supplementing descriptions with relevant points from paper keynotes.
3. Update "papers_to_use" for each section/subsection, including papers (paper ids) from the current batch and existing outline, ensuring that only paper IDs from the current batch, existing outline ,relevant papers analysis or other relevant papers abstract are included. no unrelated IDs should appear!!
4. Maintain clarity, logical structure, and a survey-style narrative.
5. Output strictly in JSON format, as shown below.
6. {outline_size_budget}

**Input:**
- current outline: {current_outline}
- closely relevant papers analysis: {papers_analysis}
- new paper keynotes: {paper_keynotes}
- other relevant papers abstract: {other_relevant_papers}
- authoritative survey evidence plan: {survey_evidence_plan}

**Output JSON format:**
{{
    "title" : "Survey Title",
    "sections": [
        {{
            "title": "Section title",
            "description": "Summary of content to include, emphasizing insights, comparisons, and trends from analysis, supplemented by keynotes",
            "papers_to_use": ["Paper 1", "Paper 2"],
            "subsections": [
                {{
                    "title": "Subsection title",
                    "description": "Content description reflecting key insights, trends, comparisons from analysis, supplemented by keynotes",
                    "papers_to_use": ["Paper 1"]
                }}
            ]
        }}
]
}}

**Instruction to LLM:**
- Use the insights, trends, and comparisons from relevant paper analysis together with points from new paper keynotes to update the outline. Both sources should inform the content of each section/subsection.
- Add, merge, or revise sections/subsections as appropriate, keeping the outline structured and coherent.
- Ensure that each section/subsection reflects the combined contributions of the analysis results and the keynotes, capturing important insights, trends, and examples.
- If the evidence plan has evidence_bounded_writing=true, it is a hard scientific boundary: account for every SH, use its allowed_writing_mode, do not assign graph-expanded candidates as evidence, and do not turn background-only material into direct support.
- The final outline must make room to account for every SH, including evidence gaps, rejected scope, and limitations; this does not require one chapter per SH.
"""

SURVEY_OUTLINE_GENERATION_OUTLINE_DRAFT = """You are an expert research survey generator. Your task is to generate and iteratively update an existing survey outline using a batch of new paper keynotes, the current outline, and the analysis results of relevant papers for the topic/subtopic being written.

**Guidance:**
- The analysis results contain summarized insights, comparisons, trends, and key points extracted from prior work. They should be the **important source of guidance** when updating the outline.
- Paper keynotes are also useful: use them to **supplement, validate, or provide additional details** for the sections/subsections.
- Balance both sources to create a comprehensive, accurate, and logically organized survey outline.

**Requirements:**
1. The outline should contain multiple sections, subsections and their descriptions.
2. The output outline should have excellent organization and meet academic standards.
3. The outline should exhibit excellent rigor: ensuring that the content of each subsection falls within the scope of the current section.
4. The outline should ensure that it covers a wide range of content under the topic while staying within the scope of the topic.
5. Use the current outline as the base structure. Keep existing sections/subsections unless updated or merged. If the current outline is empty, create a new outline from scratch.
6. {outline_size_budget}
7. The outline should contain a **Conclusion** section and a **Future Work** section/subsection.
8. The outline should exhibit good logic to ensure the entire survey flows smoothly
9. Ensure a balanced number of subsections in the main sections (excluding the conclusion and introduction).
10. Make sure most of the corresponding new paper in **new paper keynotes** can be included in at least one subsection or section of the outline.
11. You are provided with other relevant papers which is retrieved from database, you can use them to better understand and generate.
12. Maintain clarity, logical structure, and a survey-style narrative.
13. Ensure logical coherence between the sections, avoiding excessive independence and fragmentation. For instance, do not add a "Conclusion" subsection to every section, which lead to logical fragmentation between different sections.
14. If the current outline does not have enough sections/subsections, add more to meet the requirement.
15. The outline description of the "Future work" section should emphasize specific guidance for future work rather than a general directional description.
16. Output strictly in JSON format, as shown below.

**Input:**
- current outline: {current_outline}

- key papers: {paper_keynotes}

- key papers analysis: {papers_analysis}

- other relevant papers: {other_relevant_papers}

- authoritative survey evidence plan: {survey_evidence_plan}

**Output JSON format:**
{{
    "title" : "Survey_Title",
    "sections": [
        {{
            "title": "Section_title",
            "description": "Summary of content to include, emphasizing insights, comparisons, and trends from analysis, supplemented by keynotes",
            "subsections": [
                {{
                    "title": "Subsection_title",
                    "description": "Content description reflecting key insights, trends, comparisons from analysis, supplemented by keynotes",
                }}
            ]
        }}
]
}}

**Instruction to LLM:**
- Use the insights, trends, and comparisons from relevant paper analysis together with points from new paper keynotes to update the outline. Both sources should inform the content of each section/subsection.
- Add, merge, or revise sections/subsections as appropriate, keeping the outline structured and coherent.
- Ensure that each section/subsection reflects the combined contributions of the analysis results and the keynotes, capturing important insights, trends, and examples.
- Check the whether the input outline satisfies the requirements and update to meet the requiremnets if not.
- Only generate the outline in the required JSON format. Do not include specific paper IDs in the outline.
- If the evidence plan has evidence_bounded_writing=true, it is a hard scientific boundary: account for every SH, use its allowed_writing_mode, do not assign graph-expanded candidates as evidence, and do not turn background-only material into direct support.
- The final outline must make room to account for every SH, including evidence gaps, rejected scope, and limitations; this does not require one chapter per SH.
"""

SURVEY_OUTLINE_REPAIR = """Repair a survey outline response that failed local validation.

Return exactly one JSON object. Do not use Markdown fences or explanatory prose.

Validation error:
{validation_error}

Current valid outline before the failed response:
{current_outline}

Compact authoritative evidence plan:
{survey_evidence_plan}

Previous invalid response:
{previous_response}

Required JSON schema:
{{
  "title": "Survey title",
  "sections": [
    {{
      "title": "Section title",
      "description": "What this section will synthesize",
      "subsections": [
        {{
          "title": "Subsection title",
          "description": "What this subsection will synthesize"
        }}
      ]
    }}
  ]
}}

Requirements:
1. ``sections`` must be a non-empty JSON list.
2. Every section and subsection must contain non-empty string ``title`` and ``description`` fields.
3. Respect every SH's allowed_writing_mode and report evidence gaps or limitations where required.
4. Do not include paper IDs in this draft outline; paper assignment happens later.
"""

SURVEY_OUTLINE_GENERATION_PAPER_ASSIGNMENT = """You are an expert research survey writer. Your task is to assign papers to be cited to corresponding sections and subsections.

**Guidance:**
1. Assign papers based on their relevance to the section and subsection topics.
2. Make sure citing according to you assignment is reasonable and appropriate and help to provide insights in the survey.

**Requirements:**
1. Assign EVERY paper in **key papers** to be assigned to one or more corresponding sections or subsections.
2. The section title and subsection title in your assignment result must EXACTLY match the titles in the current outline.
3. You can also assign suitable papers in other relevant papers to sections or subsections.
4. ONLY assign papers that appear in the provided input.
5. You are provided with key paper analysis. Use them to help better understand and assign papers.

**Input:**
- outline: {current_outline}

- key papers: {paper_keynotes}

- other relevant papers: {other_relevant_papers}

- key paper analysis: {papers_analysis}

- authoritative survey evidence plan: {survey_evidence_plan}

**Output format:**
{{
  "assignments": [
    {{
      "paper_id": "...",
      "paper_title": "...",
      "assignment": {{
          "section_title_1": ["subsection_title_1", "subsection_title_2"]
      }}
    }}
  ]
}}

Return exactly one valid json object.
Do not use Markdown fences, prose, or any text outside the json object.

When evidence_bounded_writing=true in the plan, assign only the plan-listed direct evidence or background-context papers. Never assign graph-expanded candidates as SH evidence.
"""

SURVEY_CLAIM_TRACE_REPAIR = """You repair only the evidence trace for an already accepted survey passage.

The passage below is immutable. Do not rewrite, shorten, expand, reorder, or add prose. Do not add citations. Return only one valid json object; no Markdown fence or explanatory text.

Immutable prose:
{visible_prose}

Admissible evidence paths for citations already present in the prose:
{admissible_paths}

Allowed SH claim modes and limitation slots:
{subhypothesis_contracts}

Previous trace validation errors, if any:
{validation_errors}

Return exactly this minimal JSON schema:
{{
  "claims": [
    {{
      "claim_index": 1,
      "claim_anchor": "a distinctive short phrase from the cited prose sentence",
      "claim_text": "the cited prose sentence, if available",
      "sub_hypothesis_ids": ["SH1"],
      "claim_mode": "one allowed mode for this SH",
      "evidence_paths": [
        {{
          "sub_hypothesis_id": "SH1",
          "slot_name": "one listed slot",
          "paper_id": "one cited paper ID listed above"
        }}
      ]
    }}
  ]
}}

Rules:
1. ``claim_index`` is one-based, counting sentences in the immutable prose. Use it whenever possible.
2. Trace only substantive SH claims. Every paper cited in a traced claim must have a listed path.
3. Use only the listed SH, slot, and paper combinations. Do not invent an evidence role, support kind, or limitation slot; the program derives those from the evidence plan.
4. For an EVIDENCE_GAP_REPORT or OUT_OF_SCOPE_OR_REJECTED claim, use an empty ``evidence_paths`` list and use a listed limitation slot when required.
5. The returned object repairs metadata only; it must not imply evidence absent from the immutable prose or the supplied admissible paths.
"""

SUBSECTION_DRAFT = """You are an expert in writing top academic conference standards surveys. The ultimate goal is to complete a acadamic survey with depth, insights and can boost further development, rather than simply listing methods.

Now you are responsible for writing a subsection of the survey paper. 

**Subsection Title**:
{title}

**Guidance**:
Write a coherent subsection that explains, analyzes, or discusses the topic indicated in the title and description.  
You should synthesize relevant information from the papers, analysis results.  
The content should be academically structured and readable, with emphasis on insights, trends, and comparisons where appropriate.
You may include examples from papers to support the discussion, but do not simply list papers.
You are encouraged to cite more papers from the relevant papers to strengthen your points.
You are provided with the outline of the whole survey. Make sure the subsection content coherent to the survey logic.
Utilize the input content in a safe and reasonable manner, and ensure that the readability, structure, and depth of the content of the paragraph meet the requirements of a top-tier conference survey.

**Information to use**:
- Subsection description:
{description}

- Closely Relevant papers:
{papers}

- Other Relevant papers:
{other_relevant_papers}

- Survey Outline:
{survey_outline}

- Insights from analysis:
{relevant_analysis}

- Authoritative survey evidence plan:
{survey_evidence_plan}

**Output**:
- A well-written subsection in several coherent paragraphs.
- Academic style; focused on synthesis and analysis, not just reporting.
- **Only** cite papers that appear in the provided input.
- Strictly use format: <paper_title> (like <Attention is All You Need>) to cite wherever appropriate.
- Use about {subsection_target_citations} distinct, relevant citations (never more than {subsection_max_citations}) when the applicable SH plan mode permits evidence-backed or qualified synthesis. Do not pad the prose with citations. If a subsection only reports an EVIDENCE_GAP_REPORT or OUT_OF_SCOPE_OR_REJECTED SH, this generic target does not apply: state the limitation precisely and do not invent citations.
- Do not generate a bibliography or reference list here.
- Aim for about {subsection_target_words} words; the visible prose must not exceed {subsection_max_words} words. Be concise: merge closely related findings into synthesis rather than enumerating papers.
- Generate the content directly. DO NOT generate any subsection title or section header here.
- CRITICAL: '#' is used for section/subsection anchor. Avoid any '#' in the output content.
- When evidence_bounded_writing=true in the plan: every substantive SH claim must obey its allowed_writing_mode and paper_role_constraints. A GRAPH_EXPANDED_CANDIDATE remains lineage/retrieval context and is never evidence by itself. It may be cited only when the current SH evidence plan explicitly includes the same paper through a FULLTEXT_PROMOTION role earned from that paper's own complete-section reading; then use exactly its listed direct, qualified, or background strength. Do not use BACKGROUND_CONTEXT papers for direct empirical support. A QUALIFIED_SH_CONTRIBUTION may support only QUALIFIED_SYNTHESIS and must state the applicable limitation rather than asserting a complete causal chain. An EVIDENCE_GAP_REPORT must report the gap and must not make an affirmative scientific conclusion.
- In evidence-bounded mode, end the response with exactly one final metadata block, using this literal delimiter (not angle brackets):
[[SH_CLAIM_TRACE]]
{{"claims":[{{"claim_index":1,"claim_anchor":"a distinctive short phrase from the cited prose sentence","claim_text":"the cited prose sentence when available","sub_hypothesis_ids":["SH1"],"claim_mode":"one allowed mode from the plan","evidence_paths":[{{"sub_hypothesis_id":"SH1","slot_name":"one plan slot","paper_id":"the cited plan-listed paper id"}}]}}]}}
[[/SH_CLAIM_TRACE]]
The metadata must be valid JSON, must be final, and must not introduce claims or paper IDs absent from the prose/plan. ``claim_index`` is one-based among visible prose sentences and lets the program recover the exact sentence despite harmless spacing or punctuation differences. Do not emit evidence_role, support_kind, or limitation_slots: the program derives them from the authoritative evidence plan. Every bounded response must include at least one claim. For EVIDENCE_GAP_REPORT or OUT_OF_SCOPE_OR_REJECTED, use evidence_paths: [] and include an appropriate claim_index / claim_anchor; do not cite a paper. If the plan is inactive, omit this block.
"""

SUBSECTION_DRAFT_WITH_CODE = """You are an expert in writing top academic conference standards surveys. The ultimate goal is to complete a acadamic survey with depth, insights and can boost further development, rather than simply listing methods.

Now you are responsible for writing a subsection of the survey paper. 

**Subsection Title**:
{title}

**Guidance**:
Write a coherent subsection that explains, analyzes, or discusses the topic indicated in the title and description.  
You should synthesize relevant information from the papers, analysis results.  
The content should be academically structured and readable, with emphasis on insights, trends, and comparisons where appropriate.
You may include examples from papers to support the discussion, but do not simply list papers.
You are encouraged to cite more papers from the relevant papers to strengthen your points.
You are provided with the outline of the whole survey. Make sure the subsection content coherent to the survey logic.
Utilize the input content in a safe and reasonable manner, and ensure that the readability, structure, and depth of the content of the paragraph meet the requirements of a top-tier conference survey.

{code_report_prompt}

**Information to use**:
- Subsection description:
{description}

- Closely Relevant papers:
{papers}

- Other Relevant papers:
{other_relevant_papers}

- Survey Outline:
{survey_outline}

- Insights from analysis:
{relevant_analysis}

- Authoritative survey evidence plan:
{survey_evidence_plan}

**Output:**
- A well-written subsection in several coherent paragraphs.
- Academic style; focused on synthesis and analysis, not just reporting.
- **Only** cite papers that appear in the provided input.
- Strictly use format: <paper_title> (like <Attention is All You Need>) to cite wherever appropriate.
- Use about {subsection_target_citations} distinct, relevant citations (never more than {subsection_max_citations}) when the applicable SH plan mode permits evidence-backed or qualified synthesis. Do not pad the prose with citations. If a subsection only reports an EVIDENCE_GAP_REPORT or OUT_OF_SCOPE_OR_REJECTED SH, this generic target does not apply: state the limitation precisely and do not invent citations.
- Do not generate a bibliography or reference list here.
- Aim for about {subsection_target_words} words; the visible prose must not exceed {subsection_max_words} words. Be concise: merge closely related findings into synthesis rather than enumerating papers.
- Generate the content directly. DO NOT generate any subsection title or section header here.
- CRITICAL: '#' is used for section/subsection anchor. Avoid any '#' in the output content.
- When evidence_bounded_writing=true in the plan: every substantive SH claim must obey its allowed_writing_mode and paper_role_constraints. A GRAPH_EXPANDED_CANDIDATE remains lineage/retrieval context and is never evidence by itself. It may be cited only when the current SH evidence plan explicitly includes the same paper through a FULLTEXT_PROMOTION role earned from that paper's own complete-section reading; then use exactly its listed direct, qualified, or background strength. Do not use BACKGROUND_CONTEXT papers for direct empirical support. A QUALIFIED_SH_CONTRIBUTION may support only QUALIFIED_SYNTHESIS and must state the applicable limitation rather than asserting a complete causal chain. An EVIDENCE_GAP_REPORT must report the gap and must not make an affirmative scientific conclusion.
- In evidence-bounded mode, end the response with exactly one final metadata block, using this literal delimiter (not angle brackets):
[[SH_CLAIM_TRACE]]
{{"claims":[{{"claim_index":1,"claim_anchor":"a distinctive short phrase from the cited prose sentence","claim_text":"the cited prose sentence when available","sub_hypothesis_ids":["SH1"],"claim_mode":"one allowed mode from the plan","evidence_paths":[{{"sub_hypothesis_id":"SH1","slot_name":"one plan slot","paper_id":"the cited plan-listed paper id"}}]}}]}}
[[/SH_CLAIM_TRACE]]
The metadata must be valid JSON, must be final, and must not introduce claims or paper IDs absent from the prose/plan. ``claim_index`` is one-based among visible prose sentences and lets the program recover the exact sentence despite harmless spacing or punctuation differences. Do not emit evidence_role, support_kind, or limitation_slots: the program derives them from the authoritative evidence plan. Every bounded response must include at least one claim. For EVIDENCE_GAP_REPORT or OUT_OF_SCOPE_OR_REJECTED, use evidence_paths: [] and include an appropriate claim_index / claim_anchor; do not cite a paper. If the plan is inactive, omit this block.
"""

CODE_REPORT_PROMPT = """Code Report Context:
You are provided with a **Code Report** containing implementation insights for the papers in this survey topic, including: framework choices, environment setup guidance, and repository quality assessment.

**Usage Principles (CRITICAL - Follow Strictly):**
- **Topic coherence**: Only incorporate code report content that directly relates to the current subsection's theme; unrelated framework details must be ignored
- **Structure preservation**: Integrate insights seamlessly into existing paragraphs without disrupting the survey's logical flow or section organization
- **Readability maintenance**: Add technical details sparingly; if code snippets are needed, ensure clean formatting
- **Proportionality**: Code report insights should complement, not replace, paper-based analysis; aim for subtle enhancement rather than extensive additions

**Code Report:**
{code_report}
"""

CODE_REPORT_PROMPT_FOR_SECTION_REVISER = """Code Report Context:
You are provided with a **Code Report** containing implementation insights for the papers in this survey topic, including: framework choices, environment setup guidance, and repository quality assessment.

**Usage Principles (CRITICAL - Follow Strictly):**
- **Topic coherence**: Only incorporate code report content that directly relates to the current section's theme; unrelated framework details must be ignored
- **Structure preservation**: Integrate insights seamlessly into existing paragraphs without disrupting the survey's logical flow or section organization
- **Readability maintenance**: Add technical details sparingly; if code snippets are needed, ensure clean formatting
- **Proportionality**: Code report insights should complement, not replace, paper-based analysis; aim for subtle enhancement rather than extensive additions

**Code Report:**
{code_report}
"""

CODE_REPORT_PROMPT_FOR_SECTION_REVIEWER = """Code Report Context:
You are provided with a **Code Report** containing implementation insights for the papers in this survey topic, including: framework choices, environment setup guidance, and repository quality assessment.

**Usage Principles (CRITICAL - Follow Strictly):**
- **Topic coherence**: Only incorporate code report content that directly relates to the current section's theme; unrelated framework details must be ignored
- **Structure preservation**: Integrate insights seamlessly into existing paragraphs without disrupting the survey's logical flow or section organization
- **Readability maintenance**: Add technical details sparingly; if code snippets are needed, ensure clean formatting
- **Proportionality**: Code report insights should complement, not replace, paper-based analysis; aim for subtle enhancement rather than extensive additions

**Code Report:**
{code_report}
"""

CODE_REPORT_PROMPT_FOR_SURVEY_REVISER = """Code Report Context:
You are provided with a **Code Report** containing implementation insights for the papers in this survey topic, including: framework choices, environment setup guidance, and repository quality assessment.

**Usage Principles (CRITICAL - Follow Strictly):**
- **Topic coherence**: Only incorporate code report content that directly relates to the survey's themes; unrelated framework details must be ignored
- **Structure preservation**: Integrate insights seamlessly into existing sections without disrupting the survey's logical flow or organization
- **Readability maintenance**: Add technical details sparingly; if code snippets are needed, ensure clean formatting
- **Proportionality**: Code report insights should complement, not replace, paper-based analysis; aim for subtle enhancement rather than extensive additions

**Code Report:**
{code_report}
"""

CODE_REPORT_PROMPT_FOR_SURVEY_REVIEWER = """Code Report Context:
You are provided with a **Code Report** containing implementation insights for the papers in this survey topic, including: framework choices, environment setup guidance, and repository quality assessment.

**Usage Principles (CRITICAL - Follow Strictly):**
- **Topic coherence**: Only incorporate code report content that directly relates to the survey's themes; unrelated framework details must be ignored
- **Structure preservation**: Integrate insights seamlessly into existing sections without disrupting the survey's logical flow or organization
- **Readability maintenance**: Add technical details sparingly; if code snippets are needed, ensure clean formatting
- **Proportionality**: Code report insights should complement, not replace, paper-based analysis; aim for subtle enhancement rather than extensive additions

**Code Report:**
{code_report}
"""

PAPER_RELATIONSHIP_ANALYSIS = """You are an expert researcher analyzing the citation relationship between two scientific papers to understand the evolution of ideas.

Paper A (The Citer) cites Paper B (The Cited).

--- Paper A (Citing Paper) ---
{src_title}:
{src_keynote}

--- Paper B (Cited Paper) ---
{dist_title}:
{dist_keynote}

Task:
Analyze the citation relationship to determine how Paper A utilizes or relates to Paper B.

1. Classify the **Relationship Type** into one of the following categories:
   - "Foundation": Paper B provides the theoretical basis, core method, or backbone architecture that Paper A is built upon.
   - "Extension": Paper A explicitly improves, optimizes, or addresses a limitation of Paper B (e.g., "We improve [B] by...").
   - "Comparison": Paper B is used primarily as a baseline or state-of-the-art method for experimental comparison.
   - "Application": Paper A applies the method/theory from Paper B to a new problem setting or domain.
   - "Alternative": Paper A proposes a different approach to solve the same problem as Paper B, citing it as a contrasting method.
   - "Background": Paper B is cited to provide general context, definition, or motivation, without a strong technical dependency.
   - "Other": Any other type of relationship not covered above. Provide a brief explanation.

2. Provide a **Specific Analysis** (1-3 sentences).
   - Explain the logical connection.
   - Clearly state what specific part of Paper B is used, improved, or compared against by Paper A.

- Generate JSON directly without any other things.
- Output strictly in JSON format:
{{
  "type": "...",
  "analysis": "..."
}}
"""

CLUSTER_TABLE_GENERATION = """You are an expert research analyst creating a comparative survey table for a specific cluster of papers.

**Cluster Context:**
Name: {cluster_name}
Description: {cluster_description}

**Papers in Cluster:**
{paper_content}

**Task:**
1. Analyze the papers to identify 3-5 **Dimensions of Comparison** that best highlight the similarities and differences within this specific cluster.
   - Do NOT use generic dimensions like "Year" or "Author" unless they are critical to the scientific trend.
   - Choose technical dimensions relevant to the topic (e.g., "Methodology Paradigm", "Supervision Type", "Complexity", "Auxiliary Data", "Key Assumption").
2. Create a comparison table where each row is a paper and each column is one of the dimensions you identified.
3. Fill in the cells concisely (phrases, not paragraphs). Use "N/A" if the information is not applicable or available.

**Output Requirement:**
- Generate JSON directly without any other things.
- The top-level JSON value MUST be one object (``{{...}}``), never a JSON list
  (``[...]``), Markdown table, or prose. A list response is invalid and will be
  regenerated.
- Include both ``comparison_dimensions`` and ``table_data`` exactly as shown.
- Output strictly in JSON format with the following structure:
{{
    "comparison_dimensions": ["Dimension 1", "Dimension 2", "Dimension 3", ...],
    "table_data": [
        {{
            "paper_id": "Paper ID",
            "paper_title": "Paper Title",
            "columns": {{
                "Dimension 1": "Value...",
                "Dimension 2": "Value...",
                ...
            }}
        }},
        ...
    ]
}}
"""

SECTION_DRAFT = """You are writing the Introductory Paragraphs/Preamble for a specific section of an academic top-tier conference survey paper. 
**Task**:
Write the opening text that appears immediately after the Section Title but before the first subsection. This content should serve as a high-level synthesis and roadmap for the reader.

**Requirements**:
1. Synthesize, Don't Summarize: Do not simply list what each subsection will do. Instead, explain the logic behind why this section is structured this way and the significance of these topics within the broader field.
2. Establish Definition & Scope: Clearly define the core concepts covered in this section. Refer to <paper_title> to establish foundational definitions or taxonomies.
3. Identify Trends: Highlight the overarching trends or challenges that link the following subsections together.
4. Academic Tone: Maintain a formal, authoritative, and objective voice.
5. Citations: * Only cite papers provided in the relevant papers provided below(Closely Relevant papers and Other Relevant papers).
Use the format: <paper_title>.
6. Use about {section_target_citations} citations (never more than {section_max_citations}) to ground the section's scope when its SH plan allows evidence-backed or qualified synthesis. If the section only explains EVIDENCE_GAP_REPORT or OUT_OF_SCOPE_OR_REJECTED SHs, this generic target does not apply: identify the limitation and do not invent citations.
7. Utilize the input content in a safe and reasonable manner, and ensure that the readability, structure, and depth of the content of the paragraph meet the requirements of a top-tier conference survey.
8. Length: Aim for about {section_target_words} words and do not exceed {section_max_words} words. Keep this preamble compact so the subsection budgets control the complete survey length.
9. CRITICAL: '#' is used for section/subsection anchor. Avoid any '#' in the output content.

**Input**:
- Section Title:
{title}

- Section Description: 
{description}

- Full Survey Outline: 
{survey_outline}

Planned Subsections under this Section: {subsection_drafts} (Use these as a roadmap, do not detail their findings yet).

- Closely Relevant papers:
{papers}

- Other Relevant papers:
{other_relevant_papers}

- Authoritative survey evidence plan:
{survey_evidence_plan}

**Output**:
Generate the introductory content directly. DO NOT generate any subsection title or section header here.
When evidence_bounded_writing=true in the plan, obey every SH writing mode and paper_role_constraints: do not use graph-expanded candidates as evidence, because root lineage never upgrades them; do not use background papers as direct support; use QUALIFIED_SH_CONTRIBUTION only for qualified, limitation-bearing synthesis. End with the same single final [[SH_CLAIM_TRACE]] JSON block required for bounded subsection writing. Each trace claim should use a one-based claim_index, a short claim_anchor, SH, claim mode, and minimal (SH, slot, paper) evidence paths. Do not emit evidence_role, support_kind, or limitation_slots: the program derives them from the plan. Every bounded response must contain at least one claim; only gap/rejection claims may use evidence_paths: []. Omit the block only when the plan is inactive.
"""

SECTION_REVIEW = """You are an expert reviewer for an academic survey paper with deep analysis and insights concerning topic: {topic}. You are reviewing the section:{section_title}.
The draft section may contain inline paper citations in angle brackets (e.g., "<Attention is All You Need>").

**Task**:
1. Read the Draft Text for the given section and perform a short, careful review focused on clarity, logical flow, technical accuracy, and depth for an academic survey.
2. Produce a clear, specific, and actionable **list of revision suggestion list**. 
3. Each suggestion should concisely explain *what* to change, *why* and  *how* to implement it. When appropriate, point to the exact sentence or short excerpt from the draft to anchor the suggestion.
4. You will be provided with the previous and next sections for context. Use them to ensure logical flow and coherence across sections.
5. Only give suggestions on the current section. 
6. There are some basic requirements as follow. If the section does not meet any, provide relevant modification suggestions.
7. If the section is satisfactory, provide an empty suggestion list.
8. Suggest sorting by importance, with important ones coming first.
9. You are suggested to give no more than 5 suggestions

**Requirements**:
1. You should only provide suggestions on content. DO NOT give any suggestions that involve changing the titles of the section and any subsections.
2. The section text should have around {section_target_words} words and stay within the survey's total length budget. Current section length: {current_section_length} words. Avoid over long or over short section.
3. All citations in the section must be in correct format: <paper_title> (like <Attention is All You Need>).
4. The goal is to ultimately complete a survey section with depth, insights and can boost further development, rather than simply listing methods.
5. The section content should have deep insights, novelty and analysis under the field of the section. 
6. The section content should be clear and coherent. Avoid over verbose phrase or any repetitions.
7. The section content should be elegantly formatted and have good readability, avoid extremely long sentences ,paragraphs or subsections.
8. The content of the section should be strictly consistent with the outline of the section provided below.
9. The section content should be logically coherent and academically styled with acdamic rigor and precise description.
10. The paragraph should contain sufficient citations to support the viewpoints and provide specific and in-depth analysis
11. The introduction/preamble of each section must be concise, and the main content should be placed in each specific subsection.
12. You should only change the content of the current section.
13. You can use content in Additional Context if it's not None and you consider it necessary.

**Input**:
Previous Section:
{previous_section_text}

Next Section:
{next_section_text}

Current Section:
{section_text}

Section Outline:
{section_outline}

Additional Context:
{additional_context}

**Output format (exact)**:
[
  "suggestion 1",
  "suggestion 2",
  ...
]
"""

SECTION_REVISE  = """
You are a revise assistant. The section content of a survey concerning {topic} is provided below. The section name is: {section_title}.
You must propose at most ONE exact textual substitution per response according to the suggestion of reviewer.
If you think the document requires changes, choose one that you think is most important to address next, and output ONE JSON object (and nothing else).

**Revision Goal:**
Your revision target: produce a survey section that meets the quality standards of a top-tier academic conference survey, with rigorous logic, excellent readability, and sufficient depth.

**Output format:**
{{
    "action":"replace", 
    "originalText":"<the exact substring to replace>", 
    "newText":"<the replacement text>"
}}

The originalText field must match EXACTLY ONE substring in the document.
If you believe no edits are required, output exactly: {{"action":"done"}}.

Section Outline(You should not change):
{section_outline}

Original Section Text:
{text}

Citation Text:
{citations}

Additional Context:
{additional_context}

Guidance:
- Give one minimal but precise modification.
- Revise the paragraph to enhance its readability, logicality and depth.
- Your modifications **MUST** be consistent with the overall structure, logic and the scope(title) of the section.
- The revise should meets the standards of a top-tier academic literature review

Revision instructions:
- The field originalText must be an exact substring of the document matches the content part, NOT the header part (### Title).
- The section and subsection headers (lines starting with #) remain IMMUTABLE anchors. Do not change them.
- The modification has multiple iterations, so make minimal changes: prefer a single precise substitution rather than rewriting whole paragraphs.
- You will be provided with Reivewer Suggestion which guides you what and how to modify.
- You can add analysis, specific details or insights to increase the depth of survey.
- If the Review Suggestion is empty, you can give modification that enhance depth, readability, or acdamic rigor of the paper.
- You can cite new literature from Citation Text(if provided) if it helps improve the content's depth, novelty or completeness.
- You can only cite papers from the Citation Text. Make sure the title matches EXACTLY. 
- You can use content in Additional Context if its's not None and you consider it necessary.

Reviewer Suggestion:
{reviewer_suggestion}

Strict rules:
- Any modification with titles in "originalText" is strictly prohibited.
- The field originalText must be an exact substring of the document (it may include newlines).
- Output only the JSON object described above. Do NOT output any prose.
- Do not return arrays. Only one JSON object.
- Keep the substitution minimal and precise.
- Any additions that are repetitive, spoil the format, inconsistent with the paragraph logic, or beyond the scope of the content are strictly prohibited

"""


EVIDENCE_BOUNDED_SECTION_QUALITY_REVIEW = """You are a quality reviewer for one section of an evidence-bounded academic survey on {topic}.

Assess the section itself; do not propose title changes, new citations, or claims that require evidence not already present in the text.  The outline is immutable.

Score each dimension from 0 to 10:
- readability: clarity, paragraph flow, concise academic prose, and formatting;
- scientific: scientific precision, cautious interpretation, analytical depth, and whether the existing evidence is represented without overclaiming;
- framework: fidelity to the supplied section outline, logical organisation, and terminological consistency.

Give at most {max_suggestions} concrete, local revision suggestions.  Each suggestion must be feasible without adding, removing, or replacing a citation, changing any heading, or introducing a new empirical result.

Previous Section:
{previous_section_text}

Next Section:
{next_section_text}

Current Section:
{section_text}

Immutable Section Outline:
{section_outline}

Return exactly one JSON object and nothing else:
{{
  "scores": {{
    "readability": 0,
    "scientific": 0,
    "framework": 0
  }},
  "suggestions": ["specific, local suggestion"]
}}
"""


EVIDENCE_BOUNDED_SECTION_QUALITY_REVISE = """Revise one section of an evidence-bounded academic survey on {topic}.

Apply only the supplied quality suggestions.  This is a constrained editorial revision, not new research or a new evidence synthesis.

Strict rules:
1. Return the complete revised section, including all existing Markdown headings.
2. Preserve every heading line verbatim.  Do not add, remove, rename, reorder, or promote/demote headings.
3. Preserve the set of cited papers exactly.  Do not add, remove, replace, or edit any inline citation token in angle brackets.
4. Do not add empirical facts, numerical results, causal claims, or paper-specific claims that are not already expressed in the original section.
5. Keep the section aligned with the immutable outline and within {section_word_cap} words.
6. Improve prose, caveats, transitions, precision, and explanation where possible; if no safe improvement is possible, return the original section unchanged.

Immutable Section Outline:
{section_outline}

Original Section:
{section_text}

Quality Suggestions:
{suggestions}

Return exactly one JSON object and nothing else:
{{
  "revised_section": "complete revised section text"
}}
"""

SURVEY_REVIEW = """You are an expert reviewer for an academic survey paper concerning topic: {topic}. You are reviewing the whole survey.
The survey may contain inline paper citations in angle brackets (e.g., "<Attention is All You Need>").

**Task**:
1. Read the Draft Text for the given survey and perform a short, careful review focused on clarity, logical flow, technical accuracy, integrity and depth for an academic survey.
2. Produce a clear, specific, and actionable **list of revision suggestion list**. 
3. Each suggestion should concisely explain *what* to change, *why* and  *how* to implement it. When appropriate, point to the exact sentence or short excerpt from the draft to anchor the suggestion.
4. There are some basic requirements as follow. If the survey does not meet any, provide relevant modification suggestions.
5. If the survey is satisfactory, provide an empty suggestion list.

**Requirements**:
1. You should only provide suggestions on content. DO NOT give any suggestions that involve changing the outline(title of the section and any subsections).
2. All citations in the survey must be in correct format: <paper_title> (like <Attention is All You Need>).
3. The survey should avoid over verbose phrase or any repetitive content.
4. The survey content should be logically coherent and academically styled with acdamic rigor and precise description.
5. The survey content should have deep insights, novelty and analysis under the field of the survey.
6. The survey content should be elegantly formatted and have good readability, avoid extremely long sentences or paragraphs.
7. Avoid Extremely long section or subsection.
8. The introduction/preamble of each section must be concise, and the main content should be placed in each specific subsection.
9. The survey should have good clarity, acadamic rigor and coherence in description and all the conceptions.
10. The content of the survey should be strictly consistent with the outline provided below.
11. The survey should provide specific guidance on possible furture direction.
12. You can use content in Additional Context if its's not None and you consider it necessary.

**Input**:
Survey:
{survey}

SURVEY Outline:
{survey_outline}

Additional Context:
{additional_context}

**Output format (exact)**:
[
  "suggestion 1",
  "suggestion 2",
  ...
]
"""

SURVEY_REVISE  = """
You are a revise assistant. The content of a survey concerning {topic} is provided below. .
You must propose at most ONE exact textual substitution per response according to the suggestion of reviewer.
If you think the document requires changes, choose one that you think is most important to address next, and output ONE JSON object (and nothing else).

**Output format:**
{{
    "action":"replace", 
    "originalText":"<the exact substring to replace>", 
    "newText":"<the replacement text>"
}}

The originalText field must match EXACTLY ONE substring in the document.
If you believe no edits are required, output exactly: {{"action":"done"}}.

**Revision Goal:**
Your revision target: produce a survey that meets the quality standards of a top-tier academic conference survey, with rigorous logic, excellent readability, and sufficient depth.

Survey Outline(You should not change):
{survey_outline}

Original Survey Text:
{survey}

Additional Context:
{additional_context}

Guidance:
- Give one minimal but precise modification.
- Revise the paragraph to enhance its readability, logicality and depth.
- Your modifications **MUST** be consistent with the overall structure, logic and the topic of the survey.
- The revise should meets the standards of a top-tier academic literature review

Revision instructions:
- The field originalText must be an exact substring of the document matches the content part, NOT the header part (### Title).
- The section and subsection headers (lines starting with #) remain IMMUTABLE anchors. Do not change them.
- The modification has multiple iterations, so make minimal changes: prefer a single precise substitution rather than rewriting whole paragraphs.
- You will be provided with Reivewer Suggestion which guides you what and how to modify.
- If the Review Suggestion is empty, you can give modification that enhance coherence, readability, depth, or acdamic rigor.
- You can use content in Additional Context if its's not None and you consider it necessary.

Reviewer Suggestion:
{reviewer_suggestion}

Strict rules:
- Any modification with titles in "originalText" is strictly prohibited.
- The field originalText must be an exact substring of the document (it may include newlines).
- Output only the JSON object described above. Do NOT output any prose.
- Do not return arrays. Only one JSON object.
- Keep the substitution minimal and precise.
- Any additions that are repetitive, spoil the format, inconsistent with the paragraph logic, or beyond the scope of the content are strictly prohibited

"""


DRAFT_REFINEMENT = """You are refining an academic survey paper draft. The draft currently contains paper titles as citations (e.g., "<Attention is All You Need>").

**Task**:
1. Refine the draft to improve clarity, coherence, and academic style.
2. Replace all paper Title citations in format like <paper_title> (like <Attention is All You Need>) in the draft with numbered references in square brackets, in the order of first appearance.
3. Each citation number corresponds to a single paper title.
4. Keep all original content and ideas.
5. Integrate citations smoothly and naturally within the text.

**Input**:
Draft Text:
{draft_text}

**Output**:
Provide a **JSON object** with the following structure:

{{
  "refined_survey": "<refined survey text with numbered citations>",
  "references": [<paper_title for citation 1>, <paper_title for citation 2>, ...]
}}

- `refined_survey` is a string containing the survey text with citations replaced by `[number]`.
- `references` is a list of objects ordered by citation number, each mapping the index to its corresponding paper IDs.
- Ensure JSON is valid and parsable. 
- Generate JSON directly without any other things.
- Do not generate a bibliography or reference list here.
"""

DRAFT_REFINEMENT_IN_PARTS = """You are refining an section of academic survey paper draft with title: {title}. The draft currently contains paper titles as citations (e.g., "<Attention is All You Need>").

**Key Task**:
1. Improve the overall quality of the subsection according to the standards of a well formatted and in-depth academic survey
2. Refine the draft to improve clarity, coherence, and academic style.
3. Improve obscure expressions and overly lengthy sentences in subsections to enhance readability.
4. Avoid meaningless repetitions, over verbose phrases, or extremely long sentences or paragraphs.

**Requirements**:
1. Fix all the citations in other format. The correct citation must be paper title in <> (like <Attention is All You Need>).
2. Make sure each <> contains only one paper title. Split titles in to seperate <> if one <> contains multiple paper titles.
3. Keep all original content and ideas. Do not delete any citations.
4. You are provided with the previous and next section/subsection of the draft. Use them to ensure logical flow and coherence across sections.
5. Directly output the refined draft text. Do not generate any other explanations.
6. Only refine the draft in Draft Text. Do not modify the previous or next sections.
7. Enhance the readability, coherence and academic style of the draft. 
8. You can make any modification that does not change the original content and ideas, such as rephrasing sentences, improving transitions, fixing grammar or formatting issues, etc.

**Input**:
Previous Section:
{previous_text}

Next Section:
{next_text}

Draft Text:
{draft_text}

Generate refined draft content directly. 
- Do not generate any section/subsection title or header here.
- Do not generate a bibliography or reference list here. 
"""

DRAFT_REFINEMENT_SUBSECTION_IN_PARTS = """You are an expert in acdamic top-tier survey/literature review writing. Now you are refining an survey with topic {topic}'s subsection titled {subsection_title}. The subsection is under a section titled {section_title}. The draft currently contains paper titles as citations (e.g., "<Attention is All You Need>").

**Key Task**:
revision target: a subsection of survey that meets the quality standards of a top-tier academic conference survey, with rigorous logic, excellent readability, and sufficient depth.
1. Improve the overall quality of the subsection according to the standards of a well formatted and in-depth academic survey
2. Refine the draft to improve clarity, coherence, and academic style.
3. Improve obscure expressions and overly lengthy sentences in subsections to enhance readability.
4. Avoid meaningless repetitions, over verbose phrases, or extremely long sentences or paragraphs.

**Requirements**:
1. Fix all the citations in other format. The correct citation must be paper title in <> (like <Attention is All You Need>).
2. Make sure each <> contains only one paper title. Split titles in to seperate <> if one <> contains multiple paper titles.
3. Keep all original content and ideas. Do not delete any citations.
4. You are provided with the previous and next section/subsection of the draft. Use them to ensure logical flow and coherence across sections.
5. Directly output the refined draft text. Do not generate any other explanations.
6. Only refine the draft in Draft Text. Do not modify the previous or next sections.
7. Enhance the readability, coherence and academic style of the draft. 
8. You can make any modification that does not change the original content and ideas, such as rephrasing sentences, improving transitions, fixing grammar or formatting issues, etc.

**Input**:
Previous Section:
{previous_text}

Next Section:
{next_text}

Draft Text:
{draft_text}

Generate refined draft content directly. 
- Do not generate any section/subsection title or header here.
- Do not generate a bibliography or reference list here. 
"""

ERROR_FEEDBACK_PROMPT = """The previous draft attempt encountered the following issues:
{info}
Please use this feedback to improve the next draft attempt. 
For example, if previous attempt cited non-existent or error papers, avoid citing the same paper_id and ensure all cited papers are from the provided relevant papers list.
"""

###----EVALUATOR PROMPTS----###
EVAL_CRITERIA = {
    'Coverage':{
        'description':'Coverage: Coverage assesses the extent to which the survey encapsulates all relevant aspects of the topic, ensuring comprehensive discussion on both central and peripheral topics.',
        'score 1':'The survey has very limited coverage, only touching on a small portion of the topic and lacking discussion on key areas.',
        'score 2':'The survey covers some parts of the topic but has noticeable omissions, with significant areas either underrepresented or missing.',
        'score 3':'The survey is generally comprehensive in coverage but still misses a few key points that are not fully discussed.',
        'score 4':'The survey covers most key areas of the topic comprehensively, with only very minor topics left out.',
        'score 5':'The survey comprehensively covers all key and peripheral topics, providing detailed discussions and extensive information.',
    },
            
    'Structure':{
        'description':'Structure: Structure evaluates the logical organization and coherence of sections and subsections, ensuring that they are logically connected.',
        'score 1':'The survey lacks logic, with no clear connections between sections, making it difficult to understand the overall framework.',
        'score 2':'The survey has weak logical flow with some content arranged in a disordered or unreasonable manner.',
        'score 3':'The survey has a generally reasonable logical structure, with most content arranged orderly, though some links and transitions could be improved such as repeated subsections.',
        'score 4':'The survey has good logical consistency, with content well arranged and natural transitions, only slightly rigid in a few parts.',
        'score 5':'The survey is tightly structured and logically clear, with all sections and content arranged most reasonably, and transitions between adajecent sections smooth without redundancy.',
    },
            
    'Relevance':{
        'description':'Relevance: Relevance measures how well the content of the survey aligns with the research topic and maintain a clear focus.',
        'score 1':'The content is outdated or unrelated to the field it purports to review, offering no alignment with the topic',
        'score 2':'The survey is somewhat on topic but with several digressions; the core subject is evident but not consistently adhered to.',
        'score 3':'The survey is generally on topic, despite a few unrelated details.',
        'score 4':'The survey is mostly on topic and focused; the narrative has a consistent relevance to the core subject with infrequent digressions.',
        'score 5':'The survey is exceptionally focused and entirely on topic; the article is tightly centered on the subject, with every piece of information contributing to a comprehensive understanding of the topic.',
    },

    "Relevance-10-score": {
        "aspect": "Core Quality",
        "description": "Relevance (10-point scale): measures how well the content of the survey aligns with the research topic and maintains a clear, unwavering focus throughout. It evaluates whether every section, paragraph, and sentence contributes to advancing the reader's understanding of the stated topic, and whether tangential content is either absent or minimal.",
        "score 1":  "Completely irrelevant — the survey addresses a fundamentally different topic; content has no meaningful connection to the stated research area.",
        "score 2":  "Mostly irrelevant — the survey only tangentially touches the topic, with the majority of content being off-topic, peripheral, or unrelated.",
        "score 3":  "Weakly relevant — several sections or subsections discuss the topic, but significant portions (more than 30%) are digressive or off-topic.",
        "score 4":  "Somewhat relevant — the survey covers the topic but often digresses into unrelated areas; focus is inconsistent throughout.",
        "score 5":  "Moderately relevant — the survey is generally on topic, with most content aligning with the research focus, though notable unrelated details appear in places.",
        "score 6":  "Reasonably relevant — the survey maintains focus on the topic with occasional minor digressions; most sections contribute meaningfully to the core subject.",
        "score 7":  "Strongly relevant — the survey is largely focused, with consistent alignment to the research topic; only rare and minor unrelated content present.",
        "score 8":  "Very strongly relevant — the survey is tightly focused with near-perfect topical alignment; every section contributes to the core subject with only negligible peripheral content.",
        "score 9":  "Exceptionally relevant — the survey demonstrates exemplary topical coherence; content is exclusively focused on the research topic with no discernible digressions.",
        "score 10": "Perfectly relevant — the survey is a model of topical unity; every single element, from introduction to conclusion, is laser-focused on advancing the reader's understanding of the research topic, with no off-topic content whatsoever."
    },

    'Depth':{
        'description':'Depth: Depth evaluates the level of *technical and analytical rigor* in explaining underlying principles, assumptions, failure modes, trade-offs, and engineering implementations of different methods. It emphasizes *mechanism-level reasoning*, *comparative analysis with clear criteria*, and *actionable synthesis* (not just literature aggregation).',
        'score 1':'The survey is largely a bibliography or a list of methods/tasks with near-zero technical content. It does not explain how methods work, what assumptions they rely on, or why they differ; comparisons are absent or purely descriptive.',
        'score 2':'The survey contains minimal technical explanation (mostly high-level intuition or slogans). Comparisons are shallow (e.g., “better/worse” without conditions), key assumptions and limitations are ignored, and there is little to no discussion of implementation details, complexity, or failure cases.',
        'score 3':'The survey provides basic mechanism-level descriptions for a subset of methods and can state a few meaningful differences. However, analysis remains coarse: trade-offs are not articulated with clear axes (e.g., compute/data/latency/robustness), evidence is not tied to claims, and engineering details (hyperparameters, architectures, training regimes, evaluation setups) are only partially covered.',
        'score 4':'The survey gives *substantive* technical analysis for most core methods, including explicit trade-off axes (e.g., accuracy vs. efficiency, scalability vs. stability, robustness vs. alignment), common failure modes, and reproducibility-relevant engineering details. It synthesizes patterns across works (not just per-paper summaries) and derives *well-supported* future directions with concrete open problems.',
        'score 5':'The survey demonstrates *exceptional* depth with rigorous, end-to-end synthesis: it explains methods at the level of objectives/derivations or algorithmic steps, clarifies assumptions and when they break, analyzes empirical outcomes through causal or mechanistic hypotheses, and connects theory ↔ implementation ↔ evaluation. It provides taxonomy-level insights grounded in evidence (e.g., why certain design choices dominate under specific constraints), highlights non-obvious pitfalls and boundary conditions, and proposes *actionable, testable* research directions (including what to measure, how to evaluate, and what would falsify key claims).',
    },

    'Rigor&Authenticity':{
        'description':'Rigor&Authenticity: Rigor&Authenticity assesses whether the survey\'s claims are truthful, verifiable, and precisely stated. It evaluates citation integrity, evidence support, correct attribution, numerical/detail accuracy, and the avoidance of hallucinations, fabricated references, or overconfident unsupported assertions. It also checks whether uncertainty and limitations are clearly disclosed, and whether the survey enables readers to trace key statements back to reliable sources.',
        'score 1':'The survey contains pervasive hallucinations or fabricated content (e.g., non-existent papers, wrong attributions, invented datasets/metrics). Many core claims are unverifiable or false; citations are missing or clearly incorrect; strong conclusions are made without evidence.',
        'score 2':'The survey shows frequent factual errors or questionable claims. Citations are sparse, mismatched, or low-quality; multiple key details (dates, numbers, method names, benchmarks) appear unreliable or cannot be traced. Uncertainty is rarely acknowledged.',
        'score 3':'The survey is mostly plausible and broadly accurate, but has several unverified statements or minor inaccuracies. Some important claims lack direct support or use vague referencing; a few citations may be incomplete or weakly connected. Limitations/uncertainty are mentioned but not systematically handled.',
        'score 4':'The survey is largely factual and carefully grounded. Most nontrivial claims are supported by credible, traceable references; attribution is correct; numerical/details are consistent. Uncertainty, assumptions, and limitations are clearly stated, with only minor lapses (e.g., occasional vague wording or missing support for a small claim).',
        'score 5':'The survey is exceptionally rigorous and trustworthy. All key claims are verifiable with high-quality sources; citations precisely match statements and are sufficient for tracing. It avoids overgeneralization, clearly distinguishes evidence from speculation, reports uncertainty and boundary conditions, and includes falsification-friendly details (e.g., exact settings, metrics, datasets, versions) enabling independent verification. No fabricated, misleading, or unsupported content is present.',
    },

    "Synthesis Quality": {
        "aspect": "Core Quality",
        "description": "Synthesis quality: distinguishes true integration and conceptual grouping of literature from mere enumeration of papers.",
        "score 1":  "No synthesis — the text is a disconnected list of papers with no comparison, grouping, or integrative statements.",
        "score 2":  "Very weak synthesis — occasional grouping but mostly descriptive lists; links between works are absent or mistaken.",
        "score 3":  "Minimal synthesis — some attempts to group papers or note similarities, but links are shallow and inconsistent.",
        "score 4":  "Basic synthesis — groups and comparisons exist but are superficial and miss deeper patterns or tensions.",
        "score 5":  "Moderate synthesis — reasonable grouping and some comparative statements; important cross-paper themes are noted but not developed.",
        "score 6":  "Good synthesis — clear groups and comparisons, with emerging themes and some cross-cutting analysis.",
        "score 7":  "Strong synthesis — integrates findings across multiple works, highlights causes of differences, and builds partial conceptual links.",
        "score 8":  "Very strong synthesis — conveys nuanced relationships among studies, articulates patterns and contradictions, and forms clear conceptual maps.",
        "score 9":  "Excellent synthesis — deeply integrates diverse sources, proposes coherent frameworks, and resolves or explains major discrepancies.",
        "score 10": "Outstanding synthesis — creates novel unifying frameworks or taxonomies, transforms raw literature into new conceptual insight."
    },

    "Organization": {
        "aspect": "Core Quality",
        "description": "Organization: evaluates logical flow, section/subsection ordering, and ease of following the argument across the survey.",
        "score 1":  "No logical order — sections are chaotic and the reader cannot form a coherent view of the topic.",
        "score 2":  "Very poor ordering — frequent abrupt jumps and misplaced content; reader must constantly backtrack.",
        "score 3":  "Weak organization — some logical chunks but many misplaced paragraphs or unclear section boundaries.",
        "score 4":  "Below-average organization — parts make sense but transitions are rough and structure sometimes redundant.",
        "score 5":  "Adequate organization — overall structure is serviceable though some sections could be rearranged for clarity.",
        "score 6":  "Good organization — clear sections and logical progression with occasional weak transitions or minor redundancies.",
        "score 7":  "Strong organization — well-ordered sections, clear flow, and purposeful subsectioning.",
        "score 8":  "Very strong organization — sections build on each other smoothly; transitions are purposeful and guide the reader.",
        "score 9":  "Excellent organization — highly coherent structure, logical sequencing, and efficient, non-redundant layout.",
        "score 10": "Exemplary organization — impeccable flow, perfect chapter/subsection design, and the structure itself aids understanding."
    },

    # ---------- Writing Quality ----------
    "Readability": {
        "aspect": "Writing Quality",
        "description": "Readability: clarity and accessibility for the intended academic audience (sentence-level clarity, pacing, and jargon handling).",
        "score 1":  "Unreadable — sentences are confusing, grammar errors abound, and jargon is opaque.",
        "score 2":  "Very poor readability — frequent grammar issues and unclear sentences; reader struggles to extract meaning.",
        "score 3":  "Low readability — many awkward sentences and unclear phrasing; frequent re-reading required.",
        "score 4":  "Below-average readability — understandable in places but style is verbose or clumsy; jargon often unexplained.",
        "score 5":  "Fair readability — generally clear though some sentences or paragraphs are convoluted.",
        "score 6":  "Good readability — clear prose overall with occasional dense passages or uneven pacing.",
        "score 7":  "Very good readability — fluent writing, appropriate use of terminology, and easy to follow.",
        "score 8":  "Excellent readability — crisp sentences, well-balanced pacing, and accessible to the target academic audience.",
        "score 9":  "Near-perfect readability — highly engaging academic prose with precise phrasing and smooth flow.",
        "score 10": "Outstanding readability — exemplary clarity and elegance; highly accessible without loss of technical precision."
    },

    "Academic Rigor": {
        "aspect": "Writing Quality",
        "description": "Academic rigor: fidelity to scholarly standards (proper citations, fair representation of prior work, and methodological transparency).",
        "score 1":  "No rigor — citations missing or blatantly incorrect; claims unsupported and methods misrepresented.",
        "score 2":  "Very low rigor — many unsupported claims, poor citation practice, and factual errors.",
        "score 3":  "Low rigor — partial or inconsistent citation and occasional misrepresentation of methods/results.",
        "score 4":  "Below-average rigor — citations present but incomplete and some claims lack supporting evidence.",
        "score 5":  "Moderate rigor — generally correct citations and basic methodological descriptions but missing nuance.",
        "score 6":  "Good rigor — solid citation practice and fair representation of methods with minor gaps.",
        "score 7":  "Strong rigor — careful referencing, transparent presentation of methods and limitations.",
        "score 8":  "Very strong rigor — thorough citations, balanced critique of methods, and clear evidence-backed claims.",
        "score 9":  "Excellent rigor — meticulous referencing, rigorous methodological critique, and consistently supported claims.",
        "score 10": "Exceptional rigor — exemplary scholarship: exhaustive, accurate citations and deep, transparent methodological analysis."
    },

    "Clarity": {
        "aspect": "Writing Quality",
        "description": "Clarity: precision in technical descriptions, definitions, and explanations so readers can unambiguously understand methods and results.",
        "score 1":  "Opaque — technical terms undefined, descriptions vague or misleading.",
        "score 2":  "Very unclear — frequent ambiguity in definitions and technical statements.",
        "score 3":  "Unclear in places — several technical passages lack precision or necessary definitional context.",
        "score 4":  "Somewhat clear — important terms sometimes defined, but many explanations remain imprecise.",
        "score 5":  "Moderately clear — most terms and methods are defined, but some technical ambiguity persists.",
        "score 6":  "Generally clear — technical descriptions are understandable though occasionally terse or under-specified.",
        "score 7":  "Clear — good precision in explanations and consistent definitions of key concepts.",
        "score 8":  "Very clear — technical passages are well-explained and precise; readers can reproduce reasoning.",
        "score 9":  "Extremely clear — excellent definitional consistency and precise, unambiguous technical exposition.",
        "score 10": "Perfect clarity — crystal-clear technical writing enabling immediate reproducibility and understanding."
    },

    "Coherence": {
        "aspect": "Writing Quality",
        "description": "Coherence: internal consistency of claims, definitions, and conclusions across sections (no contradictions or drifting terms).",
        "score 1":  "Contradictory — multiple direct contradictions and inconsistent use of terms across the text.",
        "score 2":  "Very incoherent — frequent inconsistencies and shifting definitions or claims.",
        "score 3":  "Inconsistent — notable contradictions or drifting terminology that confuse the narrative.",
        "score 4":  "Some inconsistencies — occasional contradictions or uneven use of terms across sections.",
        "score 5":  "Partly coherent — most sections consistent but a few conflicting statements remain.",
        "score 6":  "Generally coherent — consistent claims and terminology with minor lapses.",
        "score 7":  "Coherent — internally consistent throughout, with good alignment between sections and conclusions.",
        "score 8":  "Very coherent — strong internal consistency; different parts reinforce a unified message.",
        "score 9":  "Highly coherent — near-perfect consistency and thematic harmony across the survey.",
        "score 10": "Exceptionally coherent — flawless internal consistency; every section supports the central narrative."
    },

    "Clarity & Coherence": {
        "aspect": "Writing Quality",
        "description": "Clarity and Coherence: the extent to which the survey presents technical ideas with precision, unambiguous definitions, and internally consistent terminology, claims, and conclusions across sections.",
        "score 1":  "Very poor — highly vague, undefined terms, and multiple contradictions or inconsistent claims throughout.",
        "score 2":  "Poor — frequent ambiguity and major inconsistencies that seriously hinder understanding.",
        "score 3":  "Weak — many passages are unclear, with noticeable drifting terminology or conflicting statements.",
        "score 4":  "Below average — some key ideas are understandable, but clarity is limited and inconsistencies remain in several places.",
        "score 5":  "Moderate — the survey is mostly understandable, but important technical details are under-specified and coherence is uneven.",
        "score 6":  "Fairly good — generally clear and mostly consistent, with a few imprecise explanations or minor inconsistencies.",
        "score 7":  "Good — technical terms are usually defined well, and the narrative is coherent with only small lapses.",
        "score 8":  "Very good — clear, precise, and internally consistent; readers can follow the logic with little effort.",
        "score 9":  "Excellent — highly precise exposition with strong definitional consistency and near-zero contradictions.",
        "score 10": "Outstanding — crystal-clear, fully consistent, and immediately understandable; every section reinforces a unified narrative."
    },

    # ---------- Content Depth ----------
    "Comprehensiveness": {
        "aspect": "Content Depth",
        "description": "Comprehensiveness: breadth of coverage across subtopics, methods, datasets, and perspectives relevant to the research area.",
        "score 1":  "Extremely narrow — only a tiny slice of the topic covered; many core areas absent.",
        "score 2":  "Very limited — major subtopics missing; coverage skewed to a few papers or approaches.",
        "score 3":  "Sparse — several important areas omitted and coverage lacks depth.",
        "score 4":  "Partial — some important areas covered but many relevant subtopics absent or lightly treated.",
        "score 5":  "Moderate — key areas present but notable gaps in methods, datasets, or perspectives.",
        "score 6":  "Reasonably comprehensive — most core areas covered though some peripheral topics missing.",
        "score 7":  "Comprehensive — broad coverage including major methods and datasets with minor omissions.",
        "score 8":  "Very comprehensive — covers almost all relevant facets with useful detail across areas.",
        "score 9":  "Extensive — deep and wide coverage across subfields and perspectives; only small gaps remain.",
        "score 10": "Exhaustive — near-complete coverage across the domain, methods, datasets, and viewpoints."
    },

    "Critical Analysis": {
        "aspect": "Content Depth",
        "description": "Critical analysis: depth of evaluation, fairness of critique, and the comparative assessment of strengths/weaknesses across works.",
        "score 1":  "No critique — purely descriptive with no critical evaluation of methods or findings.",
        "score 2":  "Very weak critique — token criticisms that are superficial or inaccurate.",
        "score 3":  "Shallow critique — limited or one-sided criticisms lacking evidence or depth.",
        "score 4":  "Some critique — occasional meaningful evaluation but inconsistent and incomplete.",
        "score 5":  "Moderate critique — reasonable evaluations but lacking systematic comparative rigor.",
        "score 6":  "Good critique — fair assessments, identifies key weaknesses and trade-offs in several areas.",
        "score 7":  "Strong critique — systematic comparisons, balanced judgments, and evidence-backed critiques.",
        "score 8":  "Very strong critique — deep analysis of methodological limitations, assumptions, and empirical gaps.",
        "score 9":  "Excellent critique — rigorous, balanced, and insightful comparative evaluation across major works.",
        "score 10": "Masterful critique — transformative critique that clarifies fundamental limits, suggests remedies, and reshapes thinking."
    },

    "Novelty and Insights": {
        "aspect": "Content Depth",
        "description": "Novelty and insights: the degree to which the survey produces original synthesis, useful conceptual reframing, or fresh research questions.",
        "score 1":  "No novelty — restates existing content without any new perspective or insight.",
        "score 2":  "Very little novelty — trivial observations only; no original framing or notable insight.",
        "score 3":  "Low novelty — occasional small observations, but no meaningful new contribution.",
        "score 4":  "Limited novelty — a few modest insights but mostly derivative.",
        "score 5":  "Some novelty — useful observations that add modest clarity or re-organization.",
        "score 6":  "Notable novelty — several original observations or useful reframings emerge.",
        "score 7":  "Strong novelty — clear new insights or a helpful conceptual framing that aids understanding.",
        "score 8":  "Very strong novelty — original synthesis that changes how parts of the field are seen.",
        "score 9":  "Excellent novelty — significant conceptual contribution or new taxonomy with wide applicability.",
        "score 10": "Exceptional novelty — groundbreaking synthesis or insight that opens new directions or major re-interpretation."
    },

    "Future Directions": {
        "aspect": "Content Depth",
        "description": "Future directions: quality and specificity of identified open problems, research trajectories, and actionable next steps for the field.",
        "score 1":  "No future directions — none suggested or suggestions are irrelevant/obvious to the point of uselessness.",
        "score 2":  "Very weak — vague or trivial future work statements without justification.",
        "score 3":  "Weak — a few general suggestions that lack specificity or connection to gaps.",
        "score 4":  "Limited — some potential directions mentioned but they are broad and under-motivated.",
        "score 5":  "Moderate — plausible future directions linked to gaps but lacking concrete research paths.",
        "score 6":  "Good — relevant and justified directions with some sense of how to pursue them.",
        "score 7":  "Strong — clear, actionable research directions that address concrete gaps and trade-offs.",
        "score 8":  "Very strong — well-motivated, specific proposals and near-term experiments or benchmarks suggested.",
        "score 9":  "Excellent — insightful and prioritized research agenda with clear milestones and evaluation ideas.",
        "score 10": "Outstanding — visionary yet practical roadmap for the field, with detailed, high-impact research programs and measurable goals."
    },

    "Specified Future Directions": {
        "aspect": "Content Depth",
        "description": "Future directions: the extent to which the survey provides concrete, well-justified, and actionable guidance for future research, including clearly defined problems, feasible methodologies, experimental setups, and evaluation strategies.",
        "score 1":  "Absent — no meaningful future directions or only trivial/obvious statements.",
        "score 2":  "Very weak — vague suggestions with no actionable detail or justification.",
        "score 3":  "Weak — general directions mentioned but disconnected from identified gaps and lacking feasibility discussion.",
        "score 4":  "Limited — some relevant directions, but still broad, under-specified, and difficult to operationalize.",
        "score 5":  "Moderate — plausible directions linked to gaps, but limited detail on how to implement or evaluate them.",
        "score 6":  "Good — directions are relevant and partially actionable, with some discussion of methods or evaluation.",
        "score 7":  "Strong — clearly defined problems with actionable research paths, including hints of methodology or experimental design.",
        "score 8":  "Very strong — specific and well-motivated directions, with concrete proposals (e.g., datasets, benchmarks, model designs) and feasibility considerations.",
        "score 9":  "Excellent — detailed and insightful research agenda, including prioritized problems, methodological guidance.",
        "score 10": "Outstanding — highly actionable and deeply analyzed roadmap, offering concrete research programs with justified feasibility, step-by-step strategies, and measurable success criteria."
    },

    "Specificity": {
        "aspect": "Content Depth",
        "description": "Specificity: the granularity and concreteness of the survey's analysis, including whether it goes beyond high-level summaries to discuss concrete implementation details, code-level mechanisms, module interactions, design choices, operational steps, and fine-grained distinctions between methods.",
        "score 1":  "Extremely vague — entirely generic statements with no concrete mechanisms, examples, or fine-grained analysis.",
        "score 2":  "Very low specificity — mostly broad labels or superficial lists; almost no detail beyond high-level descriptions.",
        "score 3":  "Low specificity — a few concrete terms appear, but the survey remains mostly abstract and non-operational.",
        "score 4":  "Below-average specificity — some partial detail is given, but analysis is still dominated by general summaries.",
        "score 5":  "Moderate specificity — the survey includes some concrete mechanisms or examples, but many sections remain at a high level.",
        "score 6":  "Fair specificity — several parts discuss implementation or structural details, though the analysis is not consistently fine-grained.",
        "score 7":  "Good specificity — the survey regularly addresses concrete methods, internal mechanisms, or module-level distinctions.",
        "score 8":  "Very good specificity — detailed analysis of implementation choices, workflow steps, architectural components, or code-level behavior in multiple places.",
        "score 9":  "Excellent specificity — highly fine-grained discussion with precise breakdowns of mechanisms, modules, design trade-offs, and operational details.",
        "score 10": "Outstanding specificity — exceptionally granular analysis that closely examines implementation logic, code mechanisms, and detailed system behavior throughout the survey."
    }
}

JUDGE_WITH_CRITERIA_PROMPT = """Here is an academic survey about the topic "{TOPIC}":
{SURVEY}
Please evaluate this survey about the topic "{TOPIC}" based on the criterion above provided below, and give a score from 1 to 10 according to the score description: 
--- 
Criterion Description: {Criterion_Description} 
--- 
Score 1 Description: {Score_1_Description} 
Score 2 Description: {Score_2_Description} 
Score 3 Description: {Score_3_Description} 
Score 4 Description: {Score_4_Description} 
Score 5 Description: {Score_5_Description} 
--- 
Return the score and reason without any other information.

The output should be in strict JSON format as below:
**Output format:**
{{
    "score": <score from 1 to 5>, 
    "reason":"<your reasoning here>"
}}
"""

JUDGE_WITH_CRITERIA_PROMPT_10_DIMENSIONS = """Here is an academic survey about the topic "{TOPIC}":
{SURVEY}
Please evaluate this survey about the topic "{TOPIC}" based on the criterion above provided below, and give a score from 1 to 10 according to the score description: 
--- 
Criterion Description: {Criterion_Description} 
--- 
Score 1 Description: {Score_1_Description} 
Score 2 Description: {Score_2_Description} 
Score 3 Description: {Score_3_Description} 
Score 4 Description: {Score_4_Description} 
Score 5 Description: {Score_5_Description} 
Score 6 Description: {Score_6_Description} 
Score 7 Description: {Score_7_Description} 
Score 8 Description: {Score_8_Description} 
Score 9 Description: {Score_9_Description} 
Score 10 Description: {Score_10_Description} 
--- 
Return the score and reason without any other information.

The output should be in strict JSON format as below:
**Output format:**
{{
    "score": <score from 1 to 10>, 
    "reason":"<your reasoning here>"
}}
"""

JUDGE_WITH_CRITERIA_PROMPT_NO_EXP = """Here is an academic survey about the topic "{TOPIC}":
{SURVEY}
Please evaluate this survey about the topic "{TOPIC}" based on the criterion above provided below, and give a score from 1 to 10 according to the score description: 
--- 
Criterion Description: {Criterion_Description} 
--- 
Score 1 Description: {Score_1_Description} 
Score 2 Description: {Score_2_Description} 
Score 3 Description: {Score_3_Description} 
Score 4 Description: {Score_4_Description} 
Score 5 Description: {Score_5_Description} 
--- 
Return the score without any other information.
"""

JUDGE_WITH_CRITERIA_PROMPT_10_DIMENSIONS_NO_EXP = """Here is an academic survey about the topic "{TOPIC}":
{SURVEY}
Please evaluate this survey about the topic "{TOPIC}" based on the criterion above provided below, and give a score from 1 to 10 according to the score description: 
--- 
Criterion Description: {Criterion_Description} 
--- 
Score 1 Description: {Score_1_Description} 
Score 2 Description: {Score_2_Description} 
Score 3 Description: {Score_3_Description} 
Score 4 Description: {Score_4_Description} 
Score 5 Description: {Score_5_Description} 
Score 6 Description: {Score_6_Description} 
Score 7 Description: {Score_7_Description} 
Score 8 Description: {Score_8_Description} 
Score 9 Description: {Score_9_Description} 
Score 10 Description: {Score_10_Description} 
--- 
Return the score without any other information.
"""

NLI_PROMPT = """---
Claim:
{CLAIM}
---
Source: {SOURCE}
Claim: {CLAIM}
---
Is the Claim faithful to the Source? 
A Claim is faithful to the Source if the core part in the Claim can be supported by the Source.
Only reply with 'Yes' or 'No':
"""
