# ExperimentDesign Agent: CRISP-ICF Computational Research Design

## Design status and scope

This is a `DESIGN_ONLY` computational research protocol. It does not operate a laser, prepare a target, conduct plasma experiments, submit high-performance-computing jobs, access fusion-facility controls, or report observed results. Its aim is to create a decision-ready simulation and validation plan that a qualified laser-plasma/ICF team could review and implement under appropriate facility and safety governance.

## Research brief

**Question.** Can a coherence-resolved, matched-control workflow determine whether a sunlight-like high-power laser model is a credible candidate for lower LPI risk in a declared regime without unacceptable degradation of delivery, uniformity, or multi-beam coupling proxies?

**Unit of analysis.** `regime card x driver card x control card x quantity-of-interest card`.

**Primary design claim.** A candidate is not ranked by incoherence alone. It must satisfy representation fidelity, matched energy/spectrum/intensity controls, physical-scope compatibility, uncertainty disclosure, and coupling/transport escalation before it can receive a favorable conditional label.

## Driver and regime model cards

| Card | Role | Required fields | Prohibited shortcut |
|---|---|---|---|
| `D0` | Narrowband coherent baseline | carrier definition, temporal envelope, polarization, focal statistics, energy normalization | Treating any nonidentical driver as a matched control. |
| `D1` | SSD-like/broadband phase control | spectral shape, bandwidth, phase process, smoothing time | Calling bandwidth alone sunlight-like. |
| `D2` | Orthogonal polarization smoothing control | component balance, mutual coherence, focal statistics | Ignoring divergence or spatial-statistics changes. |
| `D3` | Sunlight-like stochastic candidate | spectrum, independent phase processes, Stokes-statistics, temporal-speckle statistics | Assuming a name proves incoherence at target. |
| `D4` | Vector/structured polarization candidate | spatial polarization map, propagation model, side-scattering geometry | Generalizing one angular mechanism to all LPIs. |
| `D5` | Overlap/cross-beam adversarial control | crossing geometry, beam independence, density gradient, coupling model | Using a single-beam result as a multi-beam conclusion. |
| `R0-R3` | Regime ladder | homogeneous analytic screen, inhomogeneous wave model, kinetic/PIC scope, transport/target compatibility | Treating a lower tier as end-to-end validation. |

## Variables and outcome ledger

The inputs include spectral support and shape, phase-correlation time, polarization statistics, spatial-intensity moments, temporal-speckle lifetime, normalized intensity, density/temperature profile representation, gradient and flow assumptions, overlap geometry, and solver/discretization choices. Controlled quantities include energy normalization, wavelength convention, focal-envelope definition, numerical resolution policy, target physical scope, and reference route. Unknowns include high-energy driver implementation, target-scale transport coupling, diagnostic equivalence, and model discrepancy outside the declared regime.

The protocol records a vector of planned outputs: `LPI risk proxy`, `reflected/scattered energy proxy`, `hot-electron-risk proxy`, `drive nonuniformity proxy`, `cross-beam transfer sensitivity`, `representation error interval`, and `resource interval`. These are analysis fields, not values asserted by this proposal.

## Model and validation ladder

1. **Representation verification.** Confirm that spectrum, energy normalization, phase statistics, and polarization statistics of each generated driver match its declared card. A field that is broadband at injection but not characterized at the interaction plane fails this gate.
2. **Analytic/linear screen.** Use a scoped resonance-memory calculation to reject drivers that do not decorrelate on the candidate response timescale. This screen ranks feasibility for further analysis; it does not predict a facility outcome.
3. **Wave and kinetic comparison.** For a tightly bounded regime, use matched coherent, SSD-like, polarization-smoothing, and sunlight-like cards. The independent variable is coherence structure; the control is equalized physical scope and documented numerical resolution.
4. **Overlap and coupling stress test.** Introduce the `D5` adversarial card. A benefit that disappears, reverses, or becomes non-identifiable under credible overlap conditions cannot be presented as a multi-beam benefit.
5. **Transport/implosion compatibility review.** Carry only robust candidates into a separate specialist review of propagation and drive compatibility. No reduced-model output is converted into an ignition inference.

## Decision labels

| Label | Authorized meaning |
|---|---|
| `REPRESENTATION_INVALID` | The driver does not satisfy its declared spectrum, phase, polarization, or normalization contract. |
| `BASELINE_ONLY` | Existing controls are sufficient for the stated scope; no sunlight-like candidate case is established. |
| `COHERENCE_BENEFIT_CANDIDATE` | Matched, scoped evidence justifies a higher-fidelity specialist benchmark; this is not observed suppression or ignition improvement. |
| `TRADEOFF_DOMINATED` | A favorable LPI proxy is outweighed by a declared delivery, uniformity, or coupling penalty. |
| `COUPLING_SENSITIVE` | The conclusion switches under plausible overlap/cross-beam assumptions. |
| `INCONCLUSIVE` | The evidence, fidelity, or uncertainty coverage is insufficient. |
| `MODEL_INVALID` | Units, physical scope, reference route, or observation/projection status fails validation. |

## Human review and safety boundary

An implementation requires independent review by high-energy-density physicists, laser-plasma theorists, target physicists, numerical-methods specialists, and the responsible facility's safety/governance process. The protocol intentionally excludes target specifications, laser timing, irradiation controls, facility operating settings, and experimental execution guidance.
