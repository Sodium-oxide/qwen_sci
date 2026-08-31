# ExperimentDesign Agent Output: Design-Only Evaluation Protocol

## Intake and execution boundary

**Selected direction:** D2 — Auditable Multistage Pandemic-Escalation Forecasting.  
**Design status:** `DESIGN_ONLY`.  
**Observed results:** none.  
**Permitted work:** an ethical, aggregate-data evaluation plan for future human-led implementation.  
**Prohibited work:** pathogen creation or testing, animal work, clinical enrollment, individual-level profiling, autonomous alerts, or real-world public-health action.

## Research brief

The system's unit of analysis is an aggregate region and predeclared time window. It is designed to produce four calibrated, noninterchangeable quantities: (1) spillover-context risk, (2) local amplification concern, (3) regional dissemination readiness, and (4) actionability given data timeliness, uncertainty, and local capacity. A fifth output, **abstain/insufficient information**, is mandatory.

### Hypotheses

- **H1 (attribution):** Separate stage models will make the reason for a high-risk alert more traceable than a pooled score.
- **H2 (calibration):** Time-forward and geography-held-out calibration will be better preserved by a stage-aware framework with explicit missingness than by a pooled model trained on randomly split records.
- **H3 (utility):** For predeclared alert costs and lead-time needs, actionability-aware risk states will improve decision utility over a threshold on pooled risk alone.
- **H4 (equity):** Missingness, reporting delay, and research-effort diagnostics will reveal conditions under which a system must abstain instead of ranking regions with false precision.

## Variables and measurement plan

| Construct | Examples of aggregate inputs | Output / control | Guardrail |
|---|---|---|---|
| Spillover context | Host/virus surveillance summaries, land-use and climate anomalies, exposure proxies | Calibrated context interval | No individual or precise wildlife-location targeting. |
| Local amplification | Validated aggregate syndromic/laboratory indicators and anomalies | Probability/ordinal risk state plus uncertainty | Confirmatory signals are not treated as case truth by themselves. |
| Regional spread readiness | Aggregate mobility connectivity, health-system surge indicators, reporting latency | Preparedness-relevance state | No individual mobility tracking. |
| Data quality | Source age, missingness, coverage, revision history, reporting effort | Abstain flag and reliability card | No imputation that hides absence of surveillance. |
| Decision utility | Action owner, cost, lead-time threshold, opportunity cost | Human-reviewed recommendation class | Never triggers automatic action. |

## Comparator plan

1. **Pooled baseline:** one calibrated risk score using the same eligible aggregate inputs.
2. **Signal-only baseline:** contemporaneous clinical/event anomaly indicator without upstream stage separation.
3. **Multistage proposal:** linked stage models with monotonic decision rules, uncertainty intervals, data-quality flags, and abstention.
4. **Oracle excluded:** no comparator may assume access to future laboratory confirmation, retrospectively cleaned labels, or unobserved outbreak dates.

## Evaluation protocol

1. Freeze a data dictionary, inclusion rules, regional resolution, outcome definitions, alert costs, and analysis code plan before any model fitting.
2. Use sequential historical training windows and later time windows for evaluation. Hold out entire geographies to test transportability; do not rely on random-record splits.
3. Recreate realistic data latency, revisions, and missingness. Evaluate both complete and degraded-information conditions.
4. Assess discrimination only as secondary evidence. Primary metrics are calibration slope/intercept, proper scoring rules, interval coverage, decision-curve net benefit, lead-time distribution, abstention rate, and error disparity across data-coverage strata.
5. Conduct a structured attribution audit: for sampled high-risk outputs, a reviewer determines whether the stated stage, source freshness, uncertainty, and action mapping are internally consistent.
6. Run a prospective **shadow deployment** only after ethics, governance, and partner approval. It may display human-reviewed retrospective or delayed outputs; it cannot direct field response or publish stigma-inducing rankings.

## Decision rules and conditional conclusions

| Evaluation label | Required evidence | Permitted conclusion |
|---|---|---|
| `stage_specific_signal_supported` | Stable calibration and traceable stage attribution on held-out data | The stage representation merits further monitored evaluation. |
| `actionable_lead_time_supported` | Predeclared action utility exceeds baselines at stated false-alert cost | The design may inform a human-reviewed preparedness pilot. |
| `transportability_insufficient` | Geographic/time transfer materially fails or is uncertain | Do not generalize; local recalibration or abstention is required. |
| `definition_or_governance_abstain` | Labels, data rights, equity, or accountability are inadequate | Do not generate a ranked decision product. |

## Safety, ethics, and governance

The proposed work requires public-health, data-governance, and community review before access to nonpublic data. Each participating jurisdiction retains authority over data-sharing and response decisions. Documentation must specify intended use, prohibited uses, false-positive harms, appeal pathways, and a communication plan that does not stigmatize locations or populations. The system may report uncertainty, defer, or abstain; it may not claim to have forecast a pandemic.

## Design evidence and human-input needs

The design is grounded in stage separation from spillover studies [S1--S4], surveillance-system evaluation [S5--S7], and machine-learning evaluation cautions [S8,S9]. Human reviewers must still supply jurisdiction-specific outcome definitions, authorized data sources, policy actions, thresholds, ethical approval, and an equity impact assessment.
