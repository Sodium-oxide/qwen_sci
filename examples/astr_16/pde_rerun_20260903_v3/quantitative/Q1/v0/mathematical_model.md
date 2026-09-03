Abstract—This model formalizes the coupled temporal evolution of neutron star spin period and magnetic inclination angle under competing torque mechanisms. By encoding phase-dependent switching between vacuum dipole braking, wind enhancement, inclination decay, and accretion-driven spin-up directly into the state derivatives, the framework isolates the dynamical signatures distinguishing isolated magnetic-dipole evolution from binary recycling. The formulation enables population-level statistical comparison against observed braking indices and characteristic ages while maintaining computational tractability through effective constants that absorb unresolved microphysical geometry and electromagnetic factors.

Assumptions
- ASM-001: Stellar geometry, electromagnetic constants, and moment of inertia are absorbed into effective braking constants K_dipole and K_acc. Violation removes direct physical interpretability of derived constants.
- ASM-002: Magnetic inclination evolves smoothly via exponential decay without discontinuous glitches or magnetospheric state transitions. Violation breaks continuous derivative assumptions required for ODE integration.
- ASM-003: Accretion torque activates exclusively during t < t_acc with nonzero Mdot; isolated dipole torque applies otherwise. Violation produces unphysical simultaneous opposing torques.

Symbols
- S-P: Spin period (s, time, STATE)
- S-alpha: Magnetic inclination angle (rad, angle, STATE)
- S-t: Integration time (s, time, PARAMETER)
- S-P0: Initial spin period (s, time, PARAMETER)
- S-alpha0: Initial inclination angle (rad, angle, PARAMETER)
- S-B0: Surface magnetic field strength (T, magnetic_flux_density, PARAMETER)
- S-Kdip: Vacuum dipole braking constant (s_T^-2, time_magnetic_flux_density_inverse_squared, PARAMETER)
- S-eta: Wind braking efficiency (dimensionless, dimensionless, PARAMETER)
- S-tau: Inclination decay timescale (s, time, PARAMETER)
- S-Mdot: Mass accretion rate (kg_s^-1, mass_time_inverse, PARAMETER)
- S-Kacc: Accretion spin-up constant (s^2_kg^-1, time_squared_mass_inverse, PARAMETER)
- S-tacc: Accretion phase duration (s, time, PARAMETER)
- S-Tmax: Maximum simulated age (s, time, PARAMETER)
- S-Pdotmin: Minimum detectable period derivative (dimensionless, dimensionless, PARAMETER)
- S-Nmc: Monte Carlo sample count (dimensionless, count, PARAMETER)

Equations
- Q1-EQ-001: Governs period evolution dP/dt. Where: S-P, S-t, S-Kacc, S-Mdot, S-tacc, S-Kdip, S-B0, S-alpha, S-eta. Implements conditional torque switching based on accretion phase boundaries.
- Q1-EQ-002: Governs inclination evolution dalpha/dt. Where: S-alpha, S-t, S-tau. Models smooth exponential decay toward alignment.
- Q1-EQ-003: Defines braking index n(t). Where: S-P. Derived diagnostic from period and its second derivative.
- Q1-EQ-004: Defines characteristic age tau_c(t). Where: S-P. Derived diagnostic from period and first derivative.

Algorithm
Input: Initial conditions (P0, alpha0), approved parameter set, scenario configuration.
Output: Time series arrays for P(t), alpha(t), derived diagnostics n(t), tau_c(t), population histograms.
Steps:
1. Initialize state vector with P0 and alpha0.
2. Select scenario parameter overrides.
3. Evaluate derivative AST at current time t.
4. Advance state using fixed-step integrator.
5. Compute n(t) and tau_c(t) from derivatives.
6. Check termination criteria against T_max and Pdot_min.
7. Repeat until termination or N_mc tracks completed.

Parameter and Scenario Material
Parameters are drawn from the approved set with exact scalar values: P0=0.5 s, alpha0=0.7853981633974483 rad, B0=1e8 T, K_dipole=9.765625e-32 s_T^-2, eta=0.1, tau_alpha=3.15576e14 s, Mdot=6.3e14 kg_s^-1, K_acc=6.3e-31 s^2_kg^-1, t_acc=3.15576e14 s, T_max=3.15576e15 s, Pdot_min=1e-22, N_mc=5000.
Scenarios operationalize mechanism differences via parameter overrides:
- isolated_dipole: Sets K_acc=0.0, Mdot=0.0, t_acc=0.0, forcing exclusive evaluation of the dipole branch.
- binary_recycling: Sets K_acc=5e-31, preserving default Mdot and t_acc to activate the accretion spin-up branch during the defined interval.
These overrides directly alter the derivative AST branches, ensuring computationally distinct trajectories.

Numerical Validation Plan
- Analytical limit check: Verify dalpha/dt converges to zero as t approaches infinity (relative error < 1e-6).
- Scenario isolation test: Confirm isolated_dipole yields strictly positive dP/dt throughout the horizon (sign consistency).
- Recycling transition test: Verify dP/dt switches sign at t_acc and returns to positive post-accretion (branch activation count matches definition).
Convergence monitored via step-halving error estimation and residual tolerance 1e-9.

Limitations
- Excludes glitch events, magnetospheric state transitions, and variable moment of inertia.
- Assumes fixed stellar geometry and absorbs unresolved electromagnetic factors into effective constants.
- Observational selection effects and survey detection thresholds are not dynamically coupled to the simulation loop.

References
- Feng, G., et al. (2006). Birth and Evolution of Isolated Radio Pulsars. ApJ, 646, 381. DOI: 10.1086/501516
- Lorimer, D. R. (2008). Binary and Millisecond Pulsars. Living Rev. Relativity, 11, 8. DOI: 10.12942/lrr-2008-8
