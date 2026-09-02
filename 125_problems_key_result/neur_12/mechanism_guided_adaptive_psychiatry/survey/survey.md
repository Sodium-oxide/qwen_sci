# Survey Agent: Complex Mental Disorders

## Scientific reframing

Can a transdiagnostic, mechanism-guided, adaptive care system improve diagnosis and treatment matching for people whose symptoms cross conventional psychiatric categories, while detecting loss of benefit early enough to support a safe treatment adjustment?

This reframing treats depression, schizophrenia, anxiety, and related conditions as heterogeneous clinical phenotypes rather than as perfectly separated natural kinds. It does not erase diagnoses. It asks whether symptom dimensions, neurobiological mechanisms, treatment history, and repeated response measurements can jointly improve decisions.

## Scope and evidence boundary

The survey focuses on four linked problems:

1. Diagnostic overlap and symptom heterogeneity.
2. Biological mechanisms that cut across categories.
3. Patient-level prediction of treatment response and durability.
4. Adaptive, human-supervised treatment selection.

The survey does not claim that a biomarker is ready for routine clinical deployment, that an algorithm can replace a clinician, or that one mechanism explains every patient. Its evidence boundary is deliberately more useful than a generic warning: it supports a mechanism-guided design that is bold about testing individualized treatment pathways and explicit about calibration, external validation, and clinical safety.

## Evidence capsules

### Transdiagnostic biomarkers must model complexity

McQuaid's 2021 review argues that depression has heterogeneous symptom profiles and high comorbidity, making reliable personalized biomarkers difficult to identify. It motivates a transdiagnostic approach that maps biomarkers onto shared symptoms or constructs across disorders. The review discusses brain activity and connectivity, neuroendocrine measures, inflammatory markers, and the need to account for context and individual histories. This is direct support for dimensional phenotyping and multimodal, context-aware prediction, not evidence that any single marker is clinically decisive.

### Inflammation can link symptoms and dysconnectivity

Goldsmith and colleagues' 2023 review reports that inflammatory stimuli can disrupt circuits involved in motivation, threat detection, anxiety, interoception, and emotional processing. Elevated inflammatory biomarkers occur in a subset of people with depression, anxiety-related disorders, and schizophrenia and have been associated with differential treatment responses and poorer outcomes. The authors emphasize reproducible assessment of inflammation-associated dysconnectivity before biomarker-driven trials. This supports a mechanistic module, but the subset structure prevents treating inflammation as a universal diagnostic label.

### Imaging genomics offers a translational bridge

Chen, Liu, and Calhoun's 2019 IEEE review describes imaging genomics as a way to connect genetic variation with neurobiological traits and potentially inform pathogenesis, diagnosis, and precision medicine. The opportunity is to combine modalities and connect molecular variation to brain networks rather than relying on symptoms alone. The gap is translational: association, prediction, clinical utility, and fairness are different claims and must be evaluated separately.

### A transdiagnostic randomized cohort is feasible

Thomas and colleagues' 2020 study examined a transdiagnostic internalizing-psychopathology cohort and randomized patients to an SSRI or cognitive behavioral therapy. Graph measures in an uncinate-fasciculus subnetwork differed between patients and controls, and treatment-specific neural correlates were observed for the two modalities. The study supports a design in which baseline network features and treatment-specific changes are modeled together. It does not establish a universal SSRI or CBT predictor, and it motivates held-out validation.

### Closed-loop therapy addresses changing response

Lo and Widge's 2017 review notes inconsistent outcomes in well-designed psychiatric neuromodulation trials and presents closed-loop stimulation as a route toward more precise, patient-specific treatment. It also identifies the difficulty of finding meaningful biomarkers for titration as a central challenge. This evidence supports repeated measurement and adaptive control, while showing why a model needs a safety supervisor and a predefined escalation policy.

### Dimensional psychiatry supplies a conceptual scaffold

Kelly and colleagues' 2018 discussion of the Research Domain Criteria describes a move toward transdiagnostic functional dimensions grounded in neurobiology and observable behavior. This supports organizing phenotypes by domains such as threat, reward, cognitive control, and social processing. It does not imply that current diagnostic systems should be discarded or that dimensions automatically yield better outcomes.

## Gap ledger

| ID | Accepted research gap | Evidence anchor | Testable consequence |
|---|---|---|---|
| G1 | It is unclear whether multimodal, transdiagnostic profiles predict response better than diagnosis-only baselines. | McQuaid 2021; Kelly et al. 2018 | Compare nested models under patient- and site-held-out validation. |
| G2 | Mechanistic signals such as inflammation and network dysconnectivity may be present only in subgroups. | Goldsmith et al. 2023 | Estimate latent mechanism strata and test calibration within strata. |
| G3 | Treatment response can be modality-specific and may change over time. | Thomas et al. 2020; Lo and Widge 2017 | Use repeated response trajectories and treatment-by-biomarker interactions. |
| G4 | Biological associations often fail to translate into safe clinical decisions. | Chen et al. 2019; Goldsmith et al. 2023 | Separate association, prediction, utility, and safety endpoints. |
| G5 | The appropriate role of an adaptive algorithm in clinician-led care is unresolved. | Lo and Widge 2017 | Test a supervised policy against fixed-care and diagnosis-only policies. |

## Survey conclusion

The evidence supports a clear primary direction: a transdiagnostic, multimodal, mechanism-guided adaptive care model should predict symptom trajectories and treatment durability using both stable patient features and time-varying response signals. The model should be judged by clinical utility, calibration, subgroup transportability, and safety rather than by discrimination alone.

The strongest near-term claim is not that mental disorders can be reduced to one brain signature. It is that diagnosis and treatment can become more effective when they are treated as a repeated inference-and-control problem: estimate the patient's active symptom mechanisms, select a treatment with a transparent rationale, monitor response, and adapt only inside a clinically governed policy.

