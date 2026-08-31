# ExperimentDesign Agent Output: Design-Only Protocol for Individual Immune Resilience

## Intake and execution boundary

**Selected direction:** D2 -- Personal Longitudinal Immune-Homeostasis Atlas with Bounded Human Microphysiological Counterfactual Testing.  
**Design status:** `DESIGN_ONLY`.  
**Observed results:** none.  
**Permitted work:** a future human-observational and nonclinical ex-vivo evaluation plan, conditional on ethics, consent, biosafety, and data-governance approval.  
**Prohibited work:** participant recruitment, treatment assignment, patient-specific diagnosis, gene editing, pathogen work, animal work, autonomous medical advice, or clinical intervention.

## Research brief

The unit of analysis is a consented participant's de-identified, longitudinal, context-annotated measurement window. The system estimates a multi-layer **homeostasis state card** with: (1) personal baseline distance, (2) tolerance--effector coordination, (3) barrier/microbiota context, (4) exposure- and memory-context uncertainty, (5) data coverage, and (6) recovery or abstention state. It does not label a person healthy or diseased and does not replace a clinical evaluation.

### Hypotheses

- **H1 (personal trajectory):** A personal longitudinal baseline will calibrate expected within-person variation and recovery better than a cross-sectional population reference.
- **H2 (layer attribution):** Separating tolerance/effector, barrier/microbial, and memory layers will make an apparent deviation more auditable than a single immune score.
- **H3 (bounded feedback test):** For a predefined immune--barrier feedback hypothesis, the direction of a model-predicted relationship can be assessed in a nonclinical human microphysiological system without claiming whole-body or clinical validity.
- **H4 (abstention and equity):** Explicit tissue, data-coverage, and consent constraints will identify situations where a homeostasis state should not be estimated.

## Variables and state card

| Construct | Example authorized representation | Model output | Guardrail |
|---|---|---|---|
| Personal baseline | Repeated de-identified immune-cell, protein, and transcriptomic summaries | Individual operating-range interval | No diagnostic reference range. |
| Tolerance/effector coordination | Predefined aggregate regulatory and activation modules | Coordination trajectory and uncertainty | No claim that a module equals an entire cell function. |
| Barrier/microbial context | Authorized noninvasive microbial/metabolite and barrier-associated summaries | Context layer and coverage flag | Association is not a causal or treatment target. |
| History/memory context | Consent-authorized exposure/vaccination metadata and cell-state memory summaries | Context adjustment, not disease label | No inference about unreported infection history. |
| Platform feedback readout | Predefined aggregate immune--barrier measurements in an approved nonclinical platform | Directional-consistency test | No therapeutic or whole-human efficacy claim. |
| Data quality | Tissue availability, source age, missingness, batch and consent restrictions | Abstention/reliability card | Missing tissue is never treated as normality. |

## Comparator and validation plan

1. **Population-reference baseline:** cross-sectional reference intervals stratified only by prespecified, ethically justified variables.
2. **Single-score baseline:** a pooled multi-omic anomaly score without layer attribution.
3. **Personal state-space proposal:** individual operating-range model with layer outputs, coverage flags, recovery estimates, and abstention.
4. **Platform comparator:** a predefined simplified immune--barrier system used to assess only the directionality of a stated feedback relation; it is not an oracle for participant outcomes.

## Evaluation protocol

1. Freeze consent language, data dictionary, sample windows, permitted metadata, homeostatic modules, recovery horizon, missingness rules, and all analysis metrics before model fitting.
2. Use time-forward holdouts within people and held-out participants for external-person generalization. Use site/batch holdouts when data provenance permits; do not let future measurements enter a past state estimate.
3. Evaluate calibration of personal operating intervals, recovery-time prediction, layer-attribution consistency, abstention accuracy, and coverage-stratified disparities. Do not use a generic classification accuracy as the primary endpoint.
4. For the platform sub-study, preregister a small number of nonclinical, ethically approved feedback hypotheses and the aggregate readouts that would be directionally consistent or inconsistent with each. No model is allowed to select its own mechanism after seeing platform data.
5. Require paired human review: a computational reviewer checks provenance, temporal cut-off, and uncertainty; an immunology/clinical-governance reviewer checks biological plausibility, consent restrictions, and communication risks.
6. Treat all results as research-state evidence. Any path to patient care would require independent analytical validation, clinical validation, regulatory review, and a separate protocol.

## Conditional conclusion labels

| Evaluation label | Required evidence | Permitted conclusion |
|---|---|---|
| `individual_baseline_stable` | Calibrated personal range and expected fluctuation pattern on held-out windows | The observed research measurements are consistent with the modelled personal range. |
| `contextual_adaptation_resolved` | A deviation returns within the preregistered recovery structure with adequate coverage | The trajectory is consistent with a resolved contextual adaptation in this research model. |
| `persistent_dysregulation_candidate` | Persistent, layer-attributed deviation plus adequate coverage and reviewer agreement | A hypothesis for further human expert investigation, not a diagnosis. |
| `model_or_data_abstain` | Insufficient tissue coverage, consent, calibration, or mechanism resolution | Do not assign a homeostasis-state interpretation. |

## Safety, ethics, and governance

The protocol must be reviewed by appropriate ethics, privacy, biosafety, and clinical-governance bodies before any human data or human cells are accessed. Data must be de-identified, consent-limited, and purpose-limited. The system cannot surface an individual score to a participant or clinician as medical advice. Human microphysiological work must remain nonclinical, use only approved materials and established institutional procedures, and report its model limitations prominently. The platform may test a bounded mechanistic relation; it cannot establish treatment response, systemic efficacy, or replacement of animal or human studies.
