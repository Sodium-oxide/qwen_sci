# ExperimentDesign: Phenotype Pathway Attribution Atlas

## Design status and objective

This is a design-only, noninterventional observational protocol. It does not
collect data, fit a model, perform a simulation, or report observed results.
It asks whether a pathway-aware, longitudinal model produces better calibrated
and more transportable descriptions of selected population-level physical
phenotypes than a cohort-only baseline.

## Study population and unit

The analysis dataset may be assembled only from existing or prospectively
consented longitudinal cohorts that have ethics approval, data-use authority,
documented phenotype measurement procedures, and an explicit prohibition on
individual appearance prediction. The unit is a participant-visit or a
participant-age interval, depending on the endpoint. No recruitment,
intervention, clinical action, or imaging for research alone is proposed.

Sites must document calendar period, measurement instrument and protocol,
eligible ages, referral pathway, missingness mechanism, and available
technology or treatment history. The final eligible cohort list, sample size,
and data-access restrictions are human-review inputs and are intentionally
not invented here.

## Pre-specified phenotype families

1. Dental case study: congenital third-molar agenesis, coded only when the
   developmental assessment is age-adequate and the source record can
   distinguish congenital absence from extraction, impaction, eruption
   status, and treatment history.
2. Craniofacial measurements: only de-identified scalar distances or ratios
   extracted from already collected, approved measurements. Raw facial images
   are not an analytic deliverable and are not released.
3. Anthropometric measurements: standardised height and a pre-registered
   body-composition or circumference measure, only when measurement method is
   harmonised or modelled explicitly.

Each phenotype is analyzed independently. A discovery analysis cannot be
relabelled a confirmatory result. The dental endpoint is included because
evidence supports its heterogeneity, not because a trend direction is known.

## Pathway variables

The baseline contains age or developmental stage, birth cohort, site, and
measurement-method indicators. The pathway-aware model adds the following
blocks, each with a missingness and eligibility rule:

- demographic-composition block: variables needed to detect site and cohort
  composition shifts, not categories treated as biological essences;
- developmental-exposure block: preregistered early-life and developmental
  exposures only where consent, timing, and quality allow;
- technology and treatment block: orthodontic, dental-care, nutrition-access,
  or other documented intervention proxies, never interpreted causally
  without a separate causal design;
- measurement-process block: instrument, protocol, assessor, and calendar
  period;
- optional inherited-feature block: quality-controlled genotype summaries
  analyzed only after separate consent and after ancestry-aware, family-aware,
  and transferability sensitivity requirements are met.

## Core model and estimands

For outcome Y of person i at visit j, the primary descriptive model is

Y_ij = f(age_ij, cohort_j, site_j, measurement_j, composition_ij,
         exposure_ij, technology_ij, optional_genetic_ij) + b_site + e_ij.

The model is a predictive and attribution-audit device, not a causal diagram.
The pre-specified comparison is between a baseline that omits the pathway
blocks and a pathway-aware model. The primary estimands are locked holdout
proper scores, calibration intercept and slope, and outcome-appropriate error
or discrimination measures. Effect estimates for technology or environment
are associational unless a separately justified causal analysis is added and
approved.

## Validation and decision rules

The primary split is temporal: later birth cohorts or later measurement
periods remain untouched until final evaluation. The secondary split is
external-site validation. Within each split, outcome definition, feature
engineering, imputation, and hyperparameter choices are frozen before the
evaluation set is opened.

A claimed improvement is permitted only if all of the following are true:

1. the pathway-aware model improves the pre-registered proper score relative
   to baseline on temporal and external-site holdouts;
2. calibration intercept, calibration slope, and reliability plots satisfy
   the registered tolerances in all adequately sized prespecified strata;
3. results are stable after removing a site, a measurement era, and the
   optional inherited-feature block;
4. the dental outcome retains its congenital-versus-treatment definition; and
5. privacy, consent, and communications review approve the result wording.

If any gate fails, the study reports the failure, limits itself to a
descriptive audit, and does not make a future-phenotype forecast.

## Bias, missingness, and robustness

Measurement change is treated as a competing explanation, not a nuisance to
hide. The protocol records eligibility, source and timing for each variable;
uses site and period effects; describes missing data; compares complete-case
and preregistered imputation analyses; and performs negative-control checks
where a purported pathway should have no effect. A genetic block is removed
if ancestry structure, relatedness, or data imbalance prevents a credible
sensitivity analysis.

## Governance and stop conditions

Human ethics, data-governance, dental or craniofacial specialist review, and
independent statistical review are mandatory. The project stops before
analysis if consent or lawful basis is unclear, endpoint definitions cannot
be harmonized, data release would enable reidentification, subgroup sample
support is inadequate, or planned communication would invite deterministic
claims about human groups.
