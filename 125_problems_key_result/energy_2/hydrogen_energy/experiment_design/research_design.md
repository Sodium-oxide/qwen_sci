# ExperimentDesign Agent: Service-Normalized Hydrogen System Study

## 1. Objective

Determine where hydrogen provides additional climate, industrial, resilience, or energy-access value relative to direct electrification and competing fuels, after production, electricity timing, conversion, transport, storage, lifecycle emissions, water, land, material, leakage, safety, cost, and demand uncertainty are included. This is a design proposal; no new experiment or simulation result is reported.

## 2. Boundary and comparator matrix

The experiment uses four nested hydrogen boundaries:

- **H0, incumbent baseline:** existing fossil-derived hydrogen and fossil energy services.
- **H1, low-emissions production:** hydrogen production pathways are compared using lifecycle emissions, but end-use and infrastructure remain otherwise fixed.
- **H2, service substitution:** hydrogen and its derivatives displace a declared incumbent service in ammonia, steel, shipping, high-temperature heat, backup, or seasonal storage.
- **H3, integrated hydrogen system:** production, electricity, hubs, pipelines, ports, storage, offtake, safety, and policy are co-optimized under a regional system boundary.

Each hydrogen pathway is compared with direct electrification, batteries, transmission, demand response, firm low-carbon supply, sustainable biofuels, and hydrogen derivatives where they deliver the same service. Fossil hydrogen with carbon capture is a separate net-zero sensitivity and is not relabeled as fossil-free.

## 3. Pathway factors

The core design varies:

1. steam methane reforming, coal gasification, biomass, electrolysis, and carbon-capture cases;
2. electricity source, marginal emissions, temporal matching, additionality, curtailment, and grid congestion;
3. electrolyser capacity, utilization, degradation, water balance, stack replacement, and flexible operation;
4. compression, liquefaction, pipeline, trucking, shipping, cavern, tank, and refueling infrastructure;
5. industrial feedstock, ammonia, direct reduction, high-temperature heat, shipping, aviation-derived fuel, backup, and seasonal-storage demand;
6. hydrogen derivatives including ammonia, methanol, and synthetic hydrocarbons;
7. leakage, embrittlement, detection, ventilation, safety zones, and monitoring;
8. water, land, biomass, mineral, recycling, and upstream methane constraints;
9. contracted offtake, demand elasticity, policy support, financing, and project timing;
10. regional access, affordability, employment, and distributional energy-service outcomes.

## 4. Six-stage research program

### Stage 1: Demand and boundary audit

Construct an hourly service ledger for current hydrogen demand and candidate new uses. Record ammonia and refining output, steel tonnage, high-temperature heat, shipping and aviation fuel service, electricity backup, and seasonal storage requirements. For each service, record the incumbent fuel, conversion efficiency, quality requirement, operating schedule, storage requirement, and existing infrastructure. Tag routine, emergency, feedstock, and energy uses separately.

### Stage 2: Pathway and lifecycle characterization

Measure or parameterize feedstock energy, electricity, water, efficiency, capacity factor, degradation, replacement, methane leakage, carbon capture, compression, transport, storage, and end-use conversion. For electrolysis, compare annual-average, hourly marginal, temporally matched, and additional-generation electricity accounting. For fossil pathways, record upstream methane and capture performance. For biomass and carbon-derived feedstocks, record land, water, biodiversity, and permanence assumptions.

### Stage 3: Service-level pilot and process comparison

For existing industrial demand and selected candidate sectors, compare hydrogen with direct electricity and other alternatives at matched output. Measurements include product quality, process temperature, conversion efficiency, ramping, downtime, purity, storage, replacement, safety incidents or near misses, and delivered energy. A fuel is not counted as successful because it can burn; it must deliver the required industrial, mobility, chemical, or reserve service.

### Stage 4: Hub, infrastructure, and grid simulation

Build a regional hourly model linking renewable and firm generation, electrolysers, hydrogen storage, pipelines, ports, industrial demand, power recovery, and grid constraints. Include electricity congestion, curtailment, reserve requirements, hydrogen inventory, pipeline flow, cavern or tank limits, and conversion capacity. Optimize hub placement and staged investment under uncertain offtake. Run separate direct-electrification and competing-fuel cases.

### Stage 5: Stress, safety, and demand uncertainty

Stress the system with prolonged low-renewable periods, drought affecting hydropower, electricity outages, pipeline or port outages, electrolyser failures, storage leakage, demand withdrawal, commodity-price shocks, water restrictions, and supply-chain interruptions. Safety scenarios include detection failure, ventilation loss, embrittlement, transport incidents, and co-location constraints; these are risk analyses, not uncontrolled physical releases. Demand cases vary contracted, policy-induced, and speculative projects.

