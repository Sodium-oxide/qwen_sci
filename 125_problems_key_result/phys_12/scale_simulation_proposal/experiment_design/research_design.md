# ExperimentDesign Agent Output: SRCL Computational Study Protocol

## Study type and boundary

**Template:** `computational_digital`.

This is a design-only benchmarking and evidence-analysis protocol. It does not run production simulations, submit jobs to HPC or quantum hardware, collect new experimental data, or claim an observed quantum advantage. Its purpose is to determine whether a proposed simulation scenario has enough declared evidence to support a conditional credibility status.

## Research brief

| Element | Design specification |
|---|---|
| Research object | A declared scientific quantity of interest across scale-specific simulation pathways. |
| Central claim | Accuracy must close a named error budget and validation route, not merely report a computation or hardware metric. |
| Unit of analysis | One `quantity-of-interest × model card × computational pathway × parameter scenario` tuple. |
| Primary outputs | Error interval, evidence tier, resource interval, status label, sensitivity and missing-field record. |
| Alternative explanation | An apparent method advantage may come from incompatible models, tolerances, references, costs, or extrapolated hardware assumptions. |
| Decision rule | Withhold a credibility or advantage label whenever required error, reference, or scope fields are missing. |

## Error contract

For a declared quantity of interest `Q`, the planned analysis records a conservative structured budget

`epsilon_Q <= epsilon_model + epsilon_input + epsilon_disc_or_repr + epsilon_solver_or_algorithm + epsilon_sampling + epsilon_coupling + epsilon_data + epsilon_quantum`.

The expression is a ledger, not a universal equality: dependencies and cancellations must be reported rather than assumed away. `epsilon_quantum` is zero for purely classical cards and otherwise expands into Hamiltonian mapping, state preparation, compilation/Trotter or algorithm approximation, noise, mitigation/correction, and measurement terms. Every bound carries an evidence type: analytic, refined-reference, validation comparison, device characterization, assumption, or `needs_human_input`.

## Model cards

`C0` defines a manufactured/analytic or high-fidelity reference where available. `C1` is a macro continuum/PDE card with conservation, mesh/time refinement, closure, and validation inputs. `C2` is an atomistic classical/ab-initio card with force-field/electronic-structure and finite-size terms. `C3` is a classically simulated quantum-many-body card with truncation, sign, tensor-network, or sampling terms. `C4` is a NISQ quantum-simulation card with mapping, circuit, noise, mitigation, and sampling terms. `C5` is a fault-tolerant projection card with logical error and resource assumptions clearly marked projected. `C6` is a cross-scale coupling card with interface and consistency conditions.

## Controls and comparisons

Hold the quantity-of-interest definition, units, tolerance, physical-model scope, input distribution, and reference route fixed within an approved comparison set. Compare classical and quantum cards only when their Hamiltonian/model, observable, target precision, and total cost accounting are compatible. Sweep mesh/basis resolution, solver tolerance, sampling budget, physical parameters, noise proxy, mitigation choice, and logical-error assumption over declared ranges. Report status switches and do not select a central case as a universal conclusion.

## Conditional status labels

| Label | Conditional criterion | Permitted conclusion |
|---|---|---|
| `VERIFIED_WITHIN_TOLERANCE` | Numerical/algorithmic error is bounded for the stated mathematical model and quantity. | The implementation pathway is verified for the declared model, not automatically physically valid. |
| `VALIDATED_FOR_DECLARED_REGIME` | Model comparison/validation evidence supports the stated physical regime and uncertainty range. | The scenario is conditionally credible in that regime. |
| `CLASSICALLY_PREFERABLE` | Compatible classical card meets tolerance at lower declared cost/risk. | Classical simulation is the current justified path for this tuple. |
| `QUANTUM_CANDIDATE_ADVANTAGE` | Quantum card has a complete comparable ledger and plausible tolerance/resource case, without claiming observation. | A specialist-reviewed quantum benchmark is justified. |
| `INCONCLUSIVE` | Evidence, baseline, sensitivity, or validation route is incomplete. | No accuracy/advantage ranking may be made. |
| `MODEL_INVALID` | Units, conservation, scope, provenance, or future/observed status checks fail. | Discard the scenario. |

## Reproducibility and review

Store model equations/Hamiltonian, quantity definition, units, reference status, error terms, parameter ranges, source IDs, code and compiler version, random seed, device-calibration snapshot where applicable, and classification log. A domain scientist must review model validity; a numerical analyst must review discretization/solver evidence; and a quantum-computing specialist must review mapping, hardware, mitigation, and projected fault-tolerant assumptions. The protocol is not authorization to operate computing infrastructure.

