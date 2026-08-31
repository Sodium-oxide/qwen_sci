# Idea Agent Output: Portfolio for Pandemic Prediction Research

## Problem reframing

The question is not whether a system can utter the sentence ``the next pandemic will occur at place X on date Y.'' That target is scientifically ill-posed: multiple biological and social transitions intervene between reservoir circulation and a pandemic-scale event, and the labels themselves arrive late and unevenly. The actionable problem is to estimate, for a defined region and decision horizon, which **stage of escalation** deserves additional surveillance or preparedness effort and how uncertain that ranking is.

## Candidate directions

| Direction | Core mechanism | Gap IDs | Verdict |
|---|---|---|---|
| D1: Reservoir and viral discovery prioritization | Rank host-virus settings for targeted characterization. | GAP-01, GAP-05 | Competitive, but stops before outbreak decision support. |
| **D2: Auditable multistage pandemic-escalation forecasting** | Separately model spillover conditions, local amplification, regional spread readiness, and system actionability. | **GAP-01--GAP-05** | **Selected primary direction.** |
| D3: Event-based anomaly detection and corroboration | Fuse syndromic, event, laboratory, and wastewater signals for earlier detection. | GAP-03, GAP-04 | Competitive component; lacks upstream ecology and formal fairness layer. |
| D4: A single AI predicts the next pandemic | Learn a universal date/place/pathogen score. | GAP-01 | Rejected: incompatible with the survey evidence and falsifiability requirements. |

## Simulated multi-route idea evolution

The search starts from the observed defect: a single risk score hides which transition drives concern. A mechanism-replacement route splits the target into stage-specific hazards. A decision-theoretic route adds a preparation action and a false-alert cost. A robustness route adds temporally separated evaluation, transportability tests, and an abstention policy. Combining these routes yields D2.

| Checkpoint | Candidate intervention | Why retained or removed |
|---|---|---|
| I0 | Map zoonotic hotspots with ecological predictors. | Retained as a spillover-context component but incomplete for operational prediction. |
| I1 | Add clinical and event-based signals to a single risk score. | Rejected as opaque: mixed inputs still cannot attribute biological stage or action. |
| I2 | Produce four calibrated stage scores plus data-quality and equity flags. | Retained: exposes mechanism and permits component-level failure analysis. |
| I3 | Attach a decision table with threshold, lead time, cost, and abstention. | Retained: converts ranking into auditable preparedness support. |

## Structured scientific debate

**Novelty critic:** A stage model could merely rename existing surveillance practice.  
**Response:** D2's contribution is the coupling of stage attribution to *prospective calibration, action utility, fairness diagnostics, and mandatory abstention*. A dashboard without those properties is not the proposal.

**Feasibility critic:** The full One Health data universe is unavailable in many regions.  
**Response:** D2 explicitly treats missingness and stale data as outputs. It may abstain or downgrade an action recommendation rather than fabricate certainty. The proposal tests value under partial data rather than presupposing universal coverage.

**Safety critic:** Health-risk scores can stigmatize communities or trigger disproportionate responses.  
**Response:** D2 provides only aggregate regional decision support, requires human governance, documents intended use and false-alert harms, and prohibits automated intervention or individual-level risk scoring.

## Selected primary idea

**Title:** *Auditable Multistage Pandemic-Escalation Forecasting: Calibrated Risk States for Surveillance and Preparedness Decisions*

**Central hypothesis.** A stage-specific forecasting system that separates spillover-context, local amplification, regional spread readiness, and operational actionability will be more interpretable and better calibrated for stated preparedness decisions than a single pooled risk score, provided it is evaluated with time-forward, geography-held-out, delay-aware, and equity-aware protocols.

**Falsification conditions.** The direction is not supported if stage-specific outputs show no improvement in calibration, lead-time utility, interpretability audit, or transportability over a properly calibrated pooled baseline; if uncertainty remains high enough to preclude decisions; or if performance disparities cannot be characterized and mitigated.

**Primary contribution.** The design shifts the success criterion from rhetorical accuracy about the ``next pandemic'' to evidence that a risk state can support a defined human-reviewed action at an appropriate confidence and lead time.
