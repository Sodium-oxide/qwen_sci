# ExperimentDesign: Developmental Canalization and Context Expression Model

## Design-only status

This document is a research design, not an executed human study. It reports no measured outcomes, no genetic discoveries, and no individual-level prediction. Any future recruitment, genotyping, imaging, or data linkage requires institutional review, consent, data-governance approval, and preregistration.

## Research questions

1. Does a latent neurodevelopmental lateralization state measured in childhood predict later hand preference, hand-performance asymmetry, and writing-hand choice?
2. Do common polygenic and rare coding variants predict this latent state through measurable developmental brain asymmetries rather than directly determining a hand label?
3. Does cultural/task exposure modify reported preference more strongly than bilateral motor-performance asymmetry?
4. Can the same hierarchical model explain a right-hand majority while preserving left, mixed, and non-right phenotypes across ancestry and task contexts?

## Hypotheses

**H1 - Multitask phenotype.** A latent phenotype built from repeated preference and performance measures will be more reliable than writing hand alone and will predict future handedness class out of sample.

**H2 - Polygenic developmental liability.** A genome-wide polygenic score and a preregistered rare-variant burden will explain incremental variance in the latent developmental state after age, sex, ancestry, birth, and family covariates. The effects will be probabilistic and small at the individual level.

**H3 - Brain mediation.** Multivariate asymmetry in motor and language-related structural and functional measures will partially mediate the association between genetic liability and later motor phenotype. No single region is required to mediate the relation.

**H4 - Context expression.** Measured pressure to switch hand, writing-tool orientation, and task affordance will have a larger effect on reported preference and writing hand than on performance asymmetry in culturally neutral bimanual tasks. The effect will vary with latent developmental liability.

**H5 - Longitudinal canalization.** Developmental measurements will show increasing stability of the latent state with age, while task-specific preference can remain plastic. This produces a stable majority without requiring a deterministic genotype.

**H6 - Generalization.** The latent-state structure and direction of effects will replicate across an ancestry-diverse cohort and a held-out cohort, while effect magnitudes may differ by task and developmental stage.

## Cohorts and measurement schedule

The planning design combines harmonized existing cohorts with a prospective non-invasive follow-up. The numbers below are planning targets, not observed sample sizes or results.

* **Discovery cohort:** approximately 30,000 participants with genotype data, repeated or harmonizable handedness measures, and covariates. Existing cohort data are preferred to minimize new participant burden.
* **Replication cohort:** approximately 20,000 participants from an independent cohort with compatible phenotype definitions and ancestry representation.
* **Prospective developmental panel:** approximately 1,500 children enrolled at 6-18 months and followed at 3, 5, 8, 12, and 16 years, with an optional adult endpoint. A nested imaging panel of approximately 500 participants is a planning target.
* **Family component:** twin or sibling pairs are included where available. The analysis will retain zygosity, birth weight, gestational age, and forced-switching information rather than treating them as nuisance omissions.

At each visit, the study records: (i) hand preference across age-appropriate tasks, (ii) timed and accuracy-matched unimanual and bimanual performance, (iii) writing or drawing hand where developmentally appropriate, (iv) foot and eye laterality as secondary asymmetries, and (v) task familiarity and instruction history. Sensors or video coding should be used where feasible to quantify spontaneous choice and switching rather than relying only on self-report.

The imaging panel uses non-invasive MRI at ages 8, 12, and 16 when feasible: structural cortical and white-matter asymmetry, diffusion measures of interhemispheric and language-related tracts, and task or resting-state functional connectivity. Scanner, site, motion, and preprocessing batch are recorded. No attempt is made to infer a person's identity or ability from a brain image.

Genetic measurements include genome-wide array data, imputation with quality control, and optional exome data. Analyses use ancestry-aware principal components, relatedness, and cohort-specific quality filters. Polygenic scores are trained only in discovery data and evaluated in held-out data. Rare coding burden is limited to predeclared frequency and consequence classes and is not converted into a clinical report.

Environmental measurements include direct questions about correction or encouragement to use a particular hand, school writing instruction, tool and workstation design, family handedness, language environment, and socioeconomic context. These are analyzed as moderators and possible sources of measurement bias, not as moral or behavioral judgments.

## Formal model

