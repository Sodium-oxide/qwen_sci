# ExperimentDesign Agent: Sleep Function Causal Atlas

## Design status

This artifact is a research design, not an execution record. `execution_policy.mode = DESIGN_ONLY`; `observed_results = []`. No sleep restriction, circadian displacement, neural measurement, blood draw, immune assay, imaging scan, or clinical intervention has occurred in this run.

## Research brief

The selected SFCA direction asks which decomposed features of sleep causally support distinct outcomes. The study object is a time-dependent sleep state, not total nightly duration. The central hypothesis is that homeostatic pressure, circadian phase, continuity, stage microstructure, and individual physiology predict distinct cognitive, immune, and maintenance outcomes; therefore, a matched-duration summary cannot fully explain intervention response.

Alternative explanations include altered pre-sleep encoding, general arousal, practice, expectancy, caffeine, medication, acute illness, stress, physical activity, social schedule, dietary timing, sensor artifact, missing data, and carryover from prior conditions. The design keeps these as measured covariates, balanced constraints, or explicit human-review fields.

## D0. Scope, safety, and preregistration

Before recruitment or analysis, preregister the population, age range, exclusion rules, sleep-disorder screening, medical and psychiatric safety criteria, maximum sleep loss, recovery plan, stop rules, compensation, consent language, task order, endpoint hierarchy, randomization, power assumptions, missing-data plan, and adverse-event process. Exclude or route for expert review participants with conditions for which altered sleep schedules would be unsafe. No participant is asked to drive, make high-stakes decisions, or perform hazardous work during a sleep-loss condition.

The study is a laboratory or closely monitored digital protocol only after institutional approval. It does not prescribe home sleep deprivation or a clinical treatment. Human-review requirements cover sleep medicine, clinical safety, consent, privacy of wearable and neural data, immunology, statistics, and ethics.

## D1. Factorial two-process protocol

Use a randomized, counterbalanced, within-person crossover design with washout and recovery nights. Core conditions are: (a) adequate sleep opportunity at habitual phase; (b) modest, safety-bounded sleep restriction at habitual phase; (c) circadian displacement with matched time in bed; and (d) recovery sleep. Where safe and approved, an additional continuity-fragmentation condition can separate duration from continuity. Fixed task schedules, light exposure, caffeine, meals, activity, and medication logs reduce confounding.

Estimate homeostatic pressure $H_t$ and circadian phase $C_t$ separately. A simple state formulation is

\begin{equation}
H_{t+1}=\rho H_t+\alpha W_t-\beta S_t+\eta_t,
\end{equation}

where $W_t$ and $S_t$ quantify wake and sleep exposure, $\rho$ captures persistence, and $\eta_t$ is unobserved disturbance. Circadian phase follows an entrained oscillator,

\begin{equation}
C_{t+1}=C_t+\omega+\gamma L_t+\xi_t \pmod {2\pi},
\end{equation}

where $L_t$ is measured light input and $\omega$ is intrinsic phase advance. These equations are operational models, not claims that every biological detail is captured.

## D2. Sleep phenotype and multimodal measurements

Measure duration, onset and offset, sleep efficiency, wake after sleep onset, fragmentation, stage composition, slow-wave activity, spindle density, rapid-eye-movement timing, circadian phase proxy, subjective sleepiness, alertness, and prior sleep debt. Use polysomnography or validated multimodal sleep sensing where appropriate. Record light, activity, caffeine, alcohol, medication, illness symptoms, menstrual phase where relevant, chronotype, stress, and task engagement.

Define a sleep state vector

\begin{equation}
z_t=[H_t,C_t,D_t,Q_t,\mathrm{SWA}_t,\mathrm{Spindle}_t,\mathrm{REM}_t,U_t]^\top,
\end{equation}

where $D_t$ is duration, $Q_t$ continuity/quality, and $U_t$ is an individualized physiological state. The design compares duration-only, timing-only, stage-only, and full decomposed-state models using held-out participant-session data.

## D3. Memory and plasticity endpoints

Use a structured learning task with item identity, temporal order, source context, and relational composition. Perform encoding before sleep, retrieval after the assigned sleep condition, and delayed retrieval after recovery. Include attention, psychomotor vigilance, motivation, and mood controls so that post-sleep performance is not misread as memory consolidation when it reflects alertness or test engagement.

