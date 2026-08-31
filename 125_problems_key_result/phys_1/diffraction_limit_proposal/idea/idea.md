# Idea Agent: TraceRes Portfolio

## Problem reconstruction

The high-value question is not whether a microscope can produce a small number of nanometers. It is whether a particular experimental task has recovered a structural distinction that was not supported by the conventional diffraction-limited measurement, and whether an independent reviewer can reproduce that conclusion from the declared raw data, assumptions, and controls. This reconstruction preserves the Survey constraint that diffraction remains a physical baseline while identifying the information resources that change the inverse problem.

## Candidate portfolio

| Candidate | Route | Strength | Limitation | Decision |
|---|---|---|---|---|
| I1: TraceRes resolution passport | Measurement contract plus blinded calibration | Directly addresses all five verified gaps; exposes what a claim means and why it is justified. | Requires common schema and reviewer discipline. | **Selected primary** |
| I2: Adaptive modality selector | Predict SIM/STED/SMLM/MINFLUX configuration from desired scale and sample constraints. | Useful operationally. | Could recommend a method without proving that its final claim is calibrated. | Competitive follow-on |
| I3: Physics-only taxonomy map | Classify methods by far-field, near-field, nonlinear, sparse, and expansion mechanisms. | Clarifies terminology. | Does not validate a particular image or biological conclusion. | Supporting component |
| I4: Image-sharpening score | Rank reconstructions by visual sharpness. | Easy to implement. | Violates G1 and G3 because sharpness is not structural recovery. | Rejected |

## Selected idea: TraceRes

**TraceRes: A Task-Specific Resolution Passport for Credible Optical Nanoscopy** is a structured assessment layer placed between an imaging pipeline and a scientific claim. It does not replace SIM, STED, SMLM, MINFLUX, expansion microscopy, or reconstruction software. It asks every modality to expose the same five elements:

1. **Task and resolution type.** The claimed object is emitter localization, pair separation, line-width estimation, molecular coordinate accuracy, or dynamic change; the claim cannot use one metric as a substitute for another.
2. **Information channel.** The record states whether the gain comes from nonlinear state control, patterned illumination, temporal sparsity, targeted excitation, physical expansion, near-field collection, or a model-based computational prior.
3. **Error budget.** Photon statistics, background, sampling density, drift, registration, labeling linkage, aberrations, reconstruction choices, sample motion, and temporal averaging are bound to the claimed scale.
4. **Counterfactual validation.** Blinded synthetic and physical nanoruler cases include known separations, density changes, background, drift, and label-offset perturbations. A result must recover or reject the known distinction at a declared confidence and scope.
5. **Bounded claim status.** The passport emits only a status supported by the record. A narrow PSF may earn `EFFECTIVE PSF CONFINED`; a precise centroid may earn `LOCALIZATION PRECISION VALIDATED`; only a passed calibration and sampling audit can earn `STRUCTURAL RESOLUTION VALIDATED`.

## Falsifiable hypotheses

* **H1:** Typed passports reduce the rate at which localization precision is misreported as structural resolution relative to a single-metric report.
* **H2:** A structural-resolution status that uses the maximum of sampling, calibration, registration, labeling, drift, and empirical-separation constraints is better calibrated on blinded truth-known cases than a status based only on nominal optical resolution.
* **H3:** Binding a declared information channel and error budget to each claim reduces omitted-alternative and reconstruction-artifact findings in an independent audit.
* **H4:** A task-specific modality recommendation constrained by the passport has higher expected valid-information yield than choosing the method with the best advertised spatial number alone.

## Scientific debate and selection

The portfolio debate rejected a universal “new diffraction law” because it would collapse distinct measurement models. It also rejected a purely software-ranking concept because a reconstruction metric cannot compensate for unknown labeling or sample motion. TraceRes was selected because it preserves the physical baseline, makes additional priors visible, and provides direct falsification paths. A claim fails if a required calibration field is missing, a truth-known separation is not recovered under matched conditions, or an alternative explanation such as drift, label offset, or reconstruction hallucination remains quantitatively competitive.
