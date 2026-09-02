# Experiment Design: Preregistered Multimodal Test of Brain-Body Emotion Models

## Objective

Test whether a distributed predictive-interoceptive state model explains held-out neural, autonomic, behavioral, and report data better than functional-circuit, stimulus-category, and general-arousal models. The protocol investigates the origins of emotion episodes as integrated biological control processes; it does not attempt to determine whether a participant's private experience is reducible to any instrument.

## Study type and participants

* **Design:** preregistered, within-subject, counterbalanced multimodal experiment.
* **Planned sample and stopping rule:** enroll 180 healthy adults, ages 18-40. The confirmatory analysis set requires at least 150 participants with at least 80% valid trials; recruitment is not expanded after outcome inspection. If this threshold is not met, results are explicitly reported as under-target rather than converted into an adaptive sample-size decision.
* **Exclusions:** MRI contraindications, current acute medical instability, uncorrected vision limitations incompatible with the task, and inability to provide informed consent. Psychiatric diagnosis is not inferred or screened for research classification beyond safety procedures.
* **Ethics:** institutional review approval, trained monitoring, content warning, voluntary withdrawal, trial pause/stop response, and debrief. Stimuli are selected to be low risk; no severe stress, trauma exposure, deception concerning danger, pharmacologic challenge, or invasive stimulation is included.

## Task structure

Each participant completes four domains with matched visual and motor structure:

1. **Threat uncertainty:** cues predict a low-intensity aversive sound or a neutral sound with parametrically varied probability.
2. **Reward approach:** cues predict small monetary gain, omission, or neutral feedback with the same timing and response requirements.
3. **Social evaluation/loss:** standardized non-personal evaluative feedback and symbolic loss cues, matched for display complexity, timing, and motor response.
4. **Interoceptive calibration:** health-screened, mild inspiratory resistive loads and sham loads are preceded by learned probability cues. Airway pressure and respiration verify the delivered bodily input, allowing expected bodily state to be separated from actual measured respiratory change.

For each domain, contextual priors are manipulated by explicitly learned cue contingencies. A subset of trials changes the contingency after learning, producing prediction-error conditions. The interoceptive module crosses cue probability with actual load/sham delivery and includes respiratory-mechanics covariates. Non-affective control blocks match sensory input, response frequency, working-memory load, and visual novelty. Trialwise ratings sample valence, arousal, uncertainty, bodily intensity, and an optional category label, but reports are analyzed as one measurement channel rather than ground truth.

## Measurements

* High-resolution BOLD fMRI for distributed systems and subcortical coverage.
* MRI-compatible 64-channel EEG for event-locked cortical dynamics, analyzed with artifact-aware pipelines.
* Pupil diameter, electrodermal activity, ECG, respiration belt, and trialwise response time/action.
* Salivary cortisol collected only at baseline and post-session, interpreted as a slow context measure rather than an event-level proxy.
* Self-report ratings at sparse, randomized trials to reduce reactivity and demand effects.

Each sensor has an independent quality-control plan. For example, ECG R-peak detection failures, excessive fMRI motion, unreliable eye tracking, EEG gradient/ballistocardiographic residuals, and missing saliva times are recorded rather than silently imputed. Analyses will include complete-case sensitivity analysis and prespecified missing-data models where justified.

## Processing and feature construction

Physiological preprocessing will respect modality-specific timing: phasic electrodermal response, heartbeat-linked features, respiration, pupil response, and BOLD response functions are never treated as samples with identical latency. fMRI preprocessing includes motion correction, susceptibility-distortion treatment, physiological nuisance regressors, censoring rules, and prespecified regions plus whole-brain multivariate features. EEG preprocessing reports ICA or equivalent artifact strategy, rejected channels/trials, and time-frequency/event-related components. No feature set may be selected using the held-out test partition.

## Locked statistical model and comparisons

The latent state has six prespecified dimensions: expected value, uncertainty, interoceptive prediction error, regulatory arousal, context/memory state, and approach-avoidance policy. The functional-circuit model uses prespecified amygdala, hypothalamus, periaqueductal gray, ventral striatum, anterior insula, dorsal anterior cingulate, ventromedial prefrontal, and hippocampal features. The distributed model uses a fixed cortical-subcortical parcel set. The null uses visual/auditory energy, reaction time, motor response, task difficulty, novelty, and measured respiratory mechanics. A state-space model relates experimental input, individual traits, and prior state to the current state; a separate observation model maps this latent state to each measurement channel. Hierarchical partial pooling estimates group regularities while allowing individual variation.

The candidate models are compared by nested cross-validation, expected log predictive density, calibration, and stability. Folds are grouped by participant and by task context so the test evaluates both person-general and context-general performance. The primary score averages equally weighted negative log predictive densities across the five outcome families: fMRI, EEG, autonomic physiology, behavior, and report. ORIGIN is supported only when its mean held-out improvement over the general-arousal/task-demand null is at least 0.02 nats per trial and the bootstrap 95% lower confidence bound exceeds zero, while its Brier score is not worse by more than 0.005. Secondary analyses compare functional-circuit and predictive-interoceptive components. The study will publish all model specifications, randomization seed, code, preprocessing exclusions, and deidentified summary data permitted by consent.

## Confounds and controls

| Risk | Design response |
|---|---|
| Reverse inference from one region | Require multichannel, model-comparison evidence and reserve causal language for interventions. |
| Arousal/effort confound | Use matched non-affective control blocks and model pupil, reaction time, difficulty, novelty, motor response, and measured respiratory mechanics. |
| Demand characteristics | Sparse randomized ratings, neutral cover instructions, and separation of task condition from report timing. |
| Temporal mismatch | Use modality-specific response windows and a joint model that permits different lags. |
| Data leakage | Lock preprocessing and feature selection inside training folds. |
| Overfitting | Nested cross-validation, held-out participants/contexts, preregistered model set, and external replication plan. |
| Individual heterogeneity | Hierarchical estimates, participant-level posterior checks, and reliability reporting. |

## Causal extension

The primary study is correlational with respect to neural-circuit causation, while the respiratory calibration module experimentally varies a mild bodily input. A future, separately approved module could test selected neural mechanistic predictions using naturally indicated intracranial recordings/stimulation or noninvasive perturbation only in appropriate clinical/research contexts. It would state an explicit intervention, counterfactual estimand, safety protocol, and eligibility restrictions. Ordinary fMRI association cannot substitute for this evidence.

## Deliverables and decision rules

The deliverables are a preregistration, stimulus library, task code, preprocessing specification, a model card, model-comparison results, negative-control analyses, and a replication package. Results will be described as supporting, inconclusive between, or contradicting the model families according to the registered score thresholds. No result will be interpreted as a single biological "emotion detector."
