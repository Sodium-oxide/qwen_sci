# Experiment Design: ARCHAIC for Cross-Hominin Gene-Flow Inference

## 1. Study type and estimand

ARCHAIC is a coordinated ancient-DNA, comparative-genomic, and simulation-based study design. A first implementation specifies a focal recipient population, one or more ancient or high-coverage archaic references, an outgroup, a calendar-time window, and a target claim. The primary estimand is the relative predictive support for a defined demographic model, not a timeless percentage of ``archaic ancestry.''

## 2. Sampling and sample passport

Use dated ancient specimens where preservation and permissions allow, together with geographically and temporally stratified present-day genomes. The passport records specimen provenance, direct or stratigraphic age, extraction and library batch, endogenous DNA fraction, damage pattern, contamination interval, coverage, sex-chromosome handling, callability mask, reference genome version, and all population labels. Sequence at least two independent libraries for a suitable subset of critical fossils. Predeclare exclusions driven by contamination, coverage, or missing metadata before model fitting.

The design never assumes that a single fossil represents a whole population. It separates individual, site, time-bin, and lineage labels, and represents low-coverage calls as genotype likelihoods or pseudo-haploid observations with error uncertainty.

## 3. Authenticity and data controls

- Estimate terminal cytosine deamination and fragment-length distributions for each library.
- Bound mitochondrial and nuclear contamination with source-appropriate methods; run sensitivity analyses across credible contamination values.
- Use read-end trimming, mapping-quality thresholds, duplicate handling, and a callability mask fixed before admixture testing.
- Test reference bias by remapping or by allele-balanced procedures where feasible.
- Stratify results by transversions, read position, library, coverage class, autosomes, and sex chromosomes.

## 4. Competing models and analysis plan

1. Freeze the passport, quartet/population sets, outgroup, block definition, and primary alternatives.
2. Compute genome-wide D and f4 statistics with block jackknife uncertainty; test whether a tree model is rejected in preregistered comparisons.
3. Estimate mixture parameters only under an explicit source and graph model; compare models using likelihood, posterior predictive checks, and held-out populations or genomic blocks.
4. Infer local ancestry using at least two complementary methods (for example, a reference-based HMM and a demography-aware ancestral recombination graph) and measure their agreement.
5. Fit tract-length and time-serial models under recombination-map uncertainty; report a date interval, not a single historical date.
6. For direct-hybrid claims, test chromosome-scale ancestry and parental relatedness against simulated ILS, contamination, and mixed-reference alternatives.
7. Test functional or adaptive consequences only in a separately preregistered module that controls for demography, linked selection, annotation bias, and phenotype ascertainment.

## 5. Primary endpoints

- Signed D and f4 estimates with block-jackknife intervals for preregistered quartets.
- Relative held-out support for tree/structure, single-pulse, multi-pulse, reciprocal-flow, and ghost-source models.
- Agreement and uncertainty of local-ancestry assignments across methods and reference panels.
- Date and mixture intervals conditional on the stated recombination and demographic model.
- Direct-hybrid likelihood ratio for a specified ancient individual.
- Calibration and sensitivity of claim labels to damage, contamination, mask, sample selection, source panel, and recombination assumptions.

## 6. Claim decision rules

Label an outcome **allele-sharing asymmetry** if a preregistered statistic departs from the tree expectation. Label it **gene-flow-supported** only when relevant ILS/structure alternatives are compared. Label it **source-qualified and time-supported** only when source uncertainty, model alternatives, and tract or serial-genome evidence have been assessed. Label an individual **direct hybrid** only when chromosome-scale ancestry patterns distinguish recent parentage from population-level ancestry. Label a region **adaptive introgression candidate** only after tests of selection and function that exceed an introgression-only model.

## 7. Risks and safeguards

| Risk | Threat | Safeguard |
|---|---|---|
| Modern contamination | false modern-like ancestry | independent libraries, damage and contamination models, sensitivity bounds |
| Reference bias | distorted archaic sharing | alternative mapping/callability analyses and transversion checks |
| Incomplete lineage sorting | false gene-flow interpretation | explicit coalescent simulations and tree/structure comparators |
| Ghost-source ambiguity | overconfident donor label | source-qualified terminology, broad source models, held-out checks |
| Low coverage | unstable local ancestry | genotype likelihoods, masking, replicate-method agreement |
| Recombination uncertainty | misleading dates | map alternatives and interval reporting |
| Functional overclaim | introgression conflated with adaptation | separate selection/functional module and preregistered controls |

## 8. Governance and ethics

Ancient human remains require consultation with curatorial institutions, local communities, descendant groups where relevant, and applicable legal/ethical review. Destructive sampling follows a minimal-material, documented-permission policy. Present-day genomic data follow consent, controlled-access, privacy, and population-stigmatization safeguards. The study reports uncertainty without attaching biological determinism or social value to ancestry proportions.

## 9. Design-only statement

No sampling, destructive analysis, sequencing, phenotype measurement, or genetic intervention is performed by this proposal. The document defines a future research protocol only.
