# ExperimentDesign Agent: Boundary-Explicit Fossil-Free System Study

## 1. Study objective

Determine which combinations of generation, electrification, storage, network expansion, flexible demand, non-fossil molecules, and feedstocks can meet energy services without fossil extraction and combustion under ordinary operation and correlated stress. The study is a design proposal. It contains no newly observed system result.

## 2. Boundary states

Four nested scenarios prevent boundary confusion:

- **B0, fossil-dependent baseline:** observed demand, generation, fuels, and infrastructure.
- **B1, fossil-free electricity:** no fossil generation in normal operation, but non-energy feedstocks and some end uses may remain fossil-dependent.
- **B2, fossil-free energy services:** no routine fossil combustion; direct electricity and non-fossil molecules serve buildings, transport, industry, and power reserves.
- **B3, stringent fossil-free materials:** B2 plus bounded or eliminated fossil carbon in chemicals, plastics, lubricants, asphalt, and other non-energy uses.

Each boundary is reported independently. Net-zero cases with fossil use and carbon capture are sensitivity cases, not substitutes for B2 or B3.

## 3. Portfolio factors

The core factorial design varies:

1. demand efficiency and demand response;
2. direct electrification of transport, buildings, and industry;
3. wind and solar deployment with geographic diversity and overbuild;
4. firm low-carbon supply, selected by regional feasibility;
5. short-duration, multi-day, and seasonal storage;
6. transmission and distribution reinforcement;
7. hydrogen, ammonia, sustainable biofuels, and synthetic fuels;
8. non-fossil chemical carbon, recycling, and carbon capture cases;
9. manufacturing, mineral, water, land, permitting, and workforce constraints;
10. adoption, financing, access, and affordability constraints.

The minimum computational experiment is a fractional factorial screening design, followed by multi-objective optimization on factors that materially affect reliability or cost. A region-specific full experiment should use representative weather years, demand traces, outage records, resource maps, technology learning assumptions, and industrial process data.

## 4. Six-stage research program

### Stage 1: Baseline and boundary audit

Construct an hourly energy-service ledger for electricity, transport, buildings, industry, agriculture, and chemical feedstocks. Record energy carriers, useful services, peak demand, seasonal demand, existing assets, retirement dates, storage, networks, and fossil uses. Tag every input as observed, modeled, or assumed. The audit produces B0 and identifies which fossil uses are hidden by an electricity-only definition.

### Stage 2: Technology and lifecycle characterization

For every technology, collect capacity, efficiency, ramp rate, minimum stable output, lifetime, degradation, outage rate, construction lead time, replacement schedule, material intensity, water use, land footprint, and upstream emissions. Include conversion chains such as electricity-to-hydrogen-to-ammonia and electricity-to-synthetic fuel. Use ranges rather than one optimistic value and preserve correlations between cost, performance, and learning.

### Stage 3: Hourly and seasonal system optimization

Optimize portfolios over representative weather and demand years with sub-hourly resolution for selected stress windows. Enforce power balance, reserve, storage state of charge, transmission flow, fuel inventory, conversion capacity, and sector-coupling constraints. Include unit commitment or an appropriate operational approximation. Repeat for low-renewable weather years and correlated outages.

### Stage 4: Stress testing and robustness

Evaluate heat waves, cold snaps, drought affecting hydropower, prolonged wind and solar lulls, transmission outages, fuel or mineral supply interruptions, demand surges, and simultaneous infrastructure failures. Use block-bootstrap or climate-informed scenario generation, then test adversarial but physically plausible combinations. Report loss-of-load probability, unserved energy, reserve shortfall, curtailment, storage depletion, emergency energy, and recovery time.

### Stage 5: Infrastructure, adoption, and distribution

Add build-rate constraints for generation, transmission, distribution, storage, electrolysers, heat pumps, vehicles, and industrial equipment. Represent permitting, financing, workforce, manufacturing capacity, and material availability as lead-time or annual-flow limits. Evaluate household and industrial energy-service access, energy burden, reliability, and regional employment. A portfolio that is technically feasible only after an impossible construction pulse should fail the transition-speed criterion.

### Stage 6: Out-of-sample validation and decision analysis

Hold out weather years, demand conditions, and outage combinations. Validate resource and demand models separately from the optimization model. Compare predicted stress outcomes with observed reliability events where available. Use regret and robust dominance rather than a single best-case scenario. Report the constraint that binds first and the portfolio lever that relaxes it.

## 5. Functional units and primary outcomes

