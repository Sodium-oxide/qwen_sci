# Idea Agent Result: DeepBio Census

## Selected primary direction

**DeepBio Census: a pressure-preserved, habitat-resolved Bayesian inventory of extent, composition, activity, and significance.**

The selected direction rejects a single global biomass number as the main scientific endpoint. It constructs linked posterior distributions for each habitat stratum:

    habitat geometry and porosity
        -> standing cells and viable biomass
        -> taxonomic and functional composition
        -> realized redox rates
        -> carbon, sulfur, methane, nitrogen, and astrobiology-relevance interpretations.

The central hypothesis is that an inventory stratified by energy flux, redox state, organic-carbon supply, temperature, pressure, sediment age, and water-rock interaction will explain more cross-site variation than depth alone and will expose which compartments dominate uncertainty in global significance estimates.

## Why this direction was selected

The Survey Agent identified a measurement mismatch: global statements often combine volumes, cell counts, genes, and metabolic claims that have different units and biases. DeepBio Census resolves the mismatch by assigning every inference to an explicit layer. It also treats contamination and preservation as model variables rather than as post hoc caveats.

The design treats the three main compartments as connected but non-interchangeable:

* **aphotic water column:** water mass, depth, oxygen, dissolved organic matter, particles, and circulation;
* **sediment and pore water:** sedimentation rate, organic-carbon burial, sulfate/methane zone, porosity, age, temperature, and diffusion;
* **upper oceanic crustal fluids:** lithology, permeability, fluid residence time, water-rock chemistry, temperature, oxygen, hydrogen, methane, iron, and sulfur availability.

## Candidate portfolio

| Candidate direction | Decision | Scientific rationale |
|---|---|---|
| Hierarchical DeepBio Census | Selected primary | Directly addresses G1--G5 and can report uncertainty without hiding compartment differences |
| Sediment-only high-resolution multiomics atlas | Competitive | Strong compositional resolution but cannot estimate whole deep-biosphere significance alone |
| Crustal-fluid long-term observatory | Competitive | Strong native-signal and activity inference, but sparse site coverage |
| DNA-only global biomass inventory | Rejected | Violates G2 and G3 because reads do not calibrate cells or rates |
| Cell-count multiplier for global flux | Rejected | Treats abundance as metabolic activity |
| Astrobiology extrapolation from extremophiles alone | High-risk/rejected as endpoint | Analog value requires energy and preservation comparisons, not presence claims |

## Mechanism and falsifiability

For habitat h, site i, and depth interval z, DeepBio Census models a latent living-cell density L_hiz and a latent redox-rate vector R_hiz. Observed microscopy, digital PCR, lipids, metagenomes, transcripts, pore-water chemistry, and rate assays are treated as noisy observation channels with method-specific bias and blank contributions. The project asks whether environmental covariates predict L and R consistently across compartments after matrix effects are controlled.

The selected hypothesis is falsified if a stratified model does not improve predictive performance over a depth-only model, if cross-platform calibration shows irreducible inconsistency beyond declared uncertainty, or if rate constraints are incompatible with the pathway and abundance inferences. A negative result would still identify the missing covariates or sample-preservation failure modes.

## Release policy

An inventory may report an integrated cell or biomass posterior only with explicit spatial support, porosity, calibration, and uncertainty. A pathway is reported as realized only when a compatible geochemical or rate constraint exists. A global significance claim must name the flux, integration domain, and uncertainty interval. No field collection, incubation, drilling, or intervention is performed by this proposal.
