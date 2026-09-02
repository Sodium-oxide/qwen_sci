# Idea Agent: A Joint Magnetic-Coherence Discriminator for Cuprates

## Portfolio

**Selected primary direction (I-01).** Construct a minimal, falsifiable
reduced pairing kernel in which antiferromagnetic spin spectral support provides
the sign-changing d-wave pairing gain and the pseudogap/charge-order sector
reduces the antinodal coherent spectral weight available to that gain. Compare
it against a spin-only kernel on the same doping path.

**Competitive direction (I-02).** Perform a material-specific multi-orbital
Hubbard/cluster calculation. This is scientifically valuable but is not
selected for the current direct study because it requires material-specific
Hamiltonian calibration, controlled solver extrapolations, and resources beyond
the present Q1 protocol.

**High-risk direction (I-03).** Infer a causal mechanism directly from a
machine-learning model of heterogeneous spectroscopy. It is rejected for the
primary direction because cross-family measurement conventions and confounding
would make causal claims underidentified.

## Primary hypothesis and falsification

Let `S(p)` denote a normalized magnetic spectral-support proxy at hole doping
`p`, and `Z_AN(p)` an antinodal coherent spectral-weight proxy. The proposed
relation is

`lambda_d(p) = lambda0 S(p) Z_AN(p)`.

The spin-only comparator sets `Z_AN(p)=1`. The primary hypothesis is that the
joint relation ranks underdoped suppression and dome asymmetry more accurately
than the comparator when both terms are evaluated from held-out measurements.
It is falsified if a pre-registered spin-only relation achieves equal or better
out-of-sample error, or if `Z_AN` does not provide a stable improvement after
uncertainty propagation and family-specific controls.

## Why this is evidence-aligned

The direction preserves the d-wave constraint from C1, treats spin
fluctuations as a candidate rather than a fact of universal causation (C3),
and makes charge/pseudogap phenomenology a measured modifier rather than an
unjustified alternative pairing interaction (C4). It is a bridge model: it does
not claim that a one-band phenomenology is the complete microscopic Hamiltonian.

## Feasibility boundary

The Q1 numerical calculation is deliberately parameterized in dimensionless
units and uses declared model assumptions. Its role is to check internal
discrimination, numerical stability, and the experimental precision needed for
the proposed test. Material-calibrated inference remains an ExperimentDesign
task requiring human review and real spectroscopy data.

