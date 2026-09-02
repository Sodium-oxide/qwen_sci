# Survey Agent Output: Particle-Acceleration Speed Limits

**Research topic.** What is the maximum speed to which a particle can be accelerated?

**Scope.** This survey distinguishes (i) the relativistic kinematic limit for a particle with nonzero rest mass, (ii) the operating constraints of laboratory accelerators, and (iii) the separate case of massless quanta. It treats the Large Hadron Collider (LHC) as a contextual example, not as evidence of a universal machine limit. The source set is frozen in `survey_evidence_plan.json`.

## Evidence-grounded synthesis

Special relativity supplies the primary answer. For a massive particle, the speed ratio `beta = v/c` satisfies `beta < 1`; as beta approaches one, the Lorentz factor and total energy increase without bound. Thus no finite, machine-independent maximum speed below `c` follows from the theory. The invariant upper bound is `c` in vacuum, not a particular number such as the LHC beam speed. A massless particle propagates at `c` in vacuum; it is not a massive particle accelerated from rest through that bound.

The LHC provides a useful engineering illustration. CERN describes it as a 27-km ring using superconducting magnets and accelerating structures to push proton or ion beams near light speed [S1]. Its 2008 machine description explains the collider design and the connection between high beam momentum, magnetic bending, radio-frequency acceleration, and protection requirements [S2]. Near `c`, further energy produces a minute change in speed, so speed ceases to rank competing machines in a meaningful way. Energy, momentum rigidity, luminosity, wall-plug power, beam quality, loss control, and reliability become the practical performance variables.

For a circular machine, the ultra-relativistic relation `p approximately q B rho` links achievable momentum to charge, dipole field, and bending radius. Superconducting-magnet technology therefore bounds compact high-energy rings [S4]. A proton collider and an electron/positron collider do not share the same dominant loss ledger: synchrotron-radiation and beamstrahlung effects are especially restrictive for light leptons in rings. Beam losses and the stored energy of high-intensity beams are also central machine-protection constraints [S3]. Future-collider design studies demonstrate that a higher collision energy is a projection with engineering assumptions, rather than an observed speed advantage [S5].

Linear RF and plasma-based accelerators alter the gradient, length, and staging trade-space, but leave the relativistic speed limit unchanged. The ILC design report defines a linear-collider reference architecture [S6]. Plasma-accelerator reviews establish the potential for very high gradients while identifying staging, energy spread, driver efficiency, and stability as unresolved system-level constraints [S7]–[S9]. Strong electromagnetic fields introduce radiation-reaction and quantum-electrodynamic regimes that must be modeled before extrapolating a high-field proposal [S11]. Astrophysical acceleration provides a complementary high-energy context, not an exception to causality or relativistic kinematics [S12].

## Sub-hypotheses and coverage

| ID | Testable survey sub-hypothesis | Evidence status | Allowed conclusion |
|---|---|---|---|
| SH-1 | A massive particle cannot reach `c` with finite energy in standard special relativity. | Direct theoretical basis | Treat `c` as an asymptote for nonzero rest mass. |
| SH-2 | In ultra-relativistic accelerator comparisons, speed is less informative than energy and machine constraints. | Supported by accelerator architecture evidence | Propose a comparative ledger; do not claim a universal threshold without analysis. |
| SH-3 | Constraint dominance changes with accelerator architecture and particle species. | Supported | Compare ring, linear, plasma, and strong-field model cards. |
| SH-4 | High-gradient concepts change compactness trade-offs but not the `v<c` bound. | Supported | Evaluate gradient, staging, power, and beam quality separately. |
| SH-5 | A common reporting ledger can make conceptual accelerator claims more falsifiable. | Research gap | Requires a design study; no outcome is asserted. |

## Research-gap triage

The survey finds no credible evidence that a massive particle can be accelerated through `c` in vacuum. The actionable gap is methodological: public descriptions routinely say “near light speed” while leaving unclear which non-kinematic constraint is decisive for a proposed architecture. The downstream study should test a transparent, sensitivity-aware classification procedure rather than seek an artificial lower speed cap.

## Source boundary

Claims about current facility operation are limited to the CERN public description. Historical machine design, future collider concepts, plasma concepts, and strong-field limits are explicitly labeled by source type and may not be presented as newly measured results. Publisher landing-page inspection remains a required human review step for DOI-bearing sources.

