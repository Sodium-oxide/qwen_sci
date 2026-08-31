# Idea Agent Portfolio: Genome Size Evolution

## Candidate directions

### D1 - Repeat Atlas
Build a phylogenetically standardized atlas of repeat-family abundance and 1C values. This is valuable for G2 and G5 but weak on time direction: static annotations alone cannot distinguish gain from loss.

### D2 - Post-WGD Compression Clock
Date whole-genome duplications and quantify rediploidization-associated DNA removal in paired lineages. This is strong for G3 but too narrow if it ignores TE turnover in lineages without recent WGD.

### D3 - GenomeFlux (selected primary direction)
Infer a lineage-specific **gain-loss balance** from dated 1C values, repeat-family composition, WGD history, and deletion/compaction proxies. Compare a gain-only model against a bidirectional model and make every inference conditional on sampling and annotation-quality gates. GenomeFlux directly joins G1-G5 and turns the “C-value enigma” into falsifiable model comparisons.

### D4 - Nucleotypic Constraint Experiment
Test whether genome size predicts cell-cycle or ecological traits. This is scientifically relevant to G4, but it should be a downstream extension because cross-lineage trait association alone cannot explain DNA accumulation histories.

## MCTS-style evaluation record

| Direction | Novelty | Mechanistic clarity | Falsifiability | Evidence alignment | Decision |
|---|---:|---:|---:|---:|---|
| D1 | medium | high | medium | high | competitive component |
| D2 | medium | high | high | medium | competitive component |
| D3 | high | high | high | high | **selected primary** |
| D4 | medium | medium | medium | medium | future extension |

## Selected idea

**GenomeFlux: a phylogenetically paired, evidence-gated framework for inferring genome-size gain-loss balance.** The core prediction is not that all large genomes arise by TE expansion or that all small genomes arise by deletion. Instead, a bidirectional model should explain held-out genome-size contrasts better than a gain-only model when repeat-family trajectories, WGD timing, and compaction/deletion proxies are informative. If quality gates fail, the valid output is `EVIDENCE_OR_MODEL_ABSTAIN`.

## Falsification conditions

1. A gain-only model matches or exceeds the gain-loss model after matched cross-validation and complexity penalty.
2. Apparent gain-loss effects disappear after controlling for phylogeny, assembly continuity, repeat-library completeness, and measurement provenance.
3. Independent related clades disagree systematically with the inferred direction under the same preregistered rules.
4. WGD timing or repeat annotation cannot be assigned a quality class adequate for the target inference.
