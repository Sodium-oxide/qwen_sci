# ExperimentDesign Agent: PERMANENT-EXTRATERRESTRIAL-HABITATION-READINESS-BENCHMARK

## 1. Status and aim

This is a preregistration-ready DESIGN_ONLY systems-engineering protocol. It tests
whether a declared settlement architecture maintains resource, power, safety, maintenance,
and human-performance constraints for a specified crew and horizon after routine
consumable resupply and real-time Earth intervention stop. It does not certify a habitat,
conduct a human mission, measure a life-support closure value, or establish that a planet
is permanently habitable.

## 2. Boundary and parameter ledger

Each scenario defines target body/site, crew size and demographic assumptions, mission
horizon, habitat volume and pressure, Earth logistics policy, emergency/evacuation rule,
resource inventory, storage limits, atmospheric composition, water and waste processors,
food system, nutrient inventory, power generation/storage/transmission, thermal system,
radiation protection, ISRU modules, maintenance/manufacturing inventory, medical
capability, communications latency, operational staffing, and acceptance thresholds.

For every module, the ledger records material/energy inputs, products, losses, quality
requirements, failure modes, replacement/repair path, sensor coverage, calibration,
state variables, uncertainty, validity range, and source. External inputs and discard
streams are explicit. An architecture with an untracked resupply item, backup item, or
ground intervention is classified as resupply-dependent until it is represented.

## 3. Resource, power, and health observables

Track resource stocks for O2, CO2 sorbent or processing capacity, water, food energy,
nutrients, buffer gas, sanitation capacity, filters, spares, medicines, and critical
manufacturing feedstock. Track critical power delivered, stored energy, thermal margin,
load shedding, ISRU product rate/quality, repair queue, fault detection/isolation time,
radiation and environmental exposure, crew physiological/operational measurements, and
external logistics mass. All stocks have minimum reserve and product-quality constraints.

## 4. Experimental phases

1. **Model audit:** verify dimensional consistency, interface contracts, accounting
   boundary, and expected steady-state mass/energy closure on synthetic data.
2. **Component qualification:** evaluate recovery units, power hardware, storage,
   crop modules, ISRU processors, sensors, and repair pathways at stated duty cycles.
3. **Integrated ground demonstrator:** operate the coupled atmosphere-water-waste-food-
   power-maintenance system without routine consumable resupply for a preregistered test
   horizon; use nonhuman and hardware-in-the-loop tests before crew exposure.
4. **Fault campaign:** inject leaks, sensor failures, crop/yield loss, fouling, power
   outages, communication delay, storage degradation, and repair delays; include
   correlated failures rather than isolated component tests only.
5. **Site-coupled scenario:** drive lunar or Martian models with site-specific resource,
   illumination, thermal, dust, radiation, and communication assumptions, all versioned.
6. **Ensemble assessment:** sample uncertain loads, recovery efficiency, degradation,
   ISRU quality/throughput, weather/environmental inputs, and repair durations; report
   a conditional distribution of autonomy rather than a single nominal pass.

## 5. Controls and held-out tests

Development data establish units and numerical tolerances. Training intervals tune only
declared model parameters. Hold out one or more fault sequences, environmental windows,
site input sets, or integrated campaign intervals before final evaluation. Use independent
mass-balance accounting and a separately validated power/thermal model. Compare measured
or simulated resource stocks with an unalterable consumption/production log. Repeat
critical scenarios under altered sensor noise, fault detection, and repair latency.

Synthetic injections include a known water loss, crop yield reduction, false-positive
sensor signal, battery capacity fade, ISRU impurity, and correlated power-plus-thermal
disturbance. The analysis must detect the injected problem, classify its source, and
avoid inventing failure in a null case. Failed recoveries and failed runs remain public
outputs of a future execution.

## 6. Metrics and decision rules

Primary metrics are per-resource closure, minimum stock margin, autonomy horizon,
critical-load unserved energy, probability of crossing an operational threshold under the
declared ensemble, repair coverage, Earth logistics mass, and health/radiation/medical
margin. A system receives conditional readiness support only if all life-critical stocks
remain above reserve; power and thermal loads are met through declared outages; product
quality stays within threshold; faults are detected and repaired or degraded safely; and
held-out scenarios do not reveal an unaccounted dependence on Earth supplies or ground
intervention.

A high average recycling fraction, one successful crop, or a nominal energy surplus is
insufficient. A scenario failing a fault campaign is not called permanent; it is reported
as constrained by the identified dependency. A successful ground demonstrator supports
the tested integrated configuration, not a planetary certification. Site-specific claims
require the surface inputs and ISRU assumptions to be independently characterized.

## 7. Reproducibility and interpretation safety

Release the system ledger; schemas; source/binary revisions; resource and power logs;
calibration files; fault scripts; environmental inputs; seeds; scenario versions;
uncertainty distributions; model outputs; failure reports; data licenses; and hashes.
Report observed quantities, inferred model parameters, site extrapolations, and
population/lifetime claims in separate layers. Each report states its crew, horizon,
resupply boundary, disturbance family, and success threshold next to every autonomy or
closure result.
