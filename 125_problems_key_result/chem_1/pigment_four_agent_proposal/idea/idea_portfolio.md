# Idea Agent Portfolio

## Inputs and immutable constraints

The Idea Agent receives the verified Survey handoff, accepted gaps `GAP-01`–`GAP-04`, and the following constraints:

- The deliverable is a research design, not a claim of pigment synthesis or discovery.
- “New colour” must never mean a new fundamental human colour dimension.
- All novelty is comparative to an explicit commercial/reference pigment library and specified CIE conditions.
- Material-selection decisions must expose safety, environmental, uncertainty, and human-review constraints.

## Candidate directions

### D1 — Spectrum-first atlas of existing pigment materials

**Mechanism.** Assemble measured reflectance spectra for a reference library, calculate CIE coordinates under several illuminants, and map undercovered regions in spectrum and colour space.

**Strength.** Directly resolves `GAP-01` and produces a reusable benchmark.

**Weakness.** It inventories the known library but may not identify structurally credible new candidates. It only partially resolves `GAP-02` and `GAP-03`.

**Disposition.** Competitive enabling work; retained as a required work package but not selected as the primary research direction.

### D2 — Safety-constrained, uncertainty-aware multiobjective inverse design of pigment candidates

**Mechanism.** Learn a calibrated mapping from safe candidate descriptors to reflectance-derived and engineering proxy objectives. Use Pareto ranking and an acquisition function to select a small, diverse candidate set for expert-reviewed characterization.

**Strength.** Integrates all four Survey gaps: an explicit novelty definition, a joint performance frontier, a benchmark need, and transparent prediction-to-observation states. It can test a falsifiable hypothesis: the proposed ranking improves the yield of candidates that pass preregistered novelty gates relative to random or scalar-score selection.

**Weakness.** Model quality is limited by data coverage and proxy validity. It cannot replace chemical judgement or a formal safety review.

**Disposition.** Selected primary direction.

### D3 — Coordination-environment rule mining inspired by YInMn Blue

**Mechanism.** Extract local coordination and symmetry descriptors from a crystal-structure corpus and search for motifs associated with selective visible absorption.

**Strength.** Scientifically interpretable and historically motivated by the trigonal-bipyramidal chromophore context of YInMn Blue.

**Weakness.** A motif-to-colour association can be confounded by composition, defects, particle size, and measurement conditions. Narrowly imitating a known example risks low novelty.

**Disposition.** High-value explanatory module nested inside D2; not a standalone primary direction.

### D4 — Generative latent-space search for maximal CIE separation

**Mechanism.** Use a generative model to propose structures that maximize distance from a reference colour library under a selected illuminant.

**Strength.** May produce visually distant theoretical candidates.

**Weakness.** Optimizing CIE distance alone encourages physically implausible, unsafe, unstable, or practically irrelevant candidates. It violates the Survey's joint-objective invariant unless extensively constrained.

**Disposition.** Rejected as primary direction; its diversity objective is retained as a secondary term in D2.

## Multi-route selection analysis

| Criterion | D1 Atlas | D2 Multiobjective inverse design | D3 Motif mining | D4 Max-separation generator |
|---|---:|---:|---:|---:|
| Alignment to validated gaps | 3/4 | 4/4 | 2/4 | 1/4 |
| Falsifiability | High | High | Medium | Medium |
| Interpretability | High | Medium–High | High | Low–Medium |
| Safety/utility integration | Medium | High | Medium | Low |
| Risk of overclaim | Low | Medium, controllable | Medium | High |
| Selected role | Benchmark | **Primary direction** | Mechanistic module | Rejected |

Scores are deliberative ranking aids, not measured performance values.

## Selected hypothesis

**H-PIGMENT.** *For a preregistered reference pigment library and stated viewing conditions, a safety-constrained, uncertainty-aware Pareto acquisition strategy will select a batch of candidate materials with a higher rate of passing the project's declared spectral–perceptual–engineering novelty gates than either random sampling or a color-distance-only ranking.*

This hypothesis can fail in three informative ways: the model may not outperform baselines; the candidate family may have no useful frontier extension; or the measurements may expose a proxy/model mismatch. None of these outcomes implies a failure of colour science; they delimit the method and material family.

## Primary direction synopsis

**Title.** *Beyond the Current Pigment Library: A Calibrated Multiobjective Search for New Usable Reflectance Signatures.*

**Research object.** A documented candidate material library restricted by composition/safety constraints and paired with a declared commercial/reference pigment set.

**Intervention.** Replace single-score “new colour” screening with a two-stage workflow: colourimetric/spectral atlas construction followed by uncertainty-aware Pareto prioritisation.

**Core mechanism.** A candidate is not selected for one target blue coordinate. It must jointly show predicted separation from the reference library, usable optical behaviour, uncertainty low enough to justify review, and no automatic exclusion under material constraints.

**Evidence of success.** A future authorised study measures a held-out set and compares pass rates, calibration, and Pareto-front coverage against prespecified baselines. A candidate remains “predicted” until those measurements are available.

**Key risks.** Training data may be sparse or heterogenous; proxy objectives may be unsuitable; novelty may disappear when the reference library is broadened; composition flags need expert interpretation. The design records each risk as a review gate.
