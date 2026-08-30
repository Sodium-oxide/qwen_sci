# ExperimentDesign Agent — Design-Only Research Protocol

## 1. Research brief

**Selected direction:** D2, *Beyond Element 118: A Calibrated, Evidence-Aware Frontier for Conditional New-Element Reachability.*

**Research question:** Can a time-versioned, uncertainty-aware model distinguish a probable nuclear-stability barrier from a present technology/evidence barrier for possible elements beyond 118, and does it classify later documented historical outcomes better than simple baselines?

**Central hypothesis:** A three-layer model that separately represents physical stability, technology/evidence reachability, and proof-chain completeness will be more calibrated than stability-only and technology-only models, while abstaining on insufficient-evidence cases.

**Execution policy:** `DESIGN_ONLY`. This protocol does not propose, execute, optimize, or simulate a nuclear reaction; operate an accelerator; handle targets; configure a detector; or report observed elemental/nuclear results.

## 2. Scope and governance gate

The primary study is a retrospective, public-record and literature-metadata analysis. It may use published summaries, formal IUPAC/IUPAP reports, peer-reviewed nuclear-model outputs, and public facility descriptions that have a documented license/provenance. It must not collect non-public experimental records, publish operational nuclear parameters, or infer priority from a model score.

Formal discovery recognition and naming remain IUPAC/IUPAP responsibilities. The project can assess whether a future evidence packet is complete under a disclosed schema; it cannot decide that an element exists or that a team has discovery priority. Any physical follow-up would require a distinct, institution-approved research protocol, qualified staff, facility authorization, and an independent IUPAC/IUPAP assessment path.

## 3. Completion taxonomy and outcome states

The model has four outputs, none of which is a final atomic number:

1. **Physical plausibility:** conditional distribution over stability/decay survival under a stated nuclear-model ensemble.
2. **Scenario reachability:** conditional distribution over whether an abstracted technology scenario could produce, transport, and observe sufficient evidence.
3. **Proof sufficiency:** a structured completeness assessment of the public evidence chain for an identity/priority claim.
4. **Completion status:** an interpretive label showing whether a frontier is institutional, observational, technological, or physical; it never converts a conditional model output into a formal endpoint.

Historical record labels are deliberately conservative: `formally_recognized`, `subsequently_supported`, `not_confirmed_or_disputed`, `evidence_insufficient`, and `outside_scope`. A label may describe a record's documented assessment state, not a universal truth about a nuclide's existence.

## 4. Data contract and variables

| Variable family | Symbol/type | Definition | Source class | Proposal-time state |
|---|---|---|---|---|
| Nuclear identity | `nuclide_id` | Candidate \(Z,N\) label and provenance | Published table/model | Required |
| Theory ensemble | \(\mathcal{M}\) | Versioned nuclear-model predictions and disagreement | Peer-reviewed/public records | Required |
| Physical component | \(p_{\mathrm{phys}}\) | Conditional stability/survival plausibility with interval | Derived from \(\mathcal{M}\) | Planned |
| Scenario descriptors | \(\mathbf{t}\) | High-level, non-operational technology/evidence era descriptors | Published metadata | Required |
| Reachability component | \(p_{\mathrm{reach}}\) | Conditional observability/reachability with interval | Model output | Planned |
| Evidence graph | \(G_E\) | Claim, observation, linkage, corroboration, provenance fields | Reports/publications | Required |
| Proof component | \(p_{\mathrm{proof}}\) | Completeness/consistency score or abstention | Rules + review | Planned |
| Outcome state | `record_state` | Formal/retrospective documented status | IUPAC/IUPAP/public record | Required |
| Uncertainty | \(u\) | Interval, ensemble dispersion, missingness and review flags | Model/ledger | Required |

Confounders include changing theory generations, missing negative results, changes in reporting language, facility-era differences, publication bias, and the fact that a non-observation may be an evidence or resource limit rather than a physics limit. The design must record these uncertainties rather than encode them as negative labels.

## 5. Work packages

### WP1 — Versioned historical evidence corpus

Create a dataset card before modelling. Each record must preserve its source date, source type, claim state, relevant IUPAC/IUPAP assessment text where available, theory/model version, and high-level technology era. Separate `claim_date`, `assessment_date`, and `recognition_date`; they answer different questions. Link statements to source passages rather than turning citations into decontextualized numeric labels. Maintain an exclusion ledger for inaccessible, ambiguous, duplicate, or out-of-scope records.

**Exit condition:** A reviewer can trace every outcome label to a source and can identify missingness/ambiguity. If label provenance is inadequate, the record is quarantined and cannot enter the primary endpoint.

### WP2 — Theory and evidence feature registration

Register all features before training. The physical layer may use published uncertainty summaries and model disagreement, but it may not assert a definitive unobserved mass, half-life, or cross section. The scenario layer may contain normalized categories describing public technology/evidence eras, but no operating parameters or facility instructions. The evidence layer contains claim-graph fields such as identity linkage, temporal correlation, corroboration status, provenance, and review status. Its schema must be checked by nuclear-physics and discovery-governance reviewers.

