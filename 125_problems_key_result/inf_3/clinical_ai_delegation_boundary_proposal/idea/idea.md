# Idea Agent Report: Clinical Delegation Boundary Contract

## Candidate synthesis

The Survey shows that “AI versus clinician” is an inadequate decision frame. A clinical system does not merely emit a score: it receives imperfect inputs, operates across patient groups and sites, directs attention or resources, affects downstream care, and must have a responsible authority. The research direction therefore treats delegation as a measurable contract rather than a technology label.

## Selected primary idea: Clinical Delegation Boundary Contract (CDBC)

The CDBC defines the maximum decision authority that an AI-enabled pathway may hold for a named clinical subtask. It binds every output to a declared intended use, data completeness threshold, out-of-distribution and uncertainty rule, escalation path, clinician authority, subgroup audit, patient-information obligation, monitoring plan, incident response, and revocation trigger.

**Concrete research object.** `screening-mammography case x site x patient subgroup x model state x uncertainty signal x delegation tier x clinician action x follow-up outcome`.

**Central hypothesis.** A CDBC-guided triage pathway that forces calibrated abstention, human escalation, equity checks, and lifecycle monitoring will yield a higher safety-adjusted delegation profile than either an AI-only counterfactual or an undefined “human-in-the-loop” workflow, even when all arms share the same prediction model.

**Mechanism.** The contract converts a raw prediction into one of four auditable states: no AI use; AI information only; AI triage recommendation requiring clinician confirmation; or narrowly delegated routing only after all gates pass. An uncertainty or context failure routes the case to a qualified clinician rather than permitting silent automation. Every override, abstention, incident, and drift signal updates the quality record.

**Falsifiers.** The idea fails if CDBC gates do not detect unsafe or inequitable conditions earlier than standard metric reporting, if clinician authority and escalation do not improve the safety-adjusted outcome, if an independent audit cannot reconstruct a delegation decision, or if the added workflow burden outweighs the measured benefit.

## Portfolio decision

| Candidate | Decision | Rationale |
|---|---|---|
| CDBC for task-level triage | Selected primary | Addresses all five Survey gaps and makes replacement claims empirically testable at the appropriate scope. |
| Higher-AUC model search | Competitive | Important engineering work, but cannot define responsibility, population scope, or safe authority. |
| Fully autonomous screening decision | High risk | A legitimate future research target only after task-specific evidence, regulation, and accountability conditions are met. |
| Generic clinician-AI chatbot | Rejected | Too broad, lacks a stable task, reference standard, harm model, and delegation boundary. |
| “AI will never replace any clinician task” | Rejected | Contradicted by evidence of task-specific automation potential. |

## Evolution trace

1. **Root: accuracy race.** Defect: a score was treated as a clinical decision. Change: define an intended-use and authority boundary.
2. **Safety branch.** Defect: abstention was absent. Change: add uncertainty, missing-data, and out-of-distribution escalation rules.
3. **Equity branch.** Defect: aggregate performance concealed group harm. Change: require subgroup gates and a disparity-triggered pause.
4. **Human branch.** Defect: “human in the loop” had no measurable role. Change: specify authority, override, workload, and response-time records.
5. **Lifecycle branch.** Defect: deployment implied permanence. Change: add drift monitoring, incident review, and revocation criteria.
6. **Selected node.** Defect: replacement language remained general. Change: make every delegation tier narrow, evidence dependent, and reversible.

## ExperimentDesign handoff

The proposed evaluation begins in retrospective and shadow modes only. It uses no live decision support, no autonomous treatment, and no modification of patient care. The future study must compare clinician-standard workflow, offline AI-only counterfactual, and clinician-plus-CDBC pathways. Its primary endpoint is a safety-adjusted delegation outcome combining patient-relevant error, calibration/abstention, equity, and traceable accountable review. Any move from shadow mode toward a live workflow requires independent governance approval and passing all predeclared gates.