### Stage 6: Out-of-sample validation and adoption

Hold out weather years, electricity conditions, outage combinations, and project outcomes. Validate component models separately from system optimization. Compare predicted hydrogen demand, project utilization, electrolyser performance, and infrastructure use with new observations when available. Estimate adoption persistence with staged investment, offtake contracts, certification, finance, and policy withdrawal. A project that survives only under permanent subsidy or uncontracted demand fails the robust-deployment criterion.

## 5. Functional units and outcomes

The primary functional unit is one unit of delivered service: tonne of ammonia, tonne of steel, tonne-kilometer of shipping, passenger-kilometer of aviation-derived fuel, MWh of recovered electricity, or an agreed industrial heat output. Secondary units are kg of hydrogen, MWh of electricity, cubic meters of water, tonnes of carbon dioxide equivalent, and infrastructure capacity.

Primary outcomes are lifecycle emissions, delivered-service cost, service efficiency, hourly and seasonal reliability, hydrogen leakage, fossil displacement, offtake fulfillment, and transition feasibility. Secondary outcomes include water, land, biomass, minerals, material replacement, safety risk, storage duration, curtailment, grid congestion, pipeline utilization, capacity factor, energy access, affordability, employment, and local air pollution.

## 6. Mathematical formulation

Let $t$ index time, $s$ scenarios, $p$ production pathways, and $j$ services. Let $h_{p,t,s}$ be hydrogen production, $e_{t,s}$ electricity input, $m_{j,t,s}$ useful service, and $u_{j,t,s}$ unserved service. A service constraint is

$$\sum_p \eta_{p,j}h_{p,t,s}+r_{j,t,s}\ge d_{j,t,s}-u_{j,t,s},$$

where $r$ represents direct electricity or an alternative carrier and $\eta$ includes pathway and end-use conversion. Lifecycle emissions are

$$E_{p,s}=E^{\mathrm{feedstock}}_{p,s}+E^{\mathrm{electricity}}_{p,s}+E^{\mathrm{process}}_{p,s}+E^{\mathrm{transport}}_{p,s}+E^{\mathrm{use}}_{p,s}-E^{\mathrm{captured}}_{p,s}.$$

For electrolysis, temporally matched electricity emissions can be written as

$$E^{\mathrm{electricity}}_{p,s}=\sum_t e_{t,s}\,\phi_{t,s},$$

where $\phi_{t,s}$ is the time-specific marginal or contracted electricity emission factor. Annual average accounting is a sensitivity, not the default, because it can conceal operation during fossil-marginal hours.

Hydrogen inventory follows

$$z_{t+1,s}=z_{t,s}+h_{t,s}-q_{t,s}-\ell_{t,s},$$

where $q$ is delivery and $\ell$ is leakage or measured inventory loss. Transport and storage impose capacity, pressure, flow, and safety constraints. The portfolio screening utility is

$$U(P)= -C(P)-\alpha\,\cvar_{\beta}(u(P))-\lambda E(P)-\gamma W(P)-\rho R(P),$$

where $C$ is annualized cost, $u$ is unserved service, $E$ is lifecycle emissions, $W$ is water and land burden, and $R$ aggregates safety, leakage, material, and distributional risks. The final study reports a Pareto frontier rather than a single universal weighting.

## 7. Mechanism tests

The design tests whether electrolysis reduces emissions under temporally matched low-carbon electricity; whether flexible electrolysers reduce curtailment without increasing scarcity; whether hydrogen storage reduces tail-event unserved energy more efficiently than batteries or transmission at long durations; whether co-located hubs improve utilization and lower infrastructure cost; whether industrial hydrogen preserves product quality and throughput; whether derivatives are better transported or used than hydrogen itself; and whether lifecycle water, material, and safety burdens remain within safeguards.

## 8. Decision rules and safeguards

A pathway advances only if it delivers the target service, meets lifecycle emissions and fossil-displacement criteria, remains reliable under ordinary and stress scenarios, has verified offtake and infrastructure, satisfies water and resource safeguards, passes safety and integrity review, and remains feasible under plausible financing and policy withdrawal. Fossil pathways with carbon capture are reported as net-zero sensitivities. Hydrogen mass, announced capacity, or a color label cannot independently establish success.

## 9. Design-only status

`expected_results` and `observed_results` remain empty. The design specifies how to evaluate hydrogen's future roles; it does not claim that any production pathway, project, hub, or region has already passed validation.
