# Idea Agent Report

## Input contract

The Idea Agent received `survey_idea_handoff.json` from the Survey Agent. The hard constraints are: a local zero-bias signal cannot be promoted to proof of non-Abelian statistics; phase, nonlocality, controlled operation, and universal computation must remain distinct; a credible plan must include null controls; and the work is `DESIGN_ONLY`.

## Problem reconstruction

The original question, ``Can topological quantum computing be realized?'', appears binary but hides a staged systems problem. Theory already says that non-Abelian anyons can implement protected operations. Candidate condensed-matter devices already produce suggestive signatures. The missing scientific bridge is not another broad claim of feasibility. It is a decision procedure that can discriminate four states of evidence:

1. **Not supported:** the signal is consistent with a trivial or uncontrolled mechanism.
2. **Phase candidate:** a reproducible gapped parameter region is compatible with the desired phase.
3. **Nonlocal candidate:** independent measurements support a separated encoded degree of freedom beyond a local mimic.
4. **Braiding-ready primitive:** predeclared phase, nonlocality, fusion/exchange, readout, and protection criteria pass against matched controls.

Only after the fourth classification should an architecture claim be evaluated for multiple qubits, logical operations, and its non-Clifford resource. This reconstruction turns a philosophical question into a falsifiable program.

## Candidate search and debate

### Candidate A: a higher-resolution local spectroscopy campaign

This idea begins from the practical fact that phase gaps and low-energy modes must be measured. It could improve device screening, but it fails the independence test: local spectra can be reproduced by trivial Andreev bound states. Candidate A is therefore rejected as a primary direction. It remains a supporting measurement within any stronger design.

### Candidate B: a twin-device nonlocal-correlator benchmark

This direction proposes matched device pairs, remote gate perturbations, parity readout, and an intentionally trivial control. It directly confronts `GAP-02` and `GAP-05`. It is scientifically strong but incomplete: nonlocality alone does not demonstrate the order-dependent transformation that motivates topological computation, nor does it quantify the protection-to-logic bridge.

### Candidate C: an architecture-level topological-Clifford plus magic-state budget

This direction acknowledges that Majorana/Ising braiding is not a universal gate set. It would construct a complete logical error and resource budget, including a non-Clifford path. It resolves `GAP-04`, but risks becoming detached from the actual physical claim: an attractive spreadsheet cannot prove that a material platform has anyons.

### Candidate D: an interferometric non-Abelian witness

Interference can be a high-specificity route to order-dependent statistics. It is a valuable high-risk candidate because it attacks `GAP-03`, but it requires demanding coherence, calibration, and background control. A null result could conflate absent topology with absent device coherence. It is retained as a later escalation path, not the first gate.

## Selected idea: Braiding-Readiness Evidence Ledger

The selected primary idea combines the strengths of B and C while retaining D as a conditional escalation path. The **Braiding-Readiness Evidence Ledger (BREL)** is not a new particle or an untested promise. It is a research architecture with five independent columns:

| Ledger column | Claim tested | Positive evidence | Predeclared rejection or pause condition |
|---|---|---|---|
| Phase | A relevant gapped regime exists | Reproducible phase map and gap proxy over a declared region | Matched trivial controls reproduce the map, or the region is not stable across devices |
| Nonlocality | The degree of freedom is spatially distributed | Coupled-end/parity behavior responds to remote controls in the predicted direction | A local model explains the joint response or remote detuning has no discriminating effect |
| Operation | Fusion/exchange has a topological order dependence | Ordered protocols differ as predicted while matched controls do not | Reordered protocols agree within the predeclared effect bound |
| Protection | Encoding suppresses an error channel relevant to the operation | A preregistered scaling trend with separation, time, temperature, or exposure | Trend is absent or attributable to a non-topological knob |
| Architecture | The primitive can contribute to useful computation | Explicit protected-Clifford and non-Clifford error/resource budget | No credible non-Clifford path or accumulated error budget is unfavorable |

The ledger uses **conjunctive logic** for a braiding-ready claim: no column is a decorative score. A weak value in one column can guide device improvement, but it cannot be averaged away by a striking result in another. This protects the study from selection bias and gives a negative result scientific value: it localizes whether a platform failed at phase preparation, nonlocality, operation, protection, or architecture.

## Mechanism and falsifiability

The central hypothesis is that a genuine, controllable topological Majorana sector has correlated consequences across these columns. A trivial Andreev-bound-state explanation may imitate one local measurement, but it should not naturally reproduce a full set of nonlocal, path-order, and scaling relationships under intentionally designed control conditions. The hypothesis is not that a single observable is magical; it is that the *joint pattern*, checked against precommitted alternatives, becomes more discriminating.

The most important falsification rules are deliberately strict. A BREL claim fails if a scrambled or trivial control recreates the full signature; if exchange-order reversal gives no meaningful difference beyond readout bias; if changing the remote network segment has no predicted effect; if apparent protection lacks the claimed scaling; or if the hardware program cannot state how protected primitives supply a universal computational resource. These conditions make the idea non-conservative in the useful sense: it permits a strong realization claim when the evidence earns it, rather than treating every result as inconclusive.

## Why this is a better primary direction

BREL aligns with all five accepted Survey gaps. It makes the realization criterion explicit (`GAP-01`), turns local-mimic risk into a matched control problem (`GAP-02`), connects operations to protection (`GAP-03`), makes the non-Clifford bridge visible (`GAP-04`), and measures reproducibility/falsification across devices (`GAP-05`). It also fits an engineering workflow: each device iteration can be stopped early when it fails a prerequisite, avoiding expensive measurement time on a device that cannot support the next claim.

The recommended ExperimentDesign phase should build a layered, future-execution plan: first an offline digital-twin and pre-registration package; then proposed device-level screening and nonlocal controls; then an exchange/fusion operation stage; and finally an architecture translation. It must state that no hardware is fabricated, cooled, pulsed, or measured by this proposal. The goal is a reproducible design that a qualified experimental team can review, adapt, and execute under laboratory safety and institutional procedures.
