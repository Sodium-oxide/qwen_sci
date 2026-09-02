# Survey: Estimating How Many Species Exist on Earth

## Scientific reframing

The question ``How many species are there on Earth?'' has no single numerical answer until the target quantity is fixed. A scientifically operational version is:

> Given an explicitly stated species concept, taxonomic scope, spatial and environmental sampling frame, time window, evidence standard, and estimator, what bounded richness estimate and uncertainty interval are supported by the available observations?

This reframing prevents a common category error. Counts of formally named taxa, estimates of extant eukaryotic taxonomic species, and richness of microbial sequence clusters are useful but different estimands. They should be reported side by side only after their units and assumptions are made visible; they must not be summed as though they were measurements on a common scale.

## Survey method

The survey searched publisher pages and two scholarly metadata engines for work on global richness estimation, species concepts, cryptic diversity, sample coverage, environmental DNA (eDNA), operational taxonomic units (OTUs), and microbial scaling. Publisher pages were manually inspected for the two claims most likely to be misquoted: the eukaryote estimate of Mora *et al.* and the microbial estimate of Locey and Lennon. Metadata searches were cross-validated between OpenAlex and AnySearch when available. The survey is evidence synthesis only; it does not conduct new biodiversity sampling or generate a global estimate.

## Evidence map

| Evidence class | What it can support | Principal limitation | Design consequence |
|---|---|---|---|
| Named, curated taxon records | Documented taxa and taxonomic revision history | Description effort, synonymy, geographic bias | Keep a frozen registry version and a synonym policy |
| Morphology, ecology, and specimens | Defensible organismal delimitation | Cryptic lineages and uneven expert coverage | Preserve vouchers and integrate independent traits |
| Single-marker barcode clusters | Repeatable provisional units and discovery triage | Gene-tree/species-tree discordance and threshold choice | Report clusters as clusters, not automatically as species |
| eDNA/metabarcoding | Broad, noninvasive detection and replication | Primer bias, contamination, reference gaps, imperfect detection | Use blanks, controls, occupancy replication, and mock communities |
| Incidence and abundance samples | Coverage, unseen fraction, and domain-specific richness | Rare-tail assumptions and incomplete sampling frame | Report estimator family, coverage, and interval |
| Cross-domain extrapolation | Conditional large-scale predictions | Extrapolation can dominate direct evidence | Validate on held-out strata and disclose sensitivity |

## What the landmark estimates do and do not mean

Mora *et al.* (2011) identified a regularity in higher taxonomic classification and estimated approximately 8.7 million plus or minus 1.3 million standard error global **eukaryotic** species. This is a model-based estimate under its taxonomic framework, not a census of all life and not a directly observed count. Its contribution is to give a transparent higher-taxon extrapolation and to quantify the large description gap.

Locey and Lennon (2016) combined a global microbial and macrobial compilation with a dominance scaling law and a lognormal biodiversity model to predict up to (10^{12}) microbial ``species.'' Their result highlights the potentially immense microbial rare biosphere, but its numerical unit is contingent on microbial delineation, abundance distributions, sampling heterogeneity, and extrapolation. It cannot simply be added to the Mora estimate or treated as a count of universally accepted Linnaean species.

de Queiroz (2007) argues that several practical species criteria can be understood as evidence for separately evolving metapopulation lineages. This perspective supports a ledger that records the criterion and evidence used for each count. Bickford *et al.* (2007) further demonstrate why morphology-only inventories can miss cryptic diversity. Molecular evidence increases discovery capacity, but a molecular cluster remains an operational unit until its connection to a biological lineage is established under a declared protocol.

## Methods that should be integrated, not collapsed

1. **Taxonomic registries and vouchers** anchor names, nomenclatural changes, and physical evidence.
2. **Multi-locus or genomic delimitation** can test candidate lineages, but its assumptions and failure modes need explicit reporting.
3. **Metabarcoding and eDNA** broaden detection, especially for hard-to-observe organisms, while requiring laboratory and bioinformatic controls.
4. **Sample-coverage and incidence/abundance estimators** quantify unobserved richness within a stated sampling universe. They should provide uncertainty intervals rather than a single endpoint.
5. **Hierarchical integration** may compare complementary domains without erasing their different units. A global figure should be withheld whenever integration gates fail.

## Gap analysis

The literature offers strong methods for individual pieces of the problem but insufficient discipline in joining them. The recurring gaps are: (i) missing estimand declarations in public headline numbers; (ii) ambiguity between named species, lineage hypotheses, barcode index numbers, OTUs, and amplicon sequence variants; (iii) unequal sampling across habitats, latitude, depth, hosts, and taxonomic expertise; (iv) weak treatment of false negatives and false positives in molecular data; (v) rare-tail extrapolation with limited out-of-sample checks; and (vi) reporting formats that allow incomparable estimates to be read as a single dispute.

## Survey conclusion

The productive research target is not to select one of the public numbers. It is to create a reproducible pipeline that makes the counting unit, coverage, detection process, extrapolation model, and uncertainty auditable. The proposed downstream framework therefore treats a total as a versioned, scope-specific estimate rather than an immutable fact.

## Core sources

1. C. Mora *et al.*, ``How Many Species Are There on Earth and in the Ocean?'' *PLoS Biology*, 2011, doi: 10.1371/journal.pbio.1001127.
2. K. J. Locey and J. T. Lennon, ``Scaling laws predict global microbial diversity,'' *PNAS*, 2016, doi: 10.1073/pnas.1521291113.
3. K. de Queiroz, ``Species Concepts and Species Delimitation,'' *Systematic Biology*, 2007, doi: 10.1080/10635150701701083.
4. D. Bickford *et al.*, ``Cryptic species as a window on diversity and conservation,'' *Trends in Ecology & Evolution*, 2007, doi: 10.1016/j.tree.2006.11.004.
5. A. Chao and L. Jost, ``Coverage-based rarefaction and extrapolation,'' *Ecology*, 2012, doi: 10.1890/11-1952.1.
6. L. R. Thompson *et al.*, ``A communal catalogue reveals Earth's multiscale microbial diversity,'' *Nature*, 2017, doi: 10.1038/nature24621.
7. K. Deiner *et al.*, ``Environmental DNA metabarcoding,'' *Molecular Ecology*, 2017, doi: 10.1111/mec.14350.
8. S. Ratnasingham and P. D. N. Hebert, ``A DNA-Based Registry for All Animal Species,'' *PLoS ONE*, 2013, doi: 10.1371/journal.pone.0066213.
