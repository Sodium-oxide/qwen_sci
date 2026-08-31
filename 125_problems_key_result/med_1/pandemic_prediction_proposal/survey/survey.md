# Survey Agent Output: Can We Predict the Next Pandemic?

**Research question.** Can existing scientific and public-health evidence support prediction of the next pandemic, and, if not, what prediction target is both scientifically defensible and operationally useful?

**Scope.** This survey addresses zoonotic emergence, outbreak early warning, spread escalation, and preparedness decision support. It does not claim to forecast an exact future pathogen, date, or location. It does not prescribe pathogen manipulation, field sampling, clinical intervention, or deployment of a real surveillance system.

## Executive finding

The evidence supports a stronger and more useful claim than either fatalism or deterministic prediction: pandemic risk can be **estimated and ranked at distinct stages** using ecological, virological, surveillance, mobility, and health-system information, provided that the model is evaluated prospectively, calibrated under delay and reporting bias, and connected to a decision with a stated cost. It does **not** support a credible claim that a single model can name the next pandemic's pathogen, location, and date.

The central scientific error in much public discussion is target collapse. A reservoir-host prediction, a spillover-risk map, a syndromic outbreak detector, and a model of cross-border dissemination answer different questions. Combining them into one unqualified ``next pandemic'' score makes failures impossible to diagnose and makes action thresholds arbitrary.

## Evidence map

| Evidence line | What it supports | Boundary on use |
|---|---|---|
| Host and viral trait studies | Host, virus, and human-contact attributes can prioritize zoonotic spillover surveillance [S1]. | A priority score is not a dated outbreak prediction. |
| Global emerging-disease analyses | Land-use change, biodiversity, and reporting effort are associated with recorded zoonotic-emergence risk [S2]. | Associations depend on heterogeneous event data and cannot be read as a single causal driver. |
| Spillover-process modelling | Reservoir occurrence, human exposure, spillover, and human infection must be represented as distinct links [S3,S4]. | Stage-specific evidence cannot be replaced by a universal label. |
| Early-warning reviews | Integrated surveillance can improve outbreak detection, but effectiveness depends on data, setting, and operating conditions [S5]. | Detection performance is not pandemic prevention or exact prediction. |
| Event-based and wastewater signals | Nontraditional signals add situational awareness and may complement formal reporting [S6,S7]. | They require corroboration, governance, and uncertainty communication. |
| Machine-learning evaluation critique | High apparent spillover-model performance can hide lineage, sampling, and transportability failures [S8]. | Random train/test splits do not establish future utility. |
| Surveillance-first critique | Broad prediction claims can divert resources from surveillance, verification, and response capacity [S9]. | This is a design constraint, not a reason to abandon quantitative early warning. |

### Interpreted evidence

Olival *et al.* show that mammalian host and viral traits can be used to characterize zoonotic spillover tendencies [S1]. Allen *et al.* find global correlates and hotspots but explicitly identify imprecision from heterogeneous published event data and limitations caused by fitting one common model across biologically different diseases [S2]. These papers justify a structured, stage-aware risk representation; they do not justify a singular future-pandemic oracle.

Basinski *et al.* combine reservoir ecology with human serosurveys for Lassa virus, demonstrating why a reservoir layer and human-exposure layer should not be treated as interchangeable [S3]. Lo Iacono *et al.* likewise formulate spillover and subsequent human transmission as connected processes [S4]. Together they motivate separate latent states for exposure/spillover, local amplification, and wider dissemination.

Meckawy *et al.* synthesize evidence on infectious-disease early-warning systems and underscore that effectiveness is a property of the full surveillance system, not only its prediction algorithm [S5]. HealthMap and wastewater work support complementary, timely signals, while also demonstrating the need to verify noisy signals against clinical and laboratory evidence [S6,S7]. Kawasaki *et al.* provide a recent warning: performance evaluation for zoonotic-virus machine-learning models can conceal model failures when labels, phylogeny, and sampling patterns are not handled carefully [S8]. Holmes, Rambaut, and Andersen argue that surveillance capacity should not be displaced by overconfident prediction claims [S9].

## Sub-hypotheses and coverage

