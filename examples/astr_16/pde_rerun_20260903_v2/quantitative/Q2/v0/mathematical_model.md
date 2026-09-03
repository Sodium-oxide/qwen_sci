Abstract— A reduced-order ordinary differential equation initial-value model simulates the thermal evolution of isolated massive neutron stars under magnetic-dipole spin-down. The system tracks core temperature, surface temperature, central density, spin frequency, and a phase-fraction proxy. Scenario-specific switches activate latent-heat release and superfluid-modified cooling proxies when spin-down compression crosses a critical density threshold, enabling direct comparison of standard cooling, phase-transition cooling, and superfluid-enhanced phase-transition tracks.

# Assumptions

- ASM-001: Neutron stars are treated as spherically symmetric, isolated systems with no binary accretion torque or magnetic field evolution. Effect if violated: Spin-down torque and rotational compression proxies become inaccurate; observed trajectories would diverge from modeled tracks.

- ASM-002: Detailed neutrino emissivity processes and heat-capacity microphysics are absorbed into a single effective cooling timescale and scenario-dependent coefficients. Effect if violated: Temperature relaxation rates would misrepresent actual stellar cooling physics, invalidating comparative scenario analysis.

- ASM-003: Moment of inertia variations are fully parameterized into the rotational compression coefficient rather than solved dynamically. Effect if violated: Central density evolution would decouple from realistic spin-down-induced structural changes.

# Symbols

- SYM-001: $\Omega(t)$ — Angular spin frequency (rad_s^-1; inverse_time; STATE)

- SYM-002: $\rho_c(t)$ — Central density (kg_m^-3; mass_length^-3; STATE)

- SYM-003: $T_{\mathrm{core}}(t)$ — Core temperature (K; temperature; STATE)

- SYM-004: $x(t)$ — Phase fraction proxy (dimensionless; dimensionless; STATE)

- SYM-005: $T_{\mathrm{surface}}(t)$ — Surface temperature (K; temperature; STATE)

- SYM-006: $M_{\mathrm{NS}}$ — Gravitational mass of the neutron star (solar_mass; mass; SCENARIO_INPUT)

- SYM-007: $T_{c0}$ — Initial core temperature (K; temperature; BOUNDARY_CONDITION)

- SYM-008: $\Omega_0$ — Initial angular spin frequency (rad_s^-1; inverse_time; SCENARIO_INPUT)

- SYM-009: $\rho_{c0}$ — Initial central density (kg_m^-3; mass_length^-3; BOUNDARY_CONDITION)

- SYM-010: $\dot{P}_0$ — Initial spin period derivative (s_s^-1; dimensionless; SCENARIO_INPUT)

- SYM-011: $\rho_{\mathrm{crit}}$ — Critical density for phase transition (kg_m^-3; mass_length^-3; MATERIAL_PROPERTY)

- SYM-012: $L_{\mathrm{latent}}$ — Effective latent-heat temperature proxy (K; temperature; MATERIAL_PROPERTY)

- SYM-013: $S$ — Scenario selector switch (dimensionless; dimensionless; SCENARIO_INPUT)

- SYM-014: $n$ — Braking index (dimensionless; dimensionless; MODEL_ASSUMPTION)

- SYM-015: $\tau_{\mathrm{cool}}$ — Effective cooling timescale (s; time; MODEL_ASSUMPTION)

- SYM-016: $\alpha_{cs}$ — Core-to-surface temperature conversion coefficient (dimensionless; dimensionless; BOUNDARY_CONDITION)

- SYM-017: $\kappa_{\mathrm{rot}}$ — Rotational compression coefficient (kg_s^2_m^-3; mass_length^-3_time^2; MODEL_ASSUMPTION)

# Equations

- Q2-EQ-001 (DERIVATIVE): $d\Omega/dt = -(\dot{P}_0 / 2\pi) \cdot \Omega_0^{2-n} \cdot \Omega^n$. Where SYM-001: Angular spin frequency; SYM-008: Initial angular spin frequency; SYM-010: Initial spin period derivative; SYM-014: Braking index.

- Q2-EQ-002 (DERIVATIVE): $d\rho_c/dt = -\kappa_{\mathrm{rot}} \cdot \Omega \cdot (d\Omega/dt) \cdot (M_{\mathrm{NS}}/1.42)$. Where SYM-002: Central density; SYM-001: Angular spin frequency; SYM-017: Rotational compression coefficient; SYM-006: Gravitational mass of the neutron star.

