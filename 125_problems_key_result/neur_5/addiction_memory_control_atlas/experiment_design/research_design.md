# ExperimentDesign Agent: Addiction Mechanism and Memory-Control Atlas

## Design status and scope

This is a research design, not an execution record. `execution_policy.mode = DESIGN_ONLY`; `observed_results = []`. No participant was exposed to a substance, withdrawal was induced, neural stimulation or memory editing was performed, treatment was assigned, or relapse outcome was observed in this run.

## Research brief

The selected AMMCA direction studies addiction as a time-dependent interaction among reward learning, incentive salience, habit, withdrawal and negative reinforcement, executive control, cue-memory reactivation, sleep/stress state, genetic liability, and environment. The target is not a universal “addictive personality” or a single dopamine value. It is a declared mechanism phenotype for a person, substance, episode, and context.

Alternative explanations include generic arousal, intoxication, sedation, pain relief, sleep deprivation, stress, depression, trauma, medication, social opportunity, treatment exposure, expectancy, device or clinic leakage, and inaccurate self-report. The design measures or balances these variables rather than calling them addiction mechanisms by default.

## D0. Clinical safety, governance, and preregistration

Before recruitment, preregister the population, substance and severity strata, diagnostic instrument, inclusion and exclusion criteria, follow-up duration, primary relapse definition, craving schedule, treatment status, data splits, genetic variables, fairness metrics, missing-data handling, and adverse-event pathway. Any controlled substance exposure, withdrawal monitoring, pharmacological treatment, neuroimaging, or neuromodulation must be separately reviewed by clinical, institutional, and ethics boards. The present design does not prescribe substance administration or withdrawal induction.

Consent must explain that participation is not treatment, that declining or withdrawing has no effect on care, and that genetic, neural, location, smartphone, and treatment data can reveal sensitive information. Models cannot be used to deny care, assign blame, or make unreviewed high-stakes decisions. Referral and crisis procedures must be available.

## D1. Longitudinal mechanism phenotype

Use repeated observations spanning baseline, active use where naturally occurring and ethically observed, treatment or recovery, high-risk cues, and follow-up. Prefer de-identified clinical or naturalistic data with validated questionnaires, ecological momentary assessment, behavioral tasks, sleep and stress measures, medication and treatment records, and optional neural or physiological recordings. Do not require an individual to relapse for research value.

The mechanism vector is

\begin{equation}
x_t=[R_t,W_t,L_t,H_t,N_t,C_t,P_t,E_t,S_t]^{\top},
\label{eq:mechanism_state}
\end{equation}

where $R_t$ is reward prediction, $W_t$ wanting or incentive salience, $L_t$ liking, $H_t$ habit persistence, $N_t$ withdrawal and negative affect, $C_t$ executive control, $P_t$ cue-memory reactivation, $E_t$ environmental opportunity, and $S_t$ sleep/stress and physiological state. These are latent constructs with multiple indicators, not direct labels read from one brain region.

Drug-associated memory is operationalized by cue identity, context, expected outcome, temporal history, affect, confidence, and response choice. It is not defined as subjective autobiographical recollection unless that endpoint is separately measured and independently validated. The 2019 mouse artificial-memory result in the prompt is treated as a bounded example of causal memory-related behavior, not as evidence for digital addiction treatment.

## D2. Reward, wanting, liking, habit, and control tasks

Use tasks that dissociate mechanisms: outcome devaluation and omission for goal-directed value; progressive response cost and cue-triggered choice for incentive salience; habit-sensitive contingency degradation for stimulus-response control; stress and withdrawal symptom measures for negative reinforcement; delay discounting and response inhibition for executive control; and cue-reactivity tasks for learned context. Use matched non-drug rewards, neutral cues, arousal controls, and motor controls.

Primary behavioral outcomes include choice probability, response vigor, latency, persistence after devaluation, cue-induced craving, subjective liking, subjective wanting, withdrawal relief seeking, response inhibition, and general reward engagement. A person can show high cue wanting without high liking, or high craving without an observed drug-seeking action. The model preserves these dissociations.

## D3. Memory and relapse endpoints

Measure cue-memory reactivation across multiple contexts and sessions. Include extinction, renewal, stress- or treatment-related context changes, and delayed follow-up when approved. Relapse is defined prospectively for the declared substance and care context, with use-day, heavy-use, treatment-return, or clinically validated event definitions reported separately. Time-to-event and recurrent-event models are pre-specified.

Let $Y_{i,t}$ represent the outcome for person $i$ at time $t$. A dynamic state-space model is

