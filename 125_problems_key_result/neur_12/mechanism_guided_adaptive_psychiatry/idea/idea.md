# Idea Agent: Mechanism-Guided Adaptive Psychiatry

## Primary direction

**MGAP: Mechanism-Guided Adaptive Psychiatry** treats diagnosis and treatment as a repeated inference-and-control problem. It combines transdiagnostic symptom dimensions, multimodal biological features, patient context, treatment history, and time-varying response signals. A clinician remains the decision maker; the system supplies calibrated predictions, uncertainty, and a reason for each candidate action.

The core hypothesis is:

> A multimodal model that maps active symptom mechanisms to treatment-specific response trajectories, then updates from early response and tolerability, will improve calibrated treatment matching and time-to-effective care over diagnosis-only and symptom-only baselines.

The idea is deliberately stronger than a catalog of possible biomarkers. It proposes a concrete comparison of care policies and asks whether adaptive information changes decisions that matter: probability of response, probability of early deterioration or intolerability, and time until a clinically useful treatment is selected.

## Mechanistic architecture

The model contains four linked layers:

1. **Phenotype layer:** dimensions such as threat/anxiety, anhedonia/motivation, cognitive control, psychosis-relevant salience, sleep and arousal, and interoceptive distress. These dimensions complement, rather than erase, clinical diagnoses.
2. **Mechanism layer:** inflammation-linked dysconnectivity, fronto-limbic network organization, imaging-genomic variation, and treatment-history features. Mechanisms are represented probabilistically and are allowed to be absent or uncertain.
3. **Response layer:** treatment-specific trajectories for pharmacotherapy, psychotherapy, and clinically appropriate neuromodulation pathways. The response target is not a single endpoint; it includes symptom improvement, functioning, adverse effects, and durability.
4. **Policy layer:** a clinician-supervised rule that recommends continue, intensify monitoring, switch, augment, or request additional assessment. The policy cannot prescribe or change treatment without an authorized clinician.

## Competitive routes

### Diagnosis-only baseline

This route uses diagnosis, age band, prior treatment, and site as predictors. It is necessary as a negative control because a complex model is useful only if it improves over routine category-level information.

### Symptom-dimensional baseline

This route uses structured symptom dimensions and clinical history but no biological features. It tests whether the improvement comes from measurement quality rather than from expensive biomarker collection.

### Single-biomarker route

This route uses one high-profile signal, such as an inflammatory marker or one network metric. It is a high-risk control: it should fail if the disorder is heterogeneous and response mechanisms are multivariate.

### MGAP

MGAP combines the phenotype, mechanism, response, and policy layers, with missing-modality handling and uncertainty thresholds. Its primary endpoint is prospective utility under held-out sites and time periods, not retrospective AUC.

## Testable predictions

- The multimodal model will improve calibration and decision-curve utility over diagnosis-only prediction.
- Mechanism profiles will form probabilistic strata with treatment-by-mechanism interactions, not one universal biomarker.
- Early repeated response signals will identify likely nonresponse sooner than baseline-only models.
- Treatment-specific network features will predict different pathways rather than merely disease severity.
- Utility gains will persist under missing-modality and subgroup validation if uncertainty is propagated instead of imputed as certainty.

## Falsification and safety

MGAP is falsified if nested out-of-sample evaluation shows no clinically meaningful improvement over the symptom-only baseline, if mechanism strata do not replicate, or if adaptation increases false alarms, treatment burden, or subgroup inequity. The autonomous-policy route is rejected. An algorithm may recommend information-gathering or a review; only a qualified clinician can authorize treatment change.

The idea also rejects leakage. Treatment response data from after a decision cannot be used to construct the baseline feature for that same decision. Site, medication availability, clinician preference, and missingness are recorded because they can make a model appear accurate while learning the health system rather than the patient.

