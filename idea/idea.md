# Idea Agent: Operational Scale Triangulation

## 1. Core idea

Operational Scale Triangulation (OST) is a selection-aware framework for asking whether several measurements support a common effective short-distance scale. OST does not assume that a fitted scale is the smallest physical unit of space-time. Instead, it tests whether a parameter describing a specified deformation or stochastic correlation can be recovered, covered, and predicted across independent observation channels.

The graph separates six scientific domains and an observation domain:

- `L`: effective length or time scale and its parameterization;
- `T`: transient propagation, energy-dependent delay, and polarization;
- `W`: gravitational-wave dispersion, waveform residuals, and polarizations;
- `I`: interferometric cross spectra and correlated fluctuations;
- `Q`: source, propagation, detector, and environmental nuisance variables;
- `M`: model class, priors, and mapping from scale to observable;
- `O`: selection, cadence, bandwidth, calibration, analysis windows, and censoring.

Each edge records whether a quantity is a target parameter, an observable, a nuisance, a selection variable, or a theory-to-observable mapping. A common `L` node is permitted only when the model declares how it enters each channel.

## 2. Hypotheses

**H1 (null calibration):** Under a continuum model with no short-distance signal, the complete OST analysis controls false evidence at the prespecified level.

**H2 (signal recovery):** Under a known effective deformation shared across channels, the joint model recovers the effective parameter with calibrated interval coverage and higher power than any single channel at matched total information.

**H3 (systematic separation):** Source lags, detector calibration drift, environmental correlation, and selection mismatch can produce single-channel residuals that are reduced by the typed nuisance and observation model.

**H4 (cross-channel specificity):** A candidate signal is more credible when one latent parameter predicts the sign, frequency/energy dependence, and cross-channel covariance pattern without channel-specific free corrections.

**H5 (ontology boundary):** Even a well-calibrated estimate or bound on `ell_eff` does not, without an independently specified theory, establish a literal minimum length of space-time.

## 3. Falsification rules

H1 is weakened if continuum-null records cross the primary threshold too frequently after multiplicity control. H2 is weakened if joint inference does not recover known injected parameters or has undercoverage. H3 is weakened if adding the correct nuisance operator does not suppress known confounders. H4 is weakened if channel-specific models fit as well as the shared model while producing incompatible latent scales. H5 is not an empirical hypothesis about the benchmark; it is a claim-discipline rule and is violated whenever an effective parameter is reported as ontology without a theory map.

## 4. Claim ladder

The permitted language levels are: (0) a theoretical possibility; (1) a channel-specific residual or bound under a named model; (2) a cross-channel effective-scale constraint with calibrated selection and nuisance treatment; (3) evidence for a particular effective mechanism after out-of-sample prediction; and (4) a statement about microscopic ontology only if a quantum-gravity theory supplies the mapping and independent observables support it. OST cannot move from level 2 to level 4 by statistical significance alone.

## 5. Design boundary

The first experiment is synthetic and does not calculate a real lower bound. Its purpose is to expose false positives and undercoverage before any real transient, gravitational-wave, or interferometer data are combined. Real data should be added only after source catalogs, calibration files, environmental monitors, and analysis windows are frozen and independently audited.
