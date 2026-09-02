# Survey Agent: Conditional Statistical Invariance of Turbulence

**Topic.** What is the ultimate statistical invariance of turbulence?

**Reframed scientific question.** Which turbulence statistics or relations remain invariant, or conditionally universal, across flows after their symmetry class, forcing, boundaries, dimension, rotation/stratification, Reynolds-number range, inertial-range interval, and estimator uncertainty are declared?

## Evidence-bounded answer

There is no single demonstrated *ultimate statistical invariant* shared by every turbulent flow. A more useful hierarchy separates four claims that are often conflated.

1. **Governing-equation symmetries.** Incompressible Navier--Stokes dynamics has translation, rotation, and Galilean symmetries under its stated domain, forcing, and boundary transformations. These are exact structural constraints, but they do not imply that every measured statistic is identical across flows.
2. **Exact conditional balance relations.** The Kolmogorov four-fifths relation connects a third-order longitudinal velocity-increment moment to mean dissipation in a three-dimensional homogeneous, isotropic, stationary inertial-range setting. It is an exceptionally strong benchmark, but its assumptions are part of the statement.
3. **Conditional small-scale universality.** Kolmogorov-style similarity proposes that suitably normalized small-scale statistics become insensitive to large-scale details at sufficient scale separation. This remains an empirical/theoretical program with finite-Reynolds-number, anisotropy, and inhomogeneity qualifications.
4. **Intermittency and regime dependence.** High-order structure functions show anomalous scaling relative to the simplest K41 prediction. Wall effects, rotation, stratification, shear, compressibility, active scalars, multiphase coupling, and measurement representation can alter both scaling windows and apparent exponent estimates.

The publisher-verified Sreenivasan--Antonia review explicitly surveys classical universality, intermittency, refined similarity, anomalous scaling exponents, and homogeneous-turbulence DNS. This supports the central conclusion: a strong answer is not one exponent or probability-density collapse, but a regime-conditioned invariance claim with a testable validity interval.

## Source registry and admissible claims

| Key | Evidence role | Status | Admissible use |
|---|---|---|---|
| `sreenivasan_antonia_1997` | Small-scale universality/intermittency review | Publisher page verified | State the review scope and use it to delimit classical universality from intermittency. |
| `kolmogorov_1941` | K41 and four-fifths relation origin | Bibliographic source; publisher review pending | Define the stated homogeneous/isotropic inertial-range relation. |
| `kolmogorov_1962` | Refined similarity/intermittency context | Bibliographic source; publisher review pending | Motivate anomalous-scaling checks. |
| `frisch_1995` | Multifractal and cascade background | Book metadata review pending | Define terminology only. |
| `eyink_sreenivasan_2006` | Onsager, dissipation anomaly, cascade theory | Bibliographic source; publisher review pending | Motivate regularity and flux boundary. |
| `vela_martin_jimenez_2021` | Statistical irreversibility/cascade context | OpenAlex discovery record | Motivate a time-asymmetry diagnostic only. |
| `sen_2012` | Rotation/anisotropy nonuniversality example | OpenAlex discovery record | Require a regime-card separation for rotating flows. |
| `andres_banerjee_2019` | Exact-relation formulation context | OpenAlex discovery record | Motivate an exact-law residual as a diagnostic, not a universal scalar. |

## Accepted research gaps

| Gap ID | Gap | Consequence |
|---|---|---|
| `GAP-LAW-001` | Exact symmetry, exact balance law, empirical collapse, and asymptotic universality are frequently reported as the same kind of invariance. | Require claim-type classification before comparison. |
| `GAP-REGIME-002` | Homogeneous isotropic turbulence evidence is too readily transferred to wall-bounded, rotating, stratified, sheared, decaying, or measured flows. | Create explicit regime cards and prohibit unrestricted pooling. |
| `GAP-ESTIMATOR-003` | Finite resolution, finite Reynolds number, scale-window selection, sampling dependence, and fitting choices can create apparent universal exponents. | Register estimators, intervals, uncertainty, and falsifiers. |
| `GAP-TRANSFER-004` | A pointwise or low-order agreement does not show distributional, high-order, or cross-flow invariance. | Use a vector of law residuals, exponent intervals, PDF distances, and anisotropy markers. |

## Handoff boundary

The Idea Agent must link every direction to the accepted gaps and preserve `DESIGN_ONLY`. A valid direction must declare the statistic, physical regime, symmetry assumptions, scaling interval, baseline/comparator, uncertainty route, and failure criterion. It may not claim that a new DNS, experiment, or engineering flow has been run.
