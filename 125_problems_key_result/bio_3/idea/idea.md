# Idea - FATE-LOCK

## Proposal

This project proposes **Fate Accessibility and Transition Evaluation - Lineage, Omics, Control, and Kinetics (FATE-LOCK)**, a design-only framework for testing why a cell state is stable and under which declared conditions it can transition to a defined target state. The framework does not treat potency as a single number. It links a source cell's lineage provenance, regulatory state, chromatin accessibility, niche input, perturbation exposure, trajectory, target function, and safety properties.

## Research question and hypotheses

For a declared source cell population, target identity, microenvironment, and perturbation set, which factor combinations causally change the probability and route of entering a stable, functional target state while retaining acceptable genomic and lineage safety?

- **H0:** apparent conversion is caused by source-cell contamination, marker ambiguity, selection of a rare pre-existing cell, batch effects, doublets, or transient stress.
- **H1:** a specified perturbation modifies regulatory and niche gates so that lineage-traced source cells reach a reproducible target-state trajectory and target-relevant function.
- **H2:** cells acquire selected markers but remain incomplete, unstable, mixed-lineage, or unsafe; this is partial reprogramming, not a target identity claim.
- **H3:** an intervention changes state access only in a source, niche, cell-cycle, or genetic context; broad claims of universal cellular plasticity are unsupported.

## Design contribution

FATE-LOCK couples time-resolved single-cell RNA and chromatin readouts with lineage tracing, perturbation controls, source-purity audits, functional validation, and persistence after cue withdrawal. It requires a separate safety gate for genomic alterations, residual pluripotent cells where relevant, uncontrolled proliferation, off-target lineages, and inappropriate in vivo extrapolation. A successful in-vitro state transition is not a cell therapy, tissue repair result, or clinical safety demonstration.

## Bounded conclusion language

Passing the framework can support: ``In the stated model and under the stated perturbations, lineage-traced source cells acquired a preregistered target-like state and passed the declared identity, stability, function, and safety gates.'' It cannot support: ``all cells can become any cell,'' ``a marker-positive population is fully differentiated,'' or ``a reprogrammed product is clinically safe.''
