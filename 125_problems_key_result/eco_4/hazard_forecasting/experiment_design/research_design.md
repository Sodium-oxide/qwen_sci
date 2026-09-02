# ExperimentDesign Agent: MULTIHAZARD-X Evaluation

## 1. Study objective

Evaluate whether a hazard-specific, physics-informed ensemble with shared uncertainty and decision calibration improves forecasting skill and end-to-end warning utility under the same observation, compute, and communication budgets. The study is a design proposal. It contains no executed forecast, no fitted model, and no observed result.

## 2. Operational hypotheses

- **H1, calibration:** The calibrated system has lower weighted distributional score and better reliability than the same forecasts before calibration.
- **H2, action value:** At the same false-alert rate, latency-aware decisions have lower impact-weighted regret or longer useful lead time than uncalibrated decisions.
- **H3, physical structure:** Removing the hazard-specific transition constraints degrades extrapolation under rare-event and distribution-shift tests.
- **H4, transfer boundary:** Shared representations for data quality and uncertainty can transfer; physical transition parameters should remain hazard-specific.

## 3. Data and splits

Use three layers in order to expose failure modes before expensive training:

1. **Synthetic layer:** Generate controlled cyclone-like advection-intensification trajectories, shallow-water tsunami propagation with uncertain sources, and marked point-process earthquake sequences with known latent truth. Vary observation density, sensor delay, missingness, and regime shift.
2. **Retrospective layer:** Use time-stamped historical tracks, intensity and impact fields for cyclones; seismic, GNSS, DART, tide-gauge, bathymetry and coastal data for tsunamis; and waveform, phase-pick, event-catalogue and ground-motion data for earthquakes. Reconstruct the information available at each forecast issuance time.
3. **Prospective shadow layer:** After all locks are frozen, run a time-forward shadow evaluation without sending public alerts. This layer tests whether the method works when the data distribution and observing network evolve.

Partition by time and event, not random individual records. Keep a final event-level holdout. Apply an information cutoff so that no reanalysis, post-event label, or future sensor packet enters an earlier forecast.

## 4. System definition

For each hazard (h\), the state transition is (x_{h,t+1}=f_h(x_{h,t},u_{h,t})+\epsilon_{h,t}\), with an observation model (o_{h,t}=g_h(x_{h,t})+\eta_{h,t}\). The module produces (K\) trajectories and an impact distribution. The shared layer estimates a calibrated distribution \(\tilde p_h\) and an action using an explicit loss matrix.

The time budget is

\[
 L_h=L_{\mathrm{ingest}}+L_{\mathrm{quality}}+L_{\mathrm{infer}}+L_{\mathrm{cal}}+L_{\mathrm{communicate}}+L_{\mathrm{act}}.
\]

Every component is logged. A model may not trade away communication or action time while reporting only inference latency.

## 5. Baselines and ablations

Baselines are: persistence and climatology; physics-only numerical propagation; AI-only sequence or graph model; uncalibrated hybrid ensemble; and the strongest available operational or consensus guidance that can be reconstructed under the same cutoff. Ablations remove one property at a time: physical transition constraints, shared calibration, missingness-aware fusion, ensemble spread, tail-risk head, latency gate, and cross-hazard representation transfer.

## 6. Metrics

Use hazard-appropriate scores plus a common decision layer:

- track and arrival errors, intensity and rainfall errors, water-level and inundation errors, and ground-motion or warning-time errors;
- weighted continuous ranked probability score and energy score for distributions;
- reliability diagrams, expected calibration error, Brier score, and sharpness;
- precision, recall, false-alert rate, missed-event rate, and warning lead time at fixed alert thresholds;
- tail-weighted loss for high-consequence quantiles;
- impact-weighted regret (R=\mathbb{E}[C(a,y)]-\min_a\mathbb{E}[C(a,y)]\), with cost matrices specified before evaluation;
- end-to-end latency and compute-energy budget.

Report confidence intervals by event-level block bootstrap. Compare paired forecasts at the same issuance times. Correct for multiple primary comparisons and publish all secondary metrics.

## 7. Stress tests and falsification

Stress cases include rapid cyclone intensification, land interaction, near-field tsunami source uncertainty, sparse or delayed DART observations, dense earthquake swarms without a mainshock, sensor outages, novel observing platforms, and climate or network distribution shift. A claim is falsified if it fails its pre-registered primary score or if any apparent gain disappears after enforcing information cutoffs and latency parity. A deterministic earthquake prediction claim is outside the design and is not an acceptable interpretation of a positive early-warning result.

## 8. Reproducibility and safety

Freeze event lists, feature definitions, cutoffs, cost matrices, software versions, and random seeds before the final holdout. Store model cards and an audit trail for every forecast. Keep all runs in shadow mode until independent review confirms that warnings cannot be confused with public emergency instructions. Do not use unvalidated probabilities to trigger evacuation.

## 9. Decision rule

The selected system advances only if it improves the pre-registered primary distributional score and calibration at matched cutoff, and also improves the decision metric at a fixed false-alert budget without increasing the maximum component latency beyond the available hazard-specific window. Otherwise, the failing component is rejected or restricted to offline analysis.

## 10. Expected deliverables, not results

The study would deliver forecast files, score tables, calibration plots, latency traces, ablation analyses, and a model card after execution. These are planned outputs only; this package deliberately records neither expected numerical values nor observed results.
