# ExperimentDesign Agent Output: EVSL Computational Study Protocol

## Study type and boundary

**Template:** `computational_digital`.

This is a design-only analysis protocol. It specifies no accelerator operation, no facility access, no beam steering, no collection of experimental measurements, and no claim of observed performance. Its purpose is to evaluate whether a transparent analysis ledger can distinguish kinematic saturation from architecture-specific limiting conditions.

## Research brief

| Element | Design specification |
|---|---|
| Research object | Ultra-relativistic charged-particle acceleration architectures. |
| Central claim | The useful frontier is a constraint classification after beta saturation, not a lower speed limit below `c`. |
| Unit of analysis | One source-bounded model card and its declared parameter scenario. |
| Primary observables | `gamma`, `1-beta`, rigidity, energy-gain/loss balance, gradient/length, power, beam-quality and protection variables. |
| Alternative explanation | An apparent dominant constraint could reflect arbitrary ranges, missing loss terms, or inconsistent architecture assumptions. |
| Decision rule | Return a label only when every required field and a sensitivity interval are present; otherwise return `NON_IDENTIFIABLE` or `MODEL_INVALID`. |

## Model cards

`C0` relativistic baseline calculates gamma and beta only for a stated rest mass and total energy. `C1` is a proton circular-ring ledger with field, radius, RF, loss and protection fields. `C2` is an electron/positron ring ledger with explicitly scoped radiation and beamstrahlung conditions. `C3` is a linear-RF ledger with gradient, length, power and luminosity proxy. `C4` is a plasma-wakefield ledger with driver energy, staging, energy spread and stability fields. `C5` defines a strong-field/radiation-reaction applicability boundary. `C6` provides a Hillas-like astrophysical context and is never merged with laboratory performance labels.

## Equations and operationalization

For the baseline, calculate `gamma = E/(m c^2)` and `beta = sqrt(1-gamma^-2)` for gamma greater than or equal to one. Track `delta_beta = 1-beta` with sufficient numerical precision rather than rounding beta to one. For a circular card, use the ultra-relativistic planning relation `p approximately q B rho`; retain exact units and particle charge assumptions. A conceptual turn ledger is

`Delta E_turn = q V_RF sin(phi_s) - U_rad - U_collective - U_operational`.

It is an accounting structure for scenario evaluation, not an equation fitted to a particular machine. Every nonzero loss term requires a cited model or must be tagged `needs_human_input`.

## Controls and sensitivity plan

Hold particle identity, rest mass convention, energy definition, and source version fixed within each scenario. Vary field/radius, RF voltage, gradient, power, loss assumptions, emittance/energy spread, and protection threshold across predeclared plausible intervals. Report which variable changes the constraint class and whether the class remains stable. Compare only compatible scope: proton ring to proton ring, lepton ring to lepton ring, and laboratory concepts separately from astrophysical context.

## Expected conditional outcome branches

| Label | Conditional criterion | Permitted conclusion |
|---|---|---|
| `KINEMATIC_SATURATION` | beta is within a declared numerical tolerance of one and no engineering ledger is complete. | Speed is saturated for comparison; no practical limit is identified. |
| `RIGIDITY_LIMITED` | field-radius requirements dominate the scenario feasibility interval. | Ring momentum is constrained by stated `B rho` assumptions. |
| `RADIATION_LIMITED` | scoped radiative losses/beamstrahlung dominate. | Radiation is the active modeled constraint in this species and architecture. |
| `POWER_OR_GRADIENT_LIMITED` | energy gain requires unavailable modeled power, gradient, or length. | Acceleration infrastructure is the active modeled constraint. |
| `BEAM_QUALITY_OR_PROTECTION_LIMITED` | spread, stability, loss, or protection threshold fails first. | Beam delivery or safe operation is the active modeled constraint. |
| `NON_IDENTIFIABLE` | evidence or sensitivity range is incomplete. | No dominant constraint may be claimed. |
| `MODEL_INVALID` | unit, kinematic, or provenance checks fail. | Discard the scenario. |

## Reproducibility, safety, and review

Store input cards, units, equations, source identifiers, code version, parameter ranges, and classification logs. Any implementation must be reviewed by an accelerator physicist for ring and protection assumptions, by a radiation/strong-field specialist for `C5`, and by a relativistic-theory reviewer for any nonstandard extrapolation. The protocol is not authorization to operate a facility.

