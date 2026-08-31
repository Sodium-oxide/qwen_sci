# ExperimentDesign Agent: TraceRes Research Design

## Design status

This is a **DESIGN_ONLY** proposal. It specifies a computational and calibration-benchmark protocol but does not acquire microscope data, execute reconstruction, operate an instrument, or report observed performance.

## Research brief

TraceRes evaluates whether an optical microscopy claim is appropriate for a declared task. Its central claim is operational: a reported structural scale is credible only when the claimed separation is supported jointly by information-channel documentation, empirical separation recovery, sampling density, calibration, and coordinate-accuracy controls.

For a candidate dataset \(c\), the proposed passport records

\[
P_c=\{T_c,M_c,I_c,Q_c,E_c,V_c,S_c,F_c\},
\]

where \(T_c\) is the task, \(M_c\) the modality and acquisition model, \(I_c\) the added information channel, \(Q_c\) quality and calibration data, \(E_c\) the error budget, \(V_c\) blinded-validation results, \(S_c\) the bounded status, and \(F_c\) follow-up actions. In the final IEEE report the same equations are typeset with numbered LaTeX environments.

## Scope and safety gate

* **Primary route:** computational/digital analysis of authorized public benchmark data, synthetic image simulations, and human-approved physical calibration data.
* **Secondary route:** mathematical/statistical measurement model and falsification analysis.
* **Execution policy:** no automatic optical acquisition, live-cell imaging, sample preparation, high-power illumination, biological manipulation, or data release is allowed by this proposal.
* **Human review:** required before use of any experimental data, microscope configuration, fluorophore, sample, or public claim.

## Variables and operational definitions

| Role | Variables | Operationalization |
|---|---|---|
| Independent | Modality class; information channel; photon count; background; emitter density; separation; drift; label offset; aberration; temporal change | Factorial, pre-registered synthetic and calibration-case conditions. |
| Dependent | Structural-separation recovery; localization precision; coordinate accuracy; false structural claim rate; valid-information yield | Compared with known case truth or traceable nanoruler geometry. |
| Controls | NA, wavelength, pixel size, simulation generator version, PSF model, analysis version, threshold policy, blinded label | Frozen in the passport manifest. |
| Moderators | Sample thickness, scattering, label density, motion, field of view, acquisition time | Reported as scope limits; not silently averaged away. |

## Proposed validation protocol

1. Pre-register task definitions, resolution metrics, status thresholds, the hypothesis library, and release language.
2. Build synthetic cases spanning 10--500 nm pair separations, density, photons, background, drift, label linkage, aberration, and temporal motion. The truth geometry remains hidden from the primary analyst.
3. Add human-approved physical calibration cases such as traceable nanorulers or well-characterized patterned structures. Physical cases validate only the stated geometry and optical regime.
4. For each modality branch, record raw-data identity, acquisition settings, calibration, reconstruction parameters, FRC/FSC or matched empirical-separation metric, sampling density, drift/registration estimate, and label-linkage estimate.
5. Assign a passport status through the registered decision rule. An independent reviewer sees the record without the hidden truth label and checks whether the status and allowed wording follow from the evidence.
6. Compare TraceRes with single-metric and nominal-resolution reporting baselines. Planned metrics include calibration curves, false positive/negative structural claim rate, claim-type confusion, alternative-explanation omission, time/light/resource cost, and valid-information yield.

## Decision rule

The design uses a conservative but informative structural lower-bound envelope,

\[
r_{\mathrm{claim}}=\max\{r_{\mathrm{emp}},\;2d_{\mathrm{Nyq}},\;e_{\mathrm{label}},\;2\sigma_{\mathrm{reg}},\;r_{\mathrm{drift}}\},
\]

with each term defined for the selected task and modality. The expression is not a universal law or a replacement for a validated resolution estimator. It is a release gate: a report may not claim a smaller structural scale than the largest relevant unexcluded constraint. A status is upgraded only when its required evidence fields and task-specific validation are complete.

## Counterfactual and failure analysis

* **Drift or chromatic registration mimics separation:** withhold structural status until fiducial or registration audit supports the stated coordinate accuracy.
* **Sparse localization precision but insufficient label density:** report validated localization precision, not structural resolution.
* **A reconstruction is sharper under a changed prior:** retain `CLAIM NOT SUPPORTED` until the result is stable across registered plausible models or truth-known cases discriminate them.
* **A method loses its advantage in dynamic or light-sensitive samples:** report the task constraint and route to a less nominally sharp but more valid modality.
* **A calibration target is recovered but biology differs:** restrict the conclusion to the calibrated regime; require new validation for the biological sample class.

## Author handoff

The Author Agent may state that the proposal redefines “bypass” as a documented change in information and inference, not a repeal of diffraction physics. It must not assert that TraceRes has measured a method, validated a dataset, reduced a false-claim rate, or achieved any nanometer value.
