# Survey Agent Output: Photon Antiparticle Identity and Opposite States

**Topic.** Are there particles that behave oppositely to the properties or states of photons?

**Scientific reframing.** The word *opposite* must name an operation and an observable. The useful question is not whether there is a distinct antiphoton, but whether a symmetry-resolved state analysis can distinguish (a) a photon’s self-conjugate particle identity from (b) physically distinguishable photonic states with opposite helicity, propagation direction, polarization, or structured-mode labels.

## Evidence-grounded synthesis

In the standard quantum-field description, the photon is the gauge boson of electromagnetism and is its own antiparticle. The electromagnetic field is odd under charge conjugation, so a one-photon state can acquire a charge-conjugation eigenvalue or phase; that phase does not create a distinct antiphoton species. For a density operator, a global phase cancels, leaving the same operational state. A photon is massless and electrically neutral. CERN’s public antimatter description confirms the general particle--antiparticle context: matter antiparticles have matching mass with opposite charge and are produced/annihilated in pairs, while photons are a principal annihilation product [S1]. The photon-specific self-conjugacy statement is treated as standard quantum-field theory, not inferred from this general webpage.

Photons nevertheless possess multiple degrees of freedom that admit contrasting labels. Circular polarization/helicity may be right- or left-handed. A photon can propagate along opposite directions, and structured optical modes can carry opposite orbital-angular-momentum (OAM) indices. These are states of the same particle, not particle--antiparticle pairs. The helicity of a massless particle is tied to its momentum direction; parity reverses momentum and flips helicity, whereas charge conjugation does not turn a photon into a new charged counterpart. Time reversal and reflections require careful convention and antiunitary treatment, so they cannot be replaced by an informal word such as “opposite.”

Quantum-optics evidence establishes that photonic polarization and spatial/OAM modes are controllable, measurable state degrees of freedom [S7]–[S12]. Such work supports a study of state distinguishability and symmetry transformations. It does not provide evidence for a distinct antiphoton. A nonstandard “composite photon/antiphoton” search candidate returned by discovery search is excluded from the frozen source set because it is not an accepted replacement for the standard gauge-field description and is not needed to formulate a falsifiable test.

## Sub-hypotheses and evidence coverage

| ID | Sub-hypothesis | Evidence status | Permitted interpretation |
|---|---|---|---|
| SH-1 | The one-photon sector is self-conjugate; charge conjugation cannot label a distinct antiphoton observable. | Established theory | Use a density-matrix invariance test. |
| SH-2 | Helicity, propagation direction, and selected structured-mode labels can form operationally distinct photon states. | Supported by theory and quantum optics | Treat them as state transformations, not new particles. |
| SH-3 | A fixed measurement context can distinguish some transformed states even when particle identity is unchanged. | Testable design hypothesis | Evaluate trace distance and measurement statistics in simulation. |
| SH-4 | A transformation ledger reduces false “opposite photon” claims. | Research gap | Requires a design-only computational test. |

## Gap triage

`GAP-SYMMETRY-001` is accepted: explanations of antiphotons commonly conflate charge conjugation, parity, helicity, polarization, and counterpropagation. `GAP-OPERATIONAL-002` is accepted: a state label should be called “opposite” only after its transformation and measurement context are specified. `GAP-DISTINCT-ANTIPHOTON-003` is rejected under the standard-model scope: a distinct antiphoton is not predicted for the photon.

## Evidence boundary

The Survey stage freezes twelve sources in `survey_evidence_plan.json`. CERN’s antimatter page was browser-inspected. The dual-engine search independently cross-validated the selected modern quantum-optics/OAM literature. Textbook and foundational-theory bibliographic entries remain subject to publisher/page verification before external dissemination. No source is allowed to support a claim of a new particle, a new symmetry violation, or an observed experiment in this proposal.

