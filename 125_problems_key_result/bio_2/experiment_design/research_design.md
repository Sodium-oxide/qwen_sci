# ExperimentDesign - STABLE-AGE Protocol

## Status and scope

**DESIGN_ONLY.** No cohort was enrolled, no intervention was administered, no biomarker was measured, and no efficacy, safety, or mortality result is claimed. The design is intended to distinguish a causal, bounded change in aging-related trajectories from measurement artifacts or selective survival.

## Scientific unit and scenario ladder

The unit is an eligible participant with a versioned baseline phenotype, clinical history, medication record, exposure context, specimen schedule, and consented follow-up. The design evaluates five scenario classes:

| Scenario | Purpose | Permissible evidence |
|---|---|---|
| S0 - demographic reanalysis | Separate conditional late-life hazard from individual biological change | Data-quality and model-sensitivity finding only |
| S1 - assay calibration | Quantify repeatability, batch effects, and cross-platform agreement | Measurement validity for a stated assay and population |
| S2 - randomized comparative core | Estimate prespecified intervention effects where ethical and feasible | Bounded causal comparison for the enrolled population |
| S3 - observational event extension | Observe longer-horizon clinical events and retention | Association or follow-up signal, not unrestricted causal proof |
| S4 - external replication | Reproduce locked analysis in an independent site/cohort | Reproducibility support, not a universal aging claim |

## Population, arms, and boundaries

Eligibility, age range, comorbidity exclusions, medication stability, reproductive considerations, frailty limits, and baseline risk must be set before recruitment. Randomization is stratified by factors that affect assay values and clinical risk. The protocol specifies a candidate intervention class and a comparator but does not prescribe a dose, supplementation regimen, or off-label treatment. Candidate-specific pharmacology, interactions, contraindications, and stopping rules require clinician, ethics-board, and regulator review.

The primary analytic horizon, event-extension horizon, visit schedule, assay laboratories, specimen processing, endpoint definitions, and analysis code are frozen before unblinding. No post hoc swapping of clocks, subset restrictions, or outcome windows is permitted to rescue a preferred result.

## Endpoint hierarchy

1. **Safety hard gates:** serious adverse events, clinically meaningful laboratory abnormalities, functional deterioration, and intervention-specific risks.
2. **Multidomain trajectory:** a locked composite built from calibrated molecular, physiologic, immune, and functional domains; each component remains separately reported.
3. **Concordance endpoints:** target engagement and independent functional outcomes, with blinded outcome assessment where possible.
4. **Exploratory events:** incident multimorbidity, hospitalizations, disability, and mortality observed on the declared schedule. These are not replaced by a clock and are interpreted with follow-up completeness.

## Analysis model

For participant $i$, domain $k$, and time $t$, estimate change with a mixed model that includes baseline state, treatment assignment, time, treatment-by-time interaction, site/batch effects, and prespecified covariates. Construct the composite only after direction, scaling, weights, missingness policy, and multiplicity adjustment are locked. A positive composite result needs concordance across domains, no safety-gate breach, and appropriate sensitivity analyses for missingness, adherence, assay drift, and informative censoring.

## Calibration and fault tests

Before unblinding, run technical replicates, sample swaps, blinded duplicate specimens, batch and site controls, and a locked assay-quality dashboard. Synthetic data tests inject batch shifts, selective dropout, transient acute illness, nonadherence, and differential survival. The pipeline must recover known injections, avoid inferring treatment benefit in null simulations, and expose uncertainty rather than silently dropping problematic records.

## Decision rules

An intervention can progress from mechanistic evidence to a bounded trajectory claim only if all preregistered hard safety gates pass, the primary trajectory criterion is met, independent functional or clinical evidence is directionally compatible, and held-out/replication analysis does not reverse the interpretation. A single biomarker improvement is insufficient. A late-life mortality plateau is analyzed separately as population demography and cannot serve as efficacy evidence for an intervention.

## Reproducibility package

Release a versioned protocol, statistical analysis plan, endpoint dictionary, code, randomization procedure as permitted, assay specifications, calibration logs, batch metadata, de-identified analysis-ready data where ethics allow, all exclusions, adverse-event summaries, missing-data diagnostics, null and fault-injection tests, and report versions. Every conclusion is labeled as observation, model-based inference, causal estimate, or long-horizon extrapolation.
