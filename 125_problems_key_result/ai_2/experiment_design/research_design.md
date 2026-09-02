# Experiment Design: Conditional Intelligence Frontier Benchmark

## 1. Objective and design status

This is a preregistration-ready, design-only human research protocol. It does not report participant results and is not a substitute for institutional ethics approval. The objective is to test whether a conditional upper boundary in cognitive performance can be distinguished from a norming artifact, an item ceiling, practice, aging, or insufficient environmental opportunity.

The primary estimand is the change in a calibrated latent ability trajectory under declared task, age, and resource conditions. The study does not attempt to estimate an absolute maximum human mind. It estimates whether a reproducible asymptote exists for specified cognitive domains and whether an intervention shifts that asymptote.

## 2. Participants and sampling

Recruit a multi-site cohort spanning four age strata: adolescence, early adulthood, midlife, and later adulthood. A planning target of approximately 1,200 participants is used for simulation and feasibility discussions, with the final sample determined by preregistered power simulation, expected attrition, and the number of site and language strata. The sample is stratified by education, sex, socioeconomic conditions, language background, and health status rather than treating the most convenient population as universal.

An approximately 400-participant intervention subset is randomized after baseline assessment, subject to consent and site capacity. A neurocognitive sub-study enrolls a consented subset for EEG and structural/resting-state MRI. Exclusion is limited to conditions that prevent informed consent, safe participation, or valid task completion. Participants with sensory or motor differences are accommodated where possible and their measurement conditions are recorded.

## 3. Measurement battery

The battery contains multiple alternate-form tasks in fluid reasoning, crystallized knowledge, working memory, processing speed, spatial reasoning, and novel-task learning. Each domain includes items that extend beyond ordinary screening ranges. Item-response calibration is performed in a pilot sample before confirmatory analysis, with item difficulty, discrimination, differential item functioning, and response-time distributions recorded.

Each participant completes both speeded and time-unlimited versions where the construct permits. Speeded scores are not treated as pure reasoning scores; the model includes processing-speed factors and time-limit indicators. Alternate forms prevent the same answer key from becoming a memory test. A subset repeats the battery after a short interval to estimate measurement reliability and practice, while the main follow-up is long enough to separate retest from developmental or training change.

Environmental and biological covariates include years and quality of education, sleep regularity, nutrition indicators that can be collected ethically, chronic disease burden, medication, stress exposure, language of testing, digital-task exposure, and neighborhood or school opportunity measures. These variables are explanatory covariates or moderators, not automatic causal effects. The randomized training contrast supplies the principal causal test of modifiable cognitive performance.

## 4. Randomized plasticity module

Participants are assigned to one of two time-matched arms. The adaptive-training arm receives an adaptive reasoning and working-memory curriculum with difficulty updated from current performance. The active-control arm receives engaging, non-adaptive tasks matched for contact time, feedback, and expectancy but not designed to train the target mechanisms. Both arms use novel item pools and identical assessment schedules.

The primary intervention contrast is the difference in change in the latent domain factors and higher-order general factor at post-test and delayed follow-up. Near-transfer tasks share some component processes with training but use new stimuli. Far-transfer tasks are structurally distinct and are not used during training. A gain only on trained items is classified as practice. The intervention does not claim to increase intelligence if the gain disappears on alternate forms or delayed follow-up.

## 5. Neurocognitive sub-study

EEG measures task-evoked timing, spectral dynamics, and trial-to-trial variability. Structural MRI measures regional and whole-brain properties, while resting-state MRI estimates network connectivity. Predefined features are selected based on prior literature and reliability, with nested cross-validation for prediction. The sub-study tests whether neural measures mediate or moderate latent trajectories and intervention response.

The neural analysis is deliberately non-diagnostic. A brain correlate cannot by itself establish a ceiling, and a predictive model cannot be interpreted as a biological destiny. Mediation is tested only under temporal ordering and sensitivity analyses for confounding. Missing scans, motion, site, scanner, and preprocessing batch are recorded and modeled rather than silently excluded.

## 6. Formal model

For participant $i$, domain $d$, item or task $j$, and time $t$, observed performance is modeled as

\begin{equation}
y_{ijdt}=\nu_j+\lambda_j g_{it}+\delta_{jd}d_{idt}+\beta_j s_{it}+\rho_j p_{ijt}+\epsilon_{ijdt},
\end{equation}

