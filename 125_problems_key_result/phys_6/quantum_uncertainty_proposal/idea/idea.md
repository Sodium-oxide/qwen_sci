# Idea Agent: Uncertainty Budget Tomography

## Input contract

This stage accepts the Survey Agent's frozen manifest, six accepted gaps, and four invariants: preparation uncertainty is not measurement error-disturbance; decoherence and readout noise are separate from incompatibility; error correction does not remove noncommutation; and no hardware observation is invented.

## Candidate portfolio

| Candidate | Scientific operation | Strength | Decision |
|---|---|---|---|
| Calibrated entropic uncertainty with quantum memory | Transfer entropic uncertainty bounds to a memory-assisted qubit task | Directly targets conditional entropy | Retain as a module, but it does not independently separate apparatus and channel effects. |
| Generalized measurement error-disturbance benchmark | Compare operational error and disturbance definitions for incompatible qubit measurements | Resolves definition-sensitive claims | Retain as a module, but it lacks a direct device-performance link. |
| Decoherence-aware quantum-error-correction benchmark | Compare a controlled channel with a mitigation or encoded-control protocol | Tests the boundary between noise mitigation and fundamental limits | Retain as an optional extension; it cannot make incompatible observables jointly sharp. |
| **Uncertainty Budget Tomography (UBT)** | Combine calibrated preparation, instrument, channel, and readout models before predicting a qubit information metric | Closes G1-G6 in one falsifiable protocol | **Selected primary direction.** |

## Selected direction

**Uncertainty Budget Tomography (UBT)** is a calibrated inference program for a qubit experiment. It estimates four quantities that often appear together in measured randomness but are not the same object:

1. the state-dependent preparation spread caused by noncommuting observables;
2. apparatus error and disturbance under declared operational definitions;
3. open-system decoherence represented by a calibrated channel; and
4. classical readout noise represented by a calibrated confusion matrix.

The central hypothesis is that a joint, explicitly calibrated model will predict held-out information-task performance more accurately and transparently than a single aggregate-noise term. This is a proposal for a measurement-and-inference protocol, not a claim that the protocol has run.

## Falsifiability and guardrails

UBT fails if the four terms cannot be identified from the declared calibration data, if it does not improve held-out prediction relative to an aggregate-noise baseline, or if independent measurement and channel calibrations disagree with the inferred decomposition outside their uncertainty bounds. A failure of a simplified error-disturbance product is not interpreted as a failure of the Robertson preparation relation. Quantum memory is treated through conditional entropies, and error correction is treated only as mitigation of declared noise channels.

## Handoff

The next stage receives the selected idea, its gap identifiers, operational variables, falsifiers, and the Survey identity. It must create a DESIGN_ONLY research design with no observed results.
