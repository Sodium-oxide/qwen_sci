# ExperimentDesign Agent: CoastWeave Design-Only Research Protocol

## 1. Scope and safety boundary

**Selected idea:** D3, *CoastWeave: An Equity-Constrained, Climate-Robust Portfolio Model for Land-Sea Coastal Conservation*.

**Execution policy:** `DESIGN_ONLY`. This is a computational evidence-integration and scenario-design study. It does not enforce fishing rules, establish a marine protected area, build waste infrastructure, alter land use, restore habitat, sample biota, collect community data, recruit participants, make regulatory decisions, or provide site-specific management advice.

**Research unit:** a declared coastal-seascape planning cell, with a linked watershed pressure layer and an associated set of ecological, governance, and livelihood evidence cards. No geographic cell is evaluated in this proposal.

## 2. Research questions and primary estimand

| Research question | Planned estimand | Decision target |
|---|---|---|
| RQ1 | Does an equity/capacity-gated portfolio differ from an ecological-only portfolio? | Classification and reason trace | Detect hidden implementation or distribution failures |
| RQ2 | Which pressure and intervention domains are bottlenecks? | Domain sufficiency and uncertainty map | Identify research/monitoring gaps |
| RQ3 | Which portfolios remain acceptable across climate and socioeconomic scenarios? | Minimum scenario performance and regret | Climate robustness, not forecast certainty |
| RQ4 | When should the model abstain? | Abstention rate and cause | Prevent unsupported local claims |

The primary estimand is not ``which intervention will improve a real coast.'' It is whether a specified evidence package supports a conditional, climate-robust, equity-constrained **portfolio-readiness classification**.

## 3. Intervention and outcome ontology

The intervention library has six separable classes: `nutrient_source_reduction`, `plastic_leakage_prevention`, `habitat_blue_carbon_protection_or_restoration`, `area_based_fisheries_management`, `observing_and_data_access`, and `governance_capacity_strengthening`. These labels are research categories, not operational instructions.

Outcome domains are: coastal nutrient-pressure proxy, plastic-leakage proxy, habitat/ecosystem-function proxy, fisheries/ecological-connectivity proxy, climate-exposure proxy, monitoring observability, implementation capacity, procedural legitimacy, and livelihood/equity safeguard status. Each outcome carries a source, scale, direction, uncertainty class, and transferability qualifier.

## 4. Evidence cards and non-compensatory gates

An Evidence Card contains the planning scale, ecosystem type, pressure/intervention mechanism, outcome measure, observation horizon, evidence setting, source ID, transfer limits, uncertainty, and permitted-claim ceiling. The initial demonstrator is populated only with the Survey registry; it does not infer effect sizes where evidence is conceptual or context-specific.

The critical gates are: (G1) pressure-mechanism plausibility; (G2) ecological safeguard; (G3) monitoring/observability; (G4) implementation capacity; (G5) procedural legitimacy and participation; and (G6) equity/livelihood safeguard. Any adverse or insufficient critical gate prevents a portfolio from being classified as implementation-ready.

For portfolio $p$ in scenario $s$, define $E_{psd}$ as the registered evidence status for critical domain $d$ and $T_{psd}$ as its transferability qualifier. The gate is:

\begin{equation}
R_{ps}=\prod_{d\in\mathcal{D}_{\mathrm{critical}}}\mathbb{I}(E_{psd}=\mathrm{sufficient})\mathbb{I}(T_{psd}\geq\tau_d),
\label{eq:coastweave-gate}
\end{equation}

where $\tau_d$ is declared before comparison. A favorable ecological score cannot offset missing capacity, participation, monitoring, or equity evidence.

## 5. Portfolio and scenario analysis

Model A ranks portfolios on ecological pressure and ecosystem proxies only. Model B adds gates in \eqref{eq:coastweave-gate}, scenario analysis, and equity/capacity constraints. Portfolios are evaluated under a bounded matrix of climate/runoff, coastal exposure, socioeconomic/implementation, and data-availability assumptions.

For gated portfolios, an optional conditional objective is:

\begin{equation}
U_{ps}=w_EB_{ps}+w_PP_{ps}+w_HH_{ps}+w_LL_{ps}-w_CC_{ps}, \qquad \sum w=1,
\label{eq:portfolio-objective}
\end{equation}

where $B_{ps}$ is ecological-benefit evidence, $P_{ps}$ pressure-reduction evidence, $H_{ps}$ habitat/connectivity evidence, $L_{ps}$ livelihood-safeguard evidence, and $C_{ps}$ conditional implementation burden. Equation \eqref{eq:portfolio-objective} is only a transparent comparison aid after the gates pass; it is not a prediction of environmental outcomes.

Robustness is measured as the minimum eligible conditional score over scenarios, with a separate regret report relative to the best eligible scenario portfolio. Weights and thresholds are varied. If ranking depends on arbitrary assumptions, the state is `EVIDENCE_OR_MODEL_ABSTAIN`.

## 6. Decision states and challenge cases

| State | Interpretation | Prohibited conclusion |
|---|---|---|
| `MECHANISMALLY_PLAUSIBLE` | Evidence supports a linked pressure-intervention rationale | A real coast will improve |
| `SCENARIO_CONDITIONAL` | A portfolio remains eligible under stated assumptions | A universal best portfolio exists |
| `EQUITY_OR_CAPACITY_BLOCKED` | A critical distributional, legitimacy, or capacity gate fails | Ecological gain justifies implementation |
| `EVIDENCE_OR_MODEL_ABSTAIN` | Evidence is missing, non-transferable, or assumption-dominated | A directional local recommendation |

The design is stress-tested using: (i) an ecologically favorable MPA/habitat portfolio with inadequate enforcement capacity; (ii) a nutrient/plastic portfolio that shifts cost or participation burdens disproportionately to a dependent community; (iii) a historical optimum that fails under a high-runoff/high-exposure scenario; and (iv) a data-rich model that cannot be transferred to a data-poor coastline.

## 7. Quality, ethics, and human review

- Keep coastal, watershed, and governance evidence in separate linked modules; do not fabricate a common effect size.
- Predeclare scales, transferability limits, gates, scenario ranges, and weights.
- Report sensitivity, disagreement, and abstention rather than filling missing evidence with assumed benefit.
- Require ecology, hydrology, fisheries, waste systems, climate science, governance, Indigenous/local knowledge, social science, and equity review before any local interpretation.
- Treat local/Indigenous knowledge and community participation as substantive governance inputs; this proposal does not collect or represent any such knowledge.

## 8. Deliverables and falsification

Expected deliverables are an intervention ontology, evidence-card registry, gate matrix, scenario/robustness report, equity/capacity challenge log, and a claim-validation checklist. The idea is weakened if gating never changes an ecological-only ranking, if scenario robustness offers no extra discrimination, or if the result depends on unbounded weights rather than registered evidence.
