# ExperimentDesign Agent: CRYO-FINGERPRINT Evaluation

## 1. Objective and design mode

This design tests how reservoir definition, transient melt history, coupled Earth-system feedbacks, and regional sea-level physics alter the answer to the complete-ice-loss question. The study is `DESIGN_ONLY`: no simulation has been run, no numerical outcome is reported, and no coastal region is declared to have a measured future impact.

## 2. Hypotheses

- **H1, spatial structure:** A sea-level fingerprint and solid-Earth response model changes regional relative-sea-level estimates compared with a uniform global-mean map, even when total grounded-ice volume is held fixed.
- **H2, pathway dependence:** Melt schedule and freshwater delivery change transient timing, ocean stratification, circulation, and climate response, so the endpoint alone is insufficient.
- **H3, reservoir separation:** Floating sea ice and ice shelves affect climate, habitat, and grounded-ice dynamics differently from grounded ice volume; treating all ice as one reservoir creates identifiable bias.
- **H4, impact realism:** Tides, surge, waves, river flow, and vertical land motion alter flooding and exposure relative to static elevation thresholding.
- **H5, uncertainty decomposition:** A hierarchical model can attribute uncertainty to inventory, melt dynamics, climate response, regional fingerprints, coastal processes, and human exposure without conflating them.

## 3. Model hierarchy

Use four nested levels. Level 0 is a scalar grounded-ice volume conversion and static elevation map. Level 1 adds reservoir-resolved mass balance and several melt schedules. Level 2 adds climate-ocean feedbacks, freshwater, albedo, and sea-level fingerprints with solid-Earth response. Level 3 adds dynamic coastal hydrodynamics, compound extremes, ecosystem indicators, and exposure or adaptation scenarios. Every level uses the same final grounded-ice constraint where possible, so added complexity can be isolated.

For reservoir (r\), use the mass-balance equation

\[
\frac{dM_r}{dt}=A_r(t)-S_r(t)-B_r(t)-C_r(t),
\]

and convert the grounded component into a global mean contribution using ocean-area and density conventions. A fingerprint operator maps each source distribution and Earth response into local relative sea level:

\[
\Delta \eta(x,t)=\mathcal{G}[M_r(\cdot,t)]+\mathcal{D}[T,S,u](x,t)+\mathcal{E}[x,t]+\mathcal{L}(x,t),
\]

where (mathcal{G}) is the mass, gravity, rotation, and solid-Earth operator, (mathcal{D}) represents steric and dynamic ocean effects from temperature (T), salinity (S), and circulation (u), (mathcal{E}) represents tides, extremes, and coastal dynamics, and (mathcal{L}) represents local vertical land motion.

## 4. Data and calibration targets

The calibration set should include present-day ice mass balance, glacier and ice-sheet geometry, satellite altimetry and gravimetry products, tide-gauge records, GNSS vertical land motion, ocean temperature and salinity, sea-ice concentration, river discharge, bathymetry, topography, and historical extreme water levels. Paleoclimate or geological sea-level constraints can test long timescales but must be separated from modern validation. The study uses the data available at the declared reconstruction time and records product versions and uncertainties.

The complete-loss endpoint cannot be directly validated. Validation is instead staged: recover synthetic truth from controlled perturbations; reproduce observed present-day mass and sea-level trends; reconstruct historical regional fingerprints and extremes; then propagate the calibrated model into hypothetical complete-loss scenarios. A model that misses present-day fingerprints is not rescued by agreement with a scalar 70 m check.

## 5. Scenario ensemble

Construct a factorial or space-filling ensemble over:

1. reservoir histories for Greenland, Antarctica, glaciers, sea ice, ice shelves, and frozen ground;
2. abrupt, fast, multi-century, and multi-millennial grounded-ice loss schedules with matched endpoints;
3. weak, intermediate, and strong freshwater, albedo, and ocean-mixing responses;
4. alternative fingerprint, solid-Earth, bathymetry, and coastal-friction parameterizations;
5. fixed present-day, projected, retreat, protection, accommodation, and ecosystem-based exposure pathways.

The first four groups are physical scenarios. The fifth is a conditional impact layer and must not feed back into physical sea level unless a separate coupled socio-hydrological model is explicitly declared. The reported output is a distribution over maps, timing, and impacts, not a single deterministic future.

## 6. Baselines and ablations

Baselines are: scalar 70 m conversion; global-mean sea-level-only projection; reservoir-resolved but uncoupled mass balance; coupled model without fingerprints; and coupled model without dynamic coastal processes. Ablations remove one mechanism at a time: reservoir separation, freshwater flux, albedo, ocean dynamics, gravitational fingerprints, solid-Earth response, vertical land motion, compound extremes, and exposure adaptation. A no-fingerprints ablation is especially important because it measures the error from assuming a uniform local rise.

## 7. Metrics

Physical metrics include reservoir mass-balance error, global mean sea-level consistency, regional fingerprint bias, spatial correlation, timing error, ocean heat and salinity pattern error, and coverage of uncertainty intervals. Coastal metrics include inundation depth and area, duration, connectivity, extreme-water-level exceedance, salinity intrusion, and wetland habitat change. Ecological metrics are habitat suitability or seasonal productivity indicators with their own uncertainty. Exposure metrics include population, assets, ports, agriculture, and critical infrastructure under clearly labeled scenarios.

Use continuous ranked probability score, energy score, interval coverage, interval width, and continuous ranked probability score skill relative to the scalar baseline. Decompose variance by reservoir, path, feedback, fingerprint, coastal process, and exposure. Report maps and regional distributions rather than only a global mean.

## 8. Synthetic and real-world tests

Synthetic tests perturb a known ice source, melt schedule, gravity response, ocean mixing coefficient, and coastline. The pipeline must recover the known global mean, spatial pattern, and uncertainty coverage under missing observations. Present-day hindcasts test whether the model reproduces observed ice mass and regional sea-level variability. Historical event tests evaluate tides, surge, waves, rainfall, river discharge, and vertical land motion. Distribution-shift tests hold out a basin, sensor product, climate regime, and coastline type.

## 9. Falsification and decision rules

The selected model fails H1 if its regional fingerprint does not improve reconstruction or if its uncertainty coverage is worse than the global-mean baseline without a declared resolution tradeoff. It fails H2 if matched-endpoint schedules produce indistinguishable transient dynamics across all predeclared diagnostics. It fails H3 if treating reservoirs as one pool performs as well as separate modules on climate, habitat, and grounded-ice discharge tests. It fails H4 if dynamic and compound coastal modeling do not improve historical extreme-water-level reconstruction. It fails H5 if uncertainty components cannot be recovered in the synthetic attribution test.

Advance a model level only if it improves the primary physical metric or impact metric while retaining calibration coverage and a reproducible uncertainty decomposition. Do not advance because a map looks more detailed. Do not interpret an endpoint scenario as a date prediction.

## 10. Reproducibility and safety

Freeze reservoir definitions, ocean area, density assumptions, coastline version, elevation datum, model versions, random seeds, scenario distributions, and exposure datasets before final holdout scoring. Store all maps with coordinate reference, vertical datum, time slice, and uncertainty metadata. Separate physical outputs from population and asset scenarios. Any use in adaptation planning requires regional geodetic, coastal-engineering, ecological, and community review; this package itself is not an engineering evacuation map.

## 11. Planned deliverables

After execution, the study would produce reservoir mass trajectories, global and regional sea-level fields, uncertainty decompositions, climate-ocean diagnostics, coastal hazard maps, habitat indicators, exposure tables, and model cards. These are planned outputs only. `expected_results` and `observed_results` remain empty in the current handoff.
