"""Prompts for evidence-bounded, post-draft survey visualisation.

The image model is deliberately given a compact ``VisualBrief`` instead of the
whole survey. This keeps generated figures tied to an auditable part of the
finished manuscript and prevents the image model from inventing a second,
untraced narrative.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


FIGURE_TYPE_LAYOUT_INSTRUCTIONS = {
    "overview_framework": (
        "Build a polished scientific visual abstract with one central thesis or system "
        "anchor, surrounding evidence and process modules, and a visually distinct "
        "outcome or interface region. Use nested regions, varied module scales, "
        "symbolic icons, structured connectors, and a compact semantic strip. Avoid "
        "a flat row of identical boxes."
    ),
    "mechanism": (
        "Build a visually rich causal systems map rather than a simple linear flowchart. "
        "Place the dominant mechanism or outcome as a central anchor, arrange upstream "
        "drivers as an asymmetric evidence cluster, and place intermediate processes "
        "as layered or nested modules. Use solid connectors for direct support, dashed "
        "or translucent connectors for qualified or unresolved relations, and include "
        "one restrained inset, symbolic icon, or uncertainty region when supported by "
        "the supplied content. Avoid repeated equal-sized cards."
    ),
    "causal_pathway": "Arrange supplied drivers, mediators, and outcomes into a readable causal pathway; keep qualified or unresolved links visibly distinct.",
    "evidence_to_inference": "Organize three levels: source observations or cited evidence, intermediate analysis or theory, and survey-level inference; never turn background context into direct evidence.",
    "method_comparison": "Use balanced parallel panels or converging pathways for the supplied approaches; show inputs, analytical focus, contribution, and stated limitation without unsupported ranking.",
    "multiscale_synthesis": "Show supplied scales, levels, stages, or system layers in a clear nested or progressive arrangement; connect levels only where explicitly supported.",
    "conceptual_workflow": "Arrange supplied conceptual stages into a practical workflow with a clear beginning, intermediate steps, and outcome.",
    "research_landscape": "Map supplied approaches, themes, or evidence clusters as a conceptual landscape, not a quantitative ranking or bibliometric chart.",
    "future_roadmap": "Organize established foundations, present limitations, and explicitly stated future directions into a forward-looking roadmap; show open questions as muted or dashed elements.",
}


VISUAL_CANDIDATE_PLANNER = """You are the visual editor for a completed academic survey.

Choose only the sections where a conceptual scientific figure would materially improve
reader understanding. This is a multidisciplinary task: do not assume a specific field.
Prefer a small, diverse figure set over an image after every heading.

Allowed figure types:
{allowed_figure_types}

Survey title:
{survey_title}

Approved outline context:
{outline_context}

Sections (paragraph indices restart at 1 inside each section):
{sections}

Task:
Aim for {min_figures} to {max_figures} candidates when the survey has enough eligible
material; never force a weak candidate merely to hit the target. A candidate is allowed only when it can
integrate multiple supplied paragraphs or at least three supplied entities/processes.
Choose distinct knowledge functions across the survey where possible. Do not select the
references section. Do not select a section that only lists papers, definitions, or
unsupported speculation. Do not choose a data chart when exact data are required.
{numeric_chart_policy}

Return exactly one JSON object in this schema:
{schema}

Use English for every reader-facing string. Do not add scientific facts absent from the
supplied section excerpts. ``source_paragraph_indices`` must identify the supplied
paragraphs that justify the proposed figure."""


VISUAL_BRIEF_BUILDER = """You are preparing a tightly evidence-bounded visual brief for a
publication-ready conceptual scientific figure in an academic survey.

Survey title: {survey_title}
Section title: {section_title}
Selected figure type: {figure_type}
Proposed purpose: {proposed_message}

Approved outline context for this section:
{outline_context}

The only survey paragraphs that may supply scientific content are below:
{source_paragraphs}

Evidence-plan context (this gives permitted evidence boundaries, not extra facts):
{evidence_context}

Task:
Create one concise but visually specific art-direction brief. It must explain
relationships already present in the supplied paragraphs, and it must make explicit
uncertainty, qualification, or evidence gaps when the paragraphs state them. It must
never introduce new measurements, numerical values, causal links, instruments,
entities, biological structures, physical processes, or comparative rankings.

