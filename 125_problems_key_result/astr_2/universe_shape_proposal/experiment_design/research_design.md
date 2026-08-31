# ExperimentDesign Agent — CurvLedger Study Design

## Design boundary

`execution_policy.mode = DESIGN_ONLY`  
`observed_results = []`

This artifact specifies a reproducible computational analysis plan. It does **not** download data, execute Boltzmann codes, fit a likelihood, claim a posterior, or assert a new curvature result. All public-data use must respect the release licence, collaboration likelihood documentation, and version-specific nuisance prescriptions.

## Research brief

**Question.** Under which declared cosmological models, likelihood configurations, and probe combinations is a nonzero spatial-curvature preference replicated, compatible with other observations, or better explained by a non-curvature alternative?

**Core hypothesis.** A curvature preference is scientifically meaningful only if it remains stable under specified nuisance/model alternatives and is supported by compatible, non-duplicated evidence channels.

**Central claim to test.** `Omega_K` is a model parameter inferred through a joint forward model; it is not a detector readout, and it cannot alone identify global topology.

## Model and variable specification

| Category | Variables | Operationalization |
|---|---|---|
| Primary parameter | `Omega_K` | Curvature density parameter with declared sign convention `Omega_K=-k c^2/(a_0 H_0)^2`; closed FLRW corresponds to `Omega_K<0`. |
| Baseline parameters | `omega_b`, `omega_c`, `theta_s`, `tau`, `A_s`, `n_s` | Six-parameter LCDM block and documented priors. |
| Curvature alternatives | `A_L`, foreground/calibration parameters, `w_0,w_a`, neutrino sector, primordial-spectrum flexibility | Activated only in predeclared model cards; not silently marginalized away. |
| Channel observables | CMB TT/TE/EE spectra, CMB lensing reconstruction, BAO `D_M/r_d` and `H r_d`, SN distance moduli, growth/lensing summaries | Kept as separate likelihood cards until covariance/overlap is established. |
| Nuisance and controls | masks, multipole cuts, beams, foreground templates, shear/photo-z calibration, BAO reconstruction, covariance release | Versioned exactly with each analysis card. |
| Decision outcomes | five CurvLedger labels | Produced by decision rules below, not free-form narrative. |

## Template routing

This is a `computational_digital` study template. The experimental unit is a **versioned likelihood/model card**, not an individual galaxy, CMB pixel, or simulation draw. This choice prevents pseudo-replication: several summary products derived from the same maps cannot be treated as independent experiments.

## Evidence bundle and data-release cards

| Card | Intended public source | Role | Independence assessment |
|---|---|---|---|
| C1 | Planck 2018 primary TT/TE/EE + low-ell likelihood | reproduces the reported curvature-direction sensitivity | Baseline CMB card; do not multiply with overlapping compressed Planck summaries. |
| C2 | Planck CMB lensing reconstruction | tests peak-smoothing interpretation against reconstruction | Partially shared sky/calibration with C1; covariance and shared nuisance review required. |
| C3 | ACT DR6 spectra and lensing products | independent high-resolution CMB replication test | Different instrument and likelihood; sky overlap must be explicitly handled. |
| C4 | SPT-3G lensing | additional CMB-lensing cross-check | Complementary; lensing tracer/covariance links must be declared. |
| C5 | eBOSS/DESI BAO | late-time distance geometry and CMB degeneracy breaking | Treat release versions separately; no duplicate BAO bins. |
| C6 | Supernovae/weak-lensing optional validation | external distance/growth check | Include only with calibration and selection nuisance model. |

## Analysis protocol

