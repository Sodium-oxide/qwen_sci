# ExperimentDesign Agent - MARS-CELL Design-Only Protocol

## Research brief

MARS-CELL will evaluate whether a bounded, non-critical product family can be described by a stable resource-to-release dossier under declared feedstock, process, environmental, energy, inspection, and recovery conditions. It will not manufacture hardware for Mars, authorize crew-critical use, or represent any trial as completed.

## Design template and scope gate

- **Template:** `engineering_energy` with materials-processing and computational-digital submodules.
- **Execution policy:** `DESIGN_ONLY`.
- **Permitted future work:** terrestrial simulant/analog studies, model development, quality-method comparison, and expert review.
- **Prohibited inference:** Mars deployment, pressure-vessel qualification, life-support use, flight qualification, autonomous facility operation, or economic viability claim.

## Experimental unit

`product class x feedstock lot x conditioning state x process route x environment-energy profile x inspection protocol x recovery route`.

The initial product class must be selected from non-pressure construction coupons, shielding/fixture demonstrators, repair fixtures, or external nonstructural components. Each actual future study must document why the item cannot transfer load, seal a habitat, control life support, carry flight loads, or create a crew hazard.

## Variables and evidence cards

| Role | Variables or fields |
|---|---|
| Independent | Feedstock lot/conditioning, binder or fusion route, build geometry, thermal route, environmental exposure profile, energy-availability profile. |
| Dependent | Geometric fidelity, defect indicators, bounded mechanical/functional proxy, energy/consumable use, inspection decision stability, recovery outcome. |
| Controlled | Product use class, measurement method, fixture, software version, process recipe identity, lot tracking, acceptance threshold. |
| Moderators | Simulant fidelity, dust contamination, partial-gravity transfer assumption, thermal cycling, maintenance delay, inspection access. |
| Unknowns | Actual site mineralogy, operations architecture, true power profile, long-duration exposure, human factors, logistics cost. |

## Predeclared validation ladder

1. **Dossier completeness:** verify product, feedstock, process, environment-energy, inspection, and recovery cards exist.
2. **Material/process eligibility:** reject any route without a bounded process window, provenance, or safety statement.
3. **Environmental and resource stress:** vary only declared analog conditions and document changes in qualification outcome.
4. **Inspection and release:** compare predeclared inspection routes; label release, rework, quarantine, or discard without changing thresholds after inspection.
5. **Recovery and transfer audit:** require fallback feasibility and a separate Mars-transfer justification. No analog result alone may be promoted to Mars deployment.

## Decision rules

The primary outcome is a status label rather than a single performance number. `CONDITIONALLY_RELEASEABLE` requires complete cards, stable inspection decisions, a declared bounded use class, and a viable recovery route. `TRANSFER_NOT_JUSTIFIED` is required when any Mars-specific assumption is unsupported. `INSPECTION_INSUFFICIENT` is required when an item cannot be reliably classified. `MODEL_INVALID` is required when a product escapes the allowed non-critical use class.
