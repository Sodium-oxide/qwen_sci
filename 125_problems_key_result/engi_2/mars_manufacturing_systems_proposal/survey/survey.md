# Survey Agent - Mars Manufacturing Systems

## Scoped research question

**How can a first-generation Mars manufacturing system produce and certify a bounded family of non-critical construction and repair items from local and imported feedstocks while preserving energy, thermal, dust, quality, and recovery constraints?**

This question is intentionally narrower than “build a factory on Mars.” A credible early system cannot be assumed to make every material, electronics package, pressure boundary, medical device, or life-critical replacement part. It must instead identify a small product family for which local feedstock, process route, inspection method, and fallback logistics can be declared together.

Mars manufacturing should not be modeled as terrestrial manufacturing moved to a different address. The surface environment, a thin carbon-dioxide-dominated atmosphere, dust, thermal cycling, radiation exposure, communication delay, limited maintenance labor, constrained spares, and finite power alter what counts as a viable process. Mars has partial gravity rather than microgravity; the relevant operational distinction is the approximately Martian-gravity field together with the environmental, energy, and logistics constraints. This Survey treats that correction as a scope invariant.

## Evidence map

| Evidence ID | Bounded finding | Permitted use | Boundary |
|---|---|---|---|
| E-REG-001 | Karl, Cannon, and Gurlo review Martian simulants, regolith-bonding concepts, and additive-manufacturing routes. | Identify material-processing route families and simulant-transfer limits. | Does not certify a flight-ready Mars process. |
| E-REG-002 | Wang et al. review regolith ISRU and additive manufacturing for lunar/Martian habitats. | Establish that the field spans resource use, bonding, construction, and additive manufacturing. | Review-level evidence, not a system demonstration. |
| E-REG-003 | Karl et al. report clay-based shaping with Mars global simulant slurries. | Motivate a material-route candidate for screened experiments. | Simulant and terrestrial processing are not Mars operations. |
| E-AM-004 | Balla et al. report direct laser fabrication of lunar/Martian-regolith-simulant parts. | Motivate laser-based processing as a comparative route. | Lunar/simulant evidence cannot establish Mars reliability. |
| E-ISRU-005 | The MOXIE literature documents an oxygen-ISRU technology demonstrator on Mars. | Treat atmospheric processing as a real architectural interface, not proof of an integrated factory. | Browser landing-page review was blocked; source use remains bounded. |
| E-SYS-006 | Do et al. analyze Mars settlement architecture, ISRU, spares, and logistics. | Motivate coupled manufacturing/logistics accounting. | It is not a validated colony design. |
| E-SYS-007 | Moses and Bushnell describe ISRU, robotics, autonomy, and additive manufacturing as linked Mars-enabling technologies. | Motivate a system-of-systems research frame. | NASA-STI discovery record requires source-page review. |
| E-SYS-008 | Rüede et al. address systems engineering for a Mars research base. | Motivate requirements, interfaces, and recovery planning. | Not evidence that a selected manufacturing cell is feasible. |

Evidence E-REG-001 through E-SYS-006 were found by an OpenAlex + AnySearch search and cross-matched by DOI/title metadata. The in-app browser was asked to inspect NASA and DOI pages but navigation was blocked by the current browser network policy. Therefore this Survey does **not** elevate any source to publisher-page-verified status. Before external publication, a human reviewer must verify authorship, title, year, venue, DOI, and any quantitative claim against the publisher or agency landing page.

## Subhypotheses and coverage

1. **SH-1 - Feedstock qualification:** If a build depends on regolith or an ISRU-derived intermediate, a reproducible product claim requires a lot-level material card covering provenance, granulometry or analogous feedstock descriptors, conditioning, and allowable route. Evidence supports regolith-route exploration but does not demonstrate transfer across Martian sites.
2. **SH-2 - Process and quality closure:** A usable product family needs a process card plus an inspection/acceptance card; coupon strength alone is inadequate. Existing literature motivates processing routes, leaving the system-level quality closure open.
3. **SH-3 - Resource coupling:** Energy availability, thermal control, dust mitigation, and consumable use must be coupled to the process route. A local-material fraction without these interfaces is not manufacturing viability.
4. **SH-4 - Recoverability:** A process must define a fallback: rework, substitute route, defer to Earth-supplied spare, or quarantine. The evidence base identifies logistics pressure but lacks a common, auditable recovery metric.
5. **SH-5 - Bounded deployment:** Initial work should focus on non-pressure, non-life-support, non-medical, and non-flight-critical parts or construction demonstrators. Progress on these classes does not authorize claims about habitat pressure vessels or crew-critical hardware.

## Research gaps

| Gap ID | Gap | Decision relevance | Status |
|---|---|---|---|
| GAP-CELL-001 | Material-coupon success is seldom linked to a full resource-to-part-to-inspection-to-recovery manufacturing cell. | Primary gap. | Accepted |
| GAP-FEEDSTOCK-002 | Simulant and site/feedstock variability lack a standard product-release interface. | Determines transfer validity. | Accepted |
| GAP-ENERGY-003 | Process qualification is often separated from power, thermal, dust, and consumable budgets. | Determines operational feasibility. | Accepted |
| GAP-QUALITY-004 | A common, mission-relevant acceptance and quarantine protocol for early locally made parts is under-specified. | Determines safe use. | Accepted |
| GAP-RECOVERY-005 | Manufacturing proposals rarely state explicit fallback routes and thresholds. | Determines resilience. | Accepted |
| GAP-SCOPE-006 | Broad Mars-factory narratives conflate partial gravity, environmental exposure, and human-rated production. | Prevents overclaiming. | Accepted |

## Survey conclusion and handoff boundary

The literature supports studying ISRU, regolith processing, additive manufacturing, atmospheric processing, autonomy, and systems engineering as connected capability areas. It does not establish that an autonomous, economical, human-rated general-purpose factory can operate on Mars. The downstream Idea Agent must therefore propose a **bounded manufacturing cell**, associate each claim with one or more gap IDs, and include a falsifier. The ExperimentDesign Agent must preserve `DESIGN_ONLY`, avoid Mars operations or human-rated manufacture, and retain explicit energy, thermal, dust, quality, and recovery interfaces.