Primary cognitive endpoints are item accuracy, temporal-order accuracy, relation consistency, source-monitoring accuracy, confidence calibration, response time, and interference resistance. A content-preserving memory score is

\begin{equation}
M(m)=1-\frac{E_{\mathrm{item}}(m)+E_{\mathrm{order}}(m)+E_{\mathrm{relation}}(m)+E_{\mathrm{source}}(m)}{Z_m},
\end{equation}

with separately reported error components. Sleep-stage markers can be associated with $M(m)$, but a stage is not promoted as a causal memory mechanism unless it predicts held-out memory beyond alertness, encoding, and nuisance controls and is supported by an intervention contrast.

## D4. Immune, clearance-related, and systemic endpoints

The protocol measures a panel rather than one universal biomarker. Candidate immune endpoints include complete blood count subsets, inflammatory cytokine panels, response to an ethically approved standardized challenge where applicable, and symptom/illness surveillance. Candidate systemic endpoints include resting heart rate, heart-rate variability, blood pressure, glucose regulation proxies, and mood. Clearance-related physiology is measured only with validated, ethically approved methods and interpreted as a candidate mediator, not a universal endpoint.

Let $Y_{j,t}$ be endpoint $j$ for participant $i$ after condition $c$. A hierarchical model is

\begin{equation}
Y_{i,j,t}=\theta_{0j}+\theta_{Hj}H_{i,t}+\theta_{Cj}C_{i,t}+\theta_{Zj}^{\top}z_{i,t}+b_{i,j}+\delta_{c,j}+\varepsilon_{i,j,t},
\end{equation}

where $b_{i,j}$ captures participant-specific baseline and $\delta_{c,j}$ captures condition effects. The model reports posterior or confidence intervals for each domain and tests whether duration-only predictions are inferior to the decomposed state.

## D5. Causal mediation and cross-domain utility

The causal contrast for changing sleep feature $k$ is

\begin{equation}
\tau_{k,j}=\mathbb{E}[Y_j\mid do(A_k=1),X]-\mathbb{E}[Y_j\mid do(A_k=0),X],
\end{equation}

where $A_k$ is a randomized or protocol-defined manipulation, $X$ includes preregistered covariates, and $Y_j$ is a declared endpoint. Mediation analysis can test whether a stage feature or clearance-related measure explains part of a condition effect, but mediation is not asserted when temporal order, measurement reliability, and sensitivity assumptions fail.

Construct a cross-domain utility function only as an exploratory, preference-explicit layer:

\begin{equation}
U_i=\sum_{j=1}^{J}w_{i,j}\widetilde{Y}_{i,j}-\lambda_i R_i,
\end{equation}

where $w_{i,j}$ are declared outcome weights, $\widetilde{Y}_{i,j}$ are standardized benefits, and $R_i$ is safety or burden. This avoids silently trading immune resilience against memory or mood. The primary scientific results remain endpoint-specific.

## D6. Decision rules and failure handling

A sleep feature is considered a candidate causal contributor only if: (1) it is reliably measured; (2) its effect is separated from duration, timing, alertness, and prior wake; (3) the effect generalizes to held-out sessions or participants; (4) the contrast is consistent with randomization or a justified causal design; (5) adverse and non-target outcomes remain within prespecified safety bounds; and (6) the conclusion stays at the evidence level supported by the data.

If duration-only equals the full model, simplify the theory rather than forcing a multi-feature claim. If an immune panel moves but memory does not, report a dissociation. If memory improves while mood or safety deteriorates, the intervention fails the utility/safety gate. Failed assay batches, missing stage data, irregular medication, or acute illness are recorded as invalid or `needs_human_input`, never relabeled as physiological resilience.

## Author handoff

The Author Agent must retain the Survey evidence boundaries, SFCA selection audit, all design equations, the endpoint-specific interpretation policy, human-review requirements, `DESIGN_ONLY` status, and `observed_results=[]`. It may discuss expected branches and a research program; it may not report that a sleep intervention, immune assay, or clinical outcome has occurred.
