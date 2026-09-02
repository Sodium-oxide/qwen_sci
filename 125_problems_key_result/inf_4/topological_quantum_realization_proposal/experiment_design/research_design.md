# ExperimentDesign Agent Report

## Design objective

The selected Idea Agent direction, the **Braiding-Readiness Evidence Ledger (BREL)**, converts an abstract feasibility question into a staged study design for a future experimental team. The aim is to decide whether a candidate Majorana platform has earned the narrow label **braiding-ready topological-qubit primitive**. It does not purport to build or operate a computer in this project.

The design adopts a deliberately strong claim threshold. A platform does not pass because it produces a favorable trace. It passes only when five independently motivated columns agree: a reproducible candidate phase, nonlocal parity structure, an order-dependent fusion/exchange result, protection scaling, and an explicit universal-computation resource budget. The logic is conjunctive because the final claim is conjunctive.

## Research brief

**Object.** A future gate-defined network of proximitized semiconductor-superconductor islands designed to host a candidate Majorana sector.

**Central hypothesis.** If the network supports a controllable topological Majorana sector, a preregistered collection of phase, nonlocality, operation, and scaling observables will form a consistent pattern that matched trivial-control mechanisms cannot reproduce. A local trivial state may reproduce an individual low-energy signal but will fail at least one independent ledger column.

**Alternative explanations.** Local Andreev bound states; disorder- or multi-band-induced subgap states; electrostatic and readout drift; classical pulse-order artifacts; and ordinary coherence changes unrelated to topological encoding.

**Execution boundary.** This is a `DESIGN_ONLY` plan. It contains no device fabrication, cryogenic operation, microwave/RF control, measurement, model-training, numerical run, data acquisition, observed result, or claim of Majorana/braiding observation. Any future physical work must be approved and conducted by qualified laboratory personnel under their own safety, equipment, and institutional procedures.

## Study architecture

### D0 - Preregister the competing models and the evidence ledger

Before viewing any future experimental data, the team should define: (a) the compact topological candidate model; (b) plausible local-null model families; (c) the candidate and intentionally trivial device/network configurations; (d) all protocol orders; (e) the primary endpoints and classification thresholds; and (f) the blinded analysis and hold-out scheme. A digital twin may be used in future solely to check that the planned analysis can separate model families under stated noise assumptions; it must not be tuned on the data used for confirmatory inference.

The output is a versioned BREL schema. It contains the required metadata, the target effect direction for every ledger column, a predefined uncertainty treatment, a quality-control/exclusion policy, and a stop/go rule. The protocol should distinguish exploratory device diagnosis from confirmatory evidence. An exploratory trace may inspire a next design iteration but cannot silently become confirmatory proof.

### D1 - Candidate phase and reproducibility screen

The first physical-evidence gate asks whether a candidate gapped region and its proxy are reproducible across the defined device population. The independent variables include the declared gate trajectory, field/flux operating condition as provided by the qualified team, device class, and candidate-versus-trivial configuration. The dependent variables are a gap-proxy map, stability region, inter-device yield, and the candidate/control separation. This is a screening gate: a positive outcome supports a phase candidate, not non-Abelian computation.

The analysis should report all eligible devices, not only the best one. A hierarchical summary across batch and device is preferable to a headline trace. The gate fails if the same region is equally reproduced by the intentionally trivial control, if stability is not transferable across the declared batch boundary, or if an unplanned exclusion is required to obtain the effect.

### D2 - Nonlocality and parity-structure test

The second gate tests whether the relevant low-energy degree of freedom has a remote, parity-constrained response beyond the fitted local null model. It uses paired-end/readout behavior, remote-control perturbations, parity-sensitive outcomes, and a defined separation or length series. Candidate and control configurations should receive the same analysis code and calibration procedure. A valid analysis checks both the target statistic and the distribution of residuals.

A future D2 pass requires that held-out devices reject the declared local-null envelope at the preregistered uncertainty threshold and that the remote perturbation acts in the predicted direction. A pass does not yet establish braiding. A D2 failure is useful: it prevents a local signal from being promoted to a nonlocal encoding claim.

### D3 - Fusion/exchange order-dependence test

The third gate supplies the critical operational discrimination. It compares a proposed fusion or exchange path with path-reordered and matched pulse/readout controls. The endpoint is a predeclared order-dependent contrast in the fusion/parity outcome distribution, together with repeatability and calibrated readout bias. Because non-Abelianity is an order-sensitive multi-mode property, simple repetition of one path is not sufficient.

Future protocol design must include: a candidate ordering, an order-reversal or scrambling control, a local/trivial configuration, independent calibration references, blinded labels when feasible, and a full record of time ordering and configuration versions. The operation gate is passed only if the contrast reproduces in the specified held-out devices and cannot be recreated by the matched trivial protocol. A favorable target trace without these controls is classified as exploratory, not as a braiding result.

### D4 - Protection scaling and architecture translation

