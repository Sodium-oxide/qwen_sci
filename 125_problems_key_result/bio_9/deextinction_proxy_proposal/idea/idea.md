# Idea Agent Output: ProxyGate Portfolio

## Input and constraints

The Idea Agent received the Survey handoff and preserved its seven accepted gaps (`G1`--`G7`). Every candidate below is a research proposition, not an implemented conservation intervention. The agent rejects directions that treat an edited or selectively bred organism as an exact recovered species, that collapse uncertainty into a single similarity number, or that bypass welfare and governance conditions.

## Candidate portfolio

| Direction | Novel mechanism | Gap alignment | Falsifiability | Decision |
|---|---|---|---|---|
| D1: Ancient-Genome Completeness Atlas | Map observed, reconstructed, and missing sequence across candidate lineages. | G2 | Can be tested against independent assemblies and provenance audits. | Competitive, but genomics-only. |
| D2: Ecological-Replacement Scenario Engine | Compare ecological-function scenarios and conventional conservation alternatives. | G5, G6 | Can fail if benefit reverses under plausible site assumptions. | Competitive, but weak on developmental/welfare viability. |
| D3: ProxyGate | Use hard gates for genomic evidence, phenotype mapping, welfare/development, ecological benefit, and governance; use uncertainty-aware scoring only within gates. | G1--G7 | Can reject genomic-strong candidates; can fail negative-control discrimination tests. | **Selected primary direction.** |
| D4: Mammoth-only edited-elephant pathway | Focus on one charismatic case. | G2--G5 | Narrow technical claims could be tested, but the direction risks sliding into implementation-specific reproductive detail. | High risk; not selected. |

## Selected primary direction

**D3 -- ProxyGate: Evidence-Gated Readiness Assessment for De-Extinction Proxies.**

ProxyGate separates two questions that are often blended:

1. Is there enough evidence to formulate a bounded proxy hypothesis?
2. Even if one is formulable, would research move beyond analysis without unacceptable welfare, ecological, governance, or opportunity-cost conditions?

The central hypothesis is that an integrated framework with non-compensatory gates will classify some candidates as **REJECT**, **ABSTAIN**, or **REQUIRES EVIDENCE** even when their genomic evidence score is high. This is a substantive prediction. If the framework routinely awards conditional reviewability to candidates with missing trait evidence, unclear welfare status, or unsupported ecological benefit, it has failed its purpose.

## MCTS-style idea evolution summary

| Step | Defect detected | Operation | Result |
|---|---|---|---|
| Root | ``Can we revive a mammoth?'' conflates identity and feasibility. | Reframe from resurrection to proxy readiness. | Bounded scientific object. |
| Expansion 1 | Genome-centered route ignores phenotype uncertainty. | Add observation/imputation/unknown evidence-card layers. | Trait claims become auditable. |
| Expansion 2 | Feasibility score could trade off welfare against technical attractiveness. | Convert welfare and governance into hard gates. | Non-compensatory safeguards. |
| Expansion 3 | Ecological benefit is asserted rather than compared. | Add counterfactual scenario and opportunity-cost comparator. | Conservation claim becomes falsifiable. |
| Selection | Separate modules can still produce an arbitrary final rank. | Add uncertainty propagation, negative controls, and abstention outputs. | Decision architecture selected as D3. |

## Primary falsification conditions

The primary direction should be rejected or redesigned if any of the following occurs:

- A high-genomic-evidence candidate passes despite unresolved developmental/welfare or legitimacy barriers.
- The framework cannot classify a non-avian dinosaur as non-reviewable without manually hard-coding the answer.
- An apparent ecological benefit disappears, reverses, or is dominated by a conventional conservation comparator under credible scenarios.
- The final decision is driven primarily by missing-data assumptions rather than observed evidence.
- Independent assessors cannot reproduce gate reasons from the evidence cards and decision log.

## Handoff to ExperimentDesign

Design a computational evidence-synthesis and robust decision-analysis study. It must compare candidate classes rather than conduct biological manipulation. It must return only `REJECT`, `ABSTAIN`, `REQUIRES_EVIDENCE`, or `CONDITIONALLY_REVIEWABLE`; `CONDITIONALLY_REVIEWABLE` means eligible for further multidisciplinary human review, never an authorization to create or release animals.
