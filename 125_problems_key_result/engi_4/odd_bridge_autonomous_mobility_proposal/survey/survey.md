# Survey Agent - Assurance-Gated Autonomous Mobility

## Scope correction and research question

The proposition of a future containing only self-driving cars is not a single prediction that can be answered by a sensor benchmark. It simultaneously assumes that automated driving systems (ADS) can handle all relevant operational conditions, transition safely when they cannot, coexist with human-driven and vulnerable road users during a long transition, remain safe when connectivity or mapped infrastructure degrades, earn justified public trust, and fit legal and operational institutions. A vehicle that works in one operational design domain (ODD) does not automatically support an unrestricted or exclusive traffic future.

This Survey therefore asks a narrower engineering-and-governance question:

> Under what safety, operational, infrastructure, communication, human-interaction, and public-legitimacy evidence conditions can an ADS mobility service expand its ODD and fleet share without converting an unvalidated capability into a city-wide or self-driving-only claim?

The scope includes high-automation mobility services and their surrounding system interfaces. It does not claim that an exclusive automated-vehicle road network should be built, that a human driver should be eliminated, or that an ADS is being operated by this workflow.

## Evidence acquisition and confidence

OpenAlex and AnySearch Academic were searched in parallel on 2026-09-01 using `automated driving safety validation operational design domain V2X infrastructure public acceptance review` and `public acceptance trust autonomous vehicle mixed traffic transition review`. The first query returned nine DOI/title cross-matched candidates and the second returned nine. The matched records cover takeover/conditional automation, safety blind spots, motion planning, perception, road infrastructure, connected-vehicle security, public acceptance, and future transport transition. Index matching is discovery-stage provenance; claims require publisher/full-text human verification before external scholarly use.

The user-requested in-app browser successfully opened NHTSA's Automated Vehicle Safety page. Its visible text distinguishes current driver-assistance/partial-automation functions from later automation levels, states that even the highest automation currently available to consumers requires full driver engagement and undivided attention, and describes ADS as a developing technology under testing, development, and validation. This browser-verified government statement supports an explicit present-tense boundary. It does not prove any future market or safety outcome.

| Evidence ID | Bounded finding | Permitted use | Boundary |
|---|---|---|---|
| E-STATE-001 | NHTSA distinguishes current consumer features from future ADS and states current highest consumer automation still requires full driver attention. | Present-maturity boundary and terminology correction. | Does not determine future feasibility. |
| E-HUMAN-002 | A dual-index review identifies takeover-request issues for conditional automation and ODD exits. | Require a safe transition/recovery gate where human fallback is relevant. | Does not validate a particular takeover interface. |
| E-SAFETY-003 | A dual-index safety analysis challenges broad safety assumptions and emphasizes human-systems integration and trust. | Treat safety as sociotechnical rather than sensing-only. | Does not quantify comparative risk. |
| E-CORE-004 | Dual-index surveys cover perception, localization, planning, mapping, and system robustness. | Define technical evidence classes. | Survey evidence is not a deployment result. |
| E-MOTION-005 | A dual-index review identifies sensing and V2V/V2I as planning-related research directions. | Treat communication as a potential aid, not a replacement for safe local behavior. | No communications reliability claim is transferred. |
| E-INFRA-006 | A dual-index road-environment review identifies infrastructure implications and requirements for safe AV operation. | Require infrastructure-condition and degradation cards. | Does not justify city-wide retrofit. |
| E-CYBER-007 | Dual-index CAV reviews identify cyber security, privacy, standards, and infrastructure challenges. | Add security and data-governance gates. | Does not establish a secure architecture. |
| E-TRUST-008 | Dual-index public-acceptance and user-factor literature connects adoption to trust, expectations, social influence, policy, and system characteristics. | Include public-legitimacy evidence in scaling decision. | Does not define a universal acceptance threshold. |
| E-TRANSITION-009 | Dual-index transition literature frames coexistence of automated and human-operated mobility as a systemic future question. | Treat mixed traffic as a research object rather than a temporary nuisance. | Does not predict an exclusive endpoint. |

## Subhypotheses and coverage

**SH-1: ODD is a scaling boundary.** A capability claim is meaningful only when ODD, excluded conditions, and response to ODD exit are explicit. E-STATE-001 and E-HUMAN-002 support this constraint. There is no evidence here to classify any particular service as safe.

**SH-2: layered technical assurance.** Sensing, localization, perception, prediction, planning, and control must be assessed as a connected chain with degradations and minimal-risk response. E-SAFETY-003, E-CORE-004, and E-MOTION-005 support the need for a layered approach. They do not establish that a technology stack is sufficient in every road scenario.

**SH-3: connected infrastructure is conditional.** V2X or roadside sensing can augment perception and coordination, but a scaling argument must state whether loss, delay, spoofing, or uneven coverage is safe to tolerate. E-MOTION-005 through E-CYBER-007 support the interface requirement. They do not authorize reliance on an unavailable infrastructure service.

**SH-4: mixed traffic and legitimacy are primary evidence domains.** Expansion changes interactions with human drivers, pedestrians, cyclists, users, emergency responders, regulators, and data subjects. E-SAFETY-003 and E-TRUST-008 through E-TRANSITION-009 support this claim. The evidence base does not supply a single acceptance or equity score that can decide scaling.

## Accepted gap ledger

| Gap ID | Accepted gap | Decision relevance | Handoff restriction |
|---|---|---|---|
| GAP-ODD-001 | Technical capability is over-transferred from an ODD to unconstrained roads. | Prevents invalid generalization. | Every primary idea must name its ODD, exclusions, and expansion rule. |
| GAP-DEGRADE-002 | Sensor, map, localization, software, or communications degradation is often separated from the mobility-service claim. | Determines whether a safe state exists when assumptions fail. | Candidate must bind degraded mode to a safe fallback/recovery policy. |
| GAP-MIXED-003 | Interaction with human drivers and vulnerable road users is treated as a residual edge case rather than a deployment condition. | Determines transition safety and throughput. | Scenario model must include non-ADS actors and uncertainty. |
| GAP-INFRA-004 | Infrastructure and V2X support are discussed without an explicit availability, integrity, latency, and failure boundary. | Prevents invisible single points of failure. | Connectivity must be classified as required, assistive, or unavailable. |
| GAP-ASSURE-005 | Testing, simulation, operational monitoring, and incident learning lack a common claim-to-evidence scaling contract. | Determines auditability of a safety argument. | Expansion must be gated by predeclared evidence obligations. |
| GAP-TRUST-006 | Public acceptance, privacy, responsibility, and communication are detached from technical rollout decisions. | Determines legitimate and sustainable adoption. | Include a public/governance contract; do not use trust as marketing evidence. |
| GAP-EQUITY-007 | Coverage and access effects can be hidden by fleet-level safety and efficiency narratives. | Determines who bears risk, exclusion, and service benefit. | Evaluate service exclusions and accessibility before scaling claim. |

## Survey conclusion and handoff

The evidence supports a clear answer: a future containing only self-driving cars is not currently a realistic unitary target. A more defensible path is a staged transition in which bounded ADS services expand only after evidence closes for their ODD, degraded operation, mixed-traffic interactions, communications/infrastructure dependency, safety case, and public/governance obligations. The Idea Agent must not select an unrestricted-replacement narrative. It must produce a falsifiable, ODD-specific scaling mechanism that classifies connectivity as an aid or an explicit dependency and preserves human-review requirements.
