# ExperimentDesign Agent - ODD-Bridge Assurance-Gated Scaling Protocol

## Design-only scope

This is an `engineering_energy` systems-design output with transportation, safety, and governance interfaces. It has `execution_policy.mode = DESIGN_ONLY` and `observed_results = []`. It does not operate an ADS, drive a vehicle, modify a vehicle, execute a simulator, collect road-user data, or claim a safety rate. A future study needs vehicle/operator, road authority, data-protection, ethics, cybersecurity, and safety-governance approvals appropriate to its jurisdiction.

## Research brief

- **Reference object:** a currently approved ADS service in a named ODD or a documented non-deployment baseline.
- **Intervention:** one predeclared ODD delta, such as a roadway class, traffic context, time, visibility condition, speed range, service procedure, or geography; it is not a blanket expansion.
- **Central claim:** the delta is eligible for a limited future evaluation only when its evidence bundle and recovery/governance obligations are complete.
- **Alternative explanations:** an apparent improvement may instead arise from changed route mix, changed supervision, changed remote support, connectivity dependence, data filtering, reporting boundary, or public-information asymmetry.

## Evidence cards and variables

| Card | Required future contents | Risk controlled |
|---|---|---|
| ODD delta | Base/candidate ODD, added condition, exclusions, actor classes, route and time envelope. | An old evidence claim is silently applied to a new operating condition. |
| Scenario and traffic mix | Interaction types, vulnerable road users, emergency/roadwork contexts, uncertainty, and exposure basis. | Human and non-ADS interaction is treated as an edge case. |
| Sensing/degradation | Sensor/map/localization/software health assumptions, detection signals, and declared failure modes. | Component availability is misreported as continuous capability. |
| Connectivity/infrastructure | V2X/roadside function, availability, integrity, latency, data minimization, and status classification. | Network support becomes an invisible single point of failure. |
| Safe state and recovery | Minimal-risk condition, transition policy where relevant, remote/onsite operational boundary, logging, and post-event review. | ODD exit or degradation lacks an accountable safe response. |
| Assurance and monitoring | Predeclared claim, test/analysis/monitoring evidence, uncertainty/coverage limits, incident handling, and change control. | Fleet aggregate hides missing claim evidence. |
| Public/governance | User information, responsibility boundary, privacy/data policy, accessibility/service exclusions, complaint/redress, and regulator review. | Social legitimacy is replaced by marketing or an opaque pilot. |

## Planned protocol

1. Freeze the approved base ODD, proposed ODD delta, system/service boundary, and claims that are explicitly out of scope.
2. Build a scenario register covering candidate-ODD conditions, mixed road users, infrastructure variation, and abnormal/degraded states; record coverage limits rather than declaring completeness.
3. Classify each external connection as `REQUIRED`, `ASSISTIVE`, or `UNAVAILABLE`. For every class, define what local behavior and safe-state policy must remain valid.
4. Establish claim-to-evidence traceability: what future controlled tests, analysis, simulator evidence, supervised operational evidence, and monitoring evidence are needed; no evidence type substitutes automatically for another.
5. Pre-register degradation detection, safe-state criteria, human/remote operational boundary if any, data retention, incident triage, and change-management process.
6. Perform a future independent public/governance review for information, consent, privacy, responsibility, accessibility, and service-exclusion concerns before expansion approval.
7. Assign a conditional status rather than a universal readiness conclusion.

## Conditional outcomes

| Status | Future interpretation | Action |
|---|---|---|
| `ODD_DELTA_EVALUABLE` | The ODD, scenario, degradation, connectivity, and governance cards are complete enough for specialist-reviewed future evaluation. | Do not call it a deployment approval. |
| `LIMITED_EXPANSION_SUPPORTED` | A future evidence bundle supports the named delta under its stated conditions and monitoring plan. | Preserve the ODD and validity domain; do not infer exclusive autonomy. |
| `DEGRADATION_POLICY_INVALID` | A declared failure lacks detection or a safe state. | Redesign; do not expand. |
| `CONNECTIVITY_DEPENDENCY_UNRESOLVED` | A required connection lacks availability/integrity/failure evidence. | Constrain ODD or add safe local behavior. |
| `MIXED_TRAFFIC_EVIDENCE_INSUFFICIENT` | Scenario/interaction evidence cannot support the added traffic conditions. | Narrow the delta or collect future evidence. |
| `PUBLIC_GOVERNANCE_HOLD` | Privacy, responsibility, accessibility, or public-information requirements remain unresolved. | Do not treat technical evidence as rollout legitimacy. |
| `INCONCLUSIVE` | The evidence cannot discriminate safe expansion from an unsupported transfer. | Report no readiness direction. |

## Human-review and safety boundary

No generic document can validate an ADS safety case. Future work must involve competent safety engineers, system developers, independent evaluators, road authorities, legal/privacy specialists, accessibility representatives, and communities affected by the service. Any vehicle operation, data collection, remote support, incident handling, or safety-critical software work is outside this proposal and requires the relevant jurisdictional permissions and organizational accountability.
