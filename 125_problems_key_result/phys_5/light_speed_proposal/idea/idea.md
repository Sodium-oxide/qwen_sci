# Idea Agent: Portfolio and Selected Direction

## Candidate portfolio

1. **Relativistic Mission Envelope (selected).** Build a coupled, uncertainty-aware feasibility frontier over target velocity, payload mass, energy infrastructure, sail or onboard propulsion, braking, shielding, and crew requirements.
2. **Adaptive sacrificial shield.** Study layered, self-diagnosing forward shielding for dust and gas impacts. It addresses `G3` but does not by itself resolve energy or braking.
3. **Two-station beam-sail rendezvous.** Explore acceleration and arrival-side braking with paired directed-energy stations. It addresses `G2`, but assumes a destination infrastructure that is itself a major prerequisite.
4. **Null-calibrated propulsion test suite.** Create an independent test protocol for anomalous-thrust claims. It is valuable for `G5`, but it cannot substitute for a mission architecture.

## Selection rationale

The selected direction is **Relativistic Mission Envelope (RME)**. It combines the gaps most likely to generate misleading claims: a target speed without a payload, an acceleration phase without braking, a kinetic-energy number without delivery infrastructure, or an ISM discussion without shield mass and reliability. RME does not attempt to evade special relativity. It asks which values of `beta = v/c` remain feasible after the constraints are coupled.

The idea is novel in the workflow sense rather than in claiming a new law of physics: it makes a mission's evidence contract executable. Any point on the frontier must disclose (i) payload and dry mass, (ii) flyby or rendezvous status, (iii) energy source and conversion chain, (iv) acceleration and braking path, (v) ISM/dust/radiation assumptions, (vi) shield mass, and (vii) a human versus robotic operational status. A point missing any item is labeled *incomplete*, not *feasible*.

## Central hypothesis

> **H-RME:** For fixed mission distance and payload class, a coupled model of relativistic energy, acceleration/braking, directed-energy optics or onboard power, interstellar-medium damage, radiation, and shield mass produces a bounded subluminal feasible region that is materially narrower than the region predicted by kinetic energy or cruise time alone.

This claim is falsifiable. A model can fail if independent engineering inputs demonstrate a self-consistent mission that lies outside the predicted infeasible region, if joint constraints add no predictive restriction beyond a simpler energy-only model, or if a validated protection architecture changes the controlling high-`beta` failure mode. It is not falsified merely because a lower-energy robotic flyby remains possible; flyby and rendezvous are distinct mission classes.

## MCTS-style evolution record

| Node | Edit skill | New content | Decision |
|---|---|---|---|
| `N0` | Problem reframing | Replace “travel at c” with “credible subluminal velocity window.” | Retained |
| `N1` | Constraint completion | Add finite-energy relativistic boundary and payload mass. | Retained |
| `N2` | Counterexample test | Separate flyby from braking/rendezvous cases. | Retained |
| `N3` | Risk coupling | Add ISM gas, dust, radiation, heat, and shield mass. | Retained |
| `N4` | Human factor | Add proper acceleration, dose, life support, and governance conditions. | Retained |
| `N5` | Overclaim filter | Reject warp, tachyon, and anomalous-thrust assertions without reproducible evidence. | Rejected branch |

## Scientific debate summary

The main alternative was to focus only on a laser sail because it can produce impressive travel-time estimates for gram-scale probes. The debate rejected it as the primary direction: sail calculations are essential evidence, but a narrow sail model cannot determine the prospect of human travel or prove a rendezvous mission. The RME direction wins because it preserves the strongest feasible near-term outcome--a validated subluminal robotic mission envelope--while making all higher-consequence claims testable.
