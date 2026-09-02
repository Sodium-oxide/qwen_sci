# Experiment Design: Testing SPECIESCOPE for Earth Species Richness

## 1. Study type and estimands

This is a multi-domain observational and computational study design. It will estimate separate richness targets rather than presume a single count:

* curated, accepted named taxa in a frozen registry release;
* species or lineage hypotheses supported by specified morphological, ecological, and genomic evidence;
* domain-specific molecular units, labelled as OTUs, ASVs, or BIN-like registry units where appropriate; and
* coverage-adjusted richness in explicitly bounded habitat, geography, and time strata.

Each target receives an estimand passport: species concept, taxonomic ranks, domain, spatial polygon, environmental stratum, sampling dates, inclusion/exclusion rules, sequence marker and pipeline, reference database version, estimator, uncertainty method, and responsible data release.

## 2. Sampling architecture

Use a stratified, rotating panel across terrestrial, freshwater, marine, subterranean, atmospheric, host-associated, and engineered habitats. Within strata, randomize primary sampling units and include repeat visits. Preserve a probability-sampling core even when opportunistic museum and citizen-science records are added. The data unit differs by organismal group: specimen plus voucher for macrobiota; water, soil, sediment, air, or host sample plus extraction and sequencing run for molecular surveys.

Oversample strata with low historical coverage, high endemism, or expected rare diversity, but retain sampling weights. Record effort, collection method, weather, depth, substrate, sequencing depth, and observer or laboratory batch. Split a predeclared set of locations and time periods for held-out validation.

## 3. Evidence and quality controls

For specimen-based observations, require identifier, collection event, georeference precision, taxonomic authority, image when feasible, voucher repository, and revision history. For molecular observations, use field blanks, extraction blanks, PCR blanks, positive mock communities, technical replicates, unique molecular identifiers when suitable, contamination tracking, and a frozen bioinformatic workflow. Retain raw reads, denoising parameters, clustering protocol, reference assignments, and negative-control outcomes.

Candidate species hypotheses should record which independent evidence streams agree or disagree. Single-locus clusters are provisional unless the study explicitly defines the intended unit as a molecular operational unit.

## 4. Analytical plan

1. Audit scope and create the S0 passport before looking at richness estimates.
2. Estimate detection and occupancy from repeated samples, allowing method and laboratory effects.
3. Compute sample coverage and observed/unseen richness using incidence- and abundance-based estimators appropriate to the data unit.
4. Fit alternative rare-tail and hierarchical models. Evaluate posterior predictive behavior and performance on held-out strata.
5. Perturb species-delimitation thresholds, primer/reference choices, taxonomic synonym treatment, stratum weights, and sampling-effort assumptions.
6. Publish domain estimates with uncertainty decomposition. Run S4 integration only where mappings, overlap rules, and units have passed the predefined gates.

## 5. Primary endpoints

* Predeclared-domain richness interval at target sample coverage.
* Held-out detection and richness calibration.
* Fraction of reported uncertainty attributable to detection, delimitation, coverage, model, and integration components.
* Sensitivity of richness to scientifically plausible analytical choices.
* Number and fraction of estimates correctly identified as incomparable rather than improperly combined.

## 6. Decision rules

An estimate may be labelled **integrable** only when its passport, data version, unit mapping, overlap treatment, sampling-frame relationship, and uncertainty representation are available. It is labelled **parallel but non-additive** when it is scientifically useful yet unit-incompatible. No headline all-life total is reported when any integration gate fails.

## 7. Statistical safeguards

Pre-register the target scope and primary model family. Use coverage-based comparisons rather than raw sample-size comparisons. Present both intervals and sensitivity distributions. Keep discovery and confirmation datasets separated where possible. Apply multiplicity control to families of confirmatory comparisons, and distinguish exploratory discoveries from confirmatory species claims.

## 8. Ethics, governance, and reproducibility

Follow permits, Indigenous data sovereignty principles where applicable, threatened-species location protections, access and benefit-sharing obligations, and sample-export regulations. Version raw data, curated records, code, containers, reference databases, and taxonomic decisions. Make sensitive locality information available only under appropriate access control. The report contains no newly collected observations and no organismal manipulation.

## 9. Risks and mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Taxonomic synonymy or revision | artificial inflation or deflation | frozen release, concept identifiers, revision ledger |
| Imperfect molecular detection | missed or false occurrences | replicated occupancy design and controls |
| Primer and bioinformatic bias | distorted unit richness | mock communities, alternative pipelines, sensitivity analysis |
| Sparse rare-tail evidence | unstable extrapolation | coverage targets, model comparison, held-out checks |
| Unit incompatibility | invalid global sum | S4 integration gate and parallel reporting |
| Geographic/access bias | misleading global weighting | probability core, effort metadata, post-stratification |

## 10. Design-only statement

No data have been collected or analysed for this proposal. All numerical values in the eventual study must be generated from the preregistered protocol, released datasets, and declared model versions; they cannot be inferred from this design document.