\begin{equation}
x_{i,t+1}=A_{c_{i,t}}x_{i,t}+B u_{i,t}+G g_i+H e_{i,t}+\epsilon_{i,t},
\label{eq:state_transition}
\end{equation}

where $c_{i,t}$ is context, $u_{i,t}$ contains treatment or naturally observed events, $g_i$ represents genetic or stable biological features, $e_{i,t}$ represents environmental and social exposures, and $\epsilon_{i,t}$ is process uncertainty. The observation model is

\begin{equation}
Y_{i,t}=f(x_{i,t},d_{i,t},a_{i,t})+b_i+\nu_{i,t},
\label{eq:outcome_model}
\end{equation}

where $d_{i,t}$ is drug or treatment exposure, $a_{i,t}$ is measured arousal, sleep, pain, and medication state, $b_i$ is a person-specific baseline, and $\nu_{i,t}$ is observation noise. The model is a testable abstraction, not a claim that addiction is literally linear.

## D4. Neural, physiological, and environmental measures

Where approved and available, measure neural cue reactivity, frontostriatal and extended-amygdala network activity, autonomic responses, sleep, stress hormones, and treatment-relevant physiology. Neural signals are evaluated against behavioral and subjective outcomes, not interpreted in isolation. Wearable and smartphone data require data minimization, consent, access control, and a plan for accidental detection of crisis or substance use.

Genetic data are used only for preregistered, probabilistic moderation analyses. Polygenic or variant-level predictors must be ancestry-calibrated and tested for transportability. Environmental features include housing stability, social exposure, trauma and stress measures, availability, transportation, policy, employment, and treatment access where consent permits. They are not converted into a deterministic risk label.

## D5. Causal contrasts and mechanism-specific intervention

The causal effect of an intervention $A_k$ on outcome $Y_j$ is

\begin{equation}
\tau_{k,j}=\mathbb{E}[Y_j\mid do(A_k=1),X]-\mathbb{E}[Y_j\mid do(A_k=0),X],
\label{eq:causal_effect}
\end{equation}

where $X$ includes declared baseline, context, treatment, and safety variables. Candidate interventions may include evidence-based medication, behavioral therapy, contingency management, cue-context modification, sleep support, or approved neuromodulation. The design does not select or prescribe a clinical intervention in this artifact.

Mechanism-specific matching compares a model-selected component against safe standard-care or substance-label comparators. Promotion requires that the selected component changes the target mechanism, improves the declared clinical endpoint, and does not worsen non-target reward, cognition, mood, agency, overdose risk, or access to care. A reduction in all motivation is not counted as successful cue-memory treatment.

## D6. Genetics, environment, fairness, and recovery

Fit hierarchical interaction models for gene-by-development-by-environment effects. Use participant- and clinic-held-out validation, calibration by demographic and clinical strata, and sensitivity analyses for missingness and treatment access. Report equalized error or clinically relevant calibration only when the target use justifies it; fairness is not a single universal metric.

Recovery outcomes include use reduction, abstinence when appropriate, treatment retention, craving burden, quality of life, safety events, social function, and patient-defined goals. Relapse is not treated as moral failure. The atlas retains individual trajectories, successful coping episodes, and non-response without implying deterministic vulnerability.

## D7. Decision rules and failure handling

A mechanism is promoted only if: (1) it has a declared operational definition and reliable indicators; (2) it predicts held-out behavior or clinical outcome beyond generic state and recent use; (3) it generalizes across sessions and settings; (4) a causal or quasi-causal contrast supports its direction; (5) target and non-target outcomes are separated; (6) calibration and fairness are acceptable for the proposed use; and (7) clinical and ethics review approve the interpretation.

If a static severity score matches AMMCA, the dynamic model does not earn a complexity claim. If cue reactivity predicts craving but not relapse, it is a proximal marker rather than a complete relapse mechanism. If an intervention lowers drug seeking by suppressing all reward, it fails selectivity. If a genetic model loses calibration across ancestry or clinic, it is not deployable. Missing treatment records, unreliable exposure dates, acute intoxication, withdrawal danger, or crisis signals become `needs_human_input` and are routed for review.

## Author handoff

The Author Agent must preserve the NIDA definition boundary, the separation of addiction from moral judgment, the distinction between artificial-memory animal behavior and human treatment, the AMMCA mechanism vector, all causal equations, unknowns, fairness and autonomy constraints, `DESIGN_ONLY`, and `observed_results=[]`. It may state expected branches and a mechanism-specific research program, but may not claim a completed treatment, memory edit, relapse prediction deployment, or human recovery result.
