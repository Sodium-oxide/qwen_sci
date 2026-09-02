# Idea Agent: Addiction Mechanism and Memory-Control Atlas

## Portfolio search

The Idea Agent combines the accepted Survey gaps with five research routes:

- **R1 — Addiction control-balance state space:** model reward valuation, incentive salience, withdrawal relief, executive control, stress, and cue reactivation as time-varying latent states.
- **R2 — Cue-memory and relapse atlas:** test how drug-associated cues, contexts, temporal history, and extinction/reinstatement shape craving and seeking across time.
- **R3 — Gene-environment developmental model:** estimate how genetic liability, adolescence, trauma, stress, social exposure, and treatment access interact rather than producing independent risk scores.
- **R4 — Mechanism-specific recovery controller:** select interventions according to dominant cue, withdrawal, habit, or control signatures and evaluate treatment response without using a substance label as a mechanism.
- **R5 — Addiction Mechanism and Memory-Control Atlas (AMMCA):** integrate R1–R4 into a longitudinal, causal and ethical atlas with explicit separation of wanting, liking, craving, behavior, and subjective report.

## Selected direction

**Addiction Mechanism and Memory-Control Atlas (AMMCA)** is selected as the primary direction. AMMCA asks which mechanism is active in a given person and episode, then tests whether that mechanism predicts compulsive seeking and relapse under held-out cues and contexts. It treats memory as one component of addiction: drug-associated memories can make cues motivationally powerful, but cue reactivity is not a complete subjective memory and artificial-memory experiments are not addiction treatments.

The central strategy is a longitudinal multimodal state-space model coupled to safe, mechanism-specific intervention tests. The model tracks reward prediction, incentive salience, outcome value, habit persistence, withdrawal/negative affect, executive control, cue-memory reactivation, sleep/stress state, and environmental opportunity. Clinical outcomes include use days, craving, treatment engagement, adverse events, quality of life, and relapse defined prospectively.

## Core hypothesis

If addiction is a dynamic interaction among reward learning, cue memory, stress/withdrawal, habit, control, and environment, then a decomposed state-space representation should predict held-out craving and relapse better than a static severity score or dopamine-only model. Mechanism-specific perturbations should alter the target process while preserving general motivation, cognition, agency, and non-target reward behavior within safety bounds.

## Falsification conditions

AMMCA is weakened or rejected if:

1. A static severity score predicts held-out relapse as well as the dynamic decomposed model.
2. Cue, withdrawal, habit, and control states cannot be separated beyond generic arousal, stress, medication, sleep, and treatment exposure.
3. Memory-cue measures do not generalize across contexts or add no value beyond recent use and craving self-report.
4. Mechanism-specific intervention selection does not outperform a safe, substance-label or standard-care comparator.
5. Apparent prediction depends on ancestry, clinic, device, or socioeconomic proxy leakage and fails fairness calibration.

## Why this direction wins

R1 gives a coherent computational model but can become abstract. R2 offers a direct memory mechanism but can mistake a cue response for subjective recollection. R3 captures etiological complexity but risks static risk labeling. R4 is clinically useful but can optimize a proxy and overstep human autonomy. AMMCA combines them with held-out temporal/context tests, causal controls, fairness checks, and clinical review gates.

## Planned portfolio

- **Primary:** AMMCA, a longitudinal atlas of addiction mechanisms and memory-driven control.
- **Competitive:** cue-memory relapse model; gene-environment developmental trajectory model; mechanism-specific recovery matching.
- **High risk/high value:** a subject-specific controller that identifies whether relapse is driven mainly by cue wanting, withdrawal relief, habit persistence, or control failure and selects a safe treatment component accordingly.
- **Rejected:** dopamine-only addiction, artificial-memory-as-cure, and static genetic destiny models. They discard multiple mechanisms or overinterpret a behavioral memory manipulation.

## Agent handoff

ExperimentDesign must preserve:

- `execution_policy.mode = DESIGN_ONLY` and `observed_results = []`.
- No drug exposure, withdrawal induction, neural stimulation, memory editing, or treatment assignment is executed.
- Wanting, liking, craving, habit, withdrawal, behavior, and subjective report remain separate endpoints.
- Genetic and environmental variables are probabilistic and privacy-sensitive, never deterministic labels.
- Treatment and relapse claims require clinical review, safety monitoring, fairness analysis, and participant autonomy.
