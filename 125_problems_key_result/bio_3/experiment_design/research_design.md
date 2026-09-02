# ExperimentDesign - FATE-LOCK Protocol

## Status and scientific unit

**DESIGN_ONLY.** No cells were isolated, cultured, perturbed, sequenced, or transplanted. The scientific unit is a lineage-traceable source cell (or clone) with a versioned source identity, culture/niche condition, perturbation history, time point, assay batch, and target-state assessment. The protocol asks for a bounded source-to-target transition, not a universal property of all cells.

## Scenario ladder

| Scenario | Purpose | Permissible conclusion |
|---|---|---|
| S0 - source audit | Verify source purity, lineage provenance, and target-marker specificity | Source population is defined for the stated assay |
| S1 - state atlas | Establish time-resolved transcriptomic/chromatin reference states under baseline conditions | State variation is mapped, not causally explained |
| S2 - perturbation core | Test a frozen factor, signaling, matrix, or niche perturbation against matched controls | Bounded causal state-access contrast in the stated model |
| S3 - stability/function | Test persistence after cue withdrawal and target-relevant function | Target-like behavior is supported within the assay scope |
| S4 - independent replication | Repeat locked protocol in an independent batch/site/source donor set | Reproducibility support for the stated boundary |

## Experimental arms and controls

The protocol prespecifies: source-cell class; target cell type; identity markers and anti-markers; perturbation class; dose/timing range only after model-specific ethics and biosafety review; culture medium; matrix; neighboring-cell/conditioned-medium inputs; oxygen/nutrient conditions; cell-cycle synchronization policy; and assay times. Controls include untreated baseline, vector or delivery control where applicable, perturbation-minus-key-factor control, known-reference target cells, source-cell spike-in controls, technical replicates, biological replicates, sample swaps, and blinded assay labels.

## Readouts and identity hierarchy

1. **Provenance gate:** genetic or physical lineage tracing distinguishes induced transitions from contamination, doublets, or survival of a rare precursor.
2. **State gate:** RNA, chromatin, protein, and morphology are compared against source and reference target atlases with predeclared markers and anti-markers.
3. **Trajectory gate:** multiple time points distinguish a plausible transition route from a post hoc endpoint similarity.
4. **Function/stability gate:** target-relevant function and persistence after cue withdrawal are measured in the declared model.
5. **Safety gate:** proliferation, residual pluripotency where relevant, off-target lineages, genome integrity, and tumor-related risk signals are investigated before any translational claim.

## Analysis and causal tests

Represent each cell with a multidomain state vector spanning transcriptomic, chromatin, protein, cell-cycle, and niche variables. Fit time-resolved trajectory models only after source provenance is confirmed. The primary comparison is the difference in target-state occupancy and target-function distribution between the locked perturbation and matched control. Report every component readout, not only the target marker.

Perform factor ablation, rescue, timing, and niche perturbations to distinguish a required regulator from correlated response. Use synthetic doublets, known source/target mixtures, barcode collisions, batch shifts, and transient stress signatures to test whether the inference pipeline falsely calls conversion. The protocol must correctly identify the injected artifact and refrain from declaring a target state in null-control data.

## Decision rules and reproducibility

A source-to-target claim requires all gates: verified provenance; agreement across predeclared state modalities; a time-resolved trajectory; target-relevant function; persistence after induction cues are withdrawn; and no breached safety rule for the stated assay/model. A clinical or regenerative-medicine claim additionally requires a distinct product, manufacturing, delivery, host-interaction, tumorigenicity, biodistribution, and long-term safety program. Release protocol version, source identity, culture/niche conditions, perturbations, barcode design, raw/processed data subject to governance, code, reference atlases, quality metrics, excluded cells, null tests, and failed replicates.
