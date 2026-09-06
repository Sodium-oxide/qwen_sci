Abstract— This model materializes a reduced one-dimensional diffusion-reaction surrogate for the time-dependent actinide-line source-density proxy in expanding kilonova ejecta. It isolates delayed fission timing, expansion dilution, and free-escape boundary loss while deliberately omitting the full isotopic network, detailed atomic opacities, and multidimensional radiative transfer.

# Assumptions

- Q1-AS-001: The evolved scalar u is a surrogate for actinide spectral-line source density rather than a full isotopic abundance network. Effect if violated: Inferences about specific nuclear pathways or isotopic line ratios would not be supported by the surrogate.

- Q1-AS-002: Unresolved radiative transport is closed by a constant effective diffusion coefficient. Effect if violated: Temporal spreading and escape timing of the proxy may be biased if the true transport is strongly non-diffusive.

- Q1-AS-003: Expansion is represented by a linear dilution loss with timescale formed from R_domain and v_ejecta rather than a moving mesh. Effect if violated: The surrogate may misrepresent geometric dilution and peak-time shifts in an expanding spherical flow.

- Q1-AS-004: The initial actinide-line proxy is spatially uniform at the approved u_initial value. Effect if violated: Initial spatial asymmetries or seed concentration gradients would not be represented.

- Q1-AS-005: The approved explicit time step is coarse relative to the approved fission-release timescale, so the delayed source is numerically smeared. Effect if violated: The executable surrogate cannot resolve sub-step delayed-release structure and should be interpreted as a reduced kinetic proxy.

# Symbols

- u: $u(x,t)$ — Actinide-line source-density proxy evolved by the PDE. (kg m^-3; M L^-3; FIELD)

- x: $x$ — One-dimensional radial surrogate coordinate. (m; L; INDEPENDENT_VARIABLE)

- t: $t$ — Time since the start of the kinetic phase. (s; T; INDEPENDENT_VARIABLE)

- D_effective: $D_{\mathrm{eff}}$ — Effective diffusion coefficient representing unresolved line-energy transport. (m^2 s^-1; L^2 T^-1; PARAMETER)

- R_domain: $R_{\mathrm{domain}}$ — Outer radial extent of the one-dimensional surrogate domain. (m; L; SCENARIO_INPUT)

- v_ejecta: $v_{\mathrm{ejecta}}$ — Characteristic ejecta expansion velocity used to form the expansion dilution timescale. (m s^-1; L T^-1; SCENARIO_INPUT)

- tau_f: $\tau_f$ — Characteristic delayed fission neutron release timescale. (s; T; MATERIAL_PROPERTY)

- u_initial: $u_{\mathrm{initial}}$ — Uniform initial amplitude of the actinide-line source-density proxy. (kg m^-3; M L^-3; SCENARIO_INPUT)

- u_outer: $u_{\mathrm{outer}}$ — Dirichlet proxy value at the free-escape outer boundary. (kg m^-3; M L^-3; BOUNDARY_CONDITION)

- t_end: $t_{\mathrm{end}}$ — Final integration time for the executable surrogate. (s; T; MODEL_ASSUMPTION)

- delta_t: $\Delta t$ — Temporal step size for explicit parabolic integration. (s; T; MODEL_ASSUMPTION)

- delta_r: $\Delta r$ — Target radial grid spacing for the one-dimensional finite-difference discretization. (m; L; MODEL_ASSUMPTION)

# Equations

- Q1-EQ-001 (GOVERNING_PDE): $\frac{\partial u}{\partial t} = \frac{\partial}{\partial x}\left[ \left(D_{\mathrm{eff}}\frac{\Delta r}{\Delta r}\right) \frac{\partial u}{\partial x}\right] + \left(\frac{u_{\mathrm{initial}}}{\Delta t} e^{-t/\tau_f} \frac{t_{\mathrm{end}}}{t_{\mathrm{end}}}\right) - \frac{v_{\mathrm{ejecta}}}{R_{\mathrm{domain}}} u$. Where u: Actinide-line source-density proxy evolved by the PDE.; t: Time since the start of the kinetic phase.; x: One-dimensional radial surrogate coordinate.; D_effective: Effective diffusion coefficient representing unresolved line-energy transport.; delta_r: Target radial grid spacing for the one-dimensional finite-difference discretization.; u_initial: Uniform initial amplitude of the actinide-line source-density proxy.; delta_t: Temporal step size for explicit parabolic integration.; tau_f: Characteristic delayed fission neutron release timescale.; t_end: Final integration time for the executable surrogate.; v_ejecta: Characteristic ejecta expansion velocity used to form the expansion dilution timescale.; R_domain: Outer radial extent of the one-dimensional surrogate domain..

- Q1-EQ-002 (INITIAL_CONDITION): $u(x,0) = u_{\mathrm{initial}}$. Where u: Actinide-line source-density proxy evolved by the PDE.; x: One-dimensional radial surrogate coordinate.; u_initial: Uniform initial amplitude of the actinide-line source-density proxy..

