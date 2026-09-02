# ExperimentDesign: HCFCA

## Design status and aim

This is a design-only plan. It does not execute forecasting runs and contains no observed results. The aim is to test whether an intelligent forecasting system can extend and identify the useful prediction horizon across systems with different dynamics, rather than asking whether a machine can produce an unconstrained prophecy.

## Research questions and hypotheses

**RQ1.** Does an AI or hybrid forecaster retain out-of-sample skill at longer normalized horizons than strong statistical and mechanistic baselines?

**RQ2.** Can calibration and uncertainty decomposition identify the point at which a forecast stops adding predictive information?

**RQ3.** Does forecastability transfer across domains, or is it conditional on observations, dynamics, and regime stability?

**H1:** Dense observations and a model class matched to the system will extend useful skill, with the largest expected gain in short- to medium-range weather and selected orbital targets.

**H2:** Properly calibrated ensembles will preserve decision-relevant probability quality farther into the horizon than point forecasts, even when their mean error grows.

**H3:** Observation perturbations, initial-condition perturbations, and temporal distribution shift will shorten the effective horizon through distinct signatures.

**H4:** No model will maintain exact-state superiority indefinitely; at long horizons the forecast will approach a climatological, stationary, or scenario-conditional baseline depending on target type.

## Benchmark cohorts

The benchmark uses public, versioned data and rolling-origin evaluation:

1. **Orbital and satellite state:** JPL Horizons or equivalent public ephemerides and satellite-orbit state vectors; evaluate position/velocity errors under known dynamical models and perturbed initial states. These serve as a high-predictability control, not as evidence that all future systems are predictable.
2. **Weather:** ERA5 reanalysis plus archived operational or open forecast products; target temperature, pressure, wind, precipitation, and selected severe-event indicators. GraphCast is an evidence-anchored reference model class, not an assumed winner.
3. **Climate:** CMIP6 historical/hindcast segments and scenario runs; evaluate historical or hindcast targets as forecasts, while treating future scenario output as a conditional projection and never as a realized observation.
4. **Economics:** FRED or M4-style macroeconomic series with release-vintage control where available; target inflation, industrial production, rates, and aggregate demand proxies. Use forecast vintages to prevent revision leakage.
5. **Public health:** public epidemic forecasting-hub data and surveillance time series; target incidence or hospitalization at regional and national aggregation, with reporting-delay and policy covariates. This cohort is for methodological evaluation, not clinical or individual-risk prediction.

For each target, estimate a dominant timescale `tau_d` from autocorrelation decay, seasonal period, or a preregistered system-specific characteristic time. Evaluate `h/tau_d` at `{0.25, 0.5, 1, 2, 4, 8}` when data support it. The exact calendar horizon is reported alongside the normalized horizon; normalization never erases domain meaning.

## Information-set and shift perturbations

Every origin is evaluated under an information ladder: full observations, masked observations, coarsened spatial/temporal resolution, noisy observations, and delayed observations. Initial-state perturbations are applied to dynamical cohorts. Model perturbations include alternate parameterizations and stochastic ensemble members. Temporal shifts are defined by pre-registered windows: normal holdout, event-rich holdout, sensor/release change, and known policy or forcing transition where metadata permit.

The test matrix records whether a loss increase arises from less information at initialization, model misspecification, irreducible variability, or a changed data-generating relationship. No post-hoc choice of the easiest window is permitted.

## Forecasting systems

The minimum model set is: persistence and seasonal climatology; AR/VAR or state-space statistical models; a mechanistic numerical model where the cohort supplies one; gradient-boosted lag features; a probabilistic autoregressive neural model; a transformer or graph-based model for high-dimensional fields; and a hybrid model that learns residual corrections to a mechanistic forecast. All model classes receive the same information ladder and origin splits. Compute, parameter count, inference latency, and training-data volume are recorded as covariates, not treated as scientific outcomes.

Each probabilistic model produces quantiles or samples. Calibration is estimated on training-era validation only and frozen before each test window. Conformal or ensemble recalibration is allowed as a declared component and is evaluated against an uncalibrated version. For scenario targets, outputs are labeled conditional projections and scored against compatible hindcast tasks only.

