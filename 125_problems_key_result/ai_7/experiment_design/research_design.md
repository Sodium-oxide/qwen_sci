# ExperimentDesign Agent: CREATIVE-AI-AGENCY-BENCHMARK

## 1. Design status

This document is a preregistration-ready protocol. It contains no observed model
outputs, human ratings, or performance claims. The default execution mode is
simulation-first and offline. Any participant study requires local ethics review,
consent, low-stakes tasks, and a separate approval before recruitment.

## 2. Study stages

### Stage A: controlled offline benchmark

Freeze model versions, prompts, sampling parameters, retrieval indexes, task instances,
random seeds, and evaluation code. Partition every task family into training/reference,
development, and held-out test concepts. Generate at least 20 independent candidates per
condition and task instance. Retain full prompts, candidates, tool calls, search trees,
edits, rejected candidates, and timestamps.

### Stage B: sandbox co-creation

Implement a local interface with four role policies: human-first, AI-first, alternating
turns, and critique-only. The interface must support human veto, revision, undo, export
of provenance, and deletion of participant data. No external posting, purchasing,
deployment, or high-stakes recommendation is allowed.

### Stage C: optional blinded evaluation

Use low-stakes artifacts and independent raters. Randomize source labels and presentation
order. Each rater scores novelty, usefulness, surprise, coherence, and constraint
satisfaction separately, with an "insufficient information" option. A second evaluation
uses objective tests whenever the domain allows them. Report inter-rater reliability and
do not interpret preference as evidence of agency.

## 3. Experimental factors

The minimum factorial comparison includes:

* author: human-only, AI-only, or human-AI;
* retrieval: reference-enabled or reference-disabled;
* search: single-sample, generate-and-rank, or tree/search trace;
* critique: absent, model self-critique, or human critique;
* order: human-first or AI-first;
* evaluation: blind or source-labeled;
* task split: in-distribution, held-out concept, held-out domain, and perturbed
  constraints.

Use blocked randomization by task family and difficulty. Do not compare different model
families without reporting compute budget, context length, tool access, and training data
exposure.

## 4. Operational metrics

Let candidate x be evaluated relative to a reference set R, objective constraints C,
and a task value function V. The primary product profile is:

* novelty: embedding distance to the nearest reference, adjusted for length and domain;
* usefulness: normalized objective score or preregistered blinded rating;
* surprise: calibrated evaluator unexpectedness, reported separately from value;
* diversity: mean pairwise distance among independent candidates;
* constraints: proportion of hard constraints satisfied;
* transfer: performance difference between development and held-out concepts/domains;
* memorization: nearest-neighbor similarity, phrase overlap, and canary recovery;
* process: search breadth, revision gain, error correction, and response to perturbation;
* co-creation: joint score, human edit distance, veto rate, and marginal contribution.

Avoid a single creativity index in the primary analysis. A preregistered exploratory
profile score may be computed only after all axis-level results are reported.

## 5. Candidate statistical model

For task-level outcome y from condition i, task family j, instance k, and replicate t,
fit a hierarchical model with task and replicate effects. Report effect sizes and
uncertainty intervals, not only p-values. Planned contrasts are AI-only versus
human-only, human-AI versus the better solo baseline, retrieval versus no retrieval,
and critique versus no critique.

Multiplicity is controlled by treating the product profile as a family of preregistered
primary axes. Transfer and provenance analyses are confirmatory for process claims;
ratings of agency are not analyzed as evidence of consciousness.

## 6. Falsification tests

* Replace the reference corpus and repeat novelty scoring.
* Introduce semantically equivalent but visually new constraints.
* Test canary concepts absent from training and retrieval sources.
* Shuffle or truncate search traces to test whether raters infer creativity from style.
* Keep the final artifact fixed while changing source labels to quantify expectancy bias.
* Compare generated candidates with a retrieval-matched recombination baseline.
* Evaluate transfer after prompt paraphrase and task-order permutation.

## 7. Reproducibility package

Release task specifications, public reference data, hashes of private data, model and
tool versions, seeds, prompts, evaluation scripts, metric definitions, exclusion rules,
and an event log. If model weights or data cannot be redistributed, release an executable
adapter and a complete provenance record. Record compute energy only as contextual
metadata; it is not a creativity metric.

## 8. Safety, ethics, and interpretation

The benchmark is not a test of consciousness, sentience, moral status, or human worth.
It must not be used to rank people by intelligence or creativity. Human participants are
not exposed to clinical, employment, educational, or legal decisions. Generated
scientific hypotheses remain proposals until independently checked. Dataset licenses,
privacy, copyright, and contamination are audited before release. Human evaluators may
withdraw and delete their data.

## 9. Decision rules

Support for bounded product creativity requires improvement over a retrieval-matched
baseline on both novelty and value while meeting hard constraints. Support for process
creativity additionally requires held-out transfer, adaptive error correction, and
robustness to perturbations. Support for co-creativity requires a predeclared joint
advantage over both solo baselines and a measurable complementary contribution pattern.
None of these rules supports a claim of human-like consciousness or intention.