- Q2-EQ-003 (DERIVATIVE): $dx/dt = \begin{cases} (1-x)/(0.01\tau_{\mathrm{cool}}) & S \geq 1 \land \rho_c \geq \rho_{\mathrm{crit}} \\ 0 & \text{otherwise} \end{cases}$. Where SYM-004: Phase fraction proxy; SYM-013: Scenario selector switch; SYM-002: Central density; SYM-011: Critical density for phase transition; SYM-015: Effective cooling timescale.

- Q2-EQ-004 (DERIVATIVE): $dT_{\mathrm{core}}/dt = -\gamma \cdot T_{\mathrm{core}}/\tau_{\mathrm{cool}} + L_{\mathrm{latent}} \cdot dx/dt, \quad \gamma = \begin{cases} 1 & S < 2 \\ 0.5 & S \geq 2 \end{cases}$. Where SYM-003: Core temperature; SYM-013: Scenario selector switch; SYM-015: Effective cooling timescale; SYM-012: Effective latent-heat temperature proxy; SYM-004: Phase fraction proxy.

- Q2-EQ-005 (DERIVATIVE): $dT_{\mathrm{surface}}/dt = \alpha_{cs} \cdot dT_{\mathrm{core}}/dt$. Where SYM-005: Surface temperature; SYM-016: Core-to-surface temperature conversion coefficient; SYM-003: Core temperature.

# Initial and Boundary Conditions

- {'condition_id': 'IC-001', 'state': 'Omega', 'value': 30.44178928}

- {'condition_id': 'IC-002', 'state': 'rho_c', 'value': 4.5e+17}

- {'condition_id': 'IC-003', 'state': 'T_core', 'value': 1000000000.0}

- {'condition_id': 'IC-004', 'state': 'phase_fraction', 'value': 0.0}

- {'condition_id': 'IC-005', 'state': 'T_surface', 'value': 1000000.0}

- {'condition_id': 'BC-001', 'description': 'Surface temperature initialized as linear projection of core temperature via alpha_cs.', 'symbol_refs': ['SYM-005', 'SYM-003', 'SYM-016']}

- {'condition_id': 'BC-002', 'description': 'Central density seeded below transition threshold to permit spin-down crossing.', 'symbol_refs': ['SYM-002', 'SYM-011']}

# Algorithm

Input: Parameter set values; Scenario selector override; Time span bounds

Output: State trajectories over time; Surface temperature vs age tracks

Steps: Initialize state vector from approved initial conditions and parameter values.; Evaluate scenario selector to determine active cooling proxy and latent-heat activation logic.; Integrate coupled ODE system using stiff adaptive solver over defined time span.; Apply conditional branching for phase fraction evolution based on central density threshold.; Compute surface temperature trajectory from core temperature derivative and conversion coefficient.; Export synchronized time-series arrays for post-processing and observational comparison.

# Parameters and Scenarios

- Parameter: {'parameter_id': 'neutron_star_mass', 'mathir_symbol': 'M_NS', 'value': 1.42, 'unit': 'solar_mass', 'role': 'SCENARIO_INPUT'}

- Parameter: {'parameter_id': 'initial_core_temperature', 'mathir_symbol': 'T_c0', 'value': 1000000000.0, 'unit': 'K', 'role': 'BOUNDARY_CONDITION'}

- Parameter: {'parameter_id': 'initial_spin_frequency', 'mathir_symbol': 'Omega0', 'value': 30.44178928, 'unit': 'rad_s^-1', 'role': 'SCENARIO_INPUT'}

- Parameter: {'parameter_id': 'initial_central_density', 'mathir_symbol': 'rho_c0', 'value': 4.5e+17, 'unit': 'kg_m^-3', 'role': 'BOUNDARY_CONDITION'}

- Parameter: {'parameter_id': 'initial_spin_period_derivative', 'mathir_symbol': 'Pdot0', 'value': 9.7228e-13, 'unit': 's_s^-1', 'role': 'SCENARIO_INPUT'}

