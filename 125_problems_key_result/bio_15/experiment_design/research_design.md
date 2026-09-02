# ExperimentDesign: Component-Resolved Population Peak Persistence Atlas

## Design status

This is a computational-digital research design. Its execution policy is DESIGN_ONLY. No demographic model has been fitted, no future trajectory has been generated, and no model score or peak probability is reported here.

## Objective and estimand

The objective is to estimate, conditional on a pre-registered set of demographic and optional climate-disruption assumptions, the posterior probability that global population growth is positive at the terminal year 2100. A complementary estimand is the posterior distribution of the first year at which global population reaches a maximum before the horizon. These are conditional model outputs, not statements about an inevitable future.

The basic accounting model is cohort component. Let P(c,a,s,t) be the population in country c, age a, sex s, at year t; S be survival; M be net migration; and B be births allocated to the youngest cohort. For non-youngest ages, the update is P(c,a+1,s,t+1) = P(c,a,s,t) S(c,a,s,t) + M(c,a,s,t). The youngest cohort is generated from age-specific fertility and births. Every compared model must use the same accounting update, age bins, sex convention, geography reconciliation, and temporal grid.

## Input preparation

The core input will be an archived WPP 2024 release containing country-age-sex population, fertility, mortality, and migration series where available. Before any model fit, a release manifest will record source URL, retrieval time, checksums, country mappings, age bins, units, and exclusions. The analysis will not silently substitute a newer data vintage after the historic cutoff has been chosen.

Climate-disruption features are deliberately secondary. An execution protocol may propose heat anomaly, drought, flood, cyclone, wildfire, disaster-displacement, or food-system stress indicators only when their provenance, spatial correspondence, missingness, temporal lag, and legal use are approved. A feature is not admitted because it has a plausible story. It must have an explicit transformation, lag window, country coverage threshold, and causal-status label of predictive-only.

## Model families

The deterministic baseline propagates common central component paths. The demographic probabilistic model generates coherent draws for fertility, survival, and migration and propagates each draw through the cohort accounting system. The climate-modifier model adds the approved feature set to component equations while retaining a no-climate version with identical priors, historical cutoffs, and output draws.

Each component is partially pooled across countries to avoid unstable estimates where data are sparse, but country-level residual variation remains. Pre-specified country or region effects may be moderated by baseline age structure and data completeness. No result should be presented as a country-specific effect unless it survives the hierarchical uncertainty calculation and the holdout assessment.

## Holdout validation

The design uses rolling-origin evaluation. At each origin, all observations after the cutoff are withheld, models are fitted to the same earlier data, and forecasts are compared to the withheld demographic components and populations. At least three non-overlapping historical horizons should be used when data coverage permits. Posterior chains, random seeds, and exact cutoffs must be registered before scoring.

The primary forecast metrics are log predictive density, continuous ranked probability score, interval coverage, interval width, and bias by country, age, sex, and aggregation level. Good mean error is insufficient if uncertainty bands are systematically too narrow or too broad. The model is also checked for coherence: the sum of country trajectories must equal the independently produced regional and global aggregation within numerical tolerance.

## Component attribution and ablations

After calibration, the design will compare component-swap draws. Starting from an aligned posterior draw, one component trajectory is exchanged between an earlier-peak and a persistence draw while all other random components are retained. The resulting change in first-peak year and terminal global-growth indicator is a conditional attribution diagnostic, not proof that the component is a manipulable cause in the world.

The climate feature set is evaluated only through a planned ablation: demographic-components-only versus the identical specification plus climate features. It is retained only if primary held-out scores and calibration improve by a pre-registered practical margin, performance is stable across cutoffs, and the finding does not arise solely from a few high-leverage countries or missingness patterns. Otherwise, the no-climate result is the primary result.

## Decision branches

The study has three possible decision branches. If the calibrated posterior probability of positive global growth in 2100 clears its pre-registered threshold and remains stable under sensitivity analysis, the report may state that the specified conditions support a persistence branch. If the probability is low and stable, the report may state that the specified conditions support a pre-2100 peak branch. If calibration fails, model comparisons are inconclusive, or sensitivity dominates, the only valid conclusion is that the design cannot distinguish the branches under the current evidence and assumptions.

## Human review and ethics

The study has no direct human-subject intervention, but it has a meaningful communication risk. Population projections must not be used to rank the worth of populations, justify coercive fertility control, stigmatize migrants, or prescribe national policy. Demographic review is required for plausibility; statistical review is required for calibration and priors; climate-risk review is required for covariate construction; and data-governance review is required before use of any supplemental records. The author must preserve this boundary and must not transform proposed conditions into observed findings.
