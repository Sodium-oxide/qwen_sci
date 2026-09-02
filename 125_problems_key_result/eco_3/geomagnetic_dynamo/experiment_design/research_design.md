# ExperimentDesign Agent: GEODYNAMO-X

## 1. Study question and design mode

**Scientific question:** Can a coupled core-to-space data-assimilation model explain and predict Earth's time-varying magnetic field more accurately and with better-calibrated uncertainty than static extrapolation, core-only inversion, uncoupled source separation, and a numerical-dynamo prior used without joint assimilation?

**Design mode:** `DESIGN_ONLY`. The study specifies a reproducible experiment but reports no observed field reconstruction, forecast score, recovered core flow, or physical discovery.

**Primary estimand:** Difference in held-out forecast skill and calibration between GEODYNAMO-X and each baseline, evaluated on vector magnetic field, secular variation, internal-field pole location, and source-attribution error under a predeclared rolling-origin protocol.

## 2. System representation

The model is a hierarchical state-space system with four source layers:

1. **Core layer:** magnetic field coefficients and low-dimensional outer-core flow modes at the core--mantle boundary.
2. **Transfer layer:** mantle, lithosphere, and ocean conductivity operators that transform internal and external fields before observation.
3. **External layer:** ionospheric and magnetospheric current modes driven by solar-wind, auroral, tidal, and local-time covariates.
4. **Instrument layer:** observatory and satellite position, attitude, sampling, noise, calibration drift, and missingness.

The output is a field vector at a location and time, plus a decomposition into internal, external, and induced components. The north and south magnetic poles are derived from the internal-field estimate using a declared spherical-harmonic truncation and a declared uncertainty rule. Pole motion is not optimized independently from the field, preventing a circular target.

## 3. Physical equations and constraints

For the conducting outer core, the magnetic state follows an induction equation:

\begin{equation}
\frac{\partial \mathbf{B}}{\partial t}=\nabla\times(\mathbf{u}\times\mathbf{B})+\eta\nabla^2\mathbf{B},\qquad \nabla\cdot\mathbf{B}=0,
\label{eq:induction}
\end{equation}

where $\mathbf{B}$ is magnetic flux density, $\mathbf{u}$ is fluid velocity, and $\eta$ is magnetic diffusivity. The divergence constraint is enforced in the numerical representation. The first term is induction by flow; the second is diffusion. The equation does not imply that rotation alone creates the field.

The core-flow prior is written schematically as:

\begin{equation}
\rho\left(\frac{\partial \mathbf{u}}{\partial t}+\mathbf{u}\cdot\nabla\mathbf{u}+2\boldsymbol{\Omega}\times\mathbf{u}\right)=-\nabla p+\rho'\mathbf{g}+\mathbf{J}\times\mathbf{B}+\nabla\cdot\boldsymbol{\tau},
\label{eq:momentum}
\end{equation}

where $\rho$ is reference density, $\boldsymbol{\Omega}$ is planetary rotation, $p$ is pressure, $\rho'\mathbf{g}$ is buoyancy, $\mathbf{J}$ is electric current density, and $\boldsymbol{\tau}$ collects viscous and unresolved stresses. In practice, the experiment uses a reduced basis or surrogate of this equation, with closure terms sampled from an ensemble rather than pretending that all turbulent scales are resolved.

The latent state is advanced as:

\begin{equation}
\mathbf{x}_{t+1}=\mathcal{F}_{\theta}(\mathbf{x}_t,\mathbf{q}_t,\mathbf{w}_t)+\boldsymbol{\epsilon}_t,
\label{eq:state}
\end{equation}

where $\mathbf{x}_t$ contains core, transfer, and external states, $\mathbf{q}_t$ contains forcing and boundary covariates, $\mathcal{F}_{\theta}$ is the constrained transition model, $\mathbf{w}_t$ is a learned residual restricted by the physical constraints, and $\boldsymbol{\epsilon}_t$ is process uncertainty. The residual may correct unresolved closure error, but it cannot add magnetic monopoles or relabel external variation as core flow without a source-likelihood penalty.

