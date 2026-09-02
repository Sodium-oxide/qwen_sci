# Mathematical Model Catalog from Leading-Journal Papers Across Five Domains

> Document version: 2026-09-01  
> Scope: mathematics, physics, and astronomy; energy, engineering, and systems; Earth, environment, and agricultural ecology; materials, chemistry, and chemical engineering; and power systems.  
> Evidence standard: Bibliographic metadata for the cited papers were cross-validated using the OpenAlex and Academic sources. “Leading journals” denotes high-impact cross-disciplinary journals and flagship or leading specialist journals in their respective fields; it is not a unified ranking based on a single year's Journal Impact Factor (JIF).

## Scope and Evidence Boundary

This catalog makes a strict distinction between two layers:

1. **Paper-direct models:** Modeling methods that the representative paper in each domain actually used or explicitly described.
2. **Standard domain model families:** Executable equation skeletons compiled for conducting related research. They do not imply that every representative paper used every listed equation.

The equations use simplified, modeling-level notation. For a concrete research task, the discretization scheme, parameterization, data assimilation method, solver, and boundary conditions must be refined using the original sources and the available data.

---

## 1. Mathematics, Physics, and Astronomy

### Representative Papers and Direct Models

- **Dax et al., Physical Review Letters, 2023** — [Neural Importance Sampling for Rapid and Reliable Gravitational-Wave Inference](https://doi.org/10.1103/physrevlett.130.171403): neural posterior estimation, importance-sampling reweighting, and Bayesian evidence.
- **Agazie et al., The Astrophysical Journal Letters, 2023** — [The NANOGrav 15 yr Data Set: Evidence for a Gravitational-wave Background](https://doi.org/10.3847/2041-8213/acdac6): a power-law stochastic background, Hellings–Downs spatial correlations, and Bayesian and frequentist evidence.
- **Springel, MNRAS, 2005** — [The cosmological simulation code GADGET-2](https://doi.org/10.1111/j.1365-2966.2005.09655.x): collisionless N-body dynamics, TreePM gravity, and entropy-conserving smoothed-particle hydrodynamics (SPH).

### Detailed Model Catalog

| Model family | Mathematical skeleton | Key variables and constraints | Primary outputs |
|---|---|---|---|
| N-body gravitational dynamics | `dr_i/dt = v_i`; `dv_i/dt = -G sum_j m_j(r_i-r_j)/|r_i-r_j|^3` | Initial particles, mass conservation, softening scale, time-step stability | Orbits, density fields, dark-matter haloes |
| Poisson–fluid coupling | `nabla^2 Phi = 4 pi G rho`; `dU/dt + div F(U) = S(U,Phi)` | Conservation of mass, momentum, and energy; initial and boundary conditions | Gas density, temperature, shocks; subgrid physics can be added for galaxy-formation applications |
| SPH / moving mesh | `A(r) approx sum_j m_j A_j W(|r-r_j|,h_j)/rho_j` | Kernel function, smoothing length, adaptive resolution | Multiscale fluid evolution and feedback |
| ODE/DAE dynamics | `dx/dt = f(x,u,theta,t)`; `0 = g(x,u,theta,t)` | Initial conditions, conserved quantities, physically feasible domain | Steady states, cycles, bifurcations, response times |
| 1D advection–diffusion–reaction | `dc/dt + u dc/dx = D d2c/dx2 + R(c)` | Initial and boundary conditions, non-negativity, numerical stability | Wave fronts, diffusion lengths, concentration profiles |
| Waveform inversion | `d = h(theta) + n`; `p(theta|d) proportional p(d|theta)p(theta)` | Noise covariance, waveform physics, priors | Masses, spins, distances, and credible intervals |
| Neural posterior estimation and importance sampling | `w_i = p(d|theta_i)p(theta_i)/q_phi(theta_i|d)` | Sampling efficiency, weight degeneracy, coverage diagnostics | Corrected posteriors and Bayesian evidence |
| Stochastic-background hierarchical model | `h_c(f) = A(f/f_ref)^alpha`; `C = S_noise + S_gw Gamma_HD` | Spectral index, spatial correlations, positive-definite covariance | Background amplitude, spectral shape, model comparison |
| Constrained Monte Carlo/MCMC | `E[g] approx (1/N) sum_i g(x_i)` | Physically feasible domain, convergence, effective sample size | Uncertainty propagation and interval estimates |

**Modeling guidance:** For state-evolution problems, prioritize ODEs, discrete-state models, or 1D PDEs. For observational inversion problems, combine a forward physical model with a noise model and Bayesian or constrained Monte Carlo inference.

---

## 2. Energy, Engineering, and Systems

### Representative Papers and Direct Models

- **Wang et al., Nature, 2023** — [Accelerating the energy transition towards photovoltaic and wind in China](https://doi.org/10.1038/s41586-023-06180-8): spatial deployment optimization for 3,844 wind and photovoltaic plants, coupled with transmission, storage, load flexibility, and learning dynamics.
- **Dowling et al., Joule, 2020** — [Role of Long-Duration Energy Storage in Variable Renewable Electricity Systems](https://doi.org/10.1016/j.joule.2020.07.007): joint capacity-and-operation planning for long-duration storage in high-renewable electricity systems.
- **Brown et al., Energy, 2018** — [Synergies of sector coupling and transmission reinforcement in a cost-optimised, highly renewable European energy system](https://doi.org/10.1016/j.energy.2018.06.222): PyPSA-Eur-Sec-30 cross-sector coupling, transmission expansion, and spatiotemporal cost optimization.

### Detailed Model Catalog

| Model family | Mathematical skeleton | Key variables and constraints | Primary outputs |
|---|---|---|---|
| Capacity expansion planning | `min sum_i C_inv,i x_i + sum_t C_op(p_t)` | Installed capacity, hourly dispatch, demand balance, carbon constraints | Optimal technology portfolios and system cost |
| Siting-and-construction MILP | `x_i in {0,1}`; `0 <= p_it <= CF_it Pbar_i x_i` | Candidate sites, resource/land availability, budget | Siting of plants, lines, and storage |
| Multi-energy flow network | `sum_in f - sum_out f + s = d` | Electricity–heat–hydrogen–gas balance and conversion efficiency | Energy flows and sector-coupling pathways |
| Storage state-space model | `E_(t+1) = E_t + eta_c P_c dt - P_d dt/eta_d` | State of charge (SOC), power limits, no simultaneous charging and discharging | Capacity requirements and charge/discharge schedules |
| Transmission/pipeline expansion | `f_l,t = B_l(theta_i,t-theta_j,t)` | Thermal limits, connectivity, construction cost | Expansion locations and congestion relief |
| Time-series dispatch | `min sum_t(c_fuel p_t + c_shed L_shed,t)` | Load balance, ramping, unit commitment, availability | Hourly operating schedules |
| Stochastic/robust planning | `min_x cT x + sum_s pi_s Q(x,xi_s)` or `min_x max_(xi in U) Q(x,xi)` | Weather, load, and price scenarios or uncertainty sets | Cost–risk trade-offs |
| Reliability and resilience | `Pr(loss of load)`, EENS, LOLE | Failure rates, reserves, restoration sequence | Unserved load and restoration strategies |
| Technology learning curve | `C_t = C_0(Q_t/Q_0)^(-b)` | Cumulative deployment and learning exponent | Long-term costs and deployment pathways |
| Multi-objective optimization | `min {cost, CO2, EENS, -resilience}` | Weights or epsilon constraints | Pareto fronts |

**Modeling guidance:** The backbone is typically joint optimization of spatial siting, time-series dispatch, network constraints, storage states, and uncertainty. Add thermal inertia, electrochemical, or control ODEs when dynamic device mechanisms are material.

---

## 3. Earth, Environment, and Agricultural Ecology

### Representative Papers and Direct Models

- **Rosenzweig et al., PNAS, 2014** — [Assessing agricultural risks of climate change in the 21st century in a global gridded crop model intercomparison](https://doi.org/10.1073/pnas.1222463110): an ensemble comparison of seven global gridded crop models, five global climate models, and multiple emissions pathways.
- **Swart et al., Geoscientific Model Development, 2019** — [The Canadian Earth System Model version 5 (CanESM5.0.3)](https://doi.org/10.5194/gmd-12-4823-2019): a coupled Earth System Model covering the atmosphere, ocean, sea ice, land, and carbon cycle.
- **Guenther et al., Atmospheric Chemistry and Physics, 2006** — [Estimates of global terrestrial isoprene emissions using MEGAN](https://doi.org/10.5194/acp-6-3181-2006): a biogenic-emissions model driven by environmental activity factors.

### Detailed Model Catalog

| Model family | Mathematical skeleton | Key variables and constraints | Primary outputs |
|---|---|---|---|
| Coupled Earth System Model | `dy/dt = F_atm + F_ocean + F_land + F_ice` | Component-wise conservation and coupling fluxes | Temperature, precipitation, circulation, carbon sinks |
| Energy-balance model | `C dT/dt = F(t) - lambda T` | Radiative forcing, feedback, initial conditions | Temperature response and climate sensitivity |
| Hydrological water balance | `S_(t+1) = S_t + P_t - ET_t - R_t - D_t` | Non-negative storage and soil water-holding capacity | Soil moisture, runoff, drought |
| 1D transport–reaction | `dC/dt + u dC/dx = d(D dC/dx)/dx + R(C)` | Initial/boundary conditions, reaction rates, diffusion coefficients | Pollutant or nutrient transport |
| Crop growth/yield | `B_(t+1)=B_t+RUE*PAR*f_T*f_W*f_N-R_m`; `Y=HI*B` | Temperature, water, nitrogen, phenology | Biomass, yield, climate shocks |
| Multi-pool carbon–nitrogen model | `dC_k/dt = I_k - sum_j k_kj C_k` | Pool capacity, stoichiometry, temperature/moisture response | Soil carbon, nitrogen losses, fluxes |
| MEGAN emission factors | `E = epsilon gamma_T gamma_PAR gamma_LAI gamma_age ...` | Emission factors, temperature, radiation, leaf area, vegetation type | VOC/isoprene fluxes |
| Land-use transition | `p_ij,t = Pr(z_(t+1)=j | z_t=i,X_t)` | Category conservation, suitability, policy | Land-cover and cropland change |
| Niche/species-distribution model | `Pr(presence=1)=sigmoid(betaT X + eta_spatial)` | Climate covariates, spatial correlation, detectability | Suitable habitat and migration risk |
| Ensemble simulation and assimilation | `x_a=x_f+K(y-Hx_f)` | Observation errors, model errors, scenario ensembles | Posterior states and predictive intervals |

**Modeling guidance:** First identify the forcing–process–response chain. ODEs, discrete water-balance/carbon–nitrogen pools, 1D transport, and ensemble Monte Carlo cover most initial problems; fully coupled Earth System Models are high-fidelity extensions.

---

## 4. Materials, Chemistry, and Chemical Engineering

### Representative Papers and Direct Models

- **Xie and Grossman, Physical Review Letters, 2018** — [Crystal Graph Convolutional Neural Networks for an Accurate and Interpretable Prediction of Material Properties](https://doi.org/10.1103/physrevlett.120.145301): CGCNN for predicting DFT material properties from crystal graphs.
- **Deng et al., Nature Machine Intelligence, 2023** — [CHGNet as a pretrained universal neural network potential for charge-informed atomistic modelling](https://doi.org/10.1038/s42256-023-00716-3): a charge-informed atomistic graph neural-network potential jointly learning energy, forces, stresses, and magnetic moments.
- **Batzner et al., Nature Communications, 2022** — [E(3)-equivariant graph neural networks for data-efficient and accurate interatomic potentials](https://doi.org/10.1038/s41467-022-29939-5): E(3)-equivariant graph neural-network interatomic potentials.

### Standard Domain Model Families

The first three entries in the table below are directly supported by the materials-informatics papers above. The remaining entries are reusable standard model families in materials, chemistry, and chemical-engineering research; **they do not imply that all three materials-machine-learning papers used every model listed below**.

| Model family | Mathematical skeleton | Key variables and constraints | Primary outputs |
|---|---|---|---|
| DFT/Kohn–Sham | `[-hbar^2/(2m) nabla^2 + V_eff] psi_i = epsilon_i psi_i` | Electron count, periodic boundaries, exchange-correlation functional | Energy, electronic states, formation energies, barriers |
| Molecular dynamics | `m_i d2r_i/dt2 = -nabla_(r_i) U(r)` | Temperature/pressure ensemble, potential function, time step | Phase transitions, diffusion, interface evolution |
| Machine-learning interatomic potential | `U(R) approx sum_i u_phi(N_i)`; `F_i=-nabla_i U` | Symmetry and energy–force consistency | Large-scale atomistic simulation |
| Crystal graph neural network | `h_i^(l+1)=Phi(h_i^(l),sum_j Psi(h_i,h_j,e_ij))` | Atomic nodes, bond edges, periodic graph | Band gap, formation energy, stability |
| CALPHAD | `min G(T,P,{n_alpha,x_alpha})` | Element conservation and non-negative phase fractions | Phase diagrams and phase stability |
| Cahn–Hilliard phase field | `dc/dt = div(M grad mu)+R`; `mu=delta F/delta c` | Composition conservation, free energy, interfacial energy | Phase separation, dendrites, diffusion-driven phase transitions |
| Allen–Cahn phase field | `deta/dt = -L delta F/delta eta` | Non-conserved order parameter and interface mobility | Grain growth and interface motion |
| Microkinetics | `dtheta/dt = S r(theta,T,p)`; `k=A exp(-Ea/RT)` | Site conservation and reaction network | Surface coverage, selectivity, rate-determining steps |
| Electrochemical kinetics | `i=i0[exp(alpha_a F eta/RT)-exp(-alpha_c F eta/RT)]` | Charge conservation, mass transport, electric potential | Polarization, capacity, reaction rates |
| Reactor model | CSTR: `dC/dt=(F/V)(C_in-C)+nu r`; PFR: `dF_i/dV=nu_i r` | Mass/energy conservation, heat and mass transfer | Conversion, selectivity, operating window |
| Structural finite elements | `div sigma+b=0`; `sigma=C:epsilon` | Constitutive laws, boundary loads, damage | Strength, lifetime, failure location |
| KMC/master equation | `dp_i/dt=sum_j(k_ji p_j-k_ij p_i)` | Event rates and detailed balance | Rare events, diffusion, deposition |
| Parameter scanning/Bayesian optimization | `theta*=argmin J(theta)`; `f approx GP` | Experimental budget, feasible domain, noise | Optimal formulations and process windows |

**Modeling guidance:** Build interpretable parameter transfer across quantum/atomic, mesoscale, and engineering levels. Do not treat a machine-learning point prediction as an engineering conclusion by itself.

---

## 5. Power Systems

### Representative Papers and Direct Models

- **Lubin, Dvorkin and Backhaus, IEEE Transactions on Power Systems, 2015** — [A Robust Approach to Chance Constrained Optimal Power Flow With Renewable Generation](https://doi.org/10.1109/tpwrs.2015.2499753): robust chance-constrained OPF with cutting-plane algorithms for distributional uncertainty.
- **Ding et al., IEEE Transactions on Smart Grid, 2017** — [A Data-Driven Stochastic Reactive Power Optimization Considering Uncertainties in Active Distribution Networks and Decomposition Method](https://doi.org/10.1109/tsg.2017.2677481): data-driven two-stage stochastic reactive-power optimization and decomposition.
- **Ding et al., IEEE Transactions on Sustainable Energy, 2016** — [A Two-Stage Robust Optimization for Centralized-Optimal Dispatch of Photovoltaic Inverters in Active Distribution Networks](https://doi.org/10.1109/tste.2016.2605926): two-stage robust dispatch of photovoltaic inverters, branch-flow second-order-cone relaxation, and column-and-constraint generation.

### Detailed Model Catalog

| Model family | Mathematical skeleton | Key variables and constraints | Primary outputs |
|---|---|---|---|
| AC power flow | `P_i=V_i sum_j V_j(G_ij cos theta_ij+B_ij sin theta_ij)`; `Q_i=V_i sum_j V_j(G_ij sin theta_ij-B_ij cos theta_ij)` | Power balance, voltages, thermal limits | Voltages, phase angles, branch power flows |
| DC power flow/economic dispatch | `f_ij=B_ij(theta_i-theta_j)`; `min sum_g C_g(P_g)` | Active-power balance, line limits, generation limits | Market clearing, congestion, approximate LMPs |
| OPF | `min C(P)` subject to AC power flow | Voltage, reactive power, thermal limits, generator capability | Economic or low-loss operating point |
| SOCP/SDP-relaxed OPF | Transform non-convex power flow into conic or semidefinite constraints | Relaxation exactness and network structure | Scalable near-global solutions |
| UC/SCUC | `u_gt in {0,1}`; `Pmin u_gt <= P_gt <= Pmax u_gt` | Unit start-up/shut-down, minimum up/down times, ramping, reserves, N-1 security | Hourly unit-commitment and reserve schedules |
| DistFlow | `P_ij=p_j+sum_k P_jk+r_ij l_ij`; `v_j=v_i-2(rP+xQ)+(r^2+x^2)l` | Under the common convention, `p_j` is nodal net load and `v_i=|V_i|^2`; signs reverse when net injection is used | Voltage control, reactive power, losses |
| Storage/DER dispatch | `SOC_(t+1)=SOC_t+eta_c P_c dt-P_d dt/eta_d` | SOC, power, degradation, PV/EV availability | Peak shaving, arbitrage, reserves |
| Demand response/thermal inertia | `T_(t+1)=aT_t+bP_HVAC,t+cT_out,t` | Comfort band, device on/off constraints, compensation | Flexible load and comfort cost |
| Two-stage stochastic planning | `min_x cT x+sum_s pi_s Q(x,xi_s)` | Day-ahead decisions, real-time recourse, scenario probabilities | Plans under expected cost |
| Robust/distributionally robust optimization | `min_x max_(xi in U) Q(x,xi)` | Error uncertainty sets/confidence sets | Worst-case feasible solutions |
| Chance-constrained OPF | `Pr[g(x,xi)<=0] >= 1-epsilon` | Risk tolerance for limit violations | Explicit risk control |
| Transient-stability DAE | `ddelta_i/dt=omega_i-omega_s`; `M_i domega_i/dt=P_mi-P_ei-D_i(omega_i-omega_s)` | Algebraic power-flow constraints and fault clearing | Frequency, rotor angle, stability margin |
| State estimation | `min_x (z-h(x))T R^(-1)(z-h(x))` | Measurement error, bad data, observability | Grid state and residual alarms |
| Electricity-market bilevel optimization | `max_price Pi_agg` s.t. `x*(price)=argmin C_user(x,price)` | Price bounds, user response, network feasibility | Pricing, incentives, social welfare |
| Distributed coordination | `min sum_i f_i(x_i)` s.t. `sum_i A_i x_i=b` | Privacy, communication, local feasible sets | Multi-agent coordinated dispatch |

**Modeling guidance:** Power-system models must explicitly retain three classes of hard constraints: power flow/voltage, security/reserves, and fast dynamic stability. Add stochastic, robust, or bilevel structures around OPF/UC when modeling markets and demand response.

---

## First-Phase Implementable Model Mapping

| Domain | Priority models for initial implementation | High-fidelity extensions |
|---|---|---|
| Mathematics, physics, and astronomy | ODEs, discrete states, constrained Monte Carlo, 1D PDEs, Bayesian inversion | 3D N-body, SPH/MHD, full-waveform hierarchical inference |
| Energy, engineering, and systems | State-space models, storage ODEs, LP/MILP | Large-scale spatial capacity expansion, multi-sector coupling, distributionally robust optimization |
| Earth, environment, and agricultural ecology | Water-balance/carbon–nitrogen ODEs, discrete time, 1D transport, ensemble simulation | Fully coupled ESMs, global gridded multi-model ensembles, data assimilation |
| Materials, chemistry, and chemical engineering | Reaction-kinetics ODEs, parameter scanning, constrained optimization, simplified mass transfer | DFT, phase fields, KMC, machine-learning interatomic potentials |
| Power systems | DC/DistFlow, storage SOC, MILP, two-stage optimization | Full AC-OPF, N-1 security, transient DAEs, bilevel market models |

## Quality Notes and Remaining Boundaries

- The bibliographic metadata were cross-validated using two sources. The model equations are executable abstractions and do not replace the full discretization and calibration details in the original papers.
- The representative materials papers focus on materials informatics and atomistic machine learning. To cite CALPHAD, phase-field, KMC, reactor, or fracture models individually as “direct leading-journal evidence,” compile an additional set of original papers specifically supporting those models.
- This catalog does not use a unified JIF to define “leading journals.” `Nature`, `PRL`, `PNAS`, and `Joule` are widely recognized high-impact journals; MNRAS, GMD, ACP, Energy, and IEEE Transactions should be understood as mainstream, flagship, or leading specialist venues in their respective fields.
