# Idea Agent: CRYO-FINGERPRINT

## Selected direction

**CRYO-FINGERPRINT** is a coupled scenario emulator for the complete-loss thought experiment. It resolves ice reservoirs separately, propagates their mass and freshwater fluxes through an Earth-system response, computes sea-level fingerprints and solid-Earth adjustment, and downscales the resulting relative sea-level field into coastal and ecological impacts.

The central research question is:

> How much does a reservoir-resolved, coupled and spatially explicit model change the estimated timing, regional magnitude, and impact distribution of complete planetary ice loss compared with a global-mean, endpoint-only calculation?

The direction is deliberately ambitious. It treats the approximately 70 m figure as a mass-volume check while testing the stronger claim that a physically meaningful answer requires a transient path, regional fingerprints, and coupled feedbacks. The result should identify both the robust signal and the parts that remain scenario-dependent.

## Candidate routes and debate

### Route A: global-mean bathtub calculation

Convert grounded-ice volume to a single global mean sea-level rise and overlay it on a digital elevation model. This route is transparent and useful as a lower-complexity reference, but it omits gravitational fingerprints, solid-Earth response, tides, surge, hydrodynamics, and the time history of melt. It cannot be the primary scientific answer.

### Route B: fully coupled high-resolution Earth system simulation

Resolve ice dynamics, atmosphere, ocean, solid Earth, biogeochemistry, and coastlines at high resolution for every transient schedule. This route is physically attractive but computationally expensive, difficult to validate at an unreachable endpoint, and likely to mix structural uncertainty with numerical resolution.

### Route C: reservoir-resolved coupled emulator with process-constrained downscaling

Use a hierarchy: process-based ice and sea-level modules, a calibrated Earth-system emulator for climate-ocean feedbacks, a sea-level fingerprint and solid-Earth response layer, and regional coastal impact models. This route is selected because it preserves the mechanisms needed for the question while making uncertainty and validation tractable.

## Core mechanism

For reservoir (r\), the ice state (M_r(t)) evolves as

\[
\frac{dM_r}{dt}=A_r(t)-S_r(t)-B_r(t)-C_r(t),
\]

where (A_r) is accumulation, (S_r) surface melt, (B_r) basal melt, and (C_r) calving or discharge. Grounded-ice volume is converted to a global mean contribution, while the spatial source mass also drives a sea-level fingerprint operator. Floating ice is included in the climate, freshwater, and habitat modules but is not counted as an additional 70 m of eustatic sea-level volume.

The global mean and regional relative sea level are separated:

\[
\Delta \eta(x,t)=\Delta \eta_{\mathrm{mass}}(x,t)+\Delta \eta_{\mathrm{steric}}(x,t)+\Delta \eta_{\mathrm{dynamic}}(x,t)+\Delta \eta_{\mathrm{solid}}(x,t)+\Delta \eta_{\mathrm{local}}(x,t).
\]

The spatial terms account for gravitational and rotational fingerprints, ocean circulation, solid-Earth deformation, tides and storm response, and vertical land motion. A common uncertainty layer propagates uncertainty in melt schedule, ice geometry, bathymetry, model parameters, and exposure.

## Scenario axes

1. **Reservoir:** Greenland, Antarctica, mountain glaciers, sea ice, ice shelves, and frozen ground treated as separate physical objects.
2. **Melt schedule:** abrupt, fast transient, multi-century, and multi-millennial pathways with the same final grounded-ice loss.
3. **Earth-system response:** weak, medium, and strong freshwater and albedo feedback regimes constrained by present-day and paleoclimate behavior.
4. **Coastal process:** static elevation, tide-aware, surge-aware, wave-aware, and hydrodynamic inundation products.
5. **Human exposure:** fixed present-day exposure, projected population and assets, and adaptation scenarios kept separate from physical projections.

## Falsifiable claims

1. A global-mean-only model produces materially different regional relative-sea-level distributions than CRYO-FINGERPRINT in at least some basins when the same grounded-ice volume is used.
2. Melt schedule and feedback uncertainty change timing and circulation outcomes even when the final global mean is held fixed.
3. Floating sea-ice loss changes climate, freshwater exchange, and habitat indicators without contributing an equivalent direct eustatic rise.
4. Process-constrained downscaling improves reconstruction of present-day and historical regional sea-level patterns over endpoint-only mapping without degrading uncertainty coverage.
5. Compound extremes and vertical land motion change the ranking of exposed coastal regions relative to a static mean-sea-level map.

## Intended contribution

The contribution is a transparent, testable bridge from a memorable 70 m thought experiment to a hierarchy of physical and impact models. It will show what is robust across pathways, what depends on ice dynamics and ocean feedbacks, and what cannot be inferred from the endpoint alone. It is not a prediction that all ice will melt by a particular date and not a claim that every local coastline rises by exactly 70 m.

## Idea handoff

The ExperimentDesign Agent should define synthetic recovery tests, present-day and historical process validation, transient scenario ensembles, endpoint comparisons, regional fingerprint metrics, impact metrics, and uncertainty decomposition. Numerical outcomes must remain empty until the actual experiment is executed.
