# ExperimentDesign Agent: Design-Only Protocol for XenoReadiness

## 1. Intake and scope

**Selected direction:** D2, *XenoReadiness: A Mechanism-to-Access Readiness Framework for Translating Genetically Modified Pig Organs into a Safe, Scalable Supplement to Human Donation*.

**Research objective:** evaluate whether a provenance-aware, non-compensatory readiness framework can distinguish (a) biological promise, (b) short-term human feasibility, (c) conditional trial readiness, and (d) system deployment readiness for a specified organ--indication pathway.

**Execution policy:** `DESIGN_ONLY`. This is a computational evidence-integration and scenario-analysis design. It does not recruit people, assign treatment, perform transplantation, maintain source animals, culture organisms, perform pathogen assays, edit genomes, conduct surgery, or provide medical advice.

## 2. Research questions and estimands

| Question | Estimand | Decision target |
|---|---|---|
| RQ1 | Does a gated readiness model alter classification relative to a biological-only summary? | Classification difference and reason trace |
| RQ2 | Which evidence domains become bottlenecks for a given organ--indication package? | Domain-level sufficiency and missingness map |
| RQ3 | Under plausible uncertainty, can a pathway support an inference of deployable *supplementary* supply? | Conditional supply-readiness conclusion, not a clinical prediction |
| RQ4 | Are conclusions robust to model-transfer, duration, quality-capacity, surveillance, and access assumptions? | Sensitivity and abstention rate |

The primary estimand is **not** ``will xenotransplantation replace all donated organs?'' It is whether a proposed pathway satisfies enough evidence-conditioned requirements to support a statement of *potential deployable supplementary supply* under explicit assumptions.

## 3. Evidence unit and provenance

The analytical unit is an **Evidence Card** containing: organ and indication, study setting, recipient model, observation horizon, outcome class, mechanism domain, source identifier, evidence level, transfer limitations, and missing-data status. Every assertion retains a pointer to the Survey source registry; narrative claims without a card are excluded.

The initial demonstrator uses the following bounded evidence cases:

- `KIDNEY-HUMAN-SHORT`: two brain-dead human recipients, 54-hour kidney feasibility signal [S1].
- `HEART-NHP-DURABILITY`: pig-to-baboon cardiac durability signal [S2].
- `MECHANISM-IMMUNE-COAG`: review-level mechanism evidence [S3, S4].
- `GOVERNANCE-INFECTION`: infection and regulatory evidence [S5, S6].

These are not pooled into a clinical effect estimate. Different organs and evidence settings remain stratified.

## 4. Variables and readiness domains

| Domain | Operational variable | Evidence interpretation | Failure/unknown rule |
|---|---|---|---|
| D1 Function and durability | function signal, observation horizon, organ relevance | supports feasibility only at its observed setting | Missing durable evidence blocks deployment claim |
| D2 Immune injury | documented rejection/injury status and uncertainty | identifies residual immune risk | Inadequate evidence yields abstention |
| D3 Coagulation/physiology | compatibility and dysfunction evidence | identifies coupled vascular/physiological risk | Unresolved critical incompatibility fails gate |
| D4 Microbiological safety | donor/recipient surveillance governance evidence | assesses managed, not eliminated, risk | Missing long-term monitoring plan fails gate |
| D5 Manufacturing and quality | traceability, qualified production, release/quality evidence | assesses whether candidate organs can become qualified products | Unsupported capacity blocks supply claim |
| D6 Regulation and ethics | oversight, consent/follow-up feasibility, accountability | assesses legal/social deployability | Unresolved requirement blocks ordinary deployment |
| D7 Equity and access | access scenario, center concentration, follow-up burden | assesses distributive reach of a claimed supply increase | Severe access concentration prevents general shortage claim |

## 5. Non-compensatory classification logic

For case \(c\), let \(E_{cd}\) be the evidence status of domain \(d\), taking values `sufficient`, `adverse`, `insufficient`, or `not_applicable`; let \(T_{cd}\) be the transferability qualifier. The eligibility indicator is:

\begin{equation}
R_c=\prod_{d\in \mathcal{D}_{\mathrm{critical}}}I(E_{cd}=\mathrm{sufficient})\,I(T_{cd}\geq\tau_d),
\label{eq:readiness-gate}
\end{equation}

