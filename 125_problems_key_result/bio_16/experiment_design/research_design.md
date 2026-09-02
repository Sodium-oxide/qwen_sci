# Experiment Design: Predictive Study of Growth-Plate Closure Readiness

## Objective and boundary

This is a prospective, noninterventional, preregistered study. Its aim is not to alter growth, diagnose disease, or predict a participant's final adult height. It asks whether repeated noninvasive measurements improve prediction of a later transition to sustained low longitudinal growth beyond chronological age and bone age. All outputs are research-only and require pediatric endocrinology, radiology, biostatistical, privacy, and ethics review before execution.

## Cohort and timing

Recruit participants across prepubertal through late-pubertal developmental windows, with inclusion and exclusion criteria finalized before enrollment. The planned unit is participant-visit, with repeated visits at a fixed registered interval and at least one later follow-up interval adequate to determine residual growth velocity. Sample size is not asserted here; it will be set by a preregistered simulation using anticipated event frequency, site clustering, missingness, and subgroup calibration precision.

Height is measured by calibrated stadiometer using a fixed protocol. The primary endpoint is a **sustained low-growth state**, defined in the locked protocol as height velocity below a registered threshold across two consecutive follow-up intervals. A secondary structural endpoint is MRI evidence of growth-plate closure, treated as interval-censored because the event occurs between scans. The threshold is a research endpoint, not a clinical treatment threshold.

## Features and data governance

The baseline model uses chronological age, recorded sex variables, standardized height history, and clinically available bone-age assessment when available under the approved protocol. The multimodal model adds radiation-free MRI features of a prespecified long-bone growth plate, puberty-related endocrine variables, and limited health covariates. Genetic data, if separately consented, are restricted to quality-controlled, ancestry-aware summaries and are never used as a stand-alone closure score.

Raw images, biospecimens, and genomic data receive separate consent, minimization, access-control, retention, and withdrawal procedures. No research biopsy, experimental hormone administration, or action on a model score is permitted. Missingness is described by site, visit, age band, and feature family; imputation is a registered sensitivity analysis, never a silent default.

## Analysis plan

The main comparison uses a common outcome definition, data cutoff, preprocessing pipeline, and validation partitions. The baseline is a regularized age-and-bone-age model. The candidate model is a joint longitudinal/event model or equivalently specified survival framework that combines repeated growth velocity and interval-censored closure. MRI, endocrine, and inherited feature blocks are added in preregistered ablations so any claimed increment is attributable to a defined block.

The primary performance gates are held-out Brier score and calibration for the sustained low-growth endpoint. Secondary gates are log score, time-dependent discrimination, interval coverage for residual growth, and calibration at the site, developmental-stage, sex-variable, and ancestry-stratum levels where sample support permits. A complex model is not retained if it improves only average discrimination while producing unreliable probabilities for a subgroup.

## Validation and failure branches

Training, temporal holdout, and external-site holdout partitions are locked before fitting. All transformations, feature selection, hyperparameters, image-quality rules, and decision thresholds are frozen using training data only. The pre-registered ablations are: age-plus-bone-age baseline; baseline plus MRI; baseline plus endocrine; full multimodal; and full multimodal without inherited summaries. A model is rejected as primary if it fails calibration, if missingness causes instability, if an incremental block has no repeatable benefit, or if transport to an external site fails.

There are three reportable branches: (1) the multimodal model clears all gates, supporting conditional predictive utility; (2) the simple baseline performs comparably, supporting parsimony; or (3) no model clears calibration and transportability gates, leaving the question unresolved. None of these branches licenses causal claims about hormones, genes, or personal medical decisions.