The measurement equation is:

\begin{equation}
\mathbf{y}_{k,t}=\mathcal{H}_{k,t}\left(\mathbf{x}_t\right)+\mathbf{b}_{k,t}+\boldsymbol{\nu}_{k,t},
\label{eq:observation}
\end{equation}

where $\mathbf{y}_{k,t}$ is the observation from sensor $k$, $\mathcal{H}_{k,t}$ maps source layers to the sensor geometry, $\mathbf{b}_{k,t}$ is calibration bias, and $\boldsymbol{\nu}_{k,t}$ is measurement noise. Ground and satellite observations share the latent state but have distinct operators. External forcing enters $\mathcal{H}$ and the external transition rather than being discarded during preprocessing.

The total predicted field is decomposed as:

\begin{equation}
\mathbf{B}_{\mathrm{obs}}=\mathbf{B}_{\mathrm{core}}+\mathbf{B}_{\mathrm{ext}}+\mathbf{B}_{\mathrm{ind}}+\mathbf{B}_{\mathrm{lith}}+\boldsymbol{\delta}_{\mathrm{inst}},
\label{eq:decomposition}
\end{equation}

where the terms represent core, external, induced, lithospheric, and instrument residual contributions. This decomposition is a modeling contract: it does not assert that every term is separately identifiable from every observation.

## 4. Data and preprocessing plan

The proposed data inventory contains geomagnetic observatory vector series, satellite magnetic measurements with position and attitude metadata, solar-wind and geomagnetic activity covariates, global reference-field coefficients and secular-variation coefficients, and selected paleomagnetic records for long-horizon consistency checks. Every record receives a timestamp standard, coordinate frame, calibration flag, source label, uncertainty, and availability interval.

Preprocessing is frozen before model fitting. It includes coordinate transformation, instrument calibration, quality flags, common temporal bins, removal of known nonphysical spikes, and a documented treatment of missingness. Storm and quiet intervals are labeled using an external forcing rule fixed before the forecast. The model is not allowed to use future external covariates when producing a historical held-out forecast. Paleomagnetic records are not mixed into the instrumental target without a separate observation model for geological smoothing and recording bias.

The data are partitioned by time using rolling origins. Each origin has a training window, an assimilation window, and a forecast horizon. Spatial holdouts reserve observatories or satellite tracks to test geographic generalization. Event holdouts reserve selected disturbance intervals to test whether external-current states prevent false attribution. The split is fixed before comparing models.

## 5. Baselines and treatments

The primary treatment is GEODYNAMO-X with physical transition constraints, explicit source states, joint ground/satellite assimilation, and uncertainty propagation. The baselines are:

- **Static reference:** fixed main-field model with no secular variation.
- **Linear secular variation:** extrapolates field coefficients using a local linear trend.
- **Core-only inversion:** infers core flow after external corrections and has no latent external current state.
- **Uncoupled decomposition:** independently fits internal and external regressors.
- **Dynamo-prior-only:** samples numerical-dynamo trajectories but performs no joint data assimilation.
- **Oracle-source control:** uses simulated true source labels in synthetic twins to estimate an information upper bound; it is not a deployable baseline.

All learnable models receive the same training windows, forecast horizons, sensor metadata, hyperparameter budget, and early-stopping rule. A model with a lower in-sample error but a larger parameter budget is not considered superior without an out-of-sample gain.

## 6. Synthetic-twin identifiability experiment

Before touching historical data, a high-fidelity numerical-dynamo ensemble generates latent core fields and flows. A transfer layer adds mantle and lithospheric conductivity effects. An external-current generator creates quiet, storm, and missing-forcing regimes. Ground observatory and satellite operators then sample the resulting field with realistic geometry, noise, gaps, and calibration shifts.

The synthetic truth is hidden from the inference model. We measure recovery of internal field coefficients, core-flow modes, external-current amplitude, pole location, and uncertainty coverage. The experiment varies the number and geometry of observatories, satellite track coverage, external-forcing availability, harmonic truncation, and model discrepancy. Identifiability is accepted only for quantities whose posterior error shrinks with additional informative data and whose coverage remains calibrated.

