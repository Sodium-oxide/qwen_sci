# ExperimentDesign Agent: CURA-Turb Computational Research Design

## Scope and execution policy

This is a `DESIGN_ONLY` computational/statistical research protocol. It does not run a DNS, acquire laboratory velocity fields, control an engineering system, issue computational jobs, or claim new measurements. It specifies how a qualified team could evaluate a typed turbulence-invariance claim using public, synthetic, or authorized data.

## Research brief

**Question.** Can a claim-type and regime-resolved audit identify when a turbulence statistic is an exact conditional relation, a conditionally universal regularity, intermittency-modified, regime dependent, invalidly represented, or inconclusive?

**Unit of analysis.** `claim dossier x flow-regime card x scale-window card x estimator card x evidence card`.

**Primary design claim.** No statistic receives a universal label merely because a fitted slope or normalized PDF appears similar. A favorable label requires assumptions, compatible data representation, stability under predeclared estimator choices, and an eligible transfer bridge.

## Regime cards

| Card | Regime | Required fields | Prohibited shortcut |
|---|---|---|---|
| `F0` | Analytic symmetry/balance reference | equation form, coordinate transformation, forcing/boundary assumptions | Calling an equation symmetry a measured universal statistic. |
| `F1` | Forced periodic homogeneous isotropic turbulence | stationarity, homogeneity/isotropy diagnostics, dissipation route, scale separation | Applying the card to wall or shear data. |
| `F2` | Decaying nominally isotropic turbulence | decay protocol, time origin, nonstationarity marker, scale interval | Treating transient statistics as stationary. |
| `F3` | Wall-bounded or channel turbulence | wall distance, shear/friction scaling, sampling geometry, inhomogeneity markers | Pooling wall and core data as one isotropic ensemble. |
| `F4` | Rotating or stratified turbulence | Rossby/Froude context, direction-resolved statistics, anisotropy marker | Using isotropic exponents without directional tests. |
| `F5` | Sheared/inhomogeneous/engineering flow | production, geometry, forcing, measurement volume, transfer bridge | Inferring HIT universality from a local fit. |
| `F6` | Experimental or observational data representation | instrument/filter, resolution/noise, sampling cadence, reconstruction method | Comparing unharmonized measurements to a DNS statistic. |

## Invariance dossier and metrics

Each dossier declares a claim type: `EQUATION_SYMMETRY`, `EXACT_CONDITIONAL_LAW`, `CONDITIONAL_SIMILARITY`, or `EMPIRICAL_CROSS_FLOW_REGULARITY`. It declares a statistic, increment convention, scale window, estimator, uncertainty method, and compatible regime cards.

Planned metrics include the exact-law residual, a structure-function exponent interval, normalized PDF distance, anisotropy/inhomogeneity indicator, a time-irreversibility diagnostic, and status stability. The protocol stores intervals and sensitivity switches rather than a single fitted exponent.

## Validation ladder

1. **Representation check.** Verify coordinate units, velocity-increment definition, filtering, sampling, and derived-field provenance.
2. **Assumption check.** Test or document stationarity, homogeneity, isotropy, incompressibility, and scale-range eligibility for the specific claim.
3. **Estimator check.** Compare predeclared scale windows and at least two compatible estimator formulations where possible; quantify fit and sampling stability.
4. **Regime stress test.** Compare only designated compatible cards. A directional, wall-distance, or rotation/stratification control must be reported when it is part of the regime.
5. **Transfer audit.** Require a documented bridge before a result moves from an idealized card to an engineering or measured card.

## Conditional labels

| Label | Authorized meaning |
|---|---|
| `EXACT_RELATION_ELIGIBLE` | The data/model scope supports testing a stated exact conditional relation; no numerical agreement is implied. |
| `CONDITIONALLY_UNIVERSAL` | A predeclared statistic is stable across eligible matched cards and uncertainty intervals; scope remains explicit. |
| `INTERMITTENCY_MODIFIED` | High-order or distributional evidence departs from the simplest similarity route under the declared test. |
| `REGIME_DEPENDENT` | Direction, wall, shear, rotation, stratification, forcing, or nonstationarity changes the claim. |
| `REPRESENTATION_INVALID` | Data definition, units, filtering, or provenance fails the dossier contract. |
| `INCONCLUSIVE` | Scale separation, sample support, estimator stability, or transfer evidence is insufficient. |
| `MODEL_INVALID` | The stated equation, assumptions, regime, or observation/projection status is incompatible. |

## Human review

Implementation requires turbulence-theory, numerical-analysis, statistics/uncertainty-quantification, and experimental-metrology review. Engineering extrapolation additionally needs a domain-specific flow expert. This protocol does not prescribe operating parameters or replace validated flow-specific models.
