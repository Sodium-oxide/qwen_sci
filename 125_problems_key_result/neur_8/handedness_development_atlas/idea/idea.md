# Idea Agent: Developmental Canalization and Context Expression Model

## Input synthesis

Survey evidence supports a stable population asymmetry but rejects a single-gene or single-region explanation. The Idea stage therefore treats handedness as a latent developmental phenotype with multiple observable expressions. It separates five layers: genetic liability, prenatal and early postnatal development, hemispheric neural organization, motor performance, and socially trained task preference.

## Candidate routes

### Route A - Single-pathway genetic explanation

Use the strongest GWAS loci and microtubule genes to predict right-hand preference. This route is easy to communicate but fails the survey's polygenic and phenotype-separation constraints. It also risks converting a small statistical association into a deterministic story.

### Route B - Brain-asymmetry localization

Search for one cortical region or language network that explains right-handedness. Imaging evidence makes this biologically attractive, but distributed asymmetries and left-hander heterogeneity make a single location unlikely. The route is retained as a mediator module, not as the final direction.

### Route C - Culture and training explanation

Explain the majority through writing instruction, tool design, and pressure against left-hand use. This route captures the observed influence of forced switching, but it cannot explain early developmental liability or the persistence of a majority across differently organized task environments.

### Route D - Developmental Canalization and Context Expression Model (DCCEM)

Model handedness as a latent, probabilistic neurodevelopmental state. Common and rare genetic variation affect the probability of asymmetric motor-circuit development; prenatal and perinatal events alter the developmental trajectory; and task environments transform the latent state into a reported preference that can be task-specific. The model predicts that culture has a larger effect on preference and writing hand than on bilateral motor-performance asymmetry, but that the effect is moderated by the latent developmental state.

### Route E - Evolutionary frequency-dependent model

Use population genetics and comparative laterality data to explain the persistent 1:10 ratio. The route is valuable for explaining stability, but it is underdetermined without individual-level developmental measurements and cannot alone resolve genetic-to-neural mediation.

## Primary direction

The Idea Agent selects **DCCEM** as the primary direction and uses Routes B and E as component modules. DCCEM is more ambitious than a catalog of correlations: it proposes that a latent developmental state can be estimated, tested longitudinally, and separated from the culturally shaped expression of hand use. It remains falsifiable because the latent state may fail to predict future phenotype, the proposed mediation may not replicate, or culture may shift performance as strongly as preference.

## Core claim

> Most people are right-handed because a distributed developmental system produces a population-level bias toward left-hemisphere/right-hand motor organization, while polygenic liability, developmental variation, and task-specific cultural exposure determine how strongly that bias is expressed and whether it appears as consistent right preference, mixed use, or left preference.

The claim is explicitly population-level. It does not imply that every individual has the same neural organization or that a person's handedness can be diagnosed from genotype.

## Falsification conditions

The primary direction should be weakened or rejected if any of the following occur in a preregistered, out-of-sample test:

1. A latent state built from early brain and motor measurements does not predict later hand preference better than age- and task-only baselines.
2. Common-variant and rare-variant terms fail independent replication or explain no incremental variance after family and developmental covariates.
3. Environmental pressure predicts writing hand but not preference or performance, or shifts bilateral performance to the same degree as reported preference.
4. The proposed brain-asymmetry mediator is unstable across sessions, scanners, ancestry groups, or developmental stages.
5. A single measured task produces the same apparent mechanism as a multi-task phenotype, showing that the model is an artifact of classification.

## Decision

DCCEM is selected as `PRIMARY_DIRECTION`. The next stage must implement a family-aware longitudinal design with repeated multi-task phenotyping, genotype and exome layers, non-invasive brain measures, and an explicit environment-by-development interaction. It must not execute interventions or report empirical outcomes.

