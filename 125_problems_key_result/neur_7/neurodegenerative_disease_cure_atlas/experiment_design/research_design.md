# ExperimentDesign Agent Output: SPIRP

## 1. Aim and design logic

This proposal tests whether a Stage-Adaptive Proteostasis–Immune–Repair Platform can produce durable disease modification in defined Alzheimer’s disease (AD) and Parkinson’s disease (PD) states. The central design decision is to test **sequence and state**, not merely a list of candidate drugs. SPIRP separates four biological transitions: aggregate accumulation, clearance-capacity failure, maladaptive glial activation, and neuronal/circuit loss. A candidate is promoted only if it changes the intended state variable, improves function, remains beneficial during treatment withdrawal, and does not produce unacceptable toxicity.

The program has three linked stages:

1. **Human patient-derived cellular stage:** use isogenic and patient-derived iPSC neurons, astrocytes, and microglia to select responders and test target engagement.
2. **In vivo causal stage:** use AD- and PD-relevant animal models to test intervention order, tissue distribution, neuronal survival, circuit function, and washout durability.
3. **Translational biomarker stage:** validate the composite state classifier in longitudinal biospecimens and imaging from carefully selected clinical cohorts. This stage is observational or biomarker-focused unless a separately approved interventional trial is designed.

The proposed work is a research design, not a treatment recommendation. It contains no completed experiment and no observed efficacy estimate.

## 2. Operational definition of cure

SPIRP uses a nested endpoint hierarchy:

* **Functional control:** progression is slowed or arrested on prespecified cognitive, motor, and circuit endpoints during treatment.
* **Biological remission:** aggregate burden and maladaptive inflammatory state remain improved through a prespecified washout period, with no rebound beyond the predefined margin.
* **Repair:** lost or dysfunctional neuronal circuits show durable recovery, with safe integration and no renewed pathology after washout.

The word “cure” is reserved for a complete endpoint package: functional control, biological remission, repair where damage is reversible, acceptable safety, and replication in an independent cohort. A biomarker change or symptomatic improvement alone is not curative.

## 3. Biological state model

For subject or culture (i) at time (t), define

\begin{equation}
\mathbf{x}_{it}=[A_{it},T_{it},C_{it},M_{it},N_{it},V_{it}]^{\mathsf T},
\label{eq:state}
\end{equation}

where (A) is toxic aggregate burden, (T) is tau or alpha-synuclein propagation burden, (C) is clearance/proteostasis capacity, (M) is glial inflammatory state, (N) is neuronal reserve, and (V) is circuit-level function. Disease module identity determines whether (A,T) emphasize amyloid/tau or alpha-synuclein. Covariates include age-equivalent maturation, genotype, sex, vascular/metabolic state, and batch.

The state evolves under treatment input (\mathbf{u}_{it}) according to

\begin{equation}
\mathbf{x}_{i,t+1}=\mathbf{F}_{\phi}(\mathbf{x}_{it},\mathbf{u}_{it},\mathbf{h}_{it})+\boldsymbol{\epsilon}_{it},
\label{eq:dynamics}
\end{equation}

where (\phi) is disease stage, (\mathbf{h}) contains pharmacodynamic and systemic covariates, and (\boldsymbol{\epsilon}) is process variation. The observation vector is

\begin{equation}
\mathbf{y}_{it}=\mathbf{H}_{\phi}\mathbf{x}_{it}+\mathbf{D}\mathbf{z}_{it}+\boldsymbol{\eta}_{it},
\label{eq:observation}
\end{equation}

where (\mathbf{z}) contains assay batch, motion, locomotion, and other nuisance variables. The model is used for estimation and prediction; it is not assumed to reveal an unmeasurable “disease essence.”

## 4. Composite biomarker state score

The responder classifier combines orthogonal measurements after prespecified normalization:

\begin{equation}
S_{it}=w_A\tilde{A}_{it}+w_T\tilde{T}_{it}-w_C\tilde{C}_{it}+w_M\tilde{M}_{it}-w_N\tilde{N}_{it}-w_V\tilde{V}_{it},
\label{eq:score}
\end{equation}

