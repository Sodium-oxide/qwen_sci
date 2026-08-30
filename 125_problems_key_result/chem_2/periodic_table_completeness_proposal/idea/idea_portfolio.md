# Idea Agent Portfolio

## Inputs and invariants

The Idea Agent receives the Survey's verified IUPAC/IUPAP context and gaps `GAP-01` through `GAP-04`. It may propose models of conditional reachability and evidence quality. It may not claim that a prospective element exists, prescribe an accelerator experiment, replace IUPAC/IUPAP assessment, or turn an unobserved signal into a discovery.

## Candidate directions

### D1 — A taxonomy-only map of periodic-table completeness

**Mechanism.** Publish definitions separating institutional, observational, technological, and physical completeness, with examples from elements 113--118.

**Strength.** Resolves the language confusion in `GAP-01` and prevents public overclaiming.

**Weakness.** It does not quantify uncertainty or explain which barrier is most responsible for the next inaccessible region.

**Disposition.** Retained as a mandatory interpretive layer and reporting vocabulary, but not selected as the main research direction.

### D2 — Evidence-aware Bayesian reachability frontier for elements beyond 118

**Mechanism.** Construct a versioned corpus of historical discovery claims, recognized records, non-confirmations, nuclear-model predictions, and non-operational technology descriptors. Estimate separate uncertainty-bearing components for physical stability, scenario-conditional production/detection reachability, and proof-chain sufficiency. Combine them only in a transparent decision layer that can abstain when evidence is inadequate.

**Strength.** Addresses all four gaps. It gives a falsifiable way to distinguish ``currently inaccessible,'' ``evidence-insufficient,'' and ``physically doubtful under the model ensemble,'' while preserving the difference between them.

**Weakness.** The corpus is sparse at the extreme upper end; historical methods differ; any probability is conditional on model and technology descriptors. The output cannot be a calendar date or a guarantee of discovery.

**Disposition.** Selected primary direction.

### D3 — Automated decay-chain claim scorer

**Mechanism.** Train an event/claim classifier from published evidence fields to identify whether a proposed future observation contains a complete proof chain.

**Strength.** Directly targets `GAP-03` and may help audit evidence completeness.

**Weakness.** Raw detector traces and experimental context cannot be reduced to a generic classifier without a strict, expert-approved schema. It risks treating a software score as an IUPAC decision.

**Disposition.** Retained as a future audit module inside D2, not as a discovery arbiter.

### D4 — Single-number forecast of the final atomic number

**Mechanism.** Fit a regression or extrapolation and announce an endpoint for the periodic table.

**Strength.** Communicatively simple.

**Weakness.** Conflates model uncertainty, physical existence, technology, and formal recognition; cannot be robustly falsified in the relevant range; violates `GAP-01` and `GAP-02`.

**Disposition.** Rejected.

## Selection comparison

| Criterion | D1 Taxonomy | D2 Reachability frontier | D3 Claim scorer | D4 Endpoint number |
|---|---:|---:|---:|---:|
| Alignment to accepted gaps | 1/4 | 4/4 | 2/4 | 0/4 |
| Falsifiability | Medium | High | Medium | Low |
| Respect for IUPAC/IUPAP roles | High | High | Medium | Low |
| Physical/technology separation | High | High | Low | Low |
| Overclaim risk | Low | Medium, controllable | High | Very high |
| Selected role | Vocabulary layer | **Primary direction** | Audit module | Rejected |

Scores are deliberative choices, not measured performance data.

## Selected hypothesis

**H-REACH.** *When frozen at a historical time cutoff, a model that separately represents nuclear-stability uncertainty, technology/evidence scenarios, and proof-chain completeness will produce better-calibrated classifications of subsequently documented reachability outcomes than a stability-only or technology-only baseline, while abstaining on cases whose evidence is insufficient.*

The result can be negative in several useful ways. Stability-only models may perform just as well; the extra evidence layer may add noise; historical labels may be too sparse; or the model may prove unable to separate a physics boundary from an evidence boundary. A negative result narrows the method's validity; it does not establish that the periodic table is complete.

## Primary-direction synopsis

**Title.** *Beyond Element 118: A Calibrated, Evidence-Aware Frontier for Conditional New-Element Reachability.*

**Research object.** A time-versioned corpus of published nuclear predictions, documented discovery/non-confirmation records, IUPAC/IUPAP evidence artifacts, and high-level technology descriptors.

**Intervention.** Replace a single extrapolated final-atomic-number claim with a three-layer model: physical stability, scenario-conditional reachability, and proof sufficiency.

**Mechanism.** The model retains disagreement among nuclear theories and prevents a favorable stability forecast from becoming a discovery claim. Its decision layer may only label a case as conditional, uncertain, or abstained; formal recognition remains external.

**Evidence of success.** In a future retrospective validation, D2 has better calibrated and better discriminating predictions than declared baselines on time-split historical outcomes, and its abstention set is scientifically interpretable.

**Key risks.** Sparse extrema, unobserved confounders in facility descriptors, inconsistent historical terminology, model-era leakage, and misuse of a model output as an institutional decision. Each risk becomes a gate in ExperimentDesign.
