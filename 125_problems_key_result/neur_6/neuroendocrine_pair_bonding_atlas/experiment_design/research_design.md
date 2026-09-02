# ExperimentDesign Agent Output

## 1. Aim and design logic

This proposal tests the Neuroendocrine Pair-Bonding Causal Atlas (NPB-CA). It asks whether partner-directed behavior can be decomposed into three biological phases: sexual motivation, partner-cue reward formation, and durable partner preference. The central design principle is phase specificity. The same perturbation must be tested during bond formation and after bond maintenance, because a circuit that creates a bond need not be the circuit that preserves it.

The program has two linked arms:

* **Causal animal arm:** prairie voles provide receptor- and circuit-level perturbations with partner-preference, social-specificity, locomotor, endocrine, and neural readouts.
* **Human translational arm:** healthy adults undergo repeated, non-invasive partner-cue neuroimaging and endocrine/physiological sampling using partner, familiar non-partner, stranger, and nonsocial reward controls. No human neuropeptide, steroid, or circuit manipulation is proposed.

The animal arm tests causality; the human arm tests whether a preregistered neural state representation is detectable in the human brain. The two arms are linked through representational geometry and effect directions, not by claiming that vole behavior is identical to human romantic experience.

## 2. Biological model

The working model contains four interacting modules:

1. Hypothalamic and gonadal-axis state regulates the gain of sexual motivation and social-cue processing.
2. Oxytocin and vasopressin receptor fields in hypothalamic, septal, amygdalar, and pallidal circuits regulate partner-cue selectivity.
3. VTA-to-NAc dopamine assigns reward value during formation and changes receptor-dependent processing during maintenance.
4. Endocrine and stress-axis state modulates plasticity and persistence, but does not uniquely specify a bond.

The main prediction is a transition in a low-dimensional biological state, not a single biomarker. Candidate state variables are partner-cue neural discrimination, NAc/VTA dopamine response, receptor-dependent social selectivity, glucocorticoid tone, gonadal-axis hormones, and delayed preference persistence.

## 3. Formal state-space and causal estimands

For subject or animal (i), define the latent neurobiological state at time (t) as

\[
\mathbf{x}_{it}=[d_{it},r_{it},q_{it},s_{it},g_{it},p_{it}]^{\mathsf T},
\]

where (d) is dopamine-linked partner-cue value, (r) is receptor-gated cue selectivity, (q) is persistence/plasticity, (s) is stress-axis state, (g) is gonadal-axis state, and (p) is peptide-related signaling. We use a phase-indexed linear approximation for estimation, while allowing nonlinear observation models:

\[
\mathbf{x}_{i,t+1}=\mathbf{A}_{\phi}\mathbf{x}_{it}+\mathbf{B}_{\phi}\mathbf{u}_{it}+\mathbf{G}_{\phi}\mathbf{h}_{it}+\boldsymbol{\epsilon}_{it},
\]

\[
\mathbf{y}_{it}=f_{\phi}(\mathbf{C}_{\phi}\mathbf{x}_{it}+\mathbf{D}\mathbf{c}_{it})+\boldsymbol{\eta}_{it}.
\]

Here (phiin\{formation,maintenance\}), (\mathbf{u}) is a receptor or dopamine perturbation, (\mathbf{h}) contains measured peptide, steroid, and glucocorticoid variables, and (\mathbf{c}) contains control-condition and nuisance variables. The target causal contrast is

\[
\Delta_{k,m,\phi}=E[Y_m\mid do(U_k=1),\phi]-E[Y_m\mid do(U_k=0),\phi],
\]

where (k) is a perturbation target and (m) is one prespecified outcome: partner selectivity, general social approach, nonsocial reward, locomotion, stress physiology, or persistence. A perturbation supports a specific mechanism only if its effect on partner selectivity survives adjustment for locomotion, exposure, nonsocial reward, and stress, and if its phase interaction is replicable.

## 4. Animal arm: prairie-vole causal test

### 4.1 Subjects and phases

The target sample is 96 adult prairie voles, balanced by sex where colony availability permits, randomized within litter and housing block. The number is a planning target subject to an a priori power calculation from pilot variance and ethical review. Animals are assigned to same-sex familiarization and then to a partner or control exposure schedule. Formation is assessed after a standardized cohabitation window; maintenance is assessed after the bond has been established and again after a delay. A non-bonded control condition separates repeated social exposure from partner-specific preference.

The primary phase variable is not a verbal label. It is defined by exposure history: pre-association baseline, formation window, established-bond window, and delayed-retention test. All animals receive matched handling, light cycle, food access, and arena exposure.

### 4.2 Perturbation matrix

The animal arm uses preregistered, reversible or regionally restricted perturbations:

* OXTR signaling in a forebrain target region;
* AVPR1A signaling in a forebrain target region;
* NAc D1-family signaling;
* NAc D2-family signaling;
* VTA-to-NAc dopamine activity during partner-cue exposure;
* vehicle, sham, or pathway-control conditions.

Pharmacological antagonism, validated chemogenetic inhibition, or pathway-selective optical inhibition may be selected after local capability and welfare review. The design does not assume that a single intervention is sufficient; it requires replication with an orthogonal perturbation where the primary result is positive. No manipulation is performed in humans.

### 4.3 Readouts

The primary behavioral endpoint is a partner-selectivity index from a standard three-chamber partner-versus-stranger assay:

\[
PSI=\log\left(\frac{T_{partner}+\epsilon}{T_{stranger}+\epsilon}\right).
\]