| ID | Survey sub-hypothesis | Coverage | Evidence status |
|---|---|---|---|
| SH-01 | Ecological, host, and viral features can prioritize surveillance for spillover-relevant settings. | High | Direct, with target-limit caveat [S1-S4]. |
| SH-02 | Multi-source surveillance can detect or corroborate unusual activity earlier than a single source in some settings. | Moderate | Supported as a system-level proposition [S5-S7]. |
| SH-03 | A model that separates biological stages is more auditable and actionable than a single unqualified risk score. | Moderate | Mechanistically grounded; requires empirical evaluation. |
| SH-04 | Temporal, geographic, and reporting-bias-aware validation is necessary before operational use. | High | Directly motivated by evaluation limitations [S2,S5,S8]. |
| SH-05 | A prediction can only be useful if it maps to a time-bounded, accountable preparedness decision. | Moderate | Evidence-informed design requirement [S5,S9]. |

## Accepted research gaps

1. **GAP-01 — Target conflation.** Literature and public narratives commonly mix hotspot mapping, spillover propensity, outbreak detection, and pandemic-scale dissemination into a single ``prediction'' claim.
2. **GAP-02 — Stage attribution.** Few decision frameworks expose whether elevated risk arises from spillover conditions, local amplification, travel-mediated spread, or response-system fragility.
3. **GAP-03 — Evaluation realism.** Many models lack temporal holdouts, geographic transportability tests, reporting-delay sensitivity analysis, and calibrated uncertainty metrics.
4. **GAP-04 — Decision linkage.** Risk ranks frequently lack declared alert thresholds, lead-time requirements, false-alert costs, and named preparedness actions.
5. **GAP-05 — Equity and observability.** Sparse surveillance and research-effort bias can make low-resource locations look low-risk, thereby reinforcing unequal allocation.

## Evidence constraints for downstream agents

- Do not write that the next pandemic can be predicted exactly.
- Do write that stage-specific, calibrated risk forecasting can prioritize surveillance and preparedness decisions.
- Separate observations from proposed evaluation. No downstream output may assert a newly observed outbreak signal, model result, prevention outcome, or public-health intervention.
- Treat all ecological and social signals as context-dependent correlates unless the cited study establishes a narrower causal claim.
- Retain uncertainty, abstention, reporting bias, governance, and equity as first-class design fields.

## Source register

- **[S1]** K. J. Olival *et al.*, ``Host and viral traits predict zoonotic spillover from mammals,'' *Nature*, 2017, doi: 10.1038/nature22975.
- **[S2]** T. Allen *et al.*, ``Global hotspots and correlates of emerging zoonotic diseases,'' *Nature Communications*, 2017, doi: 10.1038/s41467-017-00923-8.
- **[S3]** A. J. Basinski *et al.*, ``Bridging the gap: Using reservoir ecology and human serosurveys to estimate Lassa virus spillover in West Africa,'' *PLoS Computational Biology*, 2021, doi: 10.1371/journal.pcbi.1008811.
- **[S4]** G. Lo Iacono *et al.*, ``A unified framework for the infection dynamics of zoonotic spillover and spread,'' *PLoS Neglected Tropical Diseases*, 2016, doi: 10.1371/journal.pntd.0004957.
- **[S5]** M. A. Meckawy *et al.*, ``Effectiveness of early warning systems in the detection of infectious diseases outbreaks: a systematic review,'' *BMC Public Health*, 2022, doi: 10.1186/s12889-022-14625-4.
- **[S6]** C. C. Keller *et al.*, ``Use of unstructured event-based reports for global infectious disease surveillance,'' *Emerging Infectious Diseases*, 2009, doi: 10.3201/eid1505.081114.
- **[S7]** D. Polo *et al.*, ``Making waves: Wastewater-based epidemiology for COVID-19—approaches and challenges for surveillance and prediction,'' *Water Research*, 2020, doi: 10.1016/j.watres.2020.116404.
- **[S8]** K. Kawasaki, Y. Suzuki, and K. Hamada, ``Hidden challenges in evaluating spillover risk of zoonotic viruses using machine learning models,'' *Communications Medicine*, 2025, doi: 10.1038/s43856-025-00903-w.
- **[S9]** E. C. Holmes, A. Rambaut, and K. G. Andersen, ``Pandemics: spend on surveillance, not prediction,'' *Nature*, 2018, doi: 10.1038/d41586-018-05373-w.

**Survey status:** VERIFIED_HANDOFF_FOR_PROPOSAL. The bibliography and claim boundaries were cross-checked against publisher pages in the in-app browser; this is a literature synthesis, not a systematic review or a new meta-analysis.
