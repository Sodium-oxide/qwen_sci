# Idea Agent Portfolio: Evidence-Constrained Directions for Xenotransplantation

## Input boundary

This portfolio is derived from `survey_idea_handoff.json`. It uses the Survey Agent's accepted gaps `G1--G4`; it does not add biological findings, clinical outcomes, or unregistered citations. The search below is a **simulated, evidence-constrained portfolio process** rather than a claim that an autonomous MCTS execution produced empirical results.

## Seed reframing

The headline asks whether xenotransplantation can ``solve'' donor-organ shortage. The evidence suggests that this binary framing hides two separable questions:

1. Can a given pig organ demonstrate function with a clinically useful safety and durability profile?
2. Can that profile be converted into a monitored, manufacturable, regulated, and accessible source of organs?

The root problem is therefore not merely graft survival. It is a condition-dependent conversion from **candidate xenografts** to **deployable supplementary supply**.

## Portfolio

| ID | Direction | Gap alignment | Strength | Principal limitation | Status |
|---|---|---|---|---|---|
| D1 | Kidney durability and injury mechanism atlas | G1, G4 | Focused biological resolution | Does not explain system-scale shortage relief | Competitive |
| D2 | **XenoReadiness: mechanism-to-access readiness framework** | **G1, G2, G3, G4** | Links evidence boundaries to deployable supply without prescribing care | Requires transparent weights and cannot replace clinical evidence | **Selected primary** |
| D3 | Multi-organ capacity and economic scenario model | G2, G3 | Directly addresses supply capacity | Easily becomes assumption-driven without biological readiness gates | Competitive |
| D4 | Infection governance and longitudinal-surveillance framework | G3, G4 | Makes public-health obligations explicit | Too narrow to answer shortage relief alone | High-value complementary |
| D5 | Universal donor-pig optimization recipe | none sufficient | Appears actionable | Violates organ-specific and safety constraints; risks operational genetic-design claims | Rejected |

## Selected primary direction: XenoReadiness

**Title:** *XenoReadiness: A Mechanism-to-Access Readiness Framework for Translating Genetically Modified Pig Organs into a Safe, Scalable Supplement to Human Donation*

**Central hypothesis:** A xenograft pathway can be classified as a credible source of *deployable supplementary supply* only when evidence passes non-compensatory gates for (i) durability/function, (ii) immune injury, (iii) coagulation and physiological compatibility, (iv) microbiological safety and longitudinal surveillance, (v) manufacturing/quality capacity, (vi) regulatory/ethical readiness, and (vii) equity/access. High performance in one domain cannot compensate for failure in a deployment-critical domain.

**Scientific object:** an organ--indication--evidence package; initially demonstrated with a kidney-focused evidence case, while keeping the framework organ-agnostic.

**Intervention:** replace unstructured ``promising/not promising'' translation narratives with a provenance-bearing, domain-separated readiness assessment.

**Falsifiable predictions:**

- P1: At least one candidate case labelled promising by a biological-only summary will be reclassified as non-deployable or abstained by the gated framework because a system-level domain lacks evidence.
- P2: Preserving model type and observation horizon will change the confidence attached to at least one conclusion compared with pooling all supporting studies.
- P3: Sensitivity analysis will show that a bottleneck in surveillance, manufacturing quality, or access can eliminate a predicted shortage-relief benefit despite an improvement in biological performance.

**Why this is novel:** it converts the familiar list of barriers into a decision structure. It does not score away uncertainty, and it does not make a clinical recommendation. Instead, it makes the conditions for an assertive claim visible and creates an auditable path for withholding a claim.

## Simulated multi-route evolution trace

| Stage | Defect detected | Editing route | Resulting refinement |
|---|---|---|---|
| Root seed | ``Can solve shortage'' conflates efficacy and deployment | Problem decomposition | Split biological feasibility from deployable supply |
| Candidate A | Biological score hides infection/manufacturing failure | Non-compensatory gating | Add mandatory readiness domains |
| Candidate B | Mixed human and baboon evidence can be over-read | Evidence provenance | Attach model and time-horizon qualifiers |
| Candidate C | A framework can fabricate precision | Abstention design | Add `MODEL_OR_EVIDENCE_ABSTAIN` and missing-evidence rules |
| Selected D2 | System model can neglect justice | Equity audit | Make access-disparity analysis a required domain |

## Debate and selection audit

**D1 advocate:** A kidney-specific injury atlas is experimentally closer to biology and could produce sharper mechanisms.

**D2 advocate:** It is necessary but insufficient for the user question. A durable kidney does not quantify whether safely deployable supply increases.

**D3 advocate:** Capacity scenarios answer the shortage question directly.

**D2 rebuttal:** Capacity-only modeling risks treating a non-deployable graft as inventory. D2 retains the capacity question but conditions it on evidenced biological and governance gates.

**Decision:** Select D2 as the primary direction. Preserve D1 and D4 as modules inside the evidence schema; retain D3 as a sensitivity-analysis component rather than a standalone claim.

## Guardrails passed downstream

- This is `DESIGN_ONLY`; no living-recipient recommendation, enrollment, transplant, animal work, source-pig operation, pathogen work, or genetic-editing procedure is proposed.
- A brain-dead-human 54-hour kidney study is labelled `SHORT_TERM_HUMAN_FEASIBILITY`, not clinical durability.
- A nonhuman-primate heart study is labelled `PRECLINICAL_PROMISING`, not human outcome evidence.
- A domain with unavailable or non-transferable evidence triggers abstention rather than optimistic extrapolation.
