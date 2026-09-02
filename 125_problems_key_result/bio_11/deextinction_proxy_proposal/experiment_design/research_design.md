# ExperimentDesign Agent Output: ProxyGate Study Design

## Design status

**Execution policy: DESIGN_ONLY.** This document specifies a computational evidence-synthesis and decision-analysis study. It does not execute genetic engineering, cloning, assisted reproduction, animal experimentation, environmental release, or medical/veterinary procedures. `observed_results = []`.

## Research brief

**Primary direction:** D3 -- ProxyGate: Evidence-Gated Readiness Assessment for De-Extinction Proxies.

**Question:** Can an uncertainty-aware, non-compensatory readiness framework distinguish scientifically impossible, evidence-insufficient, and conditionally reviewable extinct-species proxy proposals more defensibly than genome-centered or unstructured narrative assessments?

**Primary hypothesis H1:** A candidate should be conditionally reviewable only when every mandatory gate meets its threshold under robust uncertainty analysis; a high score in one domain must not compensate for failure in another.

**Secondary hypothesis H2:** Explicit counterfactual comparison against conventional conservation portfolios will change at least some apparent proxy-benefit claims to `ABSTAIN`, `REQUIRES_EVIDENCE`, or `REJECT`.

## Candidate classes and negative controls

The study samples descriptive candidate classes rather than generating organisms:

| Class | Role in analysis | Expected evidence profile |
|---|---|---|
| C1: Recently extinct taxon with archived material and an extant close relative | Positive-possibility class | Potentially richer DNA and trait evidence; still subject to all other gates. |
| C2: Late Pleistocene mammoth-like case | Intermediate/ambitious class | Informative paleogenomics but nontrivial developmental, welfare, ecological, and governance uncertainty. |
| C3: Deeper-time ancient-DNA case | Evidence-limited class | Fragmentary information and greater reconstruction uncertainty. |
| C4: Non-avian dinosaur | Negative control | Must not be conditionally reviewable; demonstrates the distinction between fossil knowledge and recoverable biological reconstruction. |
| C5: Extant conservation alternative | Counterfactual comparator | Habitat protection, extant-relative protection, translocation, or other portfolio chosen case by case. |

The examples remain paper-based case classes. The study does not select a real release site or a living animal for intervention.

## Evidence-card protocol

For each candidate and proposed trait, create an evidence card with five separate fields:

1. **Observed genomic evidence:** provenance, molecule authentication status, coverage, and source reliability.
2. **Reconstructed or imputed evidence:** inference method, phylogenetic support, alternative reconstructions, and uncertainty interval.
3. **Trait evidence:** independent phenotype, physiological, developmental, or ecological evidence relevant to the claimed proxy function.
4. **Unknowns and risk:** developmental dependencies, pleiotropy, welfare implications, behavior, microbiome, maternal context, and multigenerational viability.
5. **Governance and conservation context:** legal status, data sovereignty/stewardship, affected rights-holders, local participation, opportunity-cost comparator, and required human review.

No field may convert an unknown into an observed result. Evidence cards must retain source IDs from the Survey registry.

## ProxyGate architecture

Each candidate is evaluated by five non-compensatory gates:

| Gate | Core question | Minimum evidence condition | Failure output |
|---|---|---|---|
| G1: Genomic provenance and reconstruction | What sequence state is actually supported? | Traceable observed/reconstructed/unknown distinctions and bounded uncertainty. | `REQUIRES_EVIDENCE` or `REJECT` |
| G2: Trait-to-function bridge | Is there independent support that proposed traits could yield the stated function? | Convergent trait evidence; alternatives considered. | `REQUIRES_EVIDENCE` |
| G3: Developmental and welfare protection | Can foreseeable welfare/developmental risks be bounded sufficiently for further review? | Independent specialist review and a credible risk register. | `REJECT` or `ABSTAIN` |
| G4: Ecological benefit and reversibility | Would the proxy improve a specific system relative to realistic alternatives? | Site-specific causal model, adverse scenarios, comparator portfolio, and reversal criterion. | `ABSTAIN`, `REQUIRES_EVIDENCE`, or `REJECT` |
| G5: Governance and opportunity cost | Is the proposal lawful, legitimate, rights-respecting, and non-displacing? | Authority, participation, data stewardship, benefit-sharing, and transparent resource comparison. | `REJECT` or `ABSTAIN` |

