Abstract— A spatially resolved spherical radial thermal model for a massive neutron star core is specified as an executable PDE branch. The model replaces the parent lumped thermal state with a one-dimensional radial heat-transport field in the canonical coordinate x, where x represents the physical radial coordinate r normalized by the stellar radius. Phase-transition latent heat and modified neutrino cooling are represented through parameterized volumetric source terms. Scenario A is standard cooling without latent heat, Scenario B adds localized latent-heat release, and Scenario C modifies the cooling coefficient to emulate superfluid suppression. The declared observable outputs are radial temperature trajectories and a surface flux proxy at x=1.

# Assumptions

- Q2-ASM-001: The star is spherically symmetric and the executable PDE uses the canonical coordinate x as the physical radial coordinate r normalized by the stellar radius. Effect if violated: Non-spherical structure or multidimensional transport would not be represented, biasing radial temperature and surface-flux estimates.

- Q2-ASM-002: Spin-down induced core compression and phase-transition onset are represented by a prescribed localized latent-heat source rather than dynamically solved spin, density, or moment-of-inertia equations. Effect if violated: Feedback between rotation, compression, and transition timing is omitted, so scenario attribution becomes phenomenological.

- Q2-ASM-003: Thermal microphysics is reduced to scaled constant transport, heat-capacity, and source coefficients. Effect if violated: Temperature- and density-dependent conductivity, heat capacity, and neutrino emissivity would change cooling rates and scenario separation.

- Q2-ASM-004: The surface boundary is approximated by a fixed scaled surface temperature representing atmosphere and radiative-transfer effects. Effect if violated: An inaccurate surface boundary would alter the surface gradient, flux proxy, and inferred luminosity.

- Q2-ASM-005: Units are normalized so that the temperature field is scaled by a reference core temperature, x=1 corresponds to the stellar radius, and t=1 corresponds to a characteristic cooling time. Effect if violated: Direct physical-unit comparison requires rescaling; mismatched scaling would distort comparison with cooling curves.

# Symbols

- T: $T$ — Radial temperature field scaled by a reference core temperature (10^9 K; temperature; field)

- x: $x$ — Canonical radial coordinate representing physical radius r normalized by stellar radius (R_NS; length; coordinate)

- t: $t$ — Time scaled by a characteristic cooling time (t_char; time; time)

- source: $S$ — Volumetric heat source and sink term in scaled temperature per time (10^9 K/t_char; temperature/time; auxiliary)

- kappa: $\kappa$ — Effective radial thermal diffusion coefficient in scaled units (R_NS^2/t_char; length^2/time; parameter)

- c_v: $c_v$ — Volumetric heat capacity in scaled units (energy/(R_NS^3*10^9 K); energy/(length^3 temperature); parameter)

- latent_amp: $L_{amp}$ — Amplitude of latent-heat release from the phase-transition layer (10^9 K/t_char; temperature/time; parameter)

- cooling_amp: $\epsilon_{amp}$ — Amplitude of volumetric neutrino cooling coefficient (1/t_char; 1/time; parameter)

- transition_center: $x_{tr}$ — Normalized radial center of the phase-transition layer (R_NS; length; parameter)

- transition_width: $\sigma_{tr}$ — Normalized radial width of the phase-transition layer (R_NS; length; parameter)

- decay_rate: $\lambda$ — Inverse time scale for transition-source decay (1/t_char; 1/time; parameter)

- surface_temperature: $T_s$ — Scaled surface temperature imposed at x=1 (10^9 K; temperature; parameter)

# Equations

- Q2-EQ-001 (governing_equation): $c_v \frac{\partial T}{\partial t} = \frac{1}{x^2}\frac{\partial}{\partial x}\left(x^2 \kappa \frac{\partial T}{\partial x}\right) + S$. Where c_v: Volumetric heat capacity in scaled units; T: Radial temperature field scaled by a reference core temperature; t: Time scaled by a characteristic cooling time; x: Canonical radial coordinate representing physical radius r normalized by stellar radius; kappa: Effective radial thermal diffusion coefficient in scaled units; source: Volumetric heat source and sink term in scaled temperature per time.

