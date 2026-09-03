Abstract— This model simulates the thermal and rotational evolution of massive neutron stars to identify observational signatures of density-dependent phase transitions in the core. By coupling the spin-down history to the thermal evolution, the model tracks core and surface temperatures over time, comparing standard cooling against scenarios where core compression triggers latent heat release.

# Assumptions

- A1: The neutron star maintains spherical symmetry throughout its evolution. Effect if violated: Deviations from spherical symmetry would introduce angular dependencies in the thermal profile, invalidating the 0D core temperature approximation.

- A2: Magnetic dipole radiation is the dominant mechanism for rotational energy loss. Effect if violated: Additional spin-down mechanisms like gravitational wave emission or wind braking would alter the spin frequency evolution, decoupling it from the assumed phase transition trigger.

- A3: Latent heat release from the phase transition is proportional to the instantaneous spin frequency. Effect if violated: A different functional dependence would alter the timing and magnitude of the thermal bump, potentially masking the phase transition signature.

# Symbols

- S_T_c: $T_c$ — Core temperature (K; \Theta; state)

- S_Omega: $\Omega$ — Spin frequency (rad/s; T^{-1}; state)

- S_t: $t$ — Time (yr; T; independent)

- S_K_sd: $K_{sd}$ — Magnetic dipole spin-down constant (yr^{-1}; T^{-1}; parameter)

- S_alpha_nu: $\alpha_{nu}$ — Neutrino cooling coefficient (K^{-5} yr^{-1}; \Theta^{-5} T^{-1}; parameter)

- S_latent_heat_rate: $L_{rate}$ — Latent heat release rate coefficient (K yr^{-1}; \Theta T^{-1}; parameter)

# Equations

- Q2-EQ-001 (spin_down_evolution): $\frac{d\Omega}{dt} = -K_{sd} \Omega^3$. Where S_Omega: Spin frequency; S_t: Time; S_K_sd: Magnetic dipole spin-down constant.

- Q2-EQ-002 (thermal_evolution): $\frac{dT_c}{dt} = -\alpha_{nu} T_c^6 + L_{rate} \Omega$. Where S_T_c: Core temperature; S_t: Time; S_alpha_nu: Neutrino cooling coefficient; S_latent_heat_rate: Latent heat release rate coefficient; S_Omega: Spin frequency.

# Initial and Boundary Conditions

- {'condition_id': 'IC1', 'symbol_id': 'S_T_c', 'value': 1000000000.0, 'description': 'Initial core temperature sampled from birth distribution'}

- {'condition_id': 'IC2', 'symbol_id': 'S_Omega', 'value': 314.159, 'description': 'Initial spin frequency corresponding to a 0.02 s period'}

- {'condition_id': 'BC1', 'type': 'algebraic', 'description': 'Surface temperature is determined by radiative transfer from the atmosphere model, algebraically related to core temperature.'}

# Algorithm

Input: Initial states T_c and Omega; Parameters K_sd, alpha_nu, latent_heat_rate; Time span 0 to 10000 years

Output: Time series of T_c; Time series of Omega; Derived surface temperature and luminosity

Steps: Initialize state vector with T_c = 1.0e9 and Omega = 314.159; Integrate the coupled ODE system for spin-down and thermal evolution using a stiff solver; At each time step, compute the algebraic surface temperature from the core temperature; Record the state variables and derived observables for post-processing

# Parameters and Scenarios

- Parameter: {'parameter_id': 'P1', 'symbol_id': 'S_K_sd', 'value': 1e-10, 'description': 'Standard magnetic dipole spin-down constant'}

- Parameter: {'parameter_id': 'P2', 'symbol_id': 'S_alpha_nu', 'value': 1e-20, 'description': 'Modified Urca neutrino emissivity coefficient'}

- Parameter: {'parameter_id': 'P3', 'symbol_id': 'S_latent_heat_rate', 'value': 1000000000000000.0, 'description': 'Phase transition latent heat release scaling factor'}

- Scenario: {'scenario_id': 'SC1', 'name': 'Standard Cooling', 'description': 'No phase transition, constant moment of inertia, latent heat release disabled.', 'parameter_overrides': {'S_latent_heat_rate': 0.0}}

- Scenario: {'scenario_id': 'SC2', 'name': 'Phase Transition Cooling', 'description': 'Core compression triggers phase transition, releasing latent heat proportional to spin frequency.', 'parameter_overrides': {'S_latent_heat_rate': 1000000000000000.0}}

# Objective and Constraints

- {'item_id': 'OC1', 'type': 'objective', 'description': 'Compute the surface temperature and X-ray luminosity tracks over 10,000 years to identify thermal bumps indicative of phase transitions.'}

- {'item_id': 'OC2', 'type': 'constraint', 'description': 'Core temperature must remain positive and physically bounded below the neutron star melting point.'}

# Numerical Validation

Solver: stiff_ode_integrator. Discretization: adaptive_runge_kutta.

- Convergence check: relative_tolerance_1e-6

- Convergence check: absolute_tolerance_1e-9

- Convergence check: max_step_10.0

- Validation: {'validation_id': 'V1', 'description': 'Compare the standard cooling track against established analytical and numerical neutron star cooling curves.'}

- Validation: {'validation_id': 'V2', 'description': 'Verify energy conservation by ensuring the total rotational energy lost equals the sum of radiated energy and latent heat absorbed.'}

# Limitations

- {'limitation_id': 'L1', 'description': 'Highly sensitive to the choice of equation of state and phase transition parameters.'}

- {'limitation_id': 'L2', 'description': 'Observational uncertainties in distance and radius affect the inference of surface temperature from X-ray flux.'}

- {'limitation_id': 'L3', 'description': 'Assumes spherical symmetry, ignoring potential magnetic field-induced thermal anisotropies.'}

# References

- {'reference_id': 'R1', 'citation': 'Yakovlev, D. G., & Pethick, C. J. (2004). Neutron star cooling. Annual Review of Astronomy and Astrophysics, 42, 169-210.'}

- {'reference_id': 'R2', 'citation': 'Page, D., Lattimer, J. M., Prakash, M., & Steiner, A. W. (2004). Minimal cooling of neutron stars. The Astrophysical Journal Supplement Series, 155(2), 623.'}