where $g_{it}$ is a higher-order general factor, $d_{idt}$ is a domain factor, $s_{it}$ is a speed or time-limit component, and $p_{ijt}$ captures practice on the specific task family. Item parameters are estimated using a calibrated item-response model. Residuals account for trial-level noise, and site, language, and batch effects are included as hierarchical terms.

For a fixed task family, the latent learning trajectory is represented by

\begin{equation}
g_i(t)=\theta_i-A_i\exp(-k_i t)+u_{i,t},
\end{equation}

where $\theta_i$ is an individual conditional asymptote, $A_i$ is available improvement, $k_i$ is a learning rate, and $u_{i,t}$ is time-varying deviation. The existence of a limit is not inferred merely from a fitted curve. A conditional plateau requires a preregistered small-slope interval, a credible or confidence interval for the derivative that remains near zero over the declared horizon, stable item parameters, and replication in alternate forms.

Measurement invariance is tested across age, site, language, and time. If scalar invariance fails, raw score comparisons and a universal IQ trend are not interpreted. Intervention effects are estimated with intent-to-treat analysis and a per-protocol sensitivity analysis. Technical repetitions are not treated as independent participants.

## 7. Stages and decision gates

### S0: calibration and pilot

Verify high-range item coverage, alternate-form equivalence, test-retest reliability, response-time instrumentation, and neural preprocessing reliability. Items with severe differential functioning are revised or modeled before confirmatory collection.

### S1: baseline cross-sectional measurement

Estimate domain factors and a higher-order factor across age and environment strata. Fit competing models: no plateau, domain-specific plateau, and common plateau. Compare predictive calibration rather than selecting a curve solely by fit statistic.

### S2: longitudinal follow-up

Repeat alternate forms at preregistered intervals. Estimate individual trajectories, attrition mechanisms, cohort-by-age effects, and the separation between retest, development, and environmental change.

### S3: randomized training

Analyze adaptive training against active control with near- and far-transfer tasks. A general-intelligence claim requires a cross-domain latent effect that survives alternate forms and delayed follow-up.

### S4: neural mediation and external validation

Test preregistered neural hypotheses and validate the measurement model at an independent site or cohort. No neural signature is accepted as an upper limit unless it predicts the calibrated asymptote and remains compatible with observed intervention response.

## 8. Primary endpoints and statistical decisions

Primary endpoints are: (1) latent general-factor trajectory; (2) domain-specific asymptote with uncertainty; (3) measurement-invariance statistics; and (4) intent-to-treat difference between adaptive training and active control at delayed follow-up. Secondary endpoints include near transfer, far transfer, processing-speed tradeoffs, neural mediation, and environmental moderation.

A conditional limit is supported only if the plateau is reproducible after high-range calibration, practice adjustment, alternate forms, and site replication. A movable frontier is supported if education-related longitudinal exposure or randomized training shifts latent performance beyond the active control. A measurement ceiling is supported if the apparent plateau disappears after difficult items or time-unlimited forms are added. A practice artifact is supported if gains are confined to trained items or the short retest. Heterogeneous asymptotes support a vector or distribution of constraints rather than one human-wide IQ maximum.

## 9. Ethics, privacy, and limitations

The protocol requires informed consent or age-appropriate assent, parental consent where required, withdrawal without penalty, secure separation of identifiers from research data, and careful communication that a score is not a fixed personal value. Genetic data are not required for the core study; if collected in a future extension, separate consent and governance are necessary. MRI and EEG follow local safety screening, and the intervention is low-risk cognitive training with monitoring for fatigue or distress.

The design is vulnerable to attrition, cohort confounding, measurement non-equivalence, selective participation, language effects, and scanner-site differences. It cannot test every possible cognitive task, future educational environment, or tool-assisted intelligence. Its claim is deliberately bounded: it can estimate conditional frontiers and identify evidence for or against a stable plateau under specified conditions.

## 10. Expected evidence products

The study should release a preregistration, item-calibration report, measurement-invariance report, analysis code, de-identified summary data where permitted, model-checking plots, and a failure ledger. No result is considered positive if it depends on a hidden scoring ceiling, a single site, one training task, or an unblinded exploratory endpoint.
