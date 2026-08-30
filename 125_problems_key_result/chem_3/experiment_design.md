# Experiment Design: Correlative Geometric--Molecular--Force Metrology for Nanoscale Film Stability

- Execution mode: `DESIGN_ONLY`
- Evidence status: `DESIGNED_NOT_EXECUTED`
- Observed results: none
- Human review: required before any physical implementation

## Objective

Test, at the design level, whether a geometry-matched non-biological liquid--solid thin-film comparison can discriminate a chemistry-mediated local-interaction mechanism from a thickness-only explanation. The design does not select a material system, chemical identity, apparatus, operating parameter, or procedure.

## Central hypothesis

Within an expert-approved non-biological liquid--solid thin-film system, a temporally coherent relation among film geometry, an interface-specific molecular-state representation, and a confined-force proxy can explain a drainage or stability transition beyond geometry alone. The claim is a proposed causal-discrimination criterion, not an observed result.

## Design logic

| Evidence role | Required representation | Mechanistic purpose | Explicit limitation |
| --- | --- | --- | --- |
| Geometry | Time-indexed film thickness and/or morphology | Establishes the physical baseline and geometry-only account | Calibration and refractive-index/model assumptions can mislead |
| Molecular state | Interface-specific vibrational or chemical-state representation | Tests whether an interfacial-state change accompanies the transition | Interpretation may be model-dependent and non-unique |
| Local interaction | Confined-force or disjoining-pressure representation | Tests whether the local interaction landscape changes consistently | Probe perturbation, roughness, and interaction-model error can mislead |
| Transition outcome | Declared drainage, arrest, persistence, or rupture outcome | Provides the outcome that competing accounts must explain | Definition requires model-system approval |
| Audit | Time alignment, calibration, surface history, and perturbation record | Prevents correlation or artifact from being treated as causal evidence | Completeness must be checked before interpretation |

## Logical comparison set

1. **Geometry-only baseline** — explain the declared transition using geometry, curvature, and capillarity representations only.
2. **Geometry-plus-molecular account** — test whether the molecular-state representation adds interpretable information beyond the baseline.
3. **Geometry-plus-local-interaction account** — test whether the confined-force representation adds interpretable information beyond the baseline.
4. **Joint account** — test whether the combined molecular-plus-local-interaction representations provide a coherent, added explanation while all audits remain adequate.

The comparison is valid only inside one expert-approved geometry-matched and cross-channel comparability boundary. It is not a request to build or run a physical experiment.

## Required controls and invalidation checks

- Geometry-only and capillarity explanations remain active alternatives.
- Optical calibration and refractive-index/model assumptions require traceability.
- Surface history, contamination, and roughness require a provenance record.
- Probe, interaction-model, and observation-induced perturbations require an explicit audit.
- Cross-channel temporal or spatial mismatch requires an uncertainty record.
- A missing or non-comparable critical observation forces the `uninformative_or_invalid` outcome branch.

## Outcome interpretation

| Branch | Decision meaning |
| --- | --- |
| `supports_mechanism` | Joint evidence adds explanatory information beyond geometry and named artifact alternatives are insufficient within the approved boundary. |
| `partial_or_heterogeneous` | The relation is conditional, state-specific, or incompletely identifiable. |
| `null_or_contradictory` | Geometry explains the transition equally well, or added evidence is inconsistent. |
| `uninformative_or_invalid` | Calibration, comparability, perturbation, or timing evidence is inadequate; no causal claim is allowed. |

## Evidence and provenance

The design reuses only cross-validated component-method anchors from the Survey: `R2`, `R3`, `R4`, `R9`, `R10`, and `R11`. The formal evidence bundle retains direct traceability cards for molecular-state capability (`R2`), molecular interpretation limits (`R4`), confined-force capability (`R10`), and geometric observation capability (`R11`). These sources support component capabilities only; none is presented as proof of the proposed three-channel mechanism.

Upstream inputs are [idea_result.json](C:/Users/31390/Desktop/2026tzb/aiscientist-v0820/Xcientist/src/agents/idea_agent/outputs/interfacial-metrology-codesign-20260830/idea_result.json), [idea_candidate.json](C:/Users/31390/Desktop/2026tzb/aiscientist-v0820/Xcientist/src/agents/idea_agent/outputs/interfacial-metrology-codesign-20260830/idea_candidate.json), and [survey.json](C:/Users/31390/Desktop/2026tzb/aiscientist-v0820/Xcientist/src/agents/survey_agent/outputs/20260830-172338-646840-survey-001/survey.json). The upstream Survey-to-Idea binding still requires human provenance confirmation.

## Human-review boundary

The ExperimentDesign chemistry/chemical-engineering route requires chemical-safety and facility confirmation. The pending decisions are: the non-biological model interface, compatibility of the observation classes, calibration and time-registration traceability, the eligible state frame, independent-repetition rationale, and the final analysis estimand. No people, animals, plants, clinical work, or restricted biological materials are part of this design.

The machine-readable canonical artifact is [experiment_design.json](C:/Users/31390/Desktop/2026tzb/aiscientist-v0820/Xcientist/src/agents/experiment_design_agent/outputs/interfacial-metrology-design-20260830/experiment_design.json).