where tildes denote direction-aligned standardized features and weights (w) are learned only in a training set. Higher (S) indicates a more vulnerable disease state. The weights are locked before held-out validation. Candidate measures include aggregate imaging or immunoassay, proteostasis flux, microglial transcriptional state, synaptic density, neuronal viability, electrophysiology, and behavioral or motor/cognitive function. No single peripheral marker is treated as a surrogate for brain pathology without validation.

## 5. Human patient-derived cellular stage

### 5.1 Model panel

The panel includes at least three independent donor backgrounds per disease module, isogenic correction or introduction of selected disease-associated variants where technically justified, excitatory and dopaminergic neurons, astrocytes, and microglia. AD cultures emphasize amyloid/tau-related phenotypes; PD cultures emphasize alpha-synuclein and dopaminergic vulnerability. Long-term maturation, cell identity, neuronal activity, and glial composition are quality-control endpoints.

The model is intentionally not treated as a complete human brain. It lacks full aging, vascular perfusion, systemic immunity, and whole-brain connectivity. Its purpose is responder selection, mechanism separation, and target-engagement testing in human genetic backgrounds.

### 5.2 Perturbation library

The library is organized into mechanism classes rather than named prescriptions:

* proteostasis/autophagy-lysosomal enhancement;
* disease-protein production, aggregation, or clearance modulation;
* microglial-state and inflammasome-pathway modulation;
* mitochondrial and oxidative-stress support;
* trophic or synaptic resilience support;
* stem-cell-derived neuronal or glial replacement as a later-stage module.

Repurposed compounds are prioritized when a plausible CNS target, exposure range, and pharmacodynamic assay exist. Novel compounds are retained when they provide a distinct target-engagement mechanism. Every candidate receives a brain-exposure, cytotoxicity, interaction, and off-target profile before combination testing.

### 5.3 Factorial sequence experiment

For each disease module, cultures are randomized to: vehicle; proteostasis module alone; immune-state module alone; simultaneous combination; proteostasis followed by immune-state modulation; immune-state modulation followed by proteostasis; and the same leading sequences with a repair module. The repair module is added only after a predefined reduction in aggregate burden and inflammatory-state score. Parallel no-pathology controls identify toxicity caused by the intervention itself.

Primary cellular endpoints are aggregate load, validated proteostasis flux, cell survival, synaptic density or function, neuronal activity, and microglial state. Secondary endpoints include transcriptomic state, mitochondrial function, secreted inflammatory mediators, and cell-cell interaction. The primary sequence estimand is

\begin{equation}
\Delta_{q,\phi}=E[Y\mid do(Q=q),\phi]-E[Y\mid do(Q=vehicle),\phi],
\label{eq:sequence}
\end{equation}

where (Q) is a sequence and (phi) is the molecular stage. A sequence is successful only if the intended molecular endpoint improves without loss of neuronal viability or excessive suppression of protective glial functions.

## 6. In vivo causal stage

### 6.1 Disease modules and randomization

The AD module uses a validated amyloid/tau model with pathology and cognitive endpoints; the PD module uses a validated alpha-synuclein or dopaminergic-neurodegeneration model with motor, nigrostriatal, and pathology endpoints. Model choice is locked before treatment based on phenotype stability and external replication. Animals are randomized within sex, litter, age, cage, and baseline severity. Allocation, behavioral scoring, tissue processing, and image analysis are blinded.

The design uses four stage strata: pre-pathology risk, early measurable pathology with neuronal reserve, established pathology with partial reserve, and advanced loss. The objective is not to force efficacy at every stage; it is to estimate where a sequence can still achieve durable remission and where repair becomes necessary.

### 6.2 Treatment order and controls

The in vivo factorial design compares: pathology module alone, immune-state module alone, repair module alone, simultaneous combination, pathology-first sequence, immune-first sequence, and pathology-plus-immune followed by repair. Vehicle, sham-procedure, and non-disease controls are included. Treatment timing and washout are prespecified. A repair-first arm is retained as a negative ordering control, not because it is expected to succeed.

The repair module uses well-characterized stem-cell-derived neuronal or glial populations only after identity, purity, genomic stability, tumorigenicity, and dose-range requirements pass independent review. It measures graft survival, phenotype, synaptic integration, circuit activity, ectopic activity, immune response, and tumor or overgrowth signals. The design does not presume that graft integration is beneficial.

