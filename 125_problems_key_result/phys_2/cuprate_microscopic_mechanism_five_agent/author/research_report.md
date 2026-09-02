# IEEE Research Report: Cuprate High-Temperature Superconductivity

## Final author-stage statement

**Title.** *A Falsifiable Cross-Modal Program for the Microscopic Mechanism of
Cuprate High-Temperature Superconductivity*

**Artifact class.** Proposal with non-empirical numerical evidence.

**Scope.** The report narrows the general high-temperature-superconductivity
question to copper oxides. It does not assert a universal mechanism or use the
retracted 2020 carbonaceous sulfur-hydride paper as support.

**Scientific contribution.** The report turns `GAP-HTSC-01` into a controlled
comparison between two observable mappings:

```text
H0: pairing-scale proxy = magnetic spectral support
H1: pairing-scale proxy = magnetic spectral support × antinodal coherent weight
```

The prospective experiment uses matched cuprate samples across doping and
combines spin-sensitive scattering, ARPES, resonant x-ray scattering,
transport/thermodynamics, and materials characterization. Pre-specified
hold-out validation, batch/crystal effects, temperature matching, missing-data
rules, negative controls, and rejection branches keep the experiment
falsifiable.

**Quantitative boundary.** The reduced-kernel calculation is a deterministic
`NUMERICAL_SIMULATION`. All parameters are `MODEL_ASSUMPTION`s. The output is
`SIMULATED`, `NOT_EMPIRICAL`, and does not fit a cuprate data set or establish a
pairing mechanism. Its concrete design implication is that, under the declared
assumptions, the two models differ most on the underdoped side and the
experimental grid must resolve that interval.

## Included files

- `ieee_project/conference_101719.tex`: source using the supplied IEEE template.
- `high_tc_cuprate_mechanism_report.pdf`: final 8-page IEEE-style PDF.
- `author_document.json`: evidence and quantitative-disclosure metadata.
- `author_manifest.json`: author-stage inventory and cross-stage provenance.

## Claim discipline

The paper may be read as a proposal for a discriminating experiment and a
numerically verified demonstration that the two *declared* phenomenological
kernels separate on a fixed grid. It must not be read as an experimental result,
a material prediction, a proof of spin-fluctuation pairing, or a solution of the
cuprate mechanism.
