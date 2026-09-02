# Idea Agent: CREATIVE-AI-AGENCY-BENCHMARK

## Central idea

Build a multi-domain benchmark that decomposes creativity into product, process, and
co-creative components. The benchmark does not ask whether a machine is a person. It
asks whether a system can repeatedly produce useful novelty under new constraints while
exposing an auditable search trace.

## Mechanistic proposal

Creativity in an artificial system should be modeled as a pipeline:

1. construct a candidate in a bounded conceptual space;
2. explore alternatives rather than emit a single sample;
3. test candidates against explicit constraints and value functions;
4. revise after feedback;
5. transfer the strategy to a held-out concept or domain;
6. preserve provenance so retrieval and human intervention are separable.

This mechanism makes a useful distinction. A system can have high product creativity
(novel and useful outputs) with low process creativity (no robust transfer or adaptive
search). A human-AI team can have high joint performance even if neither participant
alone displays all of the team's capabilities. These are different scientific claims.

## Benchmark task families

* **Go:** propose legal moves for novel board states and explain the search trace; use
  AlphaGo as historical motivation, not as a creativity label.
* **Engineering design:** design a lightweight structure or device under mass, cost,
  strength, and manufacturability constraints; objective simulation supplies value.
* **Music or visual motifs:** generate a constrained motif with held-out combinations;
  report structural novelty and blinded ratings.
* **Code and algorithms:** generate an implementation that passes hidden tests and
  improves a measurable resource objective.
* **Scientific hypotheses:** propose testable mechanisms with predicted observations,
  competing explanations, and falsification conditions.
* **Cross-domain recombination:** combine two held-out concepts without copying either
  reference artifact.

## Falsifiable hypotheses

* **H0:** apparent creativity is explained by retrieval, recombination, or human choice;
  held-out transfer will not exceed matched controls.
* **H1:** AI systems can attain high product novelty and usefulness in bounded domains
  without demonstrating human-like agency.
* **H2:** search and self-critique increase value and constraint satisfaction, but may
  reduce diversity when the evaluator is optimized too directly.
* **H3:** human-AI collaboration outperforms solo baselines on selected tasks when roles
  are complementary and human veto remains available.
* **H4:** held-out concepts and cross-domain tasks reduce the advantage of memorization.
* **H5:** source labels increase perceived creativity, so blind evaluation is necessary.
* **H6:** traceable provenance changes attribution even when the final artifact is held
  constant.

## Expected contribution

The contribution is a reproducible measurement architecture, not a claim that current
AI is conscious or human. The architecture treats novelty, usefulness, surprise,
diversity, constraints, transfer, and contribution attribution as separate axes. Its
primary result will be a condition-by-metric profile and a failure analysis, not one
overall creativity number.

## Risks and mitigations

Mode collapse is tested by diversity metrics and independent sampling. Memorization is
tested by nearest-neighbor search, training-corpus exclusion, and canary concepts.
Evaluator bias is reduced by blind randomization. Human contribution is recorded at
operation level. All human evaluation is low-stakes and optional; no clinical,
employment, educational, or public authorship decisions are made.
