# Idea Agent: Horizon-Conditioned Forecastability and Calibration Atlas

## Input and problem reconstruction

The Survey shows that “predict the future” is a family of tasks. The Idea Agent therefore searches for a direction that keeps the physical predictability limit visible while allowing advanced models to improve practical forecasting. The candidate must connect lead time, information quality, uncertainty decomposition, calibration, and distribution shift. It must also work for systems with very different characteristic timescales.

## Candidate portfolio

### HCFCA-001 — Horizon-Conditioned Forecastability and Calibration Atlas

Construct a common evaluation layer over orbital state, weather, climate hindcast, economic, and public-health time series. For each domain, define the target and its intrinsic timescale, generate probabilistic forecasts at normalized horizons, and estimate the effective forecast horizon at which an intelligent model ceases to add reliable information over the strongest baseline. Use perturbation experiments to separate initial-condition, observation, model, and shift uncertainty. The result is a map of where AI extends useful prediction and where it only makes uncertainty computation faster.

### CHAOS-ONLY — Local divergence and predictability horizon

Use Lyapunov-like local divergence, surrogate systems, and error-growth curves to estimate a physical horizon. This gives a mechanistic anchor, but cannot evaluate calibration, intervention feedback, or the value of probabilistic predictions in non-dynamical domains. Retain as a component of HCFCA.

### SCALE-ONLY — Larger models and more computation

Compare parameter count, inference cost, and accuracy. This is a useful engineering ablation but mistakes computational capacity for information about the future and does not explain horizon collapse. Retain as a resource-control component.

### SCENARIO-ONLY — Conditional futures under explicit forcings

Evaluate climate and policy scenarios without claiming exact events. This is essential for long-range planning but is not a universal forecast and does not provide a common skill metric across observed time series. Retain as a typed output branch.

### ORACLE-LLM — General intelligent machine as future oracle

Use a large language model to predict arbitrary future events from text. Reject: no stable target, high leakage risk, weak physical interpretation, and no principled distinction between generated narrative and calibrated probability.

## Primary direction

The selected direction is **Horizon-Conditioned Forecastability and Calibration Atlas (HCFCA)**. Its central thesis is:

> An advanced intelligent machine can extend the usable horizon of some forecast tasks, especially when it extracts structure from dense observations, but it cannot remove a horizon at which unresolved state, model error, distribution shift, and irreducible variability make exact prediction uninformative. The scientifically meaningful output is a calibrated probability distribution and a domain-specific effective horizon, not a universal prophecy.

## Falsifiable conditions

The direction should be rejected or materially revised if: (1) normalized horizon fails to align error-growth curves even within well-observed dynamical domains; (2) AI models show no held-out skill gain over strong statistical or mechanistic baselines; (3) calibration deteriorates under ordinary temporal shift while a simple recalibration baseline remains stable; (4) uncertainty perturbations do not change the estimated horizon, suggesting the metric is merely model-specific; or (5) a single aggregate score reverses conclusions across targets and hides target-specific failure.

## Selection audit

HCFCA scores high on evidence alignment because it directly operationalizes Lorenzian error growth, ECMWF ensemble uncertainty, IPCC conditional projections, proper scoring rules, and GraphCast’s bounded AI advance. It has high falsifiability because the effective horizon, calibration, baseline improvement, and shift penalty are pre-specified. It is ambitious without claiming omniscience: it asks whether an intelligent model can identify the boundary of its own useful prediction.
