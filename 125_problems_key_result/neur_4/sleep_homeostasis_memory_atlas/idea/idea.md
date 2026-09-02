# Idea Agent: Sleep Function Causal Atlas

## Portfolio search

The Idea Agent combines the accepted Survey gaps with four independent research routes:

- **R1 — Two-process perturbation matrix:** orthogonally vary prior wake, circadian phase, sleep opportunity, and recovery to separate homeostatic pressure from clock timing.
- **R2 — Stage-resolved memory replay atlas:** align sleep microstructure, spindle/slow-oscillation dynamics, and event-related reactivation with item, order, and relational memory.
- **R3 — Neuroimmune maintenance bridge:** jointly model sleep architecture, clearance-related physiology, inflammatory signaling, and cognitive performance over repeated within-person sessions.
- **R4 — Personalized sleep-resilience controller:** predict which individual sleep feature should be extended or protected to recover a defined cognitive or immune endpoint.
- **R5 — Sleep Function Causal Atlas (SFCA):** integrate R1–R4 into a staged causal atlas with explicit intervention targets, domain-specific outcomes, and individual-response predictions.

## Selected direction

**Sleep Function Causal Atlas (SFCA)** is selected as the primary direction. SFCA does not ask for one universal purpose of sleep. It builds a mechanistic map from sleep pressure, circadian phase, sleep continuity, stage composition, and physiological state to separable outcomes in memory, plasticity, immune defense, and brain maintenance.

The central idea is a factorial, repeated-measures design coupled to a multimodal state-space model. Every intervention is interpreted against matched wake and timing controls, and every positive result must identify the endpoint it improves. A longer sleep episode that restores recall but not immune response is a valid dissociation, not a failed study.

## Core hypothesis

If sleep performs multiple partly shared functions, then a representation of sleep state that separates homeostatic pressure, circadian phase, stage microstructure, continuity, and individual physiology should predict distinct outcome vectors better than total sleep duration alone. Controlled perturbations should reveal both shared and domain-specific causal effects, and a personalized model should improve recovery of a declared endpoint without assuming that one intervention optimizes every domain.

## Falsification conditions

SFCA is weakened or rejected if any of the following persists after preregistered controls:

1. Duration-only models predict memory, immune, clearance, and systemic outcomes as well as the decomposed state model.
2. Orthogonal timing and prior-wake manipulations produce no separable changes in any declared outcome.
3. Stage or continuity features fail to generalize across sessions and participants beyond arousal, stress, medication, and measurement quality.
4. A personalized controller cannot improve a prespecified target endpoint relative to a safe, duration-matched schedule.
5. Apparent cognitive effects disappear when encoding opportunity, circadian alertness, practice, and test motivation are controlled.

## Why this direction wins

R1 is highly falsifiable but may underrepresent biology. R2 gives a sharp memory mechanism but can mistake replay for the complete function of sleep. R3 connects important domains but risks an underpowered and correlational “everything model.” R4 is translationally attractive but can optimize a proxy without explaining mechanism. SFCA retains the strongest component of each while imposing promotion gates: first identify state, then estimate domain-specific effects, then test intervention specificity, and only then personalize.

## Planned portfolio

- **Primary:** SFCA, a causal atlas of decomposed sleep features and domain-specific outcomes.
- **Competitive:** a stage-specific memory consolidation model; a sleep–immune resilience model; a safe adaptive sleep scheduling controller.
- **High risk/high value:** a cross-domain latent state that predicts when a single sleep intervention improves both memory and immune response without sacrificing another endpoint.
- **Rejected:** “sleep is only for memory,” “sleep is only for waste clearance,” and duration-only health prediction. Each presupposes a single mechanism or discards the structure that the Survey identified as essential.

## Agent handoff

ExperimentDesign should preserve the following invariants:

- `execution_policy.mode = DESIGN_ONLY` and `observed_results = []`.
- Sleep restriction, circadian displacement, and stage manipulation are planned only; they are not performed.
- Memory outcomes remain domain-specific, immune outcomes remain multi-marker, and clearance markers remain candidate mediators.
- Carryover, practice, stress, medication, illness, age, chronotype, and socioeconomic timing are modeled or reviewed.
- Positive findings must be stated as endpoint- and condition-specific causal claims, not as a final explanation of all sleep.
