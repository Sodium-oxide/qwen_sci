# ExperimentDesign Agent: Meridian Residual Specificity Trial (MRST)

## Design status and safety boundary

**Status:** DESIGN_ONLY. This document is a protocol proposal, not an approved study and not an account of observed results. It does not recruit participants, perform needling, prescribe treatment, diagnose disease, or provide individual medical advice. Any future human work requires institutional ethics review, informed consent, trained and licensed personnel where required, adverse-event governance, privacy protection, and prospectively registered analysis.

The design deliberately separates a physical/physiological test of canonical trajectories from a clinical treatment trial. It is not designed to determine whether acupuncture should be used for any individual condition.

## Research brief

**Primary question:** Does canonical meridian membership contribute reproducible predictive information after known anatomical, acquisition, and contextual covariates are controlled?

**Competing explanations:**

- **E0: anatomy-plus-artifact model.** Observed differences are explained by tissue planes, collagenous bands, nerves, vessels, skin properties, measurement contact, hydration-related variability, expectation, or spatial dependence.
- **E1: canonical-label residual model.** After those variables are controlled, canonical labels contribute stable, directional, out-of-sample information across independent trajectories.
- **E2: non-identifiability.** Data coverage, reliability, or comparator matching is insufficient to discriminate E0 from E1; the study must abstain rather than narrate a positive or negative ontology result.

## Future study architecture

### Coordinate lock and comparators

Before any future data collection, an independent cartographic team creates a versioned coordinate file for selected body regions. The file contains:

1. canonical-path coordinates derived from a declared traditional atlas;
2. anatomy-matched noncanonical coordinates selected without knowledge of outcomes;
3. spatially shifted controls preserving region, surface geometry, and acquisition order;
4. technical repeat locations for within-session reliability.

The coordinate file is hashed, preregistered, and concealed from image annotators and primary analysts until the lock is released. “Matched” means matching on pre-specified tissue depth, body region, visible fascial-plane category, and local innervation proxy as closely as possible; balance diagnostics are mandatory.

### Measurements

No one measurement can identify a meridian. The future measurement bundle is deliberately multimodal:

| Domain | Candidate measure | Purpose | Failure mode it addresses |
|---|---|---|---|
| Structural | ultrasound-derived fascial plane, subcutaneous thickness, collagen-band echogenicity | represent ordinary anatomy explicitly | mistaking fascia prevalence for a channel |
| Electrical | calibrated four-electrode impedance at declared frequencies | test local biophysical variation | electrode contact, skin hydration, depth, and device drift |
| Surface physiology | temperature and local perfusion proxy where validated | test transient local response | interpreting generic vascular change as path-specific |
| Sensory | standardized innocuous sensory threshold/proxy | quantify regional neural context | treating sensory density as a meridian effect |
| Acquisition | operator, sequence, device, calibration phantom, contact quality | measure technical nuisance variables | operator and instrument artifacts |
| Context | expectation assessment and discomfort rating, when a future protocol uses human stimulation | model contextual contribution | confounding a mechanistic label with expectancy |

The exact equipment, operating ranges, and participant burden cannot be declared executable until an ethics-reviewed, device-specific protocol exists. This proposal therefore specifies variables and falsification logic rather than step-by-step clinical procedures.

### Blinding and data governance

- Coordinate labels are replaced by random identifiers for image annotation and primary analysis.
- The statistician receives canonical status only in a sealed analysis table after covariates, exclusions, and quality-control rules are finalized.
- Raw images, calibration logs, and analysis code receive immutable version identifiers; access follows a least-privilege human-data plan.
- Missingness, deviations, and adverse events are reported rather than silently excluded.
- The primary analysis and all negative results are released with a machine-readable coordinate schema when privacy and consent allow.

## Variables and operational claims

**Independent variable of interest:** blinded canonical-path membership \(M_{ij}\) for measurement \(j\) in individual \(i\).

**Primary dependent variables:** predeclared standardized physical/physiological measurements \(Y_{ij}\), each evaluated separately before any composite endpoint.

**Covariates:** anatomical features \(A_{ij}\), technical factors \(Q_{ij}\), person-level effects \(u_i\), spatial basis \(S_{ij}\), and declared contextual factors \(X_{ij}\).

**Primary estimand:** the held-out increment in prediction attributable to \(M_{ij}\) after adjustment. The primary mixed model is:

\[
Y_{ij} = \beta_0 + \beta_M M_{ij} + \boldsymbol{\beta}_A^{\mathsf{T}}A_{ij}
       + \boldsymbol{\beta}_Q^{\mathsf{T}}Q_{ij}
       + \boldsymbol{\beta}_X^{\mathsf{T}}X_{ij} + u_i + S_{ij} + \epsilon_{ij}.
\]

The model must be assessed with trajectory-level held-out validation, not only in-sample significance. A model with a nonzero in-sample \(\beta_M\) but no held-out increment is not evidence of a meridian-specific signal.

## Decision rules

| Result pattern | Interpretation allowed | Interpretation prohibited |
|---|---|---|
| Canonical label adds preregistered, cross-trajectory, out-of-sample information after covariate adjustment | A reproducible residual signal has been observed and merits independent replication. | “Qi” or organ correspondence has been proven; a treatment is clinically effective. |
| Initial difference disappears after anatomy or acquisition adjustment | The sampled effect is more parsimoniously explained by measured covariates. | All acupuncture mechanisms or all cultural accounts have been disproven. |
| Shifted controls perform as well as canonical coordinates | The sampled pattern lacks trajectory specificity. | A therapeutic outcome, if any, is impossible. |
| Quality-control failure, poor matching, or insufficient reliability | MODEL_OR_DATA_ABSTAIN. | Any ontological conclusion. |

## Sample, precision, and replication

The proposal does not set a recruitment target. A future protocol must use pilot reliability estimates to power the primary held-out contrast and account for within-person clustering, multiple trajectories, and multiplicity across modalities. A single laboratory or a single trajectory is not sufficient for a positive ontology claim. The confirmation stage requires a locked coordinate file, independent operators, a new sample, and replication of direction and predictive increment.

## Risk register

| Risk | Mitigation | Residual human-review requirement |
|---|---|---|
| Treating cultural labels as a biomedical premise | Blind labels and state competing models explicitly. | Interdisciplinary review with TCM historians/practitioners and biomedical methodologists. |
| False path signal from spatial autocorrelation | Use shifted controls, trajectory-held-out validation, and spatial terms. | Statistical review of the spatial model. |
| Misleading instrument differences | Calibration phantoms, repeat sites, and documented contact quality. | Device and metrology review. |
| Medical over-interpretation | Separate physical results from clinical endpoints and include abstention state. | Ethics and clinical-governance review. |
| Stigmatizing or dismissive framing | Report what was tested, what was not tested, and uncertainty. | Community-sensitive scientific communication review. |

## Author handoff

The Author Agent may state that the strongest available scientific basis is for condition-specific acupuncture research and for testable local physiological correlates. It must state that a unique meridian anatomy remains unestablished, that the proposed MRST is a falsifiable design rather than an executed experiment, and that no clinical recommendation follows from it.
