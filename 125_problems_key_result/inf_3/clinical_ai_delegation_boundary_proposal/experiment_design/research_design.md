# ExperimentDesign Agent: CDBC Shadow-Mode Validation Protocol

## Research brief

**Selected direction:** Clinical Delegation Boundary Contract (CDBC), `idea-cdbc-001`.

**Scientific question:** Can a task-specific, uncertainty-aware and human-accountable AI pathway improve the safety-adjusted performance of screening-mammography triage without creating unacceptable subgroup disparity, workflow burden, or loss of traceability?

**Execution status:** `DESIGN_ONLY`. The following is a future-study protocol. It has not accessed records, trained a model, run a retrospective analysis, entered a clinical workflow, influenced patient care, or produced observed outcomes.

## Scope and safety gate

The study is restricted to a future evaluation of image-based screening triage. It does not provide diagnosis, treatment, medical advice, or a live recommendation. The first prospective phase is shadow mode: model and CDBC outputs are recorded separately and cannot be displayed to decision makers or affect care. Any later change to a clinical workflow requires ethics, privacy, institutional, regulatory, clinical-governance, and patient-information approvals independent of this proposal.

## CDBC authority tiers

| Tier | Permitted future role | Mandatory boundary |
|---|---|---|
| 0: no-AI | Standard clinician workflow only. | No model output is produced or used. |
| 1: information | Retrospective/shadow score and explanation record. | No patient-care action and no clinician-facing alert. |
| 2: supervised triage | Future clinician-facing prioritization recommendation. | Clinician retains final interpretation, action, and override authority. |
| 3: narrow routing | Future non-diagnostic routing only after every gate passes. | Automatic treatment, definitive diagnosis, and unrestricted autonomy are prohibited. |

An output defaults to Tier 1 if data are incomplete, uncertainty or out-of-distribution thresholds are exceeded, a subgroup gate is not met, an incident review is unresolved, or the monitoring status is stale. The protocol does not authorize Tier 2 or Tier 3.

## Study design

### Data and units

The planned unit is one screening-mammography episode associated with a deidentified future dataset from multiple sites. Sites, image acquisition pathways, reporting standards, and follow-up definitions must be specified before analysis. Records are split by site and time to prevent leakage. A qualified data-governance process must verify lawful basis, privacy protection, dataset provenance, label quality, subgroup representation, and permitted secondary use.

### Comparison arms

| Arm | Evaluation role | Patient-care boundary |
|---|---|---|
| A: clinician standard | Reference workflow under the site's standard of care. | Observed only in retrospective or approved future study data. |
| B: AI-only counterfactual | Offline model predictions without CDBC escalation. | Never used for actual care. |
| C: clinician plus CDBC | Shadow-mode contract with AI score, abstention status, delegated tier, and clinician decision record. | Outputs isolated from patient care until all later approvals and gates pass. |

### Primary endpoint

The primary planned endpoint is **safety-adjusted delegation success**. A case counts only when the CDBC authority tier is appropriate, the case is correctly handled against the predeclared reference outcome, the model is calibrated within the declared range, the subgroup gate is met, and the complete escalation/override record is auditable. This endpoint refuses to award a high score to a model that is accurate on average but unsafe, inequitable, non-auditable, or used beyond its authority.

### Secondary endpoints

Secondary measures include sensitivity, specificity, positive predictive value, negative predictive value, calibration, abstention rate, out-of-distribution flag rate, time-to-review, clinician override rate, workload distribution, false-reassurance events, referral volume, subgroup-specific error disparities, patient-information completeness in a later approved study, and monitoring/incident completeness.

## Analysis plan

1. Pre-register intended use, dataset inclusion/exclusion, reference standard, clinically meaningful harm thresholds, subgroup definitions, missing-data strategy, CDBC gates, statistical model, and stopping/pause criteria.
2. Perform retrospective multi-site temporal external validation before any shadow-mode phase. Report all cases, exclusions, confidence intervals, calibration curves, and per-site/per-subgroup outcomes.
3. In shadow mode, record the AI output, CDBC tier, abstention reason, clinician interpretation, override, final follow-up outcome, workflow time, and safety incidents. Model output must remain invisible to care teams during this phase.
4. Compare A, B, and C using paired analyses where appropriate and hierarchical models that account for site, reader, and subgroup variation. Report absolute event differences and uncertainty, not only AUC.
5. Trigger a pause when a predeclared safety, calibration, subgroup, drift, or traceability threshold fails. A pause freezes the delegation tier; it does not silently retune the model using outcome data.
6. Require independent audit of code version, data lineage, model card, CDBC records, and incident logs. Any update follows a governed change-control process and returns to an appropriate validation tier.

## Conditional outcomes

| Future outcome | Interpretation | Action |
|---|---|---|
| C improves the primary endpoint without subgroup or monitoring gate failures. | Supports a bounded clinician-AI triage pathway. | Consider an independently governed next-stage study; do not generalize to physician replacement. |
| B has strong AUC but fails calibration, equity, or traceability gates. | Technical discrimination is insufficient for delegation. | Keep at Tier 1; repair evidence and governance before any clinical use. |
| C raises workload or override burden without safety benefit. | The interface or delegation policy is ineffective. | Redesign workflow; do not equate automation with efficiency. |
| Drift, missingness, or out-of-distribution flags rise. | The CDBC detects an out-of-envelope state. | Pause the tier and perform root-cause review. |
| Clinicians and patients cannot understand the authority and escalation route. | The pathway lacks usable accountability. | Co-design and test communication before a new evaluation. |

## Human review requirements

Clinicians, imaging specialists, statisticians, data stewards, ethicists, patients/public representatives, privacy officers, regulatory specialists, and safety/quality teams must review the protocol. No automatic action, patient contact, data transfer, model training, medical-device submission, procurement, or care recommendation is authorized by this design.
