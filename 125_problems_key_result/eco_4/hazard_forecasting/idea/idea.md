# Idea Agent: MULTIHAZARD-X

## Selected direction

**MULTIHAZARD-X** is a latency-constrained, physics-informed forecasting and early-warning architecture for tropical cyclones, tsunamis, and earthquakes. It does not force the hazards into one physical model. Each hazard receives its own state representation, observation operator, and transition model. A shared layer handles uncertainty calibration, tail-risk scoring, missing-data robustness, and the conversion of forecast distributions into warning actions.

The central research question is:

> At a fixed information and communication budget, can hazard-specific hybrid models plus a shared calibration-and-decision layer improve probabilistic skill and warning utility over physics-only, AI-only, and uncalibrated ensemble baselines?

## Why this idea survives the debate

### Route A: a universal multimodal model

This route learns a common representation of satellite, radar, seismic, GNSS, buoy, tide-gauge, and topographic data. It is attractive because large models can transfer statistical regularities between tasks. It is rejected as the primary design because shared representations can confuse atmospheric evolution, seismic rupture, and shallow-water propagation, while label and sampling structures differ sharply.

### Route B: independent best-in-class models

This route optimizes a cyclone model, a tsunami model, and an earthquake model separately. It respects physical differences and offers strong local baselines. It is incomplete because operational warning quality also depends on common calibration, latency accounting, communication, and asymmetric decision loss.

### Route C: hazard-specific physics-informed modules with shared calibration

This route retains Route B's physical separation and adds a small common layer for distributional calibration, missingness-aware fusion, latency-aware gating, and action thresholds. It is selected because it directly addresses the survey gaps without assuming a universal precursor or universal dynamics.

## Core mechanism

For hazard (h\) at time (t\), the module receives observations (o_{h,0:t}\), a model state (x_{h,t}\), and a quality vector (q_{h,t}\). It produces an ensemble distribution over future states and impacts:

\[
 p_h(y_{t+1:t+H},a_{t+1:t+H}\mid o_{h,0:t},q_{h,t}).
\]

The shared layer does not replace the transition model. It estimates reliability, corrects probability miscalibration, and chooses an alert action (a\) under a hazard-specific loss matrix. The system records ingestion, inference, calibration, communication, and action latencies separately.

## Hazard modules

- **Cyclone module:** an ensemble atmospheric-ocean state model for track, intensity, wind radius, rainfall, surge, and coastal impact. Satellite, aircraft, ocean, radar, and numerical-weather-model fields are assimilated with an event-aware correction model.
- **Tsunami module:** a sequential source-estimation and propagation model. Seismic and GNSS observations initialize source hypotheses; DART and coastal water-level observations update wave and inundation distributions. The output is an evolving warning product after source initiation, not a claim of pre-event exact prediction.
- **Earthquake module:** a phase-detection, event-association, ground-motion, and short-horizon early-warning module. A separate long-horizon probability head is evaluated only as a probabilistic forecast. No component is allowed to label a precursor as a deterministic prediction without prospective evidence.

## Falsifiable claims

1. At matched compute and information cutoffs, calibrated MULTIHAZARD-X distributions reduce weighted probabilistic score and improve reliability relative to each uncalibrated hybrid baseline.
2. At a fixed false-alert budget, the system improves useful warning lead time or reduces impact-weighted regret relative to the strongest single-hazard baseline.
3. Removing physical transition constraints, latency gating, or decision calibration causes a measurable failure on at least one hazard or stress regime.
4. Transfer from one hazard to another is helpful only through calibration and data-quality representations; direct transfer of physical transition parameters should not be required for success.

## Intended contribution

The contribution is an evaluation protocol and a modular design, not a claim that catastrophic events have become deterministic. It connects forecasting skill to action value under a realistic information clock. A positive result would justify operational pilots for specific hazards and regions. A negative result would identify whether the limiting factor is model error, observation sparsity, calibration, or unavoidable physical unpredictability.

## Idea handoff

The ExperimentDesign Agent should implement a synthetic-to-hindcast evaluation with strict time locks, hazard-specific baselines, ablations, reliability diagnostics, rare-event scores, and an explicit latency budget. It must leave `expected_results` and `observed_results` empty until a real study is run.
