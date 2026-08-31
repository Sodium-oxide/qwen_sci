# Idea Agent Portfolio: LifeTrace Evidence Ledger

## Intake and constraints

The Idea Agent received the verified Survey handoff for project "astr_10_alone_universe_proposal", survey run "survey-astr10-life-detection-001", and context identity "ctx-astr10-life-detection-v1". The accepted gaps are G1-G5. Any candidate that treats a habitable-zone location as life, a single molecule as proof, or a non-detection as a universal absence claim is rejected before search.

## Seed and route matrix

| Seed | Innovation route | Candidate intervention | Decision |
|---|---|---|---|
| Context is needed for a biosignature (G1) | Evidence decomposition | Bind spectrum, star, planet, retrieval, and abiotic model in one candidate record. | Retained |
| Negative results need coverage semantics (G2) | Counterfactual testing | Require recovery efficiency and detectable-class declaration. | Retained |
| Modalities use disjoint confirmation language (G3) | Interface unification | Use one provenance and falsification ledger for remote, radio, and in-situ evidence. | Retained |
| Follow-up must discriminate hypotheses (G5) | Decision-theoretic routing | Select the observation with maximum expected separation of biology, technology, abiotic chemistry, and artifact. | Retained |

The search rejected a universal "alien-life probability score" because its apparent precision would be dominated by unknown priors and it would obscure the difference between target priority, candidate evidence, and confirmed interpretation.

## Portfolio

### Selected primary idea: LifeTrace

**LifeTrace: A Contextual Multi-Modal Evidence Ledger for Life Detection** is an auditable inference framework spanning exoplanet spectroscopy, technosignature searches, and in-situ ocean-world analysis. It attaches each candidate measurement to:

1. a measurement-and-provenance record;
2. environmental context and instrument sensitivity;
3. explicit alternative hypotheses: abiotic, biological, technological, instrumental artifact, terrestrial interference, and contamination;
4. an evidence-strength ladder; and
5. a value-ranked next observation that can change the current status.

LifeTrace does not decide whether a planet is inhabited from one feature. Its output is a bounded status: CONTEXT_INSUFFICIENT, ABIOTIC_OR_ARTIFACT_NOT_EXCLUDED, BIOLOGICAL_CANDIDATE_REQUIRES_FOLLOW_UP, TECHNOLOGICAL_CANDIDATE_REQUIRES_INDEPENDENT_CONFIRMATION, or NEGATIVE_RESULT_SENSITIVITY_LIMITED. A higher confidence status is allowed only when a pre-registered collection of independent measurements rejects the relevant alternatives.

The research innovation is a common contract for otherwise separate fields. A remote atmospheric candidate must record stellar ultraviolet context, mass and radius constraints, retrieval degeneracy, co-occurring gases, time variability, and abiotic pathways. A radio candidate must record on-target localization, signal drift, injection-recovery performance, interference checks, repeat observation, and multi-observatory confirmation. An in-situ candidate must record sample provenance, molecular distribution, isotopes, chirality, mineral and geologic setting, blank controls, and contamination screening. The same ledger exposes whether an apparently exciting claim is supported by evidence or only by an untested alternative.

### Competitive idea: Oxygen-Follow-Up Scheduler

This direction optimizes observations after atmospheric O2 or O3 appears in a spectrum. It is concrete and technically useful but too narrow: it does not address false negatives, non-oxygen biosignatures, technosignatures, or in-situ evidence. It becomes a component of LifeTrace rather than the primary idea.

### Competitive idea: Interference-Resilient SETI Archive

This direction standardizes radio-frequency-interference and signal-recovery accounting across radio surveys. It directly advances G2 and G3 but does not bridge to biological or in-situ evidence. It is retained as the technosignature module of LifeTrace.

### High-risk idea: Universal Chemistry-of-Life Prior

This direction would estimate a broad prior probability of life from network complexity, chemical disequilibrium, and planetary population statistics. It is high risk because priors would remain strongly theory-dependent. It may guide future model building but cannot be allowed to turn weak evidence into a discovery claim.

## MCTS evolution trace

| Node | Parent | Edit skill | Rationale | Decision |
|---|---|---|---|---|
| N0 | root | Scalar-score framing | One score conflates target selection, detection, and confirmation. | Rejected |
| N1 | N0 | Problem decomposition | Separate habitability, signal, provenance, and sensitivity. | Retained |
| N2 | N1 | Alternative-hypothesis expansion | Add abiotic, artifact, interference, and contamination branches. | Retained |
| N3 | N2 | Cross-modal unification | Define common evidence fields for remote, radio, and in-situ measurements. | Retained |
| N4 | N3 | Falsifiability injection | Require a discriminating next observation and a sensitivity-limited null label. | Retained |
| N5 | N4 | Portfolio synthesis | Add follow-up value and human-review release gate. | Selected |

## Constrained scientific debate

**Pro position.** LifeTrace converts a broad philosophical question into an empirical protocol. It can make candidate assessment more decisive by naming the exact nonbiological or artifact explanation that survives, the measurement that can distinguish it, and the sensitivity required for a negative result to be informative.

**Challenge.** A unified ledger could be an elaborate record system with subjective likelihood models and no demonstrated improvement over specialist workflows.

**Resolution.** The selected proposal is accepted only with blinded synthetic cases, pre-registered alternative hypothesis sets, calibrated recovery tests, source-provenance audits, and ablations that remove context, provenance, and value-guided follow-up. If the ledger does not improve calibration, false-candidate control, or use of a fixed observing budget, its unification claim fails.

## Selected hypotheses

* **H1:** Context-conditioned, multi-feature assessment reduces overconfident biosignature claims relative to single-feature rules at matched data quality.
* **H2:** Explicit sensitivity and recovery cards make negative results scientifically sharper by restricting them to declared signal and population classes.
* **H3:** A shared provenance ledger reduces untracked abiotic, instrumental, interference, and contamination explanations across remote, technosignature, and in-situ branches.
* **H4:** Follow-up selected for expected hypothesis discrimination outperforms fixed follow-up in correctly classifying biological, technological, abiotic, and artifact-like synthetic cases at equal observing budget.

LifeTrace is a research design for evidence discipline, not a claim that life or technology beyond Earth has been detected.
