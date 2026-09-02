# Idea Agent: Task- and State-Conditioned Causal Neural Code Atlas

## Intake

The Survey handoff identifies G1--G6 as accepted gaps. It also establishes a non-negotiable distinction between information being present in a recorded spike train and information being used by a biological downstream circuit. The Idea Agent therefore searches for a research direction that is comparative, falsifiable, and implementable as a future design without claiming that any dataset has already been analyzed.

## Candidate search routes

**R1: Rate--timing information decomposition.** Fit matched rate-only, latency, inter-spike interval, and full point-process models. Estimate incremental information with cross-validation and bias-controlled information estimators. This directly addresses G1 and G6, but by itself does not resolve population geometry or causal use.

**R2: Correlation-aware population decoder.** Compare independent, pairwise, and latent-variable population models over controlled population sizes. Measure redundancy and synergy under correlation-preserving and correlation-destroying nulls. This addresses G1 and G4, but a decoder can still be behaviorally irrelevant.

**R3: State-conditioned neural manifold.** Estimate population trajectories and task-relevant subspaces across arousal, movement, attention, and task conditions. Test whether individual neurons remap while a population subspace remains predictive. This addresses G2 and G5, but geometry alone cannot establish causal use.

**R4: Causal downstream code assay.** Identify a candidate coding dimension, construct a matched perturbation that selectively changes its rate, timing, correlation, or subspace coordinate, and measure downstream behavior or decision variables against sham and nuisance-matched controls. This addresses G3 and G8, but it is experimentally expensive and requires ethics, hardware, and perturbation validation.

**R5: TSCC-A atlas.** Combine R1--R4 in a staged protocol with a common data schema, preregistered nested models, cross-condition generalization, population-geometry analysis, and a gated causal module. The atlas reports a condition-specific coding vector rather than a single global winner. It is the only route that covers all accepted gaps while preserving the distinction between statistical availability and biological use.

## Selected direction

**Task- and State-Conditioned Causal Neural Code Atlas (TSCC-A).** The central hypothesis is:

> If a coding dimension is functionally embedded in a neuronal population, its stimulus information should generalize across held-out stimuli and state conditions, improve a downstream-relevant decoder beyond matched nulls, and show a selective causal effect when the corresponding spike pattern or population subspace is perturbed.

The hypothesis is intentionally stronger than “a decoder can read the signal,” but it remains falsifiable. A coding dimension may pass the encoding test and fail the causal-use test. The output is consequently an atlas of conditional evidence, not a declaration that the brain uses one code everywhere.

## Formal object and novelty

For condition $c=(\text{state},\text{task},\text{area},\text{species})$, define
\begin{equation}
\mathbf C(c)=\left(I_{\rm rate},I_{\rm time},I_{\rm corr},I_{\rm pop},I_{\rm state}\right),
\end{equation}
where each component is estimated against an explicitly matched null and reported with uncertainty. A dimension is promoted from “available” to “functionally embedded” only if it satisfies three gates: held-out information, downstream relevance, and selective causal sensitivity. This three-gate structure is the principal innovation. It unifies information theory, point-process statistics, population geometry, and causal perturbation without assuming that one representation is privileged.

## Falsification and alternative explanations

The atlas is falsified as a useful unified framework if a simpler rate-only model matches the full model across held-out stimuli, states, tasks, neurons, and time windows, while the added dimensions produce no reproducible effect; or if apparent causal effects are fully explained by changes in movement, arousal, recording quality, or non-specific population disruption. A positive timing result that disappears under count-matched jitter is not accepted as timing-specific. A manifold result that predicts behavior but is not selective under subspace perturbation remains a geometric correlate, not a causal code.

## Portfolio decision

The selected TSCC-A route is primary. R1 and R2 are competitive components and can produce publishable partial results if the causal module is not feasible. R3 is a high-value companion route for motor and sensory datasets. A “single universal code” route is rejected because it contradicts the Survey's conditional evidence boundary and creates an unfalsifiable cross-context claim. A decoder-only route is rejected as a complete answer because it cannot distinguish availability from biological use.

## Expected contributions

1. A preregistered representation ledger that makes rate, timing, correlation, population geometry, state dependence, and hybrid models comparable.
2. A cross-condition evaluation protocol that exposes stimulus-neuron mappings that fail under context changes.
3. A causal criterion for promoting a statistical coding feature to a functionally embedded feature.
4. A reusable atlas format that reports positive, null, and unresolved findings without collapsing them into a single score.

## Status

This is an Idea Agent output. No neural recordings, simulations, perturbations, or behavioral results have been performed. Any result described in later sections is a conditional prediction of the proposed design.
