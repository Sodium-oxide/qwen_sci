# ExperimentDesign Agent: Relativistic Mission Envelope Protocol

## Design status and scope

**Execution policy:** `DESIGN_ONLY`. This document specifies computational analyses and future human-supervised component tests. It does not fire a laser, operate an accelerator, collect radiation data, expose materials, simulate a classified system, or claim observed results.

The selected template is `computational_digital` with a mathematical-physics module. The experimental unit is a declared mission architecture `theta`, not an unspecified “spaceship.” Each architecture has target distance, payload mass, total dry mass, target `beta`, propulsion mode, power and aperture assumptions, acceleration schedule, braking plan, environment model, shielding design, and operational class (robotic or crewed).

## Variables and observables

| Role | Variables | Operationalization |
|---|---|---|
| Independent | `beta`, payload mass, sail areal density, beam power, aperture, acceleration, brake architecture, ISM density/dust distribution, shielding areal density | Parameter ranges are declared before model execution and tagged with source or expert-review status. |
| Dependent | kinetic-energy lower bound, energy delivered, acceleration distance/time, braking closure, projected material-loss proxy, radiation-dose proxy, thermal rejection demand, payload fraction, travel time | Each output keeps units, model version, and uncertainty interval. |
| Controls | mission distance, reference frame, flyby/rendezvous label, assumed conversion efficiencies, environmental scenario, confidence target | Controls prevent a trajectory result from being compared across incompatible mission definitions. |
| Decision variables | feasible/incomplete/infeasible label; Pareto frontier rank | A mission is feasible only if all hard constraints are satisfied within their stated uncertainty policy. |

## Core derivation and model modules

Let `beta = v/c` and `gamma(beta) = (1-beta^2)^(-1/2)`. The kinetic-energy floor for an accelerated mass `m` is

`K(beta,m) = (gamma(beta)-1) m c^2`.

The equation is a lower bound for a mission energy budget, not the energy a real plant must draw. Source conversion, beam coupling, propulsion losses, thermal control, acceleration and braking must be added explicitly. For a constant proper acceleration `a`, the idealized acceleration duration and distance from rest to `beta` are

`tau_acc = (c/a) atanh(beta)` and `x_acc = (c^2/a)(gamma(beta)-1)`.

The reference model must use the same frame and operational assumptions for all alternatives. A rendezvous architecture has a braking module; a flyby architecture is labeled accordingly and cannot be reported as arrival/deployment capability. The shield module maps forward gas and dust distributions to a material-damage and thermal-load proxy, with shield areal density and exposed frontal area treated as explicit mass costs. The radiation module separately tracks ambient radiation and velocity-transformed forward-particle exposure. These proxy modules are not substituted for human-health qualification.

The overall feasibility predicate is

`F(theta) = 1` only if `E_source <= E_max`, `x_acc + x_brake <= D`, `M_damage <= M_limit`, `D_dose <= D_limit` for crewed cases, and all provenance and braking requirements are present. Otherwise `F(theta) = 0`; missing requirements create the third state `INCOMPLETE` rather than a false negative or positive.

## Study phases

1. **Analytic verification.** Test low-beta and high-beta limits, dimensional consistency, monotonic energy growth, and agreement of independently implemented equations.
2. **Architecture sweep.** Sample robotic flyby, robotic rendezvous, and crewed-rendezvous reference classes; construct Pareto fronts over travel time, source energy, payload fraction, and risk proxies.
3. **Uncertainty and ablation.** Remove braking, shielding, ISM damage, or operational constraints one at a time to quantify how a simplistic model overstates achievable beta. Hold out parameter regimes to test whether the coupled model generalizes.
4. **Human-supervised component evidence.** Subject to separate facility approval, compare candidate shield coupons under relevant ion/thermal proxy conditions and validate beam-sail thermal/optical models against calibrated bench measurements. These experiments are future validation obligations, not results of this proposal.

## Acceptance, rejection, and safety rules

The primary hypothesis is supported only if the coupled model materially changes the feasible frontier relative to energy-only screening and its predictions remain consistent with independent component evidence. It is rejected or revised if added modules do not change decisions, if their uncertainty overwhelms all rankings, or if validated component data contradict the model beyond declared uncertainty.

No automated physical execution is allowed. High-power lasers, particle beams, hazardous voltages, vacuum systems, cryogenics, radiation sources, flight hardware, or human-subject questions require qualified personnel, institutional safety review, facility procedures, and human approval. Any propulsion claim must include null tests, calibration, environmental control, and independent replication before it can modify a mission model.
