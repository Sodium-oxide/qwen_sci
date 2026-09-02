# ExperimentDesign Agent: ORIGIN-OF-SPACETIME-INFERENCE-BENCHMARK

## 1. Status and research aim

This is a preregistration-ready DESIGN_ONLY protocol. Its aim is to test whether
parameterized early-universe scenario classes make observable predictions that improve on
a stated baseline under transparent assumptions. It does not test an event at a spatial
location, create a physical time before spacetime, or infer creation from nothing.

## 2. Scenario classes and parameter ledger

The minimum comparison includes:

* **S0:** hot Big Bang late-time baseline with a phenomenological primordial spectrum;
* **S1:** parameterized slow-roll or effective inflationary scenarios;
* **S2:** parameterized bounce or ekpyrotic scenarios with a declared matching surface;
* **S3:** quantum-initial-state or no-boundary/tunneling-inspired parametrizations only
  when they give an explicit perturbation-state and background prediction;
* **S4:** curvature or nontrivial-topology extensions, treated separately from origin
  mechanism claims.

Every scenario submits a parameter ledger: background variables, primordial scalar and
tensor parameters, sound speed or matching parameters, reheating or transition variables,
late-time nuisance parameters, prior ranges, theoretical validity range, and fixed
assumptions. A scenario that cannot provide a forward model and parameter ledger is
reported as underdetermined rather than compared numerically.

## 3. Data and held-out structure

The design uses public or licensed aggregates from CMB temperature and polarization,
lensing, baryon acoustic oscillations, distance measures, large-scale structure, and
primordial-abundance consistency. The exact release, masks, likelihood code, calibration,
and foreground model are versioned. Development data choose numerical tolerances and
validate the forward implementation. Held-out tests use one or more predeclared channels:

* polarization or lensing excluded from primary parameter fitting;
* frequency or detector split withheld from feature selection;
* multipole window withheld from anomaly or feature tuning;
* low-redshift distance data withheld from early-universe selection; and
* synthetic sky realizations with known injected features.

## 4. Forward model and likelihood protocol

For each parameter vector, solve the background and perturbation equations, pass the
primordial spectrum through a validated transfer calculation, convolve with an
instrumental and foreground model, and evaluate the likelihood. Use the same late-time
parameterization and nuisance model where physically compatible. Test the numerical
forward model first on synthetic data with known parameters.

The baseline and alternative scenarios receive identical masks, likelihood choices,
calibration priors, covariance treatment, and computational tolerance. If a scenario
requires different physics or a different likelihood, the difference is declared and a
matched sensitivity analysis is mandatory.

## 5. Primary observables and metrics

Primary observables are the CMB temperature and polarization angular spectra, CMB lensing,
primordial scalar-spectrum features, tensor-to-scalar ratio constraints, spatial
curvature, and background-expansion consistency. Secondary observables include
non-Gaussianity, topology signatures, low-multipole features, and spectral distortions
when a scenario supplies a prediction.

Report likelihood, posterior predictive discrepancy, Bayesian evidence or a stated
approximation, information criteria, parameter degeneracy, prior sensitivity, predictive
coverage on held-out data, numerical convergence, and runtime. Do not use a single
"origin score." A more complex model must demonstrate an improvement on declared
held-out observables, not only a better maximum likelihood.

## 6. No-center geometry simulation

Generate synthetic catalogs in flat, open, and closed FLRW backgrounds. Place virtual
observers at many comoving coordinates, propagate light cones, and estimate recession
relations, horizons, and angular distances. Check that the inferred local Hubble relation
and horizon structure are equivalent up to statistical and curvature effects. A distinct
center claim is tested only by adding an explicit inhomogeneous model with its own
predictions; a coordinate origin is never treated as data.

## 7. Systematic and robustness checks

* vary foreground and mask choices within predeclared ranges;
* vary prior families and widths, reporting evidence sensitivity;
* use multiple Boltzmann/transfer implementations or independently validated modes;
* change multipole windows and detector/frequency splits without retuning features;
* inject synthetic oscillations, cutoffs, curvature, or topology signatures to test
  detection power and false-positive control;
* inspect posterior predictive residuals and simulation-based calibration;
* retain failed chains, numerical instabilities, invalid points, and nonconverged runs.

## 8. Statistical analysis

For scenario class $S_i$ and data $D$, sample the posterior over its parameter ledger
and compute evidence or a transparent approximation. Primary contrasts are S1 versus S0,
S2 versus S0, S3 versus S0 when forward predictions exist, and S4 versus a curvature
or topology baseline. Report parameter-shift diagnostics across data splits. Bayes-factor
or information-criterion conclusions are labeled conditional on the specified priors and
likelihoods. Feature claims must use predeclared search ranges and look-elsewhere control.

## 9. Decision rules

Support for a scenario's observational utility requires posterior-predictive improvement
on held-out observables plus robustness to foreground, prior, and pipeline changes.
Support for a distinct early-universe mechanism requires a discriminating signature that
the baseline and other alternatives fail to reproduce under matched nuisance treatment.
Support for no-center geometry is a consequence of the tested homogeneous model, not a
measurement of a unique center. No decision rule supports a statement about an observed
time before spacetime or an absolute metaphysical beginning.

## 10. Reproducibility and interpretation safety

Release scenario definitions, parameter ledgers, prior files, forward-model versions,
data-release identifiers, masks, likelihood wrappers, random seeds, sampler settings,
convergence diagnostics, posterior samples where permitted, synthetic injections, and
event logs. Preserve data licenses and do not redistribute restricted maps. The final
report explicitly distinguishes observed data, inferred parameters, extrapolated epochs,
and unobserved theoretical completions.