- Q1-EQ-003 (BOUNDARY_CONDITION): $\left.\frac{\partial u}{\partial x}\right|_{x=0} = 0$. Where u: Actinide-line source-density proxy evolved by the PDE.; x: One-dimensional radial surrogate coordinate..

- Q1-EQ-004 (BOUNDARY_CONDITION): $u(R_{\mathrm{domain}},t) = u_{\mathrm{outer}}$. Where u: Actinide-line source-density proxy evolved by the PDE.; R_domain: Outer radial extent of the one-dimensional surrogate domain.; t: Time since the start of the kinetic phase.; u_outer: Dirichlet proxy value at the free-escape outer boundary..

- Q1-EQ-005 (SOURCE_TERM): $S_f(t) = \frac{u_{\mathrm{initial}}}{\Delta t} e^{-t/\tau_f} \frac{t_{\mathrm{end}}}{t_{\mathrm{end}}}$. Where u_initial: Uniform initial amplitude of the actinide-line source-density proxy.; delta_t: Temporal step size for explicit parabolic integration.; t: Time since the start of the kinetic phase.; tau_f: Characteristic delayed fission neutron release timescale.; t_end: Final integration time for the executable surrogate..

# Initial and Boundary Conditions

- {'initial_condition_id': 'Q1-IC-001', 'description': 'Uniform actinide-line source-density proxy initialized to the approved u_initial amplitude.', 'profile': 'UNIFORM', 'applied_symbol': 'u_initial'}

- {'boundary_id': 'Q1-BC-001', 'side': 'left', 'type': 'NEUMANN_ZERO', 'description': 'Zero radial flux at the symmetry center, representing the inner spherical-symmetry surrogate.'}

- {'boundary_id': 'Q1-BC-002', 'side': 'right', 'type': 'DIRICHLET', 'boundary_value': 0.0, 'description': 'Free-escape surrogate at the outer radial surface using the approved u_outer value.'}

- Executable initial_condition: {"profile":"UNIFORM","type":"ANALYTIC_PROFILE","value":5.12186785866739e-14}.

# Algorithm

Input: Approved execution_ir document; Uniform one-dimensional grid specification; Analytic uniform initial condition; Left and right boundary condition specification

Output: Finite time-dependent scalar field u(x,t); Radial integral of u for postprocessing; Diagnostics for stability and finiteness checks

Steps: Construct the uniform one-dimensional spatial grid on the approved domain.; Initialize the field with the approved uniform analytic profile.; Evaluate the diffusion coefficient and reaction source ASTs at approved parameters.; Advance the diffusion-reaction system with the registered explicit parabolic integrator.; Enforce zero-flux symmetry at the left boundary and free-escape Dirichlet condition at the right boundary.; Store the evolved field and compute radial summary quantities for later comparison.

# Parameters and Scenarios

- Parameter: {'parameter_id': 'domain_radius', 'mathir_symbol': 'R_domain', 'approved_value': 5180413674240.0, 'unit': 'm', 'role': 'SCENARIO_INPUT', 'provenance': 'APPROVED_LITERATURE_SINGLE_SOURCE'}

- Parameter: {'parameter_id': 'ejecta_velocity', 'mathir_symbol': 'v_ejecta', 'approved_value': 59958491.6, 'unit': 'm s^-1', 'role': 'SCENARIO_INPUT', 'provenance': 'APPROVED_LITERATURE_SINGLE_SOURCE'}

- Parameter: {'parameter_id': 'fission_neutron_release_timescale', 'mathir_symbol': 'tau_f', 'approved_value': 2.3, 'unit': 's', 'role': 'MATERIAL_PROPERTY', 'provenance': 'APPROVED_LITERATURE_SINGLE_SOURCE'}

- Parameter: {'parameter_id': 'initial_actinide_density_proxy', 'mathir_symbol': 'u_initial', 'approved_value': 5.12186785866739e-14, 'unit': 'kg m^-3', 'role': 'SCENARIO_INPUT', 'provenance': 'APPROVED_LITERATURE_SINGLE_SOURCE'}

- Parameter: {'parameter_id': 'effective_diffusion_coefficient', 'mathir_symbol': 'D_effective', 'approved_value': 1e+18, 'unit': 'm^2 s^-1', 'role': 'MATERIAL_PROPERTY', 'provenance': 'APPROVED_MODEL_ASSUMPTION'}

- Parameter: {'parameter_id': 'outer_boundary_proxy_value', 'mathir_symbol': 'u_outer', 'approved_value': 0.0, 'unit': 'kg m^-3', 'role': 'BOUNDARY_CONDITION', 'provenance': 'APPROVED_MODEL_ASSUMPTION'}

- Parameter: {'parameter_id': 'simulation_end_time', 'mathir_symbol': 't_end', 'approved_value': 864000.0, 'unit': 's', 'role': 'MODEL_ASSUMPTION', 'provenance': 'APPROVED_MODEL_ASSUMPTION'}

- Parameter: {'parameter_id': 'time_step_size', 'mathir_symbol': 'delta_t', 'approved_value': 100.0, 'unit': 's', 'role': 'MODEL_ASSUMPTION', 'provenance': 'APPROVED_MODEL_ASSUMPTION'}

