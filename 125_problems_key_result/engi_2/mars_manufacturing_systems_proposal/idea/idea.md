# Idea Agent - MARS-CELL

## Problem reframing

The Survey shows that local-material processing is not itself a manufacturing system. The key challenge is to turn a resource stream into a **released, use-bounded part** under interrupted power, variable feedstock, dust/thermal exposure, limited maintenance, and uncertain resupply. The Idea Agent therefore rejects both “print everything from regolith” and “maximize coupon strength” as primary directions.

## Candidate portfolio

| Candidate | Mechanism | Strength | Rejection or selection reason |
|---|---|---|---|
| Route-only regolith additive manufacturing | Optimize one binding/printing route. | Compact materials question. | Rejected as primary: does not close quality, energy, or recovery gaps. |
| Maximum local-content optimizer | Maximize local mass fraction in a product. | Simple logistics objective. | Rejected as primary: can reward unsafe or uninspectable local substitution. |
| **MARS-CELL** | Bind product family, feedstock lot, process route, environment/energy profile, inspection contract, and recovery route into a release dossier. | Addresses all accepted gaps with explicit falsifiers. | **Selected primary idea.** |
| Fully autonomous self-replicating factory | Recursive production and repair. | High conceptual novelty. | High-risk: evidence and safety scope far exceed this proposal. |

## Selected primary idea

**MARS-CELL - Mars Adaptive Resource-to-Structure Cell with Energy, Logistics, and Lifecycle controls**

MARS-CELL treats early Mars manufacturing as a constrained production-and-release cell, not a monolithic factory. Its unit of analysis is:

`product family x feedstock-lot card x process-route card x environment-energy card x inspection-release card x recovery card`.

The product family is deliberately bounded to non-pressure, non-life-support, non-medical, non-flight-critical construction coupons, shielding/fixture demonstrators, repair fixtures, or external nonstructural components. The product must never be released solely because a local feedstock fraction is high or a sample is strong. It must pass an admissibility and recovery check.

### Central hypothesis

If a Mars manufacturing candidate is evaluated through coupled feedstock, process, environment-energy, inspection, and recovery cards, then its reported readiness will be more reproducible and operationally meaningful than readiness based only on material strength, printability, or local-material fraction.

### Falsifiers

- A route cannot maintain an agreed quality and inspection envelope across declared feedstock/energy/environment perturbations.
- An imported spare or lower-complexity fallback dominates the candidate after accounting for process consumables, energy, downtime, and recovery.
- The selected inspection protocol cannot distinguish release, rework, quarantine, and discard decisions for the stated use class.
- The conclusion changes materially when the source is correctly labeled as simulant, terrestrial analog, partial-gravity assumption, or untested Mars transfer.

### Required outcome labels

`ROUTE_ELIGIBLE`, `CONDITIONALLY_RELEASEABLE`, `FEEDSTOCK_LIMITED`, `ENERGY_OR_ENVIRONMENT_LIMITED`, `INSPECTION_INSUFFICIENT`, `RECOVERY_REQUIRED`, `TRANSFER_NOT_JUSTIFIED`, `MODEL_INVALID`, and `INCONCLUSIVE`.

No label is an observed result in this project. They are predeclared future interpretations.