### 6.3 In vivo endpoints

Primary endpoints are disease-specific pathology, neuronal survival or loss, and prespecified circuit function. AD endpoints include amyloid/tau burden, synaptic density, hippocampal or cortical circuit function, and cognitive task performance. PD endpoints include alpha-synuclein burden, substantia nigra dopaminergic neuron counts, striatal dopamine function, and motor performance. Across both modules, microglial and astrocyte state, lysosomal/proteostasis markers, systemic inflammation, body weight, general health, and adverse events are measured.

The decisive durability endpoint is the change from treatment end to washout end:

\begin{equation}
R_{m}=Y_{m,\mathrm{washout}}-Y_{m,\mathrm{end}},
\label{eq:rebound}
\end{equation}

with pathology-specific direction conventions. A favorable intervention has sustained function and no predefined pathological rebound. A short-lived post-treatment improvement is classified as control, not remission.

## 7. Translational biomarker stage

The translational stage enrolls observational cohorts spanning biomarker-defined risk, early disease, established disease, and matched controls. It collects longitudinal blood and, where clinically justified, CSF, molecular imaging, structural/functional imaging, digital motor or cognitive measures, and medication and vascular covariates. The primary goal is to validate whether (S_{it}) predicts progression and target engagement in held-out participants. It is not a clinical efficacy trial.

If a later interventional trial is proposed, eligibility, dose, endpoint, stopping rules, adverse-event monitoring, and treatment combinations require a new clinical protocol and regulatory review. The present design does not authorize off-label treatment, experimental cell transplantation, or self-directed biomarker interpretation.

## 8. Statistical analysis and power

Cellular data use donor-aware mixed-effects models with donor, differentiation batch, and plate as random effects. Animal data use mixed-effects models with treatment sequence, disease stage, sex, baseline severity, and time; cage and litter are random effects. Longitudinal translational data use joint models of biomarker trajectory and disease progression. The primary estimands are sequence-by-stage interactions and washout rebound, not isolated within-group (p)-values.

Power is determined independently for cellular donor replication, animal stage-by-sequence interaction, and translational prediction. Pilot variance, minimum biologically meaningful difference, attrition, and multiple comparisons are fixed before unblinding. The proposed sample size is not an observed result. Cross-validation is grouped by donor, animal, participant, and batch to prevent leakage. A model is accepted only if it improves held-out prediction over a simple disease-stage baseline and remains calibrated across disease modules.

## 9. Decision rules

* **Promote:** target engagement, improved pathology and function, acceptable toxicity, and sustained benefit through washout in an independent replicate.
* **Mechanism-only:** target engagement without functional rescue; retain for combination or earlier-stage testing.
* **Symptom-control:** function improves without pathology or durability improvement; do not call disease modification.
* **Nonspecific toxicity:** glial, neuronal, motor, or systemic injury exceeds benefit; terminate that sequence.
* **Stage-limited:** benefit appears only in early pathology; restrict claims to that state.
* **Repair-dependent:** pathology control alone is insufficient but controlled repair improves durable circuit function; advance only with integration and safety evidence.
* **Reject shared backbone:** AD and PD require incompatible sequences or no cross-disease state classifier generalizes; retain disease-specific programs rather than forcing convergence.

## 10. Safety, ethics, and reproducibility

Animal work requires institutional animal-care approval, 3R justification, minimized distress, humane endpoints, and transparent reporting of exclusions. Cell models require donor consent, genomic privacy, biosafety, authentication, and genomic-stability monitoring. Stem-cell-derived repair requires tumorigenicity, ectopic activity, immune compatibility, and long-term surveillance. Human biomarker studies require informed consent, secure health-data governance, and clear communication that the classifier is investigational.

All raw-to-derived transformations, randomization, treatment sequence, assay limits, preregistration, code, and model versions are archived. Independent replication uses a new donor, animal batch, or clinical cohort. The design reports null and adverse outcomes as first-class outputs. No claim of cure is released until the operational endpoint package, durability, and safety criteria are all met.