The composition_en field must be an actionable visual blueprint, not a generic sentence
such as "Use a left-to-right layout." Specify:
1. the dominant focal anchor;
2. the main spatial arrangement;
3. the hierarchy between primary, secondary, and uncertain relationships;
4. at least one supported visual motif, such as an inset panel, symbolic icon,
   layered region, loop, bridge, scale transition, or localized zoom;
5. the connector language: solid, dashed, translucent, branching, converging, or looping;
6. how colour and depth distinguish the major semantic roles;
7. a controlled label budget using short English labels only.

Prefer a visually rich editorial infographic or systems map over a generic three-column
flowchart. Avoid equal-width repeated cards and avoid an empty canvas. Keep the layout
readable and evidence-bounded.

All reader-facing content must be English. Write a concise English caption and English
alt text. Caption text will be placed beneath the image, not drawn into the image.

For every relation, include an exact contiguous quote from the supplied source paragraphs,
retaining the source language, and the paragraph index containing that quote. The program, not you, derives
the evidence support kind from the evidence plan and claim trace. Do not return a relation
that cannot be grounded by an exact supplied quote.

Return exactly one JSON object in this schema:
{schema}"""


VISUAL_BRIEF_REPAIR = """Repair one rejected visual brief for a completed academic survey.

Survey title: {survey_title}
Section title: {section_title}
Selected figure type: {figure_type}

Source paragraphs (the only permitted scientific source):
{source_paragraphs}

Evidence-plan context:
{evidence_context}

Original brief response:
{original_payload}

Deterministic validation findings:
{rejection_reasons}

Return one corrected JSON object using this schema:
{schema}

Repair format and grounding only. Preserve the supplied scientific meaning. Every
relation must use an exact contiguous quote from one supplied paragraph and the correct
paragraph index. Do not invent entities, mechanisms, measurements, citations, or causal
links. Reader-facing fields must be concise English; source_quote must retain the source
paragraph language. The composition_en field must be an actionable art-direction
blueprint: name the focal anchor, spatial arrangement, visual hierarchy, connector
styles, one supported visual motif, and a short-label budget. Do not replace it with a
generic phrase such as "Use a left-to-right layout." Caption, alt text, and overlay
labels may be minimal, because the program supplies safe English fallbacks when they
are absent."""


ARTICLE_STYLE_PLANNER = """You are the art director for one multidisciplinary academic
survey. Create a single coherent visual style profile for polished scientific
infographics and systems maps that every figure in this survey will reuse.

Survey title: {survey_title}
Planned figures:
{figure_summaries}

Choose a palette appropriate to the topic, suitable for a rigorous, high-impact
scientific visual abstract: print-friendly, colour-blind-aware, layered enough to
support visual hierarchy, and readable on a light background. The palette must have
exactly these semantic roles:
background, ink, primary, secondary, accent, uncertainty. Return six valid #RRGGBB
hex colours. Do not choose a palette per figure; this one palette will be locked for the
whole survey.

The visual language should support controlled density, asymmetric but balanced layouts,
varied module scales, nested regions, symbolic icons, inset details, and distinct
connector styles. It should feel like an editorial scientific infographic rather than a
generic slide-deck flowchart. Keep the style coherent across figures without forcing
every figure into the same geometry.

Return exactly one JSON object in this schema:
{schema}

All prose values must be English."""


IMAGE_PROMPT = """Create a publication-ready conceptual scientific figure for an academic survey.

Figure type:
{figure_type}

Central message:
{main_message}

Scientific content that must be represented:
{relations}

Relationship rendering guidance:
{relation_guidance}

Entities or modules to include:
{entities}

Exact visible label inventory:
{exact_visible_labels}

Typography and layout protocol:
The inventory above is the only permitted reader-facing text. Copy each supplied label
character-for-character, including spelling, capitalization, hyphens, apostrophes, slashes,
underscores, and scientific symbols. Do not paraphrase, translate, abbreviate, pluralize,
correct, or merge labels. Do not render the surrounding JSON/list punctuation or quotation
marks. Do not render the full relation sentences, uncertainty sentences, evidence metadata,
Paper IDs, SH IDs, or any other prompt text. The entities/modules list is semantic guidance
only; render an entity name only when the exact same string appears in the inventory. If a
label cannot be rendered clearly, omit that label rather than inventing a replacement.