where \(I(\cdot)\) is an indicator, \(\mathcal{D}_{\mathrm{critical}}\) is the declared critical-domain set, and \(\tau_d\) is a predeclared minimum transferability standard. Equation \eqref{eq:readiness-gate} deliberately prevents a high score in one domain from compensating for an unexamined safety or governance requirement.

When domains pass their gates, an optional transparent scenario score may summarize remaining uncertainty:

\begin{equation}
Q_c=\sum_{d=1}^{7}w_dq_{cd}, \qquad \sum_{d=1}^{7}w_d=1,
\label{eq:conditional-score}
\end{equation}

where \(q_{cd}\) is an explicitly elicited conditional assessment and \(w_d\) is a stakeholder-tested weight. The score cannot override a failed gate in \eqref{eq:readiness-gate}; it is used only to compare already eligible scenarios. Weights are reported, varied, and never represented as observed clinical probabilities.

## 6. Decision states

| State | Minimum interpretation | Disallowed inference |
|---|---|---|
| `PRECLINICAL_PROMISING` | supportive nonhuman or mechanistic signal | human safety or efficacy |
| `SHORT_TERM_HUMAN_FEASIBILITY` | bounded human model shows early function | durable living-recipient benefit |
| `CONDITIONAL_TRIAL_READINESS` | evidence package meets predeclared research-readiness conditions | routine clinical deployment |
| `SYSTEM_DEPLOYMENT_NOT_ESTABLISHED` | a critical biological, governance, capacity, or access gate is unresolved | shortage relief at scale |
| `MODEL_OR_EVIDENCE_ABSTAIN` | evidence is too sparse or non-transferable for classification | an optimistic or negative definitive claim |

The kidney brain-dead-human card can enter only `SHORT_TERM_HUMAN_FEASIBILITY` under its present evidence boundary. The pig-to-baboon heart card can enter only `PRECLINICAL_PROMISING` for a human claim. These are initial rules, not observed results of the proposed study.

## 7. Analysis plan

1. **Register a claim dictionary.** Each candidate assertion is labelled as feasibility, durability, immune/coagulation, infection, capacity, governance, or equity and linked to a source card.
2. **Construct evidence cards.** Two reviewers independently assign setting, observation horizon, outcome class, transferability, and domain status; conflicts are adjudicated and retained in a trace log.
3. **Apply two models.** Model A summarizes biological evidence only. Model B applies the seven-domain non-compensatory framework. Compare decision state and the reason for any disagreement.
4. **Run bounded scenarios.** Vary unknown durability, surveillance feasibility, manufacturing/quality throughput, regulatory delay, and access concentration over transparent low/base/high assumptions. Do not interpret any scenario as a clinical forecast.
5. **Conduct challenge cases.** Test whether the model refuses overclaiming in three counterexamples: (i) strong graft function but no scalable quality system; (ii) strong biological signal but no implementable surveillance/follow-up; and (iii) technically feasible care limited to a few high-resource centers.
6. **Report abstentions.** A high abstention rate is a result about evidence insufficiency, not a failure to be hidden.

## 8. Quality, uncertainty, and bias control

- Keep direct human, brain-dead-human, nonhuman-primate, and review-level evidence separate.
- Record source type and observation horizon before interpretation.
- Predeclare gate definitions and scenario ranges; publish all changed assumptions.
- Run a biological-only comparator to reveal the value and cost of system gating.
- Perform sensitivity analysis on every domain weight and transferability threshold.
- Require an external transplant-medicine, infectious-disease, bioethics, regulatory, and health-equity review before any clinical interpretation.

## 9. Safety, ethics, and human review

This design cannot determine clinical eligibility, prescribe immunosuppression, validate donor conditions, or authorize transplantation. It deliberately omits operational protocols, individual-level data, intervention assignments, invasive procedures, pathogen manipulation, genetic-modification methods, and medication detail. Any future clinical, animal, genomic, or infectious-disease work would require separate protocol development, ethics and regulatory review, biosafety governance, accredited facilities, and qualified specialist supervision.

## 10. Expected output and falsification

Expected outputs are a structured evidence registry, domain-readiness matrix, conditional decision memo, scenario table, counterexample log, and a list of evidence gaps. The primary idea is weakened if gated classification adds no decision-relevant distinction over biological-only evidence, or if its conclusions depend entirely on unconstrained assumptions. It is strengthened if it exposes reproducible reasons why an apparently promising graft cannot yet be counted as deployable supply.