1. **Freeze cards and priors.** Store release identifiers, likelihood commit/version, parameter convention, prior bounds, masks, cuts, calibration treatment, and overlap decision before sampling.
2. **Run model ladder.** Evaluate the same card set under: `M0` flat LCDM; `M1` non-flat LCDM; `M2` M1 plus free `A_L`; `M3` M1 plus selected foreground/calibration robustness variants; and `M4` M1 plus a declared late-time expansion extension. Topology is not fitted by this ladder.
3. **Channel-local inference.** Produce posterior and posterior-predictive summaries separately for C1–C6. Do not claim agreement from similar central values alone.
4. **Compatibility audit.** For every proposed joint combination, record shared sky, shared calibration, shared external priors, and covariance evidence. A combination fails closed if the correlation treatment is unknown.
5. **Joint inference.** Combine only cards satisfying the audit. Report `Omega_K` posterior, tension metrics, and predictive residuals within each model card.
6. **Alternative challenge.** Test whether changing `A_L`, foreground/calibration treatment, primordial flexibility, or expansion history removes the curvature-specific residual without worsening independent-channel fit.
7. **Topology guard.** Any topology statement requires a separately registered topology likelihood (e.g., matched-circle/compact-topology analysis); curvature posteriors cannot populate that field.

## Formal decision rules

For a model card `m`, let `D_c` be a channel dataset, `theta_m` its parameter vector, and `eta_c` its nuisance parameters. The proposed joint posterior is

`p(theta_m,{eta_c}|D,m) proportional to p(theta_m|m) product_c L_c(D_c|theta_m,eta_c,m) p(eta_c|m)`,

only after the independence audit declares the factorization admissible. If overlap makes direct multiplication invalid, the design requires a joint covariance or a non-combined comparison.

The transverse distance map used by the geometry card is

`D_M(z) = (c/H_0)/sqrt(|Omega_K|) S_K[sqrt(|Omega_K|) integral_0^z dz'/E(z')]`,

where `S_K` is `sinh`, identity, or `sin` according to the curvature convention and `E(z)=H(z)/H_0`. The formula is a forward-model definition, not a standalone measurement of topology.

| Output label | Required evidence | Disqualifying condition |
|---|---|---|
| `CURVATURE_CONSISTENT_WITH_ZERO` | Predeclared model/data posterior includes zero with no coherent residual demanding curvature. | A hidden prior or model restriction excludes the relevant comparison. |
| `CLOSED_PREFERENCE_CHANNEL_LOCAL` | One card/model combination prefers `Omega_K<0`. | Any claim of global curvature confirmation. |
| `CLOSED_PREFERENCE_CROSS_VALIDATED` | Compatible independent channels support an overlapping closed region and alternatives fail specified predictive tests. | Unknown overlap/covariance, or only one instrument family drives the result. |
| `MODEL_OR_LIKELIHOOD_INCONSISTENT` | No shared region predicts all included cards under a declared model. | Treating tension as evidence for curvature alone. |
| `TOPOLOGY_UNRESOLVED` | No registered topology-specific observable has passed its own test. | Inferring topology from `Omega_K` alone. |

## Robustness, ablations, and false-positive controls

- **Prior ablation:** repeat each non-flat analysis with scientifically defensible alternative `Omega_K` prior ranges and parameterizations; report prior sensitivity rather than averaging it away.
- **Lensing ablation:** compare peak-smoothing-driven constraints with lensing-reconstruction constraints; flag evidence that requires an anomalous `A_L`.
- **Instrument ablation:** withhold Planck, ACT, or SPT cards one at a time and test whether a status changes category.
- **Low-redshift ablation:** withhold BAO release groups and SN sets separately to expose calibration or overlap dependence.
- **Synthetic injection:** use mock likelihood summaries with known flat, closed, and nuisance-shift generators to estimate false `CLOSED_PREFERENCE_CROSS_VALIDATED` classifications.
- **Posterior-predictive checks:** generate observable-level residual diagnostics rather than comparing only parameter credible intervals.

## Reproducibility and human review

Required outputs are a data manifest, model/prior cards, likelihood versions, covariance decisions, sampler configuration, random seeds, convergence diagnostics, blinded-analysis record where supplied, and a decision ledger. Human expert review is required for CMB likelihood validity, covariance treatment, foreground models, data-use terms, and interpretation of any tension. No design field authorizes new observation, telescope operation, or publication of a discovery claim.
