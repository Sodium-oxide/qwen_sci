# ExperimentDesign Agent: Mechanism-Guided Adaptive Psychiatry

## 1. Design objective

The study tests whether a clinician-supervised, transdiagnostic, multimodal model can improve treatment matching and treatment durability for complex mental disorders. It is a design-only proposal. It does not diagnose a real patient, recommend a real treatment, or report an observed clinical outcome.

The primary comparison is not whether a neural feature correlates with a symptom score. It is whether a pre-registered care policy makes better predictions and safer decisions than diagnosis-only and symptom-only alternatives under prospective, held-out evaluation.

## 2. Cohort and data layers

The target cohort includes adults receiving care for depressive, anxiety-related, schizophrenia-spectrum, or mixed/comorbid presentations. Enrollment records the clinician's working diagnosis without treating it as the only phenotype. Participants are stratified by site and treatment pathway. The design is compatible with a prospective observational cohort plus a randomized comparison of clinically appropriate treatment modalities where equipoise and ethics permit.

The feature layers are:

- **Clinical dimensions:** anhedonia and motivation, threat/anxiety, cognitive control, psychosis-relevant salience, sleep/arousal, interoceptive distress, functioning, medication history, and prior response.
- **Network features:** reproducible resting-state and task-related connectivity summaries, including fronto-limbic and uncinate-fasciculus network measures where acquisition is feasible.
- **Inflammation and physiology:** repeated inflammatory markers, endocrine or autonomic measures, and batch or time-of-day metadata. These features define a probabilistic subgroup, not a universal disease label.
- **Imaging-genomic features:** quality-controlled genetic or epigenetic summaries linked to imaging traits. Raw high-dimensional data are kept in a governed environment; only pre-registered feature transformations enter the analysis.
- **Time-varying response:** symptom dimensions, functioning, tolerability, adherence, sleep, and clinician-rated risk at each monitoring window.

The data dictionary includes acquisition device, missingness reason, medication exposure, therapy dose, clinician site, demographic variables relevant to fairness, and the exact time at which each feature became available. This time stamp prevents post-decision leakage.

## 3. Treatment pathways and comparators

The model is evaluated against nested policies:

1. **Diagnosis-only policy:** diagnosis, broad severity, demographics, prior treatment, and site.
2. **Symptom-dimensional policy:** diagnosis-only features plus transdiagnostic symptom dimensions and history.
3. **Mechanism policy:** symptom features plus network, inflammation, physiology, and imaging-genomic features.
4. **MGAP policy:** mechanism policy plus repeated response updates, calibrated uncertainty, and a clinician-supervised action rule.

Treatment pathways may include pharmacotherapy, structured psychotherapy, and clinically approved neuromodulation pathways. The design does not assume that any one pathway is superior. A randomized SSRI-versus-CBT component, modeled after the feasibility of a transdiagnostic internalizing cohort, supports treatment-by-feature estimation when clinically appropriate. Neuromodulation is represented as a separately governed pathway; the policy cannot autonomously stimulate a patient.

## 4. Endpoint hierarchy

The primary endpoint is out-of-sample clinical utility at a fixed decision horizon. It combines response probability, time to useful response, adverse-effect or burden probability, and uncertainty. Secondary endpoints are:

- calibration of response and nonresponse probabilities;
- area under the precision-recall curve for clinically important nonresponse;
- improvement in symptom dimensions and functioning;
- treatment-specific trajectory prediction;
- time from treatment initiation to a clinician-authorized review;
- subgroup calibration, equalized error summaries, and missing-modality robustness;
- clinician override rate and reason for override.

The proposal reports raw outcome distributions and decision curves in addition to summary scores. A model is not considered effective because it has a high AUC if its probabilities are poorly calibrated or its recommendations increase avoidable burden.

## 5. Response trajectory model

Let \(Y_{i,t,d}\) denote the standardized outcome for patient \(i\), time \(t\), and symptom or function dimension \(d\). A treatment-specific hierarchical trajectory is:

\[
Y_{i,t,d} = \alpha_d + u_{i,d} + \beta_{a,d} + \gamma_d^T X_i + \rho_{a,d}^T M_i + \tau_d t + \omega_{a,d} t + \epsilon_{i,t,d}.
\]

Here \(a\) is treatment pathway, \(X_i\) is the symptom and history vector, \(M_i\) is the mechanism vector, \(u_{i,d}\) is an individual random effect, and \(\rho_{a,d}\) estimates treatment-by-mechanism moderation. The time interaction \(\omega_{a,d}\) allows response durability to differ by treatment. The model is fitted only with features available before the predicted time point.

For a binary clinically useful response \(R_{i,t}\), the prediction layer is:

\[
\operatorname{logit} P(R_{i,t}=1) = \theta_0 + \theta_a + \theta_X^T X_i + \theta_M^T M_i + \theta_T^T H_{i,t} + \theta_{aM}^T(a \otimes M_i).
\]

