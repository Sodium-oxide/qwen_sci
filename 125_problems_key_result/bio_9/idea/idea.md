# Idea: SPECIESCOPE

## Central idea

**SPECIESCOPE** (Species-Concept, Evidence, Coverage, Integration, Estimation, and Scope Evaluation) is a design framework for defensible global biodiversity estimates. It turns a rhetorical numerical question into a set of linked, falsifiable measurement tasks. The framework does not assume that a universal total is currently obtainable. Its first output is a ledger of compatible and incompatible estimates; a global total is an optional later output only if predeclared integration gates are met.

## Research objective

Develop and evaluate a reproducible procedure that produces scope-specific estimates of richness together with their detection, delimitation, extrapolation, and provenance uncertainty, and that refuses arithmetic aggregation across non-equivalent counting units.

## Claims to test

* **H0 - incompatibility hypothesis:** apparent disagreement between published totals is largely explained by different species concepts, scopes, molecular clustering rules, incomplete detection, taxonomic revision, or extrapolation assumptions.
* **H1 - bounded-domain hypothesis:** after freezing a domain and unit definition, integrated observational evidence can support a bounded richness estimate with an uncertainty interval and calibrated held-out predictions.
* **H2 - sensitivity hypothesis:** the estimate changes materially under plausible changes in delimitation threshold, environmental stratum weights, detection model, or rare-tail model.
* **H3 - integration-gate hypothesis:** a combined all-life estimate is not justified if eukaryotic taxonomic units and microbial operational units cannot be mapped or jointly modelled without double counting or unit mismatch.

## Novelty and contribution

Existing global estimates often provide a method within one evidence family. SPECIESCOPE contributes an explicit interface specification between evidence families. Every reported number carries an ``estimand passport'': the unit, concept, scope, time, data version, protocol, estimator, interval, and known non-comparabilities. This makes failure to integrate a valid scientific result instead of a missing footnote.

## Five-stage ladder

| Stage | Question | Required output | Stop condition |
|---|---|---|---|
| S0: Scope | What is being counted? | estimand passport and incompatibility map | no declared unit or scope |
| S1: Evidence | Is a candidate unit defensibly detected and delimited? | controlled observation and delimitation record | failed controls or unsupported linkage |
| S2: Coverage | What was missed within a defined frame? | coverage and occupancy diagnostics | low coverage without a recovery plan |
| S3: Estimation | Which estimator is calibrated for this domain? | richness interval, sensitivity and held-out scores | unstable model or uncalibrated extrapolation |
| S4: Integration | Can domain estimates be compared or combined? | versioned ledger and integration decision | unit mismatch, overlap ambiguity, or no replication |

## Practical innovation

The framework separates **discovery acceleration** from **taxonomic assertion**. eDNA, barcodes, and automated clustering can rapidly identify candidate diversity; vouchers, reference genomes, multi-source evidence, and transparent taxonomic revision determine whether candidates are promoted to a named or lineage-level species claim. A shared data contract lets both outputs be useful without conflation.

## Anticipated value

SPECIESCOPE would improve biodiversity monitoring, resource allocation for taxonomic work, conservation baselines, and interpretation of microbiome surveys. Its most important deliverable is not a spectacular number but a richer answer: which biological entities have been estimated, where uncertainty comes from, which habitats and lineages drive it, and what observation would reduce it.

## Boundary

This is a DESIGN_ONLY proposal. It advances no new field observations, DNA sequences, taxonomic revisions, or numerical global richness result. Any future numerical result must be generated from preregistered data and analysis steps described in the experimental design.