**Exit condition:** Each feature has a scientific interpretation, source provenance, and a statement of what it cannot prove. No feature is allowed to encode an outcome from the future validation window.

### WP3 — Time-split calibration and abstention model

Use historical time splits. For each cutoff \(\tau\), fit only to information public on or before \(\tau\), then assess predictions against later documented outcomes. Group related records so near-duplicate publications or shared claims do not leak across train/test partitions. Compare:

- **B0 Stability-only:** physical-model features with uncertainty.
- **B1 Scenario-only:** high-level reachability/evidence-era descriptors.
- **B2 Evidence-only:** proof-chain completeness without a stability model.
- **D2 Three-layer:** separate physical, scenario-reachability, and proof-sufficiency components plus abstention.

The proposed combined representation is intentionally conditional:

\[
\mathcal{F}(c)=\big(p_{\mathrm{phys}}(c\mid\mathcal{M}),\;p_{\mathrm{reach}}(c\mid\mathbf{t}),\;p_{\mathrm{proof}}(c\mid G_E),\;u(c)\big).
\]

It is a frontier vector, not a probability that a new element exists. A transparent decision layer may return `conditional_priority`, `evidence_insufficient`, `currently_unreachable_under_scenario`, or `abstain`; no label is `discovered`.

**Exit condition:** Calibration, discrimination, and abstention behavior meet preregistered criteria across multiple historical cutoffs. If not, publish the failure analysis and retain only the corpus/taxonomy contribution.

### WP4 — Expert evidence-schema review and counterfactual audit

Conduct structured review of selected records. Ask independent domain reviewers whether the schema distinguishes: a model prediction from an observation; an observation from a validated identity; a validated identity from a formal priority decision; and a changed instrument from a lowered proof standard. Use counterfactual tests in which one evidence link is masked to verify that the system moves toward abstention instead of generating confidence.

**Exit condition:** Reviewers can explain every model state in source-grounded terms. If they cannot, the output remains research metadata, not a decision-support result.

### WP5 — Future prospective registry

The future-facing output is a registry format, not an experiment. Before a new claim is assessed, the registry records the technology scenario, frozen model version, evidence schema, and pre-observation prediction. Later assessment can then test whether the model was calibrated without retroactively changing its criteria. A future public claim remains external to this project until the competent institutional process has concluded.

## 6. Endpoints and decision rules

### Primary endpoint

At each time cutoff, compare D2 against B0 and B1 on calibration of later documented record states while accounting for abstentions. The primary analysis uses a preregistered proper scoring rule and reliability analysis; a lower error value alone is not sufficient unless coverage and abstention behavior are reported. This endpoint evaluates forecasting discipline, not new-element production.

### Secondary endpoints

- Calibration and interval coverage by theory generation and technology era.
- Discrimination between subsequently supported/recognized records and evidence-insufficient or not-confirmed records, only where source labels are adequate.
- Abstention precision: fraction of abstentions linked to documented missingness, ambiguity, or out-of-distribution conditions.
- Evidence-graph completeness and inter-reviewer agreement.
- Sensitivity of frontier labels to alternative theory ensembles and source inclusion choices.
- Rate at which a scenario change alters `currently_unreachable` to `conditional_priority`, without changing the physical component.

### Negative and failure outcomes

The study reports a negative result if D2 does not outperform simpler baselines, calibration degrades at later cutoffs, theory disagreement dominates all classification, or reviewers reject the evidence schema. These outcomes are scientifically valuable because they show that a physical/technology boundary cannot yet be separated reliably. The study never translates a negative model result into a claim that the periodic table is complete.

## 7. Reproducibility and reporting contract

Every run must archive, subject to source rights: dataset card; source/provenance ledger; time cutoff; theory/model versions; feature dictionary; split identifiers; model configuration; uncertainty calculation; abstention policy; baseline definitions; evidence graph; review records; and all excluded/ambiguous cases. Every table must label a value `literature_record`, `model_prediction`, `review_assessment`, `not_available`, or `out_of_scope`. The manuscript must state: **“This model characterizes conditional reachability and evidence sufficiency; it does not establish the existence, discovery, priority, or name of a new element.”**

## 8. Required human reviews

| Review | Trigger | Authority |
|---|---|---|
| Nuclear-theory interpretation | Choice of model ensemble and physical features | Qualified nuclear-theory reviewer |
| Historical/evidence provenance | Record label or evidence graph is ambiguous | Domain historian or discovery-evidence reviewer |
| Discovery-governance boundary | Any language about identity, priority, or recognition | IUPAC/IUPAP process-aware reviewer |
| Data rights and confidentiality | Source is not clearly public/reusable | Data steward / rights holder |
| Physical-work boundary | Any transition toward actual nuclear experimentation | Authorized facility and institutional processes |