Let $L_{it}$ denote the latent developmental lateralization state for participant $i$ at age $t$:

\begin{equation}
L_{it}=\alpha+\beta_g G_i+\beta_r R_i+\beta_p P_{it}+u_{family(i)}+v_{site(i)}+\epsilon_{it},
\end{equation}

where $G_i$ is a discovery-trained polygenic score, $R_i$ is a preregistered rare-variant burden, $P_{it}$ represents measured prenatal/perinatal and developmental covariates, and $u$ and $v$ are family and site random effects. The latent state generates repeated phenotype indicators:

\begin{equation}
\Pr(Y_{ijt}=k)=\operatorname{softmax}_k\left(\lambda_{jk}L_{it}+\gamma_{jk}E_{ijt}+\delta_{jk}L_{it}E_{ijt}+c_{ijt}\right),
\end{equation}

where $Y_{ijt}$ is the outcome for task $j$, $E_{ijt}$ is task and cultural exposure, and $c$ contains age, sex, ancestry, injury, and measurement covariates. Preference, performance, and writing hand receive separate loadings.

Brain asymmetry $A_{it}$ is modeled as a multivariate mediator:

\begin{equation}
A_{it}=\theta_0+\theta_gG_i+\theta_rR_i+\theta_pP_{it}+\theta_eE_{it}+b_i+\zeta_{it}.
\end{equation}

The mediated path is estimated only if the imaging measurement has acceptable test-retest reliability and the temporal ordering is available. The study reports standardized paths, uncertainty intervals, calibration, and out-of-sample performance rather than a binary gene label.

For family data, an ACE-style model is used as a sensitivity analysis, not as a mechanistic proof:

\begin{equation}
\operatorname{Var}(L)=A+C+E,
\end{equation}

with alternative specifications that account for forced switching, birth characteristics, and cohort period. The model comparison asks whether the DCCEM structure improves prediction and explanation without assuming that broad-sense heritability equals a manipulable cause.

## Analysis plan

The primary analysis fits the latent phenotype in discovery data, locks the measurement and score construction, and evaluates replication without re-tuning thresholds. The main endpoints are:

* reliability of the multitask latent phenotype;
* incremental variance and calibration from genetic terms;
* partial mediation by multivariate brain asymmetry;
* interaction between developmental liability and measured context;
* age-dependent stability of preference versus performance;
* cross-cohort and cross-ancestry transportability.

Competing models include writing-hand-only, environment-only, genetics-only, brain-only, and unconstrained multi-factor baselines. Model comparison uses held-out log loss, Brier score, calibration slope, and predeclared variance components. AUC is secondary because the research target is explanation of a population distribution, not a diagnostic classifier. Multiple testing is controlled within predeclared endpoint families. Missingness, site effects, attrition, and measurement changes across age are modeled explicitly.

## Falsification and decision rules

The DCCEM direction is supported only if the locked latent state is reliable, improves held-out prediction over simpler baselines, and shows the predicted separation between preference and performance under context exposure. It is weakened if the model has no replication, if genetics adds no incremental information, if brain asymmetry is non-reliable, or if culture shifts performance as much as self-reported preference. A successful association is not sufficient to call the mechanism causal.

## Safety and human review

The design is non-invasive and observational. Required review includes informed consent and assent, genetic privacy, recontact and data deletion policies, MRI safety, incidental findings, equitable ancestry representation, and prevention of stigmatizing interpretation. No participant receives a handedness label as a medical diagnosis, and no intervention is proposed to change hand preference. An expert committee must approve the phenotype ontology, score construction, and cross-cohort harmonization before analysis.

## Expected outcome branches

If H1-H4 replicate, the result would support a distributed developmental explanation in which right-hand majority is a population bias and culture shapes expression. If only the context effect replicates, the report would retain a preference-expression model without claiming a neural mediator. If only genetic associations replicate, the conclusion would remain polygenic liability without a developmental mechanism. If no model generalizes, the strongest conclusion would be that current handedness measurements are insufficient for a unified explanation.

## Non-claims

This design does not claim that right-handedness is superior, that left-handedness is pathological, that a person's hand preference can be predicted from DNA, or that the population ratio is explained by one evolutionary advantage. It does not report new data and does not authorize clinical, educational, or genetic decision-making.