The fourth gate asks whether the observed primitive has engineering value. The future study estimates an error or instability proxy as a function of separated-encoding variables such as length/separation class, temperature set point, exposure/operation duration, and readout condition. It models common confounders such as drift, device disorder proxy, and finite-size hybridization. The goal is not to make a universal statement from one device but to measure whether the platform's protection mechanism improves the relevant error budget.

The architecture translation then records: which operations are protected; which are merely controlled; the readout contribution; the poisoning and thermal contribution; the connection between physical and logical error; and the source/error budget for a non-Clifford resource. Majorana/Ising operations do not become universal by assertion. The plan must describe an auditable non-Clifford path and quantify how it affects the full resource budget.

## Variables, controls, and endpoints

| Design element | Specification |
|---|---|
| Independent variables | Device class; candidate versus trivial control; gate trajectory; network path/order; separation class; temperature set point; duration; readout protocol; batch. |
| Dependent variables | Gap-proxy stability; nonlocal correlation; parity/fusion distribution; order contrast; error/poisoning proxy; reproducibility; logical resource estimate. |
| Essential controls | Matched trivial configuration; path-order scramble/reversal; calibration reference; blinded labels; hold-out devices/batches; common inclusion rule. |
| Primary endpoint | Conjunctive BREL classification: all five ledger columns meet their preregistered thresholds against their matched controls. |
| Secondary endpoints | Column-wise effect sizes and intervals; false-positive rate in controls; batch reproducibility; sensitivity to nuisance models; resource-overhead range. |

Negative results are valuable outputs. They map directly to the first unsupported link: phase, nonlocality, operation, protection, or architecture. This is preferable to an undifferentiated claim that a device ``failed to show Majoranas.''

## Formal decision logic

Let $P$, $N$, $B$, $S$, and $U$ denote the preregistered pass indicators for phase, nonlocality, braiding/fusion operation, protection scaling, and universal-resource accounting. The future confirmatory classification is

$$R_{\mathrm{BREL}}=P\cdot N\cdot B\cdot S\cdot U.$$

Each factor is one only after its target effect, matched control, quality-control, and reproducibility condition are satisfied. A zero should be reported with a diagnostic code; it must not be hidden in an aggregate score. For a numerical target statistic $T_j$ in ledger column $j$, the preregistration identifies its estimated effect $\hat T_j$, uncertainty interval, alternative-model sensitivity, and the corresponding control statistic. The classification condition has the generic form

$$\mathcal{G}_j=\mathbb{I}\{\hat T_j\in\mathcal{A}_j,\;\Delta(\hat T_j,\hat T^{\mathrm{control}}_j)>\delta_j,\;Q_j=1,\;H_j=1\},$$

where $\mathcal{A}_j$ is the expected admissible region, $\delta_j$ is a predeclared practical separation, $Q_j$ records quality-control status, and $H_j$ records hold-out reproducibility. Values and estimators are to be selected and justified by the future qualified team for its physical platform; this proposal deliberately does not invent them.

## Analysis and reproducibility plan

The future analysis freezes primary endpoints before unblinding, fits the candidate and null model families under the same data-governance rules, reports full distributions rather than selected traces, and separates confirmatory from exploratory work. When the required data structure exists, hierarchical models should represent device, batch, and session variation. Sensitivity analyses test reasonable nuisance model families. The report should give effect sizes and uncertainty alongside any hypothesis-test notation, rather than relying on a binary significance label.

Raw future data, instrument/configuration metadata, calibration records, and analysis environments require versioned archival under the host laboratory's policies. Device inclusion/exclusion, labels, protocol order, model version, and any unblinding point should be traceable. At least one held-out device batch should remain outside threshold setting. Summary-level evidence and a non-sensitive analysis specification should be released where institutional and intellectual-property rules allow.

## Risk and human-review register

| Risk | Design response | Required human review |
|---|---|---|
| Local mimic produces an attractive signal | Conjunctive multi-axis gate with matched trivial controls and null models | Condensed-matter theory and experimental review |
| Calibration loss produces a false null | Independent references and an explicit inconclusive state | Instrument and measurement review |
| Selection bias from many traces | Preregistration, blinding, full-distribution reporting, hold-out devices | Statistical review |
| Physical signature is overstated as fault tolerance | Separate phase, operation, protection, and universal-resource claims | Quantum-information architecture review |
| Laboratory/equipment safety | No execution in this artifact; future lab work follows approved local procedures | Laboratory safety and facility review |

## Handoff to Author

The Author Agent receives the ResearchBrief, BREL decision logic, the list of source-bound evidence cards, the staged D0--D4 method, the `DESIGN_ONLY` boundary, and the human-review register. It may report direct conditional conclusions: topological computing is theoretically realizable and current platforms can be assessed rigorously; a full realization claim should be earned through the multi-axis ledger. It may not state that a device was fabricated, cooled, measured, simulated, or shown to braid.
