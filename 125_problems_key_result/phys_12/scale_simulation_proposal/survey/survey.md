# Survey Agent Output: Credible Simulation Across Macro- and Microscales

**Topic.** Can we accurately simulate the macro- and microworld?

**Scientific reframing.** Accuracy is not a property of a simulator in the abstract. It is a bounded claim about a declared quantity of interest, physical model, parameter regime, numerical approximation, computational resource, and reference/validation evidence. The downstream question is: *under which error and resource conditions is a macro-, classical-micro-, or quantum-micro simulation credible for its declared quantity of interest?*

## Evidence-grounded synthesis

Macroscopic simulation is often highly useful, but it is not automatically straightforward. Conservation-law models, continuum approximations, turbulence closures, multiscale couplings, chaotic sensitivity, uncertain inputs, and out-of-regime extrapolation can all limit prediction. Verification determines whether code and numerical solution correctly solve the stated mathematical model; validation asks whether the model represents the target physical system in its claimed regime. Cross-validated verification-and-validation literature treats these as distinct necessities [S2], [S3]. Multifidelity methods can combine cheaper and higher-fidelity models, but the high-fidelity reference must remain in the loop to establish accuracy or convergence [S4].

At microscopic scales, many problems remain tractable with classical approaches: molecular dynamics, electronic-structure methods, Monte Carlo, tensor networks, reduced models, and high-performance numerical algorithms each apply in particular regimes. Microscopic does not imply that a quantum computer is required. The bottleneck arises for specific quantum many-body dynamics, strongly correlated systems, sign/real-time difficulties, or exponentially large Hilbert-space representations, and then only relative to a requested observable and precision.

Quantum simulation is scientifically motivated by the quantum character of atoms, molecules, light, and materials. NIST describes quantum information science as combining quantum physics and information theory and notes that quantum computers may, in theory, simulate fundamentally quantum matter and address certain otherwise unsolved problems [S1]. Foundational quantum-simulation work and later reviews establish the conceptual basis [S5], [S6]. However, a useful simulation requires more than a qubit count: Hamiltonian mapping, state preparation, algorithmic approximation, measurement sampling, noise, error mitigation or correction, and classical comparison all enter the error and cost ledger. NISQ-era literature explicitly emphasizes noise-limited circuits [S7]. Cross-validated work on error mitigation and logical-qubit scaling demonstrates relevant progress while also showing why no general near-term accuracy conclusion follows from a platform label alone [S9], [S10].

## Sub-hypotheses and coverage

| ID | Sub-hypothesis | Evidence status | Allowed conclusion |
|---|---|---|
| SH-1 | A simulation accuracy claim requires model, numerical, and reference/validation evidence. | Supported | Use a decomposed credibility ledger. |
| SH-2 | Macro simulations can be credible yet remain limited by model discrepancy and uncertainty. | Supported | Reject “macro is automatically easy.” |
| SH-3 | Classical methods retain strong microscopic-simulation roles. | Supported | Compare against a stated classical baseline. |
| SH-4 | Quantum methods may help selected quantum systems but must close a mapping, algorithm, measurement, and hardware error budget. | Supported | Treat advantage as conditional and testable. |
| SH-5 | A common scale-resolved ledger can improve cross-platform simulation claims. | Research gap | Requires a design-only study. |

## Gap triage

`GAP-ACCURACY-001` is accepted: publications and public narratives often conflate verification, validation, and hardware performance. `GAP-CROSSSCALE-002` is accepted: macro, atomistic, classical quantum, NISQ, and fault-tolerant projections lack a shared reporting structure for a quantity-of-interest error and cost claim. `GAP-UNIVERSAL-QUANTUM-003` is rejected: no evidence supports the statement that quantum computers are universally necessary or already superior for microscopic simulation.

## Evidence boundary

Twelve sources are frozen in `survey_evidence_plan.json`. NIST’s public page was inspected through the browser. Dual-engine OpenAlex/AnySearch searches cross-validated selected simulation verification, multifidelity, NISQ, error-mitigation, and error-correction sources. DOI/publisher-page review remains a human publication check. No source supports an unqualified claim that a quantum simulator is accurate, fault tolerant, or advantageous for every microscopic system.

