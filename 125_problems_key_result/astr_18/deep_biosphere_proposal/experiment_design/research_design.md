# ExperimentDesign Agent: DeepBio Census Study Design

## Boundary and objective

This is a DESIGN_ONLY study plan. It does not drill, deploy sensors, collect samples, incubate organisms, sequence DNA, or report observed results. It defines the evidence required to estimate the volume, composition, and significance of the marine deep biosphere without conflating those constructs.

The primary objective is to estimate compartment-specific posterior distributions for:

1. accessible and occupied habitat volume;
2. living-cell abundance and biomass;
3. taxonomic and functional composition;
4. realized rates of redox transformations;
5. contributions to carbon, sulfur, methane, nitrogen, and mineral-cycling interpretations.

## Study type and sampling frame

The study is a stratified, repeated-observation design across three habitat families:

* A: aphotic water column;
* B: sediment and pore water;
* C: upper oceanic crustal fluids and basalt-associated surfaces.

Strata are defined before field work by ocean basin, margin/open-ocean setting, water depth, temperature, oxygen/redox regime, organic-carbon supply, sediment age, methane/sulfate geochemical zone, lithology, and fluid-circulation state. Sampling windows include process blanks, field blanks, recovery blanks, and replicate material from the same depth interval. A sample cannot enter biological analysis without a linked pressure-temperature history and contamination-control lineage.

## Variables and measurements

| Role | Variable | Operationalization |
|---|---|---|
| Geometry | V_h, porosity, permeability, connectivity | Bathymetry, sediment thickness, lithology, pore volume, borehole and hydrogeologic models |
| Abundance | L_hiz | Microscopy/flow count, digital PCR with extraction controls, lipid biomarkers, calibrated metagenomic coverage |
| Composition | P_hiz | 16S profiles, shotgun metagenomes, MAGs, targeted functional genes, selected lipid markers |
| Activity | R_hiz | Pore/fluid chemistry gradients, reaction-transport inversion, rate measurements when safely permitted, stable-isotope constraints |
| Covariates | X_hiz | Temperature, pressure, dissolved oxygen, sulfate, methane, hydrogen, DIC, DOC/TOC, pH, minerals, age, sedimentation, circulation |
| Error channels | B_m and K_s | Method bias, blank/contamination contribution, preservation loss, depth registration error |

## Hierarchical model

For a habitat stratum h and spatial element s:

    TotalCells_h = integral_over_volume_h L_h(s) dV,

    Flux_k,h = integral_over_volume_h R_k,h(s) dV.

The model treats L and R as distinct latent processes. For observation y from method m:

    y_m,h,s = f_m(L_h(s), P_h(s), R_h(s), B_m, K_s) + epsilon_m,h,s.

An abundance channel may inform L. A metagenome may inform P. A rate or reaction-transport observation is required to identify R. The inference returns posterior intervals, habitat coverage, and variance decomposition instead of an unsupported point estimate.

## Core methods and control logic

1. **Pressure-temperature-aware collection and registration.** Record sensor histories from recovery or observatory intake to laboratory partitioning. Retain metadata for time since recovery, pressure loss, temperature excursion, oxygen exposure, preservatives, and processing order.
2. **Contamination and extracellular-DNA controls.** Include drilling fluid tracers where relevant, procedural blanks, reagent blanks, duplicate extractions, extracellular-DNA fraction assessment, and negative-control sequencing. A lineage-aware classifier flags signals indistinguishable from blanks.
3. **Cross-platform abundance calibration.** Use matched aliquots to link microscopic/flow counts, digital PCR, lipids, and metagenomic coverage. Report matrix-specific conversion uncertainty, not a universal cells-per-read factor.
4. **Multiomics-to-rate bridge.** Pair genomes/transcripts with sulfate, methane, DIC, hydrogen, nitrate, iron, oxygen, and sulfur speciation; combine with pore-water gradients, reaction-transport modeling, or controlled rate data. A detected pathway remains POTENTIAL unless rate evidence supports it.
5. **Spatial upscaling.** Fit a stratified hierarchical model with design weights and covariates. Use withheld provinces and depth intervals to test transportability; publish regions where extrapolation is weak.

## Decision rules

* A compartment-volume estimate is released only with boundary, porosity, and uncertainty specification.
* A cell estimate requires at least two calibrated abundance channels or a justified exception marked needs_human_review.
* A realized carbon, methane, sulfur, or nitrogen process requires a matching geochemical/rate line of evidence; genes alone are insufficient.
* A global statement must include its integration domain, posterior interval, and dominant sensitivity terms.
* An astrobiology statement must identify the Earth analogue variable (energy, solvent, redox pair, temperature-pressure regime, or preservation process) and may not claim extraterrestrial detection.

## Safety, stewardship, and failure modes

The plan is non-interventional. Field deployment and drilling require vessel, permitting, biosafety, environmental, and sample-custody approvals by qualified operators. The design prohibits automatic execution. Major failure modes are low-biomass contamination, pressure-loss artifacts, incomplete habitat coverage, extracellular DNA, and pathway-rate mismatch. Each has an explicit negative-control, sensitivity, or reporting response.
