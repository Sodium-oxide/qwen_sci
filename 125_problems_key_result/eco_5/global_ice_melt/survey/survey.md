# Survey Agent: What Happens If All the Ice on Earth Melts?

## Scientific reframe

The prompt's headline number is useful but underspecified. A scientifically testable version is:

> How would the complete loss of terrestrial ice and floating marine ice alter global and regional sea level, ocean circulation, climate feedbacks, ecosystems, and coastal exposure across transient and long-term equilibrium timescales?

The study must distinguish four reservoirs: grounded ice sheets and glaciers, floating sea ice, ice shelves, and frozen ground or other non-ocean cryosphere. Grounded ice contributes directly to ocean volume when it melts. Floating ice already displaces seawater, so its direct eustatic sea-level contribution is small, although its loss changes albedo, freshwater flux, ocean stratification, circulation, atmospheric exchange, and ecosystem habitat. Ice shelves matter dynamically because their loss can accelerate grounded ice discharge even before complete melting. Frozen ground is not a simple sea-level reservoir: thaw changes water storage, carbon cycling, hydrology, and land stability.

The statement that all planetary ice corresponds to roughly 70 m of global mean sea-level rise is an order-of-magnitude consequence of melting grounded ice, not a prediction that every coastline rises uniformly by 70 m at the same time. Regional sea level is modified by gravitational, rotational, and solid-Earth responses, ocean circulation, basin redistribution, vertical land motion, tides, and coastline geometry. A complete-ice-loss thought experiment therefore requires a sea-level fingerprint model coupled to an Earth-system and coastal-impact model.

## Evidence map

### 1. Ice reservoirs and mass balance

The relevant first step is an inventory with explicit mass and density conventions. Antarctica and Greenland contain most terrestrial ice; mountain glaciers contribute less total volume but respond more rapidly. Sea ice and ice shelves are floating, while ice shelves can buttress grounded ice. A model should track accumulation, surface melt, basal melt, calving, grounding-line migration, and freshwater delivery rather than applying one scalar melt rate. The complete-loss endpoint is a boundary condition for a long transient, not a forecast for a specified near-term year.

The 70 m figure is best used as a consistency check on the integrated grounded-ice volume. It should not be treated as an exact value because ice density, bed topography, ocean area, ice-sheet geometry, land rebound, and the distinction between global mean sea level and local relative sea level all matter. The survey recommends reporting an interval and a decomposition by reservoir in the design stage.

### 2. Global mean versus regional sea level

Melting ice changes sea level nonuniformly. A large ice mass gravitationally attracts nearby seawater; when the mass decreases, local sea level near the former ice sheet can fall relative to the far field, while more distant regions rise by more than the global mean. Earth deformation and rotation further redistribute water. In addition, ocean warming, salinity changes, circulation, tides, storm surges, and vertical land motion alter relative sea level at a coast.

The important output is therefore a time-dependent field of relative sea-level change, not a single global number. Regional fingerprints must be propagated through coastal topography and uncertainty in ice-source history. Coastal flooding is controlled by extreme water levels and compound events, not only by mean sea level.

### 3. Climate feedbacks and ocean circulation

Ice loss reduces surface albedo, changes air-sea heat exchange, and injects freshwater. Freshwater can alter density stratification and ocean circulation, while a warmer and darker surface can amplify regional warming. The sign and strength of individual feedbacks depend on location, season, ocean mixing, atmospheric transport, clouds, and the time horizon. A complete-loss scenario should therefore be simulated with a coupled ocean-atmosphere model or an emulator that preserves the relevant conservation and flux constraints.

The endpoint is not simply a warmer version of today's Earth. Ice-sheet removal changes elevation and gravity, coastlines migrate, ocean basins exchange water, and the climate system may pass through multiple circulation regimes. The survey distinguishes transient pathways from a final equilibrium-like state and does not infer the path from the endpoint alone.

### 4. Ecological and biogeochemical consequences

Loss of sea ice removes or transforms habitat for ice-associated marine communities and changes light, gas exchange, and seasonal productivity. Glacier and ice-sheet melt alter river discharge, nutrient delivery, sediment transport, freshwater availability, and estuarine salinity. Coastal wetlands may migrate, drown, or be blocked by development. Permafrost thaw adds distinct carbon and methane feedbacks and should not be folded into the ice-volume sea-level estimate.

