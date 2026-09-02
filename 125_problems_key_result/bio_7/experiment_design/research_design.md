# Experiment Design: Testing Multisensory Migration Navigation With MAGNAV

## Scope and status

This is a **DESIGN_ONLY** protocol. It reports no animal experiment, tracking result, molecular assay, causal receptor finding, or species-general conclusion. The initial demonstrator is a nocturnally migrating songbird because light-dependent magnetic-compass literature enables clear cue-conflict manipulations. The framework is intentionally extensible to marine and insect systems, but those extensions require separately validated sensory and welfare protocols.

## Research question

For a preregistered population, migratory phase, and route season, does a controlled change in celestial or magnetic information alter directional orientation and free-ranging route behaviour in a manner that is cue-specific, reversible, and consistent with a defined receptor-to-behaviour model?

## Scenario ladder

| Scenario | System and perturbation | Primary endpoint | Gate passed if | Claim permitted |
|---|---|---|---|---|
| S0 | Route atlas, light regime, field vectors, weather, age/experience strata | Data completeness and preregistered eligibility | Exposure and denominator are auditable | Feasible sampling boundary |
| S1 | Orientation arena; rotated magnetic north, solar/polarization schedule, matched sham | Circular bearing and concentration | Planned cue conflict differs from sham and restoration returns toward baseline | Conditional cue-dependent orientation |
| S2 | Candidate receptor/pathway assay with target and non-target perturbations | Cue response, molecular/physiological readout, viability | Perturbation is specific and response pattern matches prediction | Bounded mechanism contribution |
| S3 | Tagged free-ranging animals with virtual magnetic displacement or natural gradient design | Route deviation, correction latency, stopover and survival-proxy observability | Track provenance, exposure, and competing cues remain interpretable | Ecological route contribution |
| S4 | New season, site, laboratory or species with locked analysis | Replication and heterogeneity | Direction and boundary replicate or restriction is identified | Context-limited generalization |

## Experimental arms

Each S1/S3 comparison includes baseline natural conditions; magnetic rotation or displacement; celestial-clock/polarization manipulation where ethically and technically appropriate; cross-cue conflict; sham handling; and restoration to the baseline cue relation. The design does not use an untreated animal as the only control because restraint, release, device mass, illumination spectrum, and arena geometry can alter orientation independently of the target cue.

## Endpoints and estimands

For individual `i`, bearing is represented as a circular unit vector. The primary S1 estimand is the adjusted mean bearing difference between a specified conflict condition and a matched sham condition. Concentration, multimodality, orientation probability, and exclusions are reported alongside the mean. The primary S3 estimand is a preregistered difference in route-direction or correction-latency distribution conditional on release site, wind, calendar date, and retained track quality. Stopover, body condition, and survival-related signals are secondary and never interpreted as proof that an individual sensed a particular field value.

## Confounding and validity controls

The protocol measures magnetic intensity, inclination, declination, field variability, RF noise, light spectrum, cloud cover, polarization proxy, wind, temperature, lunar illumination, release geometry, handling duration, tag/device characteristics, age, sex where appropriate, prior route experience, and social context. Randomization is stratified by release block; outcome scoring and track cleaning are blinded to arm where practicable. A locked exclusion ledger separates sensor failure, ethical withdrawal, predation/loss, and analysis exclusion so attrition cannot be silently converted into apparent navigational failure.

## Analysis plan

Circular mixed models estimate arm contrasts while preserving individual and release-block variation. Route analyses use a movement-state model only after validating positional error and duty-cycle missingness. The study tests the planned hierarchy: manipulation integrity, sham comparison, restoration, cross-cue interaction, receptor/pathway bridge, ecological transfer, and replication. Multiplicity adjustment covers the preregistered confirmatory family; exploratory analyses are labeled exploratory. No average result can compensate for a failed welfare, manipulation-integrity, or normal-sensory-function gate.

## Ethics and interpretation

All invasive, captive, tagging, and release procedures require species-specific approval, trained personnel, minimization of device burden and handling, and predeclared stop rules. A disoriented individual or route deviation is not evidence of a magnetic mechanism unless the physical manipulation, retained cues, health status, and restoration response support that inference. Likewise, a laboratory molecular magnetic effect remains a molecular observation until linked to a behavioural and ecological outcome through the staged design.