- Q2-EQ-002 (source_definition): $S = L_{amp}\exp\left[-\frac{(x-x_{tr})^2}{2\sigma_{tr}^2}\right]\exp(-\lambda t) - \epsilon_{amp} T$. Where source: Volumetric heat source and sink term in scaled temperature per time; latent_amp: Amplitude of latent-heat release from the phase-transition layer; x: Canonical radial coordinate representing physical radius r normalized by stellar radius; transition_center: Normalized radial center of the phase-transition layer; transition_width: Normalized radial width of the phase-transition layer; decay_rate: Inverse time scale for transition-source decay; t: Time scaled by a characteristic cooling time; cooling_amp: Amplitude of volumetric neutrino cooling coefficient; T: Radial temperature field scaled by a reference core temperature.

- Q2-EQ-003 (boundary_condition): $\left.\frac{\partial T}{\partial x}\right|_{x=0}=0,\quad T(1,t)=T_s$. Where T: Radial temperature field scaled by a reference core temperature; x: Canonical radial coordinate representing physical radius r normalized by stellar radius; t: Time scaled by a characteristic cooling time; surface_temperature: Scaled surface temperature imposed at x=1.

# Initial and Boundary Conditions

- {'condition_id': 'Q2-IC-001', 'field_id': 'T', 'profile': 'UNIFORM', 'description': 'Uniform scaled initial core temperature across the radial domain.'}

- {'boundary_id': 'Q2-BC-001', 'side': 'left', 'type': 'SPHERICAL_ORIGIN_REGULARITY', 'description': 'Regularity at the spherical origin x=0.'}

- {'boundary_id': 'Q2-BC-002', 'side': 'right', 'type': 'DIRICHLET', 'value_parameter': 'surface_temperature', 'description': 'Fixed scaled surface temperature at x=1.'}

- Executable initial_condition: {"profile":"UNIFORM","type":"ANALYTIC_PROFILE","value":1.0}.

# Algorithm

Input: scenario parameter values; spatial_domain; grid; initial_condition; boundary_conditions

Output: radial temperature field T(x,t); surface flux proxy at x=1; scenario comparison diagnostics

Steps: Select scenario parameter values.; Initialize the uniform scaled temperature field.; Apply spherical origin regularity and the surface Dirichlet condition.; Advance the spherical radial heat equation with the registered explicit integrator.; Evaluate stability and finiteness checks.; Extract radial profiles and the surface flux proxy.; Compare scenario tracks against the declared falsification criteria.

# Parameters and Scenarios

- Parameter: {'parameter_id': 'Q2-PRM-001', 'symbol_id': 'kappa', 'base_value': 0.01, 'evidence_status': 'model_assumption', 'source': 'Scaled effective radial thermal diffusion chosen for explicit spherical stability.'}

- Parameter: {'parameter_id': 'Q2-PRM-002', 'symbol_id': 'c_v', 'base_value': 1.0, 'evidence_status': 'model_assumption', 'source': 'Scaled volumetric heat capacity reference.'}

- Parameter: {'parameter_id': 'Q2-PRM-003', 'symbol_id': 'latent_amp', 'base_value': 0.0, 'evidence_status': 'scenario_input', 'source': 'No latent heat in the standard scenario; positive in phase-transition scenarios.'}

- Parameter: {'parameter_id': 'Q2-PRM-004', 'symbol_id': 'cooling_amp', 'base_value': 0.02, 'evidence_status': 'model_assumption', 'source': 'Scaled neutrino cooling coefficient.'}

- Parameter: {'parameter_id': 'Q2-PRM-005', 'symbol_id': 'transition_center', 'base_value': 0.35, 'evidence_status': 'model_assumption', 'source': 'Normalized core radius where the phase transition is concentrated.'}

- Parameter: {'parameter_id': 'Q2-PRM-006', 'symbol_id': 'transition_width', 'base_value': 0.12, 'evidence_status': 'model_assumption', 'source': 'Normalized radial width of the transition layer.'}