- Parameter: {'parameter_id': 'radial_grid_spacing', 'mathir_symbol': 'delta_r', 'approved_value': 50000000000.0, 'unit': 'm', 'role': 'MODEL_ASSUMPTION', 'provenance': 'APPROVED_MODEL_ASSUMPTION'}

- Scenario: {'scenario_id': 'Q1-SC-001', 'name': 'Instantaneous fission recycling', 'description': 'Conceptual limit in which the fission source is deposited essentially within the first numerical step.', 'mathematical_difference': 'Early-time radial integral over the first step is compared against later-time integrals.', 'execution_status': 'CONCEPTUAL_LIMIT'}

- Scenario: {'scenario_id': 'Q1-SC-002', 'name': 'Delayed fission recycling', 'description': 'Baseline executable surrogate uses the approved tau_f in the exponential source factor.', 'mathematical_difference': 'First temporal moment of the radial integral is used to quantify delay.', 'execution_status': 'BASELINE'}

- Scenario: {'scenario_id': 'Q1-SC-003', 'name': 'Geometric asymmetry only', 'description': 'Conceptual geometric comparison represented by radial variance of the proxy in postprocessing.', 'mathematical_difference': 'Radial variance replaces temporal moment as the discriminator.', 'execution_status': 'CONCEPTUAL_POSTPROCESSING'}

- Scenario: {'scenario_id': 'Q1-SC-004', 'name': 'Variable Ye only', 'description': 'Conceptual abundance comparison represented by the domain-integrated proxy mass.', 'mathematical_difference': 'Domain integral of u is used as the abundance discriminator.', 'execution_status': 'CONCEPTUAL_POSTPROCESSING'}

# Objective and Constraints

- {'objective_id': 'Q1-OBJ-001', 'description': 'Quantify whether temporal moments of the radial proxy separate fission-release timing from geometric or abundance perturbations.', 'target_symbol': 'u'}

- {'constraint_id': 'Q1-CON-001', 'description': 'Explicit diffusion stability margin is maintained with the diffusion Courant number below the parabolic limit.', 'threshold': 0.5}

- {'constraint_id': 'Q1-CON-002', 'description': 'The proxy density is interpreted as non-negative; negative excursions are treated as numerical artifacts.', 'threshold': 0.0}

# Numerical Validation

Solver: parabolic_1d. Discretization: FINITE_DIFFERENCE.

- Convergence check: Diffusion Courant number remains below the explicit parabolic stability limit.

- Convergence check: Total explicit step count remains below the authorized temporal budget.

- Convergence check: Grid cell count remains below the authorized spatial budget.

- Convergence check: Reaction loss factor remains positive and finite for the approved step size.

- Validation: {'validation_id': 'Q1-VAL-001', 'description': 'Check that the evolved field remains finite over the full approved time span.', 'expected_behavior': 'No non-finite values appear in the field or expressions.'}

- Validation: {'validation_id': 'Q1-VAL-002', 'description': 'Check that the zero-flux inner boundary preserves symmetry in the radial surrogate.', 'expected_behavior': 'No artificial flux enters through the left boundary.'}

- Validation: {'validation_id': 'Q1-VAL-003', 'description': 'Check that the outer Dirichlet boundary permits proxy escape toward the approved free-escape value.', 'expected_behavior': 'The field near the outer boundary relaxes toward the approved outer value.'}

- Validation: {'validation_id': 'Q1-VAL-004', 'description': 'Check that the explicit diffusion step size satisfies the approved stability margin.', 'expected_behavior': 'The diffusion Courant number remains safely below the parabolic limit.'}

# Limitations

- The surrogate does not resolve a full r-process isotopic network or actinide-specific line formation.

- The effective diffusion coefficient is a declared closure assumption, not a literature measurement.

- The coarse approved time step cannot resolve all structure on the approved fission-release timescale.

- Spherical symmetry is assumed in the reduced radial surrogate and cannot represent multidimensional lanthanide curtaining.

- Actinide opacity and atomic-data uncertainties are not explicitly represented.

# References

- {'reference_id': 'Q1-REF-001', 'citation': 'Barnes et al., Radioactivity and Thermalization in the Ejecta of Compact Object Mergers and Their Impact on Kilonova Light Curves, 2016', 'relevance': 'Supports the homologous-expansion radius proxy used for the domain radius.'}

- {'reference_id': 'Q1-REF-002', 'citation': 'Kasen et al., Opacities and Spectra of the r-Process Ejecta from Neutron Star Mergers, 2013', 'relevance': 'Supports the characteristic ejecta velocity range used for expansion dilution.'}

- {'reference_id': 'Q1-REF-003', 'citation': 'Mumpower et al., beta-delayed Fission in r-process Nucleosynthesis, 2018', 'relevance': 'Provides the abundance-weighted kinetic proxy for delayed fission recycling.'}

- {'reference_id': 'Q1-REF-004', 'citation': 'Domato et al., NLTE Spectra of Kilonovae, 2023', 'relevance': 'Supports the actinide mass-fraction normalization used for the initial density proxy.'}