The primary functional unit is a delivered energy service in a region-year with hourly adequacy. Secondary units are MWh of electricity, passenger-km, tonne-km, degree-days of thermal comfort, tonnes of steel or chemicals, and tonnes of non-fossil carbon feedstock. Primary outcomes are:

- loss-of-load probability and unserved energy;
- hours below reserve requirement and storage depletion duration;
- delivered service by sector and energy access group;
- lifecycle greenhouse-gas emissions and fossil extraction;
- annualized system cost and distributional energy burden;
- transition time and build-rate feasibility.

Secondary outcomes include curtailment, transmission expansion, land, water, mineral demand, material recycling, air-pollution co-benefits, emergency reserves, hydrogen or fuel production, and industrial feedstock substitution.

## 6. Mathematical formulation

Let $t$ index time, $s$ index scenarios, $k$ index technologies, and $x_k$ denote capacity. Let $g_{k,t,s}$ be dispatch, $d_{j,t,s}$ be service demand for sector $j$, and $\eta_{kj}$ represent conversion efficiency. A service adequacy constraint is

$$\sum_k \eta_{kj}g_{k,t,s}+q_{j,t,s}\ge d_{j,t,s}-u_{j,t,s},$$

where $q$ is stored or non-electric carrier delivery and $u$ is unserved service. The fossil-free boundary imposes

$$f^{\mathrm{extract}}_s=0,\qquad f^{\mathrm{combust}}_{t,s}=0$$

for B2, with explicitly bounded feedstock or emergency terms in sensitivity cases. A lifecycle accounting identity is

$$E_s=E^{\mathrm{operation}}_s+E^{\mathrm{construction}}_s+E^{\mathrm{supply}}_s-E^{\mathrm{captured}}_s.$$

The system objective is multi-objective. One decision utility for screening is

$$U(P)= -C(P)-\alpha\,\mathrm{CVaR}_{\beta}(U_s(P))-\lambda E(P)-\rho B(P),$$

where $C$ is annualized cost, $U_s$ is unserved energy service, $E$ is lifecycle emissions, and $B$ aggregates land, water, material, and distributional burdens. The final study reports the Pareto frontier rather than treating all weights as universal.

Storage follows a state equation:

$$z_{t+1}=z_t+\eta_c c_t-\frac{d_t}{\eta_d}-\delta z_t,$$

with power and energy limits, reserve requirements, and nonnegative state $z_t$. Hydrogen and synthetic-fuel chains use separate conversion capacities and inventories so that round-trip losses cannot be hidden inside a generic storage variable.

## 7. Mechanism tests

The analysis should test whether: efficiency reduces both annual energy and peak capacity; electrification moves fossil use into clean electricity without creating an unserved peak; geographic diversity reduces weather covariance; storage duration, not merely storage power, controls seasonal adequacy; transmission reduces curtailment and regional scarcity; firm supply reduces tail risk at a measurable lifecycle burden; and demand response shifts load without reducing thermal comfort or industrial output. For hard-to-electrify sectors, the key mechanism is whether non-fossil molecules deliver the service after conversion losses and infrastructure constraints.

## 8. Decision rules and safeguards

A portfolio passes a boundary only if it meets the following pre-registered conditions: zero routine fossil extraction and combustion within the declared boundary; service adequacy and reserve targets in ordinary and stress scenarios; lifecycle emissions below the specified climate budget; no violation of water, land, mineral, safety, or recycling safeguards; acceptable energy access and burden distributions; and a feasible build trajectory. Net-zero-with-CCS may pass a separate policy case but cannot be labeled B2 or B3.

The study does not prescribe one technology globally. It identifies regional bottlenecks and reports when a portfolio fails because of storage, transmission, seasonal fuels, materials, industrial conversion, or affordability. This makes the experiment useful even when the stringent boundary is not reached.

## 9. Safety, governance, and reproducibility

The work uses system data and scenario models; it does not require hazardous physical experiments. Hydrogen, ammonia, bioenergy, carbon capture, nuclear, and grid operations must still be reviewed by relevant safety and regulatory experts before deployment. Infrastructure and household data require aggregation, access controls, and protection against re-identification. All scenarios, technology assumptions, constraint versions, random seeds, and output tables should be versioned. Primary and exploratory analyses must be separated, and no modeled result should be represented as an observed fact.

## 10. Design-only status

`expected_results` and `observed_results` remain empty. The design specifies how to discover whether a fossil-fuel-free world is feasible for a declared boundary; it does not claim that any region has already passed the experiment.
