# Experiment Design: EVOTRACE for Mechanistic Evolutionary Inference

## 1. Study type and scope

EVOTRACE is a coordinated observational, comparative, and experimental design. A first implementation should focus on one focal adaptive trait in a tractable lineage, then use predeclared comparison lineages or replicated populations. The study must state the trait definition, life stage, environment, lineage boundary, generation/time scale, ancestry model, candidate mechanisms, and intended causal claim.

## 2. Sampling architecture

Use a nested design with: (i) replicated populations across ecological gradients; (ii) repeated temporal samples or historical/genomic time points where feasible; (iii) common-garden or reciprocal-environment assays; (iv) a pedigree, crosses, or relatedness-aware genomic design; and (v) developmental samples spanning the trait's formation window. Preserve a probability or stratified sampling core and record collection effort, age, sex where relevant, season, laboratory batch, environment, and ancestry metadata.

For complex organs, add comparative embryological or developmental time series from at least two lineages with an explicit phylogenetic contrast. Tissue/cell-state sampling must be matched to homologous developmental stages rather than nominal chronological time alone.

## 3. Evidence streams and controls

* **Genomic:** sequencing depth, genotype likelihoods, structural variants, recombination map uncertainty, and relatedness controls.
* **Population process:** effective population size, migration/ancestry models, neutral reference regions, and independently replicated trajectories.
* **Phenotype and fitness:** blinded trait measurement, viability, fertility, mating success, and performance across environments.
* **Developmental mechanism:** cell type, spatial expression, chromatin/regulatory state, perturbation design, and rescue where ethical and feasible.
* **History:** fossils or ancestral-state data where appropriate, calibrated phylogeny, and explicit uncertainty of ancestral inference.

## 4. Analysis plan

1. Freeze the E0 passport and preregister primary and sensitivity models.
2. Quality-control genotypes, phenotypes, developmental data, and environmental covariates before outcome modelling.
3. Fit demographic, migration, mutation, selection, and drift models; compare predictive performance rather than declaring selection from one statistic.
4. Quantify genotype-trait-fitness associations in matched environments and test for population structure confounding.
5. Test candidate regulatory/developmental mediators through perturbation, natural experiments, allele swaps, or orthogonal functional evidence where allowable.
6. Refit without a held-out population, lineage, time point, or laboratory batch; evaluate forecast calibration and sensitivity to ancestry, phenotype, and regulatory assumptions.

## 5. Primary endpoints

* Relative predictive support for selection-plus-environment versus neutral demographic/migration models.
* Calibrated interval for change in allele, haplotype, or trait frequency in a declared population.
* Strength and reproducibility of genotype-to-intermediate-to-trait evidence.
* Held-out environmental or lineage prediction error.
* Sensitivity of inferences to effective population size, migration, recombination, developmental-stage alignment, and ancestral-state assumptions.

## 6. Causal decision rules

Label a result as **descriptive trajectory** if time-resolved changes are measured. Label it as **selection-supported** only after relevant neutral/demographic and migration alternatives are evaluated. Label it as **mechanistically supported** only after a directional genotype-to-intermediate-to-trait pathway is tested with suitable controls. Label it as a **historical explanation** only after the inferred ancestral path and alternatives are reported. A lack of sufficient evidence at a stage stops promotion to the next label but does not erase the lower-level observation.

## 7. Risks and safeguards

| Risk | Threat | Safeguard |
|---|---|---|
| Population structure | false selection signal | ancestry-aware model, neutral loci, geographically replicated samples |
| Unmeasured environment | confounded trait-fitness association | measured covariates, common garden, reciprocal environment |
| Developmental-stage mismatch | false regulatory difference | homologous-stage atlas, cell-state alignment, blinded QC |
| Off-target perturbation | spurious mechanism | independent guide/allele, rescue, orthogonal assay |
| Historical overreach | deterministic narrative from one lineage | alternative ancestral models, phylogenetic replication, uncertainty interval |
| Rare variant uncertainty | unstable frequency and effect estimate | genotype likelihoods, replication, hierarchical shrinkage |

## 8. Governance and ethics

The protocol follows collection permits, animal welfare and institutional review where applicable, protection of threatened populations and sensitive locations, benefit-sharing obligations, and controlled access for genomic data. Germline or ecological interventions require organism-specific review and are not implied by this design. All code, model specifications, versions, and negative findings should be released in a reproducible ledger where permitted.

## 9. Design-only statement

No new samples, interventions, animal experiments, or genetic modifications are performed by this proposal. Numerical results can only be reported after an approved and preregistered empirical study applies these methods.
