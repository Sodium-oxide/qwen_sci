# ExperimentDesign Agent: CortexSwitch Design-Only Protocol

## Research brief

- **Question:** Do a predeclared set of human-lineage duplicated and regulatory genetic changes causally shift an early cortical progenitor-to-neuron transition in a reciprocal human/chimpanzee organoid comparison?
- **Primary endpoint:** A line-aware, quality-gated basal-radial-glia/progenitor persistence contrast relative to neurogenic transition states.
- **Mechanistic endpoints:** Candidate-linked chromatin accessibility/contact evidence, target-gene expression, and cell-state trajectory displacement.
- **Alternative explanations:** iPSC line effects, species background, edit burden, batch, regional identity, maturity, stress programs, and annotation/trajectory alignment error.

## Scope and safety gate

`execution_policy.mode = DESIGN_ONLY`; `observed_results = []`. The plan specifies a future in-vitro comparative study only. It does not collect samples, derive new lines, edit cells, grow organoids, sequence material, conduct animal work, or report results. Any implementation requires documented donor consent/provenance, institutional oversight, species-specific material-transfer permissions, qualified stem-cell and genome-editing supervision, and predefined limits on organoid culture and interpretation.

## Design structure

1. **Pre-registration and candidate locking.** Select no more than two duplicated-gene perturbation axes and three regulatory candidates using the survey evidence ledger, cell-state activity, target-gene support, and cross-line editability. Freeze the candidate list before outcome analysis.
2. **Reciprocal genotype panel.** Compare unmodified human and chimpanzee reference lines with human ancestral/orthologous reversion and chimpanzee humanization states. Include matched neutral-edit, mock-process, and single-candidate controls. Use at least three independent lines per species as biological replication; treat multiple organoids from the same line/batch as non-independent technical replication.
3. **Developmental alignment.** Sample a preregistered series spanning neural induction, radial-glial expansion, basal-progenitor competence, and early neuronal differentiation. Align trajectories with external fetal/reference-atlas checks rather than only culture day.
4. **Multimodal evidence.** Collect future single-cell transcriptomic and chromatin-accessibility data, targeted candidate--target contact validation where feasible, and blinded imaging-derived progenitor/neuron marker estimates. Each modality is an evidence layer, not an interchangeable surrogate.
5. **Quality and abstention.** Exclude or quarantine batches with failed identity, contamination, regional composition, excessive stress, insufficient representation, or failed reference alignment. A failed gate yields `EVIDENCE_OR_MODEL_ABSTAIN`, not an imputed favorable result.

## Primary analysis

For future organoid (o), line (l), batch (b), genotype state (g), and aligned developmental state (t), model a predeclared endpoint (Y) using:

\begin{equation}
Y_{olbgt}=\beta_0+\beta_S S+\beta_G G+\beta_{SG}(S\times G)+\beta_TT+u_l+u_b+\epsilon_{olbgt},
\label{eq:primary}
\end{equation}

where (S) is species background, (G) is perturbation state, (u_l) and (u_b) are line and batch effects, and β_{SG} tests whether an edit behaves differently across backgrounds. The confirmatory statistic is not a raw organoid-size comparison. It is a signed, line-aware reciprocal contrast between chimpanzee humanization and human reversion, accompanied by a prespecified molecular mediator and survival of sensitivity analyses.

## Decision rules

- **Tier 0:** Candidate association only; no causal interpretation.
- **Tier 1:** A qualified genotype effect on one molecular or cell-state endpoint; report as model-specific.
- **Tier 2:** Reciprocal, sign-consistent effect across independent lines and matched controls; report conditional causal support for the endpoint.
- **Tier 3:** Tier 2 plus a reproducible candidate-to-target molecular link and combination-vs-single perturbation comparison; report support for a defined developmental module, never whole-organism human uniqueness.

## Conditional outcome matrix

| Future outcome | Permitted interpretation | Required next step |
|---|---|---|
| Duplicated-gene axis alone replicates reciprocally | Conditional support for its specified progenitor endpoint | Test regulatory interaction, dosage sensitivity, and target pathway |
| Regulatory candidate changes molecular readout but not cell state | Molecular effect without developmental-module support | Reassess target assignment, timing, and state context |
| Combination outperforms all matched single candidates | Evidence for a conditional module interaction | Replicate in held-out lines and test mediator necessity |
| Effects differ across lineages or lines | Lineage- or background-specific result | Preserve heterogeneity; prohibit universal conclusion |
| Fidelity gate fails | Evidence/model abstention | Improve model qualification before retesting candidates |