## Mathematical specification

For domain `d`, model `m`, origin `t`, target `Y`, and lead `h`, let `P_{d,m,t,h}` be the predictive distribution and `y_{t+h}` the held-out outcome. Use log score and CRPS for probabilistic targets:

\[
  LS=-\log p(y_{t+h}), \qquad
  CRPS(P,y)=\int_{-\infty}^{\infty}(F_P(z)-\mathbf{1}\{z\ge y\})^2 dz.
\]

For continuous state targets, use normalized RMSE or energy score; for binary events use Brier score, `BS=(p-y)^2`, together with reliability and discrimination. Skill relative to the strongest eligible baseline is

\[
  S_{d,m,h}=1-\frac{L_{d,m,h}}{L_{d,b^*,h}},
\]

where lower loss is better and `b^*` is selected using validation data only. Calibration error is `CE=|coverage-alpha|` aggregated over nominal intervals. Let `U` be a preregistered shift penalty based on covariate drift and calibration degradation. The atlas score is descriptive rather than a universal law:

\[
  F_{d,m,h}=S_{d,m,h}\,(1-\widetilde{CE}_{d,m,h})\,(1-U_{d,m,h}),
\]

with each component scaled on validation-defined ranges. The effective horizon is

\[
  H^*_{d,m}=\sup\{h: S_{d,m,h}>\delta,\; CE_{d,m,h}<\epsilon,\;\Delta F_{d,m,h}>0\},
\]

where `delta`, `epsilon`, and the positive baseline-improvement criterion are fixed before test evaluation. Report a confidence interval by block bootstrap over forecast origins, not by treating adjacent horizons as independent.

An information-theoretic companion estimates

\[
  I_d(h)=H(Y_{t+h})-H(Y_{t+h}\mid X_t),
\]

using a held-out density estimator or k-nearest-neighbor estimator with sensitivity analysis. `I_d(h)` is not equated with model performance: a poorly specified model can waste available information, while an apparently skillful model can be miscalibrated.

## Statistical analysis

Fit a mixed-effects model to origin-level losses:

\[
 L_{d,m,h,w}=\beta_0+\beta_1(h/\tau_d)+\beta_2D_{shift}+\beta_3D_{obs}+\beta_4M_m
 +\beta_5(h/\tau_d)D_{shift}+u_d+u_w+\varepsilon,
\]

where `w` indexes rolling windows. The primary contrast is the difference in `H*` between the HCFCA hybrid/AI model and the strongest baseline. Secondary contrasts test calibration, tail events, and compute-normalized performance. Correct multiplicity across targets with a false-discovery-rate procedure; report effect sizes and uncertainty rather than a single leaderboard rank.

Pre-register a temporal split, a leakage audit, data-vintage rules, model seeds, missingness treatment, and stopping rules. Use rolling-origin blocked bootstrap and an untouched final period. Report negative skill and failed calibration as scientifically meaningful outcomes.

## Falsification and success criteria

HCFCA is supported only if the proposed model improves held-out skill over the eligible baseline, preserves or improves calibration, and yields an effective horizon that changes predictably under information perturbation. It is falsified if these gains disappear under a leakage-safe split, if calibration is no better than a simple recalibration baseline, or if `H*` is invariant to deliberately degraded information when the target should be sensitive to it. Cross-domain transfer is rejected if a pooled score masks large target-specific failures.

## Expected outcome branches

The design allows four substantive outcomes: (A) AI extends skill and calibration in observation-rich domains but the horizon still decays; (B) AI improves point skill while ensembles or recalibration supply the real decision value; (C) gains are strong in stable orbital and medium-range weather tasks but weak under economic, public-health, or climate regime shifts; or (D) a strong baseline matches AI after leakage and compute controls. These are conditional branches, not observed results.

## Safety, governance, and reproducibility

Use public aggregate data, version-pin every source, and preserve forecast vintages. Public-health outputs remain population-level methodological evaluations; no individual risk score or medical recommendation is produced. Register model code, splits, calibration maps, and all failed runs. Human review is required for release of any operational forecast, particularly for tail events, policy-sensitive targets, or public-health communication.