Use one short label per module, with a consistent readable sans-serif typeface, generous
letter spacing, strong contrast, and sufficient size for 100% PDF readability. Keep labels
inside their module boundaries with ample padding; never overlap labels, connectors, icons,
or panel borders. Do not create a legend, title, paragraph, axis, table, footnote, or caption
unless its exact text appears in the inventory.

Uncertainties or evidence boundaries to show:
{uncertainties}

Composition:
{composition}

Figure-type layout requirements:
{figure_type_layout}

Article-wide visual style:
{visual_language}

Locked article palette:
- Background: {background}
- Linework: {ink}
- Primary evidence-supported pathway: {primary}
- Secondary process or comparison group: {secondary}
- Key focal entity: {accent}
- Uncertainty or qualified relation: {uncertainty}

Visual language:
A visually rich editorial scientific infographic suitable for a high-impact
multidisciplinary research journal. Make it feel like a polished visual abstract or
systems-map poster, not a basic flowchart or presentation slide.

Create a clear focal hierarchy: one dominant visual anchor, two to four secondary
modules with different visual weights, and one restrained uncertainty or limitation
region. Build hierarchy through scale, position, layered panels, subtle tonal
backgrounds, symbolic icons, selective accent colour, and different connector weights.

Prefer an asymmetric but balanced composition. Combine grouped modules, inset details,
nested regions, branching or converging pathways, feedback loops, scale transitions, or
a compact semantic strip whenever supported by the supplied content. Use controlled
density: information-rich, visually layered, and detailed, while remaining readable at
50% scale in a PDF.

Do not repeat identical rounded rectangles and do not use a default three-column layout.

Text constraints:
Render only the exact labels from the inventory, preferably as 1–5 word labels. Never add
decorative pseudo-text or plausible-looking terminology. Before finalizing, perform an
internal character-by-character check against the inventory; if any character is uncertain,
leave that label out. Keep all reader-facing text sparse and subordinate to the visual
structure. Leave clean visual space for the separate English caption and programmatic labels.

Scientific constraints:
This is a conceptual synthesis of the supplied survey content, not a new empirical result.
Do not invent quantitative data, experimental measurements, causal mechanisms, instruments,
model properties, or conclusions. Use solid prominent pathways only for directly supported
relationships. Use restrained secondary pathways for qualified contributions. Use muted,
dashed, or translucent elements for explicit uncertainty, evidence gaps, or background context.

Negative prompt:
No photorealistic laboratory scene, no stock-photo appearance, no science-fiction aesthetic,
no neon palette, no rainbow gradient, no illegible text, no fake chart, no invented numerical
data, no fictional equation, no paper citation, no journal logo, no misspelled words, no
invented labels, no text outside the exact label inventory, no fake legend, and no tiny or
overlapping text.

Layout requirements:
- Do not use a flat sequence of equal-width boxes.
- Do not use a default left-to-right three-column flowchart.
- Establish one dominant anchor near the visual center or upper center.
- Use an asymmetric but balanced arrangement.
- Combine at least three of the following when scientifically appropriate: grouped
  modules, nested regions, inset detail, symbolic icons, branching pathways, converging
  pathways, feedback loops, layered backgrounds, scale transitions, or a compact
  semantic strip.
- Use solid primary-colour pathways for direct evidence-supported relations.
- Use thinner, dashed, or translucent pathways for qualified, indirect, contextual, or
  uncertain relations.
- Use the accent colour sparingly for the key focal entity or conclusion.
- Reserve muted grey-blue tones for context and uncertainty.
- Keep the figure readable at 50% scale in a PDF.

Output: landscape 4:3, high resolution, balanced margins, suitable for PDF and Markdown.
"""


VISION_QC_PROMPT = """Review this generated academic figure against the supplied figure brief.
The assessment is advisory: accept the image unless there is a clear factual, readability,
or style failure.

Figure brief:
{brief}

Locked article palette:
{palette}

Return exactly one JSON object with this schema:
{schema}

Reject only if the image has a major issue such as invented numerical data, fake readable
citations, an unsupported central relation, dense or garbled visible text, an obviously
incompatible palette, watermark/logo, or an unusable composition. Minor artistic variation
is acceptable. Do not reject merely because the image does not contain labels; labels are
added separately."""


def json_schema_text(schema: Mapping[str, Any]) -> str:
    """Render schemas consistently without introducing markdown fences."""

    return json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2)