The vector \(H_{i,t}\) contains early response, tolerability, adherence, and monitoring history. The interaction term tests the claim that different mechanisms predict different treatment paths. It is not interpreted causally unless treatment assignment is randomized or a valid causal design is established.

## 6. Mechanism strata and missing modalities

Mechanism strata are estimated with a probabilistic latent class or continuous mixture model. The number of strata is selected by pre-registered predictive criteria and stability across bootstrap samples, not by clinical convenience. A patient can have posterior probability distributed across strata. The policy receives that uncertainty instead of forcing a hard label.

Missing biological modalities are expected because scans, blood assays, or genomic measurements may be unavailable. The primary analysis uses a pattern-aware model that marginalizes over missing features. A complete-case analysis is secondary and cannot be used as the sole evidence. Performance is reported separately for complete, partial, and clinically typical data patterns.

## 7. Clinician-supervised adaptive policy

At monitoring time \(t\), an action \(a\) is selected from continue, intensify monitoring, request a review, switch pathway, or augment within the approved care plan. The policy score is:

\[
U(a \mid x_t) = p_{\mathrm{resp}}(a \mid x_t)B_{\mathrm{resp}} - p_{\mathrm{harm}}(a \mid x_t)C_{\mathrm{harm}} - B_{\mathrm{burden}}(a) - \lambda \, \mathrm{Uncertainty}(a \mid x_t).
\]

The quantities \(B_{\mathrm{resp}}\), \(C_{\mathrm{harm}}\), and \(B_{\mathrm{burden}}\) are fixed in advance with clinical and patient-partner input. The uncertainty penalty prevents an apparently attractive but weakly supported action from outranking a safer review. The algorithm produces an explanation listing the dominant feature groups, evidence timestamp, confidence interval, and missingness. A clinician can override the action, and overrides become analyzed data rather than errors.

The policy is evaluated first by prospective emulation on historical decision sequences and then, only after safety review, by a stepped implementation study. It cannot initiate or stop medication, psychotherapy, or neuromodulation without authorized clinical action.

## 8. Causal and predictive separation

The design separates four claims:

1. **Association:** a feature is related to an outcome in a specified cohort.
2. **Prediction:** a model generalizes to held-out patients or sites.
3. **Treatment moderation:** a feature changes the relative expected response across randomized pathways.
4. **Clinical utility:** using the model changes decisions and outcomes favorably without unacceptable harms.

Inflammation-associated dysconnectivity can motivate a mechanistic hypothesis, but a cross-sectional association does not prove that inflammation causes the symptom or that anti-inflammatory treatment will help. The randomized treatment component estimates moderation only for its assigned pathways. Observational policy evaluation uses target-trial emulation with explicit assumptions and reports residual confounding.

## 9. Validation and falsification

The primary split is site-held-out and time-ordered. All preprocessing, feature selection, and hyperparameter tuning occur inside the training partition. External validation uses an independent cohort where possible. The model must pass:

- calibration slope and intercept checks;
- nested model comparison against all three baselines;
- subgroup calibration by sex, age band, race or ethnicity where collected, socioeconomic proxy, and site;
- missing-modality stress tests;
- drift checks for scanner, assay batch, treatment availability, and diagnostic composition;
- decision-curve analysis with clinician review;
- simulation-based recovery of known mechanism strata and treatment interactions.

MGAP is falsified if it has no reproducible gain over the symptom-dimensional baseline, if mechanism strata fail stability, if early updating does not improve prediction of useful response, or if policy use worsens calibration, burden, or subgroup equity. If the multimodal model predicts but does not improve utility, the correct conclusion is that prediction has not translated into care.

## 10. Sample-size and power logic

Sample size is determined by simulation-based design analysis rather than by a generic rule of thumb. The simulation varies individual count, number of sites, missing-modality rate, response prevalence, treatment imbalance, mechanism-stratum separation, and treatment-by-mechanism effect. A design is retained only if it can recover a known interaction and reject a spurious biomarker under realistic leakage and drift conditions.

Repeated observations are nested within individuals and sites. The unit for uncertainty is the patient, not the row of a longitudinal table. The study should include enough patients per site to estimate calibration drift, and enough randomized participants per treatment pathway to estimate moderation without relying on retrospective subgroup selection.

## 11. Ethics and governance

Mental-health data are sensitive. Access is role-based, model development is separated from clinical identity, and every feature has a provenance record. Participants are told that algorithmic output is investigational and does not replace a clinician. High-risk indicators trigger established clinical procedures; they are not handled by an automated model alone.

The protocol registers the possibility of no benefit, subgroup harm, and false reassurance. It includes a model pause rule for safety signals, an appeal and correction pathway, and an audit log of recommendations and overrides. The study will not use a performance label to deny care or to infer personal blame.

## 12. Expected contribution

The design directly tests whether the problem is solved by better measurement, better mechanism representation, or adaptive decision timing. A positive result would support a clinically governed transdiagnostic system. A symptom-only result would show that structured phenotyping is sufficient and expensive biomarkers add little. A null result would be valuable because it would block premature deployment of a plausible but non-useful precision-psychiatry stack.