Secondary behavioral endpoints are total social contact, stranger contact, locomotion, investigation of an inanimate object, mating-related behavior when naturally occurring, and delayed preference persistence. These controls prevent a reduction in movement, arousal, or general affiliation from being misread as loss of pair bonding.

Neural readouts include NAc dopamine fluorescence or electrophysiology during partner, stranger, and nonsocial reward cues; VTA activity where technically validated; and receptor expression or occupancy in predefined regions. Endocrine readouts include oxytocin, vasopressin where assay performance is acceptable, testosterone or estradiol as sex-specific covariates, and corticosterone. Blood collection timing is standardized to the behavioral assay and analyzed with assay batch as a random effect.

### 4.4 Animal hypotheses

H1: OXTR or AVPR1A perturbation reduces partner selectivity more strongly than general social approach if receptor-gated recognition is causal.

H2: D1/D2 perturbations show a formation-by-maintenance interaction, rather than identical effects in both phases, if dopamine participates in bond formation and maintenance through different receptor configurations.

H3: Dopamine response to partner cues is larger or more selective than the matched stranger and object responses during formation; a transformed or stabilized pattern is predicted during maintenance.

H4: Peptide and dopamine effects are moderated by endocrine and corticosterone state, but endocrine variables alone do not predict PSI after circuit variables are included.

## 5. Human translational arm

### 5.1 Participants and sessions

The target sample is 120 adults in established pair relationships, with balanced sex representation where recruitment allows. Each participant completes two sessions separated by at least two weeks, scheduled to reduce acute illness, sleep deprivation, and medication-related confounds. The study collects non-invasive fMRI, pulse and respiration, skin conductance, and saliva or blood samples for endocrine covariates subject to ethics approval. No hormone administration, brain stimulation, deception, or relationship intervention is used.

### 5.2 Stimulus and control design

Images or short standardized visual cues are collected for four prespecified classes: current partner, familiar non-partner, unfamiliar person, and nonsocial reward/object. Low-level visual properties are matched. Order is counterbalanced and repeated across sessions. The primary contrast is partner minus familiar non-partner; the secondary contrast is partner minus stranger; partner minus nonsocial reward tests social specificity. The protocol measures neural response and physiological state; a short participant label is optional and is never the sole endpoint.

### 5.3 Imaging and endocrine measures

The primary imaging analysis uses preregistered regions in VTA, NAc/ventral striatum, hypothalamus, amygdala, hippocampus, septal/ventral pallidal regions where resolution permits, and medial prefrontal cortex. Whole-brain analysis is secondary and corrected for multiple comparisons. Multivoxel pattern analysis estimates whether partner-versus-control representation is stable within participant across sessions. Endocrine measures are modeled as moderators, not interpreted as direct readouts of love.

### 5.4 Human hypotheses

H5: Partner cues produce a reproducible distributed neural pattern that discriminates partner from familiar non-partner above preregistered cross-session chance performance.

H6: The human partner-cue representation shares a low-dimensional geometry with the vole partner-versus-control neural pattern after normalization, while anatomical effect sizes are not expected to match.

H7: The cross-session representation is moderated by endocrine and stress-axis state but remains distinct from general arousal and nonsocial reward.

## 6. Cross-species integration

The bridge uses a common feature dictionary rather than anatomical identity. Each species contributes a vector of standardized features: partner-cue selectivity, stranger selectivity, nonsocial reward response, locomotion/arousal control, delayed persistence, dopamine-linked cue response, and endocrine state. Representational similarity analysis compares the rank structure of partner, familiar, stranger, and object conditions. A hierarchical Bayesian model estimates a shared latent effect and species-specific deviations:

\[
\theta_{s,k}=\mu_k+\delta_{s,k},\qquad \delta_{s,k}\sim N(0,\tau_k^2),
\]

where (s) indexes species and (k) indexes shared features. The bridge is accepted only if the posterior for the shared effect is directionally consistent and out-of-sample prediction exceeds a preregistered baseline. A failure to bridge is a scientific result: it rejects the strong conservation claim while retaining species-specific mechanisms.

## 7. Analysis, power, and reproducibility

The primary analysis is a mixed-effects model with phase, perturbation, cue class, sex, endocrine covariates, and their prespecified interactions; animal and housing block are random effects. Human imaging uses cross-validated decoding and hierarchical region-level estimates. Missing data, assay limits, and motion exclusion are declared before unblinding. Multiple comparisons are controlled within each endpoint family.

Power is determined separately for the animal causal contrast and human cross-session decoding using pilot variance, minimum biologically meaningful effect, and attrition. The proposed sample sizes are planning targets, not observed evidence. All code, stimulus metadata, preregistration, exclusion rules, and analysis specifications are versioned. The primary claim is supported only by convergence across perturbation, neural readout, phase interaction, and specificity controls.

## 8. Failure modes and decision rules

If a perturbation changes locomotion or stress more than PSI, the mechanism is classified as nonspecific. If receptor perturbations disagree across orthogonal methods, the target is classified as context-dependent. If formation and maintenance show the same effect, the phase-specific prediction is rejected but a general role remains testable. If human decoding is above chance only within session, the cross-session stability hypothesis fails. If the species bridge fails, the report will not force a conserved “love circuit”; it will retain the mechanistic results separately.

## 9. Safety and human review

The animal arm requires institutional animal-care review, analgesia and humane endpoints where applicable, minimization of separation duration, and 3R justification. The human arm requires informed consent, MRI safety screening, privacy-preserving genetic handling if genotyping is added, and a clear ban on clinical or relationship manipulation. AVPR1A and OXTR variants are optional moderators and must not be used to label individuals or predict relationship outcomes. The project produces a design only; it does not provide medical treatment or behavioral advice.