- Parameter: {'parameter_id': 'Q2-PRM-007', 'symbol_id': 'decay_rate', 'base_value': 0.6, 'evidence_status': 'model_assumption', 'source': 'Inverse time scale for latent-heat release decay.'}

- Parameter: {'parameter_id': 'Q2-PRM-008', 'symbol_id': 'surface_temperature', 'base_value': 0.1, 'evidence_status': 'model_assumption', 'source': 'Scaled surface temperature representing the atmosphere boundary.'}

- Scenario: {'scenario_id': 'Q2-SCN-A', 'name': 'Standard cooling', 'description': 'No phase-transition latent heat and standard scaled neutrino cooling.', 'parameter_overrides': {'latent_amp': 0.0, 'cooling_amp': 0.02, 'surface_temperature': 0.1}}

- Scenario: {'scenario_id': 'Q2-SCN-B', 'name': 'Phase transition cooling', 'description': 'Localized latent-heat release associated with spin-down induced core compression.', 'parameter_overrides': {'latent_amp': 0.3, 'cooling_amp': 0.02, 'surface_temperature': 0.1}}

- Scenario: {'scenario_id': 'Q2-SCN-C', 'name': 'Phase transition with superfluidity', 'description': 'Latent-heat release with suppressed neutrino cooling representing superfluid modification.', 'parameter_overrides': {'latent_amp': 0.3, 'cooling_amp': 0.01, 'surface_temperature': 0.1}}

# Objective and Constraints

- {'objective_id': 'Q2-OBJ-001', 'statement': 'Compare radial temperature trajectories and the surface flux proxy among standard, phase-transition, and superfluid-modified scenarios.'}

- {'objective_id': 'Q2-OBJ-002', 'statement': 'Determine whether localized latent-heat release produces a distinguishable delay or deviation in cooling relative to standard cooling.'}

- {'constraint_id': 'Q2-CON-001', 'statement': 'Use only the registered spherical radial thermal PDE adapter with a uniform grid and explicit time integration.'}

- {'constraint_id': 'Q2-CON-002', 'statement': 'Maintain non-negative diffusion coefficient, positive heat capacity, and finite field values throughout the declared time span.'}

# Numerical Validation

Solver: spherical_radial_thermal. Discretization: FINITE_DIFFERENCE_SPHERICAL_RADIAL.

- Convergence check: Verify that the explicit spherical stability number remains below the registered limit.

- Convergence check: Repeat with a halved time step and compare the surface flux proxy.

- Convergence check: Check that all field samples remain finite throughout the time span.

- Validation: {'check_id': 'Q2-VAL-001', 'description': 'Preflight stability: the explicit spherical diffusion number remains below the registered limit.', 'status': 'required_before_execution'}

- Validation: {'check_id': 'Q2-VAL-002', 'description': 'Scenario separation: phase-transition scenarios produce different radial temperature histories and surface flux proxy values from the standard scenario.', 'status': 'required_after_execution'}

- Validation: {'check_id': 'Q2-VAL-003', 'description': 'Boundary consistency: center regularity and surface Dirichlet condition are satisfied without non-finite values.', 'status': 'required_after_execution'}

- Validation: {'check_id': 'Q2-VAL-004', 'description': 'Observational relevance: the surface flux proxy is mapped to luminosity only after external scaling and calibration.', 'status': 'postprocessing'}

# Limitations

- The model does not solve spin evolution, moment of inertia, or central density dynamically; spin-down compression is parameterized by a prescribed source.

- Microphysical equation-of-state effects, latent heat, neutrino emissivity, and superfluid suppression are represented by scaled coefficients rather than density-temperature tables.

- The surface boundary is simplified; atmosphere radiative transfer and gravitational redshift are not solved.

- Spherical symmetry and a uniform radial grid exclude multidimensional effects and sharp phase-boundary dynamics.

- No observational data are ingested; comparison to X-ray cooling curves requires external calibration and uncertainty treatment.

# References

- Standard neutron-star cooling theory and cooling-curve literature for model comparison.

- X-ray observations of isolated neutron stars and massive pulsars from Chandra and XMM-Newton archives as external comparator context.

- Equation-of-state and phase-transition literature for neutron-star cores as parameter motivation.