The synthetic twin has a deliberately adversarial case: a rapid external disturbance resembles a regional core secular-variation pulse. The coupled model must assign uncertainty or external probability to the pulse. A model that explains every rapid residual by accelerating the core fails the source-attribution test even if its total field error is small.

## 7. Historical reconstruction and forecast experiment

After the synthetic-twin gate, the same frozen model classes are fit to historical-like records. The first task is retrospective reconstruction, evaluated only on held-out observations and held-out sensor geometry. The second task is rolling-origin forecasting at short, intermediate, and decadal horizons. The forecast target is the vector field and its time derivative; pole location is a derived target with an uncertainty ellipse.

Primary metrics are vector-field RMSE, angular error, secular-variation RMSE, pole-location error, negative log predictive density, interval coverage, and source-attribution error in synthetic cases. Secondary metrics include forecast degradation under missing observatories, calibration drift, storm contamination, and changed satellite coverage. Skill scores are reported relative to the static reference and with uncertainty intervals from repeated time blocks.

The key comparison is not whether a complex model fits the past. It is whether physical coupling changes the held-out forecast and attribution in the predicted direction. The analysis reports where the gain occurs: quiet-time secular variation, storm intervals, spatial holdouts, or a particular forecast horizon. A global average can hide a failure in exactly the intervals that matter for navigation and space-weather risk.

## 8. Ablations and sensitivity

The following ablations isolate the mechanism:

1. Remove the rotation/Coriolis prior from the core-flow transition.
2. Remove compositional buoyancy and inner-core-growth covariates.
3. Replace heterogeneous core--mantle boundary heat flow with a uniform boundary.
4. Remove explicit ionospheric and magnetospheric states.
5. Replace the conductivity transfer layer with an identity operator.
6. Remove divergence-free and energy-accounting constraints from the learned residual.
7. Reduce satellite or observatory coverage.
8. Remove uncertainty propagation and evaluate only point forecasts.

Sensitivity analysis varies magnetic diffusivity, flow-mode rank, harmonic degree, forcing lag, observation noise, external-current correlation, and forecast horizon. Structural sensitivity compares at least two transition families and two external-current parameterizations. If a conclusion changes sign under a plausible structural choice, it is reported as model-dependent rather than averaged into a single number.

## 9. Falsification and interpretation rules

GEODYNAMO-X is supported only if it passes the synthetic-twin recovery gate and improves held-out calibrated forecast skill over the strongest baseline under equal data and compute accounting. It is falsified if it cannot recover source labels in controlled twins, if it attributes the adversarial external pulse to core acceleration, if its uncertainty intervals are systematically overconfident, or if its held-out gain disappears when the static and linear baselines receive the same forecast horizon.

Four outcome classes are predeclared:

- **Coupled-source gain:** full coupling improves field and attribution skill with calibrated uncertainty.
- **Physical-prior gain:** physics improves extrapolation but not reconstruction, indicating value mainly at longer horizons.
- **Separation-only gain:** explicit external states help, while core dynamics add no held-out benefit.
- **No-coupling gain:** simpler models match or beat the full model; the added latent physics is not justified for the tested domain.

None of these outcomes proves that the field will reverse or that a pole will follow a particular future path. They test whether a coupled model is a better explanatory and predictive instrument.

## 10. Reproducibility and safety of inference

The experiment stores configuration, source identifiers, coordinate conventions, time splits, parameter priors, model versions, random seeds, checkpoints, and evaluation scripts. The final record retains the exact observation masks used in each forecast. No result is overwritten by a later re-fit without a new run identifier. An audit table connects each claim in the Author report to a survey source, design clause, or future result field.

The model is not a replacement for operational geomagnetic warnings. Any future deployment must compare its alerts against established geomagnetic services, retain human review, and expose uncertainty and source attribution. The present design ends at a reproducible research plan and intentionally leaves `expected_results` and `observed_results` empty.