The design should connect physical outputs to ecological exposure through habitat suitability and hydrological models, while keeping ecological response uncertainty separate from geometric inundation. It should not claim that a single sea-level field determines biodiversity outcomes.

### 5. Coastal exposure and adaptation

A global mean rise of tens of meters would inundate or transform most present low-lying coastal settlements, ports, deltas, wetlands, and infrastructure, but exposure depends on topography, subsidence, sediment supply, defenses, migration, and the chosen time slice. A useful impact product reports depth, duration, connectivity, salinity intrusion, population and asset exposure, and uncertainty by region. It should also distinguish static bathtub mapping from dynamic hydrodynamic flooding.

Adaptation is a decision layer, not a physical input. The study can compare retreat, protection, accommodation, and ecosystem-based pathways, but it should state assumptions explicitly and avoid treating population or asset projections as observed physical results.

## Gap ledger

1. **Reservoir ambiguity:** “All ice” mixes grounded ice, floating sea ice, ice shelves, and frozen ground with different sea-level and climate effects.
2. **Endpoint-path confusion:** A complete-loss endpoint does not specify the transient rate, sequence, or climate trajectory.
3. **Mean-field shortcut:** Global mean sea level cannot represent gravitational fingerprints, vertical land motion, circulation, tides, or coastal geometry.
4. **Coupled feedback uncertainty:** Freshwater, albedo, ice elevation, clouds, and ocean circulation can alter the path and equilibrium response.
5. **Impact aggregation:** Flooded area, population, infrastructure, ecosystems, and salinity are different impact variables with different models.
6. **Compound extremes:** Storm surge, tides, waves, rainfall, river discharge, and subsidence can dominate episodic damage around a new mean sea level.
7. **Model hierarchy:** High-resolution coastal dynamics are expensive, while coarse Earth-system models can miss local exposure and feedbacks.
8. **Validation asymmetry:** No modern observation can validate a complete-loss endpoint; validation must use present-day mass balance, historical sea-level fingerprints, and synthetic recovery tests.
9. **Equity and adaptation assumptions:** Exposure maps can change with migration, protection, land use, and economic development, so these assumptions must be separated from physical projections.

## Evidence anchors

The IPCC Sixth Assessment Report provides the primary synthesis for observed and projected cryosphere, sea-level, and climate processes. Gregory et al. define sea-level terminology and distinguish global mean, regional variability, and local relative sea level. Bamber et al. quantify structured uncertainty in ice-sheet contributions. Golledge et al. connect ice-sheet melt to broad environmental consequences, while Levermann et al. and Clark et al. address long-term sea-level commitment. DeConto and Pollard provide a process-based Antarctic contribution framework. Notz and Stroeve link observed Arctic sea-ice loss to cumulative anthropogenic carbon emissions.

These references are suitable evidence anchors, but the current dual-engine search could not retrieve fresh records because both OpenAlex and AnySearch refused the network connection. The browser attempt to open the NASA sea-level page was also closed by the current browser connection. Publisher pages, DOI metadata, and data-access terms should be verified before an external submission. No network failure is converted into a fabricated source or numerical result.

## Survey conclusion

The scientifically useful answer is conditional and direct: if all grounded planetary ice were eventually removed, global mean sea level would rise by approximately the grounded-ice equivalent, commonly summarized as around 70 m, but local relative sea level would vary substantially and the climate-ocean pathway would be nonlinear. Loss of floating ice would add little direct sea-level volume but would strongly affect albedo, freshwater, circulation, and habitat. The consequences would be global, yet their timing and regional severity depend on ice-loss history, Earth-system feedbacks, coastal processes, and human adaptation.

## Handoff to Idea Agent

The recommended direction is **CRYO-FINGERPRINT**, a coupled, multi-timescale scenario emulator that combines reservoir-resolved ice mass balance, sea-level fingerprints, climate-ocean response, and coastal impact modeling. It should compare endpoint-only, global-mean-only, and coupled approaches; test transient melt schedules; and report uncertainty as fields and impact distributions. The experiment must remain design-only, must not claim that a complete-loss experiment has been executed, and must not equate floating sea-ice loss with 70 m of eustatic rise.
