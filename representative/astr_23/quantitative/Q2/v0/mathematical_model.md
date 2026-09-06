Abstract— An executable scalar Monte Carlo posterior-proxy model for the fission neutron release timescale tau_f. The run samples tau_f together with ejecta mass, electron fraction, and inclination nuisance priors using the approved Q2 parameter values. The current trusted adapter reports the sampled tau_f observable and does not claim a full hierarchical likelihood, Markov-chain diagnostic, or empirical posterior.

# Assumptions

- Q2-A-001: The approved tau_f value of 2.3 s is used as the center of a positive bounded sensitivity prior from 1.15 s to 3.45 s. Effect if violated: The sampled fission-timescale sensitivity range changes.

- Q2-A-002: The approved ejecta-mass value of 0.04 solar_mass is represented by a positive bounded interval from 0.03 to 0.05 solar_mass. Effect if violated: The nuisance ejecta-mass prior changes.

- Q2-A-003: The approved electron-fraction value of 0.16 is represented by a broad physically admissible interval from 0.08 to 0.24. Effect if violated: The neutron-richness nuisance prior changes.

- Q2-A-004: The approved inclination value is represented by the converted 19 to 42 degree interval in radians. Effect if violated: The viewing-angle nuisance prior changes.

- Q2-A-005: The current executable observable is the sampled tau_f value; nuisance variables are retained as declared prior variables for later likelihood extension. Effect if violated: The result would no longer be the scalar tau_f posterior proxy defined by this model.

# Symbols

- Q2-S-001: $\tau_f$ — Fission neutron release timescale (s; time; MATERIAL_PROPERTY)

- Q2-S-002: $M_{ej}$ — Kilonova ejecta mass nuisance parameter (solar_mass; mass; SCENARIO_INPUT)

- Q2-S-003: $Y_e$ — Electron fraction nuisance parameter (1; dimensionless; SCENARIO_INPUT)

- Q2-S-004: $i$ — Binary inclination angle (rad; angle; SCENARIO_INPUT)

- Q2-S-005: $N_{samples}$ — Monte Carlo sample count (1; count; MODEL_ASSUMPTION)

- Q2-S-006: $N_{chains}$ — Declared independent-chain control (1; count; MODEL_ASSUMPTION)

- Q2-S-007: $N_{temperatures}$ — Declared tempering-level control (1; count; MODEL_ASSUMPTION)

# Equations

- Q2-EQ-001 (OBSERVABLE_DEFINITION): $z=\tau_f$. Where Q2-S-001: Fission neutron release timescale.

- Q2-EQ-002 (PRIOR_FACTORISATION): $p(\tau_f,M_{ej},Y_e,i)=p(\tau_f)p(M_{ej})p(Y_e)p(i)$. Where Q2-S-001: Fission neutron release timescale; Q2-S-002: Kilonova ejecta mass nuisance parameter; Q2-S-003: Electron fraction nuisance parameter; Q2-S-004: Binary inclination angle.

# Initial and Boundary Conditions

- The zero-dimensional sampler is initialized by drawing each declared random variable from its validated prior distribution.

- No spatial boundary conditions apply to this zero-dimensional Monte Carlo sampler.

# Algorithm

Input: tau_f prior; M_ej prior; Y_e prior; i prior; approved parameter set

Output: sample count; mean tau_f; standard deviation of tau_f; minimum tau_f; maximum tau_f

Steps: Initialize the deterministic random generator from the integer seed.; Draw 10000 independent samples from the four declared bounded prior distributions.; Evaluate the scalar observable z=tau_f for every draw.; Report bounded summary statistics for the sampled tau_f values.

# Parameters and Scenarios

- Parameter: The execution parameter object must contain exactly tau_f=2.3, M_ej=0.04, Y_e=0.16, i=0.5585053606381855, N_samples=10000, N_chains=4, and N_temperatures=8.

- Parameter: The random-variable sensitivity bounds are explicit model assumptions and are numeric literals required by the trusted sampler.

- Scenario: baseline

# Objective and Constraints

- Estimate the scalar sampled distribution of tau_f under the declared bounded nuisance-prior setup.

# Numerical Validation

Solver: MONTE_CARLO. Discretization: independent bounded prior sampling.

- Convergence check: sample_count_bound

- Convergence check: repeat the run with a larger sample count outside the current fixed approved baseline

- Validation: Verify that the sample count is an integer between 1 and 100000.

- Validation: Verify that every distribution bound is finite and ordered.

- Validation: Verify that all observable values are finite.

- Validation: Verify that the execution parameter object exactly matches the approved parameter set.

# Limitations

- The current trusted adapter evaluates a scalar observable and does not implement a full likelihood.

- The declared N_chains and N_temperatures controls are retained for provenance but are not independently executed by the standard adapter.

- The output is a numerical simulation result and not empirical evidence.

- The nuisance priors are sampled but are not combined through a multi-messenger likelihood in this adapter.

# References

- doi:10.3847/1538-4357/aaeaca

- doi:10.1038/nature24303

- doi:10.1093/mnras/sty2932

- doi:10.3847/2041-8213/aac6c1