For gate scores (q_k \in [0,1]), thresholds \(\tau_k\), and uncertainty intervals \([\underline{q}_k, \overline{q}_k]\), the robust feasibility indicator is planned as:

\[
I_{\mathrm{gate}} = \prod_{k=1}^{5} \mathbb{1}\{\underline{q}_k \geq \tau_k\}.
\]

This formulation is a future model structure, not an estimated numerical result. It encodes that all gates must clear a conservative lower bound. A failure in welfare or governance is not offset by an attractive genomic score.

Among candidates that pass all gates, compute a transparent research-priority index only for ordering further review:

\[
P = I_{\mathrm{gate}} \min_{w \in \mathcal{W}} \sum_{j \in \{E,F,C\}} w_j\,s_j - \lambda U,
\]

where (s_j) represent evidence strength (E), prospective functional/ecological benefit (F), and comparator advantage (C); (\mathcal{W}) is a stakeholder-elicited, bounded weight set; (U) aggregates documented uncertainty; and (\lambda) controls conservatism. This score cannot turn a failing candidate into a passing one.

## Analysis plan

1. **Coding and provenance audit.** Two independent domain coders classify evidence-card statements as observed, reconstructed, proposed, or unknown. Disagreements are adjudicated by a documented rationale rather than silently averaged.
2. **Uncertainty propagation.** Vary evidence confidence, ecological scenario parameters, and allowable stakeholder weights over prespecified ranges. Report decision stability, not a single nominal rank.
3. **Negative-control testing.** Confirm that C4 is never conditionally reviewable and that low-evidence classes do not gain status simply from broad assumptions.
4. **Counterfactual comparison.** For each candidate, compare the proposed function to a conventional conservation alternative. Evaluate whether a claimed benefit remains positive under habitat, climate, coexistence, and resource-allocation scenarios.
5. **Ablation.** Remove each gate in turn. A useful architecture should reveal that genome-only or ecology-only scoring produces decisions that the full framework rejects or defers.
6. **Reproducibility package.** Publish the evidence-card schema, decision rules, source registry, scenario ranges, and an anonymized governance-review checklist. Do not publish sensitive location, cultural, or biological information without authorization.

## Decision rules and falsification

| Output | Meaning | Rule |
|---|---|---|
| `REJECT` | Proposal should not advance under the stated framing. | A hard welfare/governance failure, irreconcilable identity claim, or clearly nonviable reconstruction premise. |
| `ABSTAIN` | The framework cannot responsibly classify the proposal. | Critical contextual disagreement or uncertainty invalidates the decision model. |
| `REQUIRES_EVIDENCE` | The question remains researchable but not reviewable as a proxy proposal. | At least one scientific gate lacks adequate evidence. |
| `CONDITIONALLY_REVIEWABLE` | Eligible only for further human multidisciplinary review. | All gates pass robustly and alternatives have been transparently compared. |

The study fails H1 if a failing welfare, governance, or uncertainty gate can be masked by other dimensions. It fails H2 if counterfactual comparison never changes any classification, indicating that the ecological comparator module adds no decision value.

## Human review and safety requirements

Mandatory human review includes conservation geneticists; paleogenomicists; wildlife welfare and veterinary experts; ecologists; legal and regulatory experts; representatives of Indigenous peoples and local communities where relevant; and conservation funders or public-interest representatives. Any future move beyond this design would require separate approvals, law- and jurisdiction-specific assessment, animal-welfare oversight, data-governance agreements, and public-interest review. Those actions are outside this project.
