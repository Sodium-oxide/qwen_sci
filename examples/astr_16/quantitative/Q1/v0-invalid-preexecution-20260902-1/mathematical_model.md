Abstract— 
This model specifies a parsimonious population synthesis framework for distinguishing isolated magnetic-dipole spin-down from binary recycling in pulsar populations. It integrates ordinary differential equations governing spin period and magnetic inclination evolution, augmented by Monte Carlo sampling of birth parameters. Derived diagnostics including the braking index and characteristic age are computed along each evolutionary track. The framework establishes a falsifiable boundary between vacuum-dipole evolution and recycled populations, enabling statistical comparison against high-precision timing surveys without claiming pre-computed numerical outcomes.

# Assumptions
- ASM-001: Vacuum magnetic-dipole torque dominates the isolated spin-down phase. Violation would cause systematic deviations in predicted period derivatives and braking indices.
- ASM-002: Magnetic inclination angle evolves smoothly via exponential decay on a fixed timescale tau_alpha. Violation would reduce the model's ability to reproduce observed braking-index scatter.
- ASM-003: Accretion-driven spin-up follows a steady-state disk torque law with constant mass transfer rate during the active phase. Violation would misplace recycled pulsar initial periods.
- ASM-004: Glitches, magnetospheric state transitions, and moment-of-inertia variations are negligible over the simulated horizon. Violation would omit stochastic perturbations present in real data.

# Symbols
- S-P: Spin period (s, time, STATE)
- S-alpha: Magnetic inclination angle (rad, angle, STATE)
- S-Pdot: Period derivative (s/s, dimensionless, DIAGNOSTIC)
- S-B0: Initial surface magnetic field strength (T, magnetic_flux_density, PARAMETER)
- S-Kdip: Effective vacuum dipole braking constant (s_T^-2, time_magnetic_flux_density_inverse_squared, PARAMETER)
- S-eta: Wind braking efficiency factor (dimensionless, dimensionless, PARAMETER)
- S-tauAlpha: Inclination decay timescale (s, time, PARAMETER)
- S-Mdot: Mass accretion rate (kg_s^-1, mass_time_inverse, PARAMETER)
- S-Kacc: Effective accretion spin-up constant (s^2_kg^-1, time_squared_mass_inverse, PARAMETER)
- S-tacc: Accretion phase duration (s, time, PARAMETER)
- S-Tmax: Maximum simulated age (s, time, PARAMETER)
- S-PdotMin: Minimum detectable period derivative (dimensionless, dimensionless, PARAMETER)
- S-Nmc: Monte Carlo sample count (dimensionless, count, PARAMETER)
- S-n: Braking index (dimensionless, dimensionless, DIAGNOSTIC)
- S-tauc: Characteristic age (s, time, DIAGNOSTIC)

# Equations
- Q1-EQ-001: Governing ODE for spin period evolution. Where: S-P, S-alpha, S-B0, S-Kdip, S-eta. Defines the primary torque balance driving period increase.
- Q1-EQ-002: Governing ODE for inclination decay. Where: S-alpha, S-tauAlpha. Models smooth obliquity reduction toward alignment.
- Q1-EQ-003: Diagnostic definition of period derivative. Where: S-P, S-Pdot, S-alpha, S-B0, S-Kdip, S-eta. Computes instantaneous spin-down rate from state and parameters.
- Q1-EQ-004: Diagnostic definition of braking index. Where: S-P, S-n, S-Pdot. Quantifies curvature of spin-down trajectory.
- Q1-EQ-005: Diagnostic definition of characteristic age. Where: S-P, S-tauc, S-Pdot. Provides a proxy evolutionary timescale.

# Algorithm
- Input: Approved parameter set, scenario flag, Monte Carlo sample count N_mc
- Output: Population tables containing P, Pdot, n, tau_c, and track metadata
- Steps: Initialize empty result collection. For each of N_mc tracks, sample initial conditions (P0, alpha0, B0). Apply scenario-specific switches. Integrate governing ODEs from t=0 to t=T_max using adaptive step-size solver. Apply accretion spin-up law during [0, t_acc] for Scenario D; otherwise apply isolated dipole law. Compute diagnostics Pdot, n, and tau_c at each step. Check boundary conditions and terminate tracks if violated. Append final track state to collection. Return aggregated population tables.

# Parameter and Scenario Material
Parameters are drawn from the approved set: P0=0.5 s, alpha0=0.7853981633974483 rad, B0=1.0e8 T, K_dipole=9.765625e-32 s_T^-2, eta=0.1, tau_alpha=3.15576e14 s, Mdot=6.3e14 kg_s^-1, K_acc=6.3e-31 s^2_kg^-1, t_acc=3.15576e14 s, T_max=3.15576e15 s, Pdot_min=1e-22, N_mc=5000. Scenarios include: SC-A (pure vacuum dipole), SC-B (inclination decay only), SC-C (inclination decay plus wind braking), and SC-D (binary recycling with finite accretion phase followed by isolated spin-down).

# Numerical Validation Plan
- VP-001: Verify Scenario A yields constant braking index n=3 analytically for pure vacuum dipole evolution.
- VP-002: Confirm Monte Carlo distribution moments converge as N_mc increases beyond 5000.
- VP-003: Cross-validate Pdot_min termination logic against published survey sensitivity limits.
- VP-004: Compare Scenario B and D separation in (P, Pdot, n) space against falsification threshold of 0.05 significance.

# Limitations
The model does not account for glitches or magnetospheric state changes. It assumes a fixed moment of inertia throughout evolution. Observational selection effects in comparator data may bias statistical comparison. Detailed companion ablation and full binary orbital evolution are excluded. Effective constants absorb unresolved geometry, electromagnetic, and microphysical factors.

# References
- REF-001: Feng & George (2006), Birth and Evolution of Isolated Radio Pulsars, ApJ, 10.1086/501516
- REF-002: Lorimer (2008), Binary and Millisecond Pulsars, Living Reviews in Relativity, 10.12942/lrr-2008-8
- REF-003: Manchester et al. (2005), The ATNF Pulsar Catalogue, MNRAS, 362, 95
