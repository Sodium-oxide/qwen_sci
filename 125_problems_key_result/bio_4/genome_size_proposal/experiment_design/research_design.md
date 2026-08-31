# ExperimentDesign Agent: GenomeFlux Study Design

## Research brief

- **Selected direction:** D3, GenomeFlux.
- **Question:** Does a phylogenetically structured model that represents repeat-family gain, WGD, and DNA-loss/compaction proxies explain held-out genome-size contrasts more reliably than gain-only or WGD-only alternatives?
- **Scope:** Public comparative-genomics metadata, published 1C estimates, repeat annotations or low-pass repeat profiles, published phylogenies, and dated WGD indicators. The initial demonstration is a multi-clade land-plant analysis with optional non-plant hold-out tests.
- **Execution boundary:** `DESIGN_ONLY`; no organism collection, culture, sequencing, genome editing, sampling, ecological intervention, or human/animal participant work.

## Hypotheses and decision logic

| ID | Testable hypothesis | Supporting observation if tested | Falsifying result |
|---|---|---|---|
| H1 | A bidirectional gain-loss model has better out-of-clade predictive calibration than a gain-only model. | Higher held-out predictive density and stable sign of core terms across prespecified clades. | Gain-only model matches or exceeds it after complexity penalty. |
| H2 | Repeat-family composition adds information beyond total repeat fraction. | Family-resolved model improves held-out calibration or explains named contrasts with quality-controlled annotations. | Total-repeat model is equivalent after controls. |
| H3 | WGD effects are transient or context-dependent once time since WGD and loss proxies are represented. | WGD-only effect weakens or changes by lineage in the full model. | WGD-only model remains sufficient across matched comparisons. |
| H4 | Putative phenotypic constraints require a causal alternative set rather than direct interpretation. | Trait association is robust to phylogeny and declared covariates but remains a constrained association. | Association is unstable or disappears under the prespecified controls. |

## Variables and evidence cards

**Outcome.** Log-transformed 1C nuclear DNA amount, with measurement method, standard, tissue/cytotype information, source, and uncertainty. Values without adequate provenance cannot enter confirmatory comparisons.

**Gain predictors.** Repeat fraction; family-level abundance of major TE classes; indicators of recent TE activity only where directly supported; count/timing confidence of WGD events. These are not interchangeable variables.

**Loss/compaction predictors.** Intergenic fraction, repeat-age distribution where comparable, presence/absence patterns of repeat families in phylogenetically paired taxa, and published deletion/compaction evidence. No individual proxy is labeled “DNA loss rate” without a validated mapping.

**Controls and gates.** Phylogenetic covariance; assembly/repeat-annotation quality; data source; ploidy/cytotype; sampling density; lineage; and measurement comparability. A quality ledger assigns each record a permitted use: descriptive, exploratory model, confirmatory paired model, or excluded.

## Model comparison protocol

1. Freeze a data dictionary, inclusion/exclusion rules, clade splits, and feature transformations before model fitting.
2. Construct phylogenetically paired contrasts and withhold entire related clades rather than random species rows.
3. Fit three nested models: **A** gain-only; **B** gain plus WGD; **C** gain-loss plus WGD and quality/phylogeny structure.
4. Report predictive calibration, held-out log score, residual phylogenetic pattern, parameter uncertainty, and sensitivity to alternative repeat libraries and measurement filters.
5. Run negative controls: shuffled repeat labels, permuted WGD dates, and annotation-quality-matched subsets. These test whether apparent mechanism is carried by confounding structure.
6. Return `EVIDENCE_OR_MODEL_ABSTAIN` when critical data are missing, paired contrasts are not independent, the quality gate fails, or model results depend on a single unreplicated clade.

## Scenario matrix and robustness

| Scenario | Purpose | Required interpretation |
|---|---|---|
| Baseline curated set | Test preregistered model ranking. | Conditional, not universal. |
| Conservative measurement filter | Remove weakly documented 1C values. | Stability assesses sensitivity to measurement provenance. |
| Repeat-library alternative | Change annotation library/classification. | Stability assesses family-annotation dependence. |
| WGD-date uncertainty | Propagate age/confidence alternatives. | WGD claims must retain uncertainty. |
| Leave-one-clade-out | Test transfer beyond close relatives. | Prevents pseudo-replication from random row splitting. |
| Trait-confounding set | Add declared life-history and phylogeny controls. | Prevents trait association from becoming causal narrative. |

## Statistical analysis plan

For species or lineage (i), the confirmatory model conceptually estimates log genome size from gain features (R_i), WGD-history features (W_i), and loss/compaction features (D_i), plus quality and phylogenetic structure. A hierarchical formulation allows coefficients to vary by major clade rather than forcing a global mechanism. Model comparison focuses on out-of-clade prediction and posterior predictive checks, not on a single in-sample fit statistic. Any coefficient whose direction is unstable across declared robustness scenarios is reported as uncertain.

## Validity threats and human review

- **C-value comparability:** cytotype and method differences may create false contrasts; genome-size database expertise is required.
- **Assembly and annotation bias:** repeat-rich genomes can be incompletely assembled or differently annotated; comparative-genomics review is required.
- **Phylogenetic non-independence:** species are not exchangeable rows; evolutionary-methods review is required.
- **Causal overreach:** trait links can reflect common ancestry or reciprocal causation; evolutionary ecology review is required.
- **Taxonomic and data inequity:** model-rich clades can dominate conclusions; curators must document coverage gaps rather than impute confidence.

## Expected outcome branches

1. **Bidirectional support:** Model C robustly outperforms A/B across multiple held-out clades. Claim: the combined framework improves conditional comparative explanation; not that it identifies a universal cause.
2. **Lineage-specific support:** different clades favor different balances. Claim: genome-size mechanisms are heterogeneous, motivating clade-aware theory.
3. **Simple-model support:** A or B performs as well as C. Claim: the added mechanism is not justified for the declared dataset.
4. **Abstention:** evidence gates fail or estimates are unstable. Claim: the dataset cannot support a directional mechanism ranking; identify the missing evidence.