- Parameter: {'parameter_id': 'phase_transition_critical_density', 'mathir_symbol': 'rho_crit', 'value': 5.12e+17, 'unit': 'kg_m^-3', 'role': 'MATERIAL_PROPERTY'}

- Parameter: {'parameter_id': 'effective_latent_heat_temperature_release', 'mathir_symbol': 'L_latent', 'value': 50000000.0, 'unit': 'K', 'role': 'MATERIAL_PROPERTY'}

- Parameter: {'parameter_id': 'scenario_selector', 'mathir_symbol': 'scenario', 'value': 1.0, 'unit': 'dimensionless', 'role': 'SCENARIO_INPUT'}

- Parameter: {'parameter_id': 'braking_index', 'mathir_symbol': 'n', 'value': 3.15, 'unit': 'dimensionless', 'role': 'MODEL_ASSUMPTION'}

- Parameter: {'parameter_id': 'effective_cooling_timescale', 'mathir_symbol': 'tau_cool', 'value': 3155760000000.0, 'unit': 's', 'role': 'MODEL_ASSUMPTION'}

- Parameter: {'parameter_id': 'core_surface_conversion_coefficient', 'mathir_symbol': 'alpha_cs', 'value': 0.001, 'unit': 'dimensionless', 'role': 'BOUNDARY_CONDITION'}

- Parameter: {'parameter_id': 'rotational_compression_coefficient', 'mathir_symbol': 'kappa_rot', 'value': 150000000000000.0, 'unit': 'kg_s^2_m^-3', 'role': 'MODEL_ASSUMPTION'}

- Scenario: {'scenario_id': 'standard_cooling', 'parameter_overrides': {'scenario': 0.0}, 'description': 'Standard cooling without phase transition or superfluid modification.'}

- Scenario: {'scenario_id': 'phase_transition', 'parameter_overrides': {'scenario': 1.0}, 'description': 'Phase transition cooling with latent heat release upon density threshold crossing.'}

- Scenario: {'scenario_id': 'phase_transition_superfluid', 'parameter_overrides': {'scenario': 2.0}, 'description': 'Phase transition cooling with modified neutrino emissivity proxy (reduced cooling factor).'}

# Objective and Constraints

- {'constraint_id': 'OBJ-001', 'description': 'Maximize physical fidelity within reduced-order framework while maintaining computational tractability for scenario comparison.'}

- {'constraint_id': 'OBJ-002', 'description': 'Ensure all temperatures, densities, and phase fractions remain non-negative throughout integration.'}

- {'constraint_id': 'OBJ-003', 'description': 'Limit output trajectory points to 2000 or fewer by enforcing appropriate maximum step size relative to total simulation horizon.'}

# Numerical Validation

Solver: Stiff ODE IVP integrator (e.g., LSODA or Radau). Discretization: Adaptive step-size control with hard cap at 5.0e9 seconds to guarantee <=2000 evaluation points over 3*tau_cool horizon..

- Convergence check: Step-size tolerance verification

- Convergence check: Mass-conservation proxy monitoring

- Convergence check: Non-negativity enforcement checks

- Validation: {'plan_id': 'VAL-001', 'method': 'Cross-scenario consistency check: verify that changing scenario selector alters at least one derivative term or state initialization.'}

- Validation: {'plan_id': 'VAL-002', 'method': 'Boundary limit test: confirm surface temperature remains positive and bounded for all three approved scenarios.'}

- Validation: {'plan_id': 'VAL-003', 'method': 'Observational bracketing: compare simulated T_s(t) tracks against published X-ray cooling curves for isolated massive pulsars.'}

# Limitations

- Highly sensitive to the choice of EOS and phase transition parameters; observational uncertainties in distance and radius affect temperature inference.

- Assumes spherical symmetry and ignores binary recycling, companion-ablation evolution, and detailed crustal heat blanketing.

- No resolved neutrino microphysics or full equation-of-state integration; relies on effective proxy coefficients for first executable run.

# References

- {'ref_id': 'REF-001', 'citation': 'Stejner et al. (2009), Signature of Deconfinement with Spin-down Compression in Cooling Hybrid Stars, ApJ, 694, 1019.'}

- {'ref_id': 'REF-002', 'citation': 'Gao et al. (2017), On the magnetic field evolution of PSR J1640-4631, ApJ, 840, 12.'}
