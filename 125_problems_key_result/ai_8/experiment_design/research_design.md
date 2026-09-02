# ExperimentDesign Agent: Q-BRAIN-IMITATION-BENCHMARK

## 1. Status and aim

This is a preregistration-ready, DESIGN_ONLY protocol. It will test whether quantum or
hybrid models improve declared brain-like targets after matching classical and spiking
controls. It does not test consciousness, subjective experience, personhood, or the
claim that the entire human brain is a quantum computer.

## 2. Target definition and data splits

Each experiment declares exactly one target scale: (a) a recorded neural population,
(b) a validated spiking microcircuit simulator, or (c) a closed-loop agent with a known
neural-style controller. The data package includes a stimulus/input stream, neural
observation modality, train/development/held-out split, temporal resolution, permitted
preprocessing, and a causal perturbation set. Hold out not only trials but also stimulus
families, task rules, and intervention magnitudes.

## 3. Model conditions

The core comparison is:

* **C0:** parameter- and compute-matched classical recurrent network;
* **C1:** spiking neural network with matched readout and training data;
* **Q0:** quantum kernel or variational quantum circuit in ideal simulation;
* **Q1:** hybrid quantum-classical recurrent model in ideal simulation;
* **Q2:** Q1 with finite shots, calibrated noise, circuit compilation, and latency;
* **A1:** Q1 with entangling gates removed or replaced by separable operations;
* **A2:** Q1 with a matched classical feature-map surrogate;
* **A3:** Q1 with matched parameter count but shuffled quantum encoding.

All models use the same input representation or a documented lossless model-specific
encoding. Tune hyperparameters only on development tasks. Freeze model versions,
compiler versions, random seeds, shot counts, optimizer steps, and stopping criteria
before the held-out evaluation.

## 4. Metrics

### Signal fidelity

Evaluate per-neuron or per-channel prediction likelihood, correlation, timing error, and
calibration. If observations are spike trains, use a declared bin size and report
sensitivity across at least two bin sizes.

### Dynamical fidelity

Evaluate autocorrelation, cross-correlation, spike-count distribution, synchrony,
attractor occupancy, transition probabilities, and recovery after a controlled input or
state perturbation. Dynamic time warping is supplementary because it can reward a
visually similar but causally wrong trajectory.

### Behavioral and learning fidelity

Measure task reward, error distribution, reaction-like latency, sequence recall, learning
curve slope, retention after delay, and adaptation after rule change. Few-shot transfer
is measured on held-out concepts with the number of examples fixed for all conditions.

### Quantum and practical resources

Report qubits, circuit depth, entangling-gate count, shots, noise model, compilation
time, wall-clock time, energy estimate if available, memory, and classical accelerator
use. A claimed quantum advantage must improve a declared target while remaining within a
specified resource envelope.

## 5. Statistical analysis

Use blocked randomization by target, instance, noise level, and seed. Fit hierarchical
models with condition, task scale, and split effects. The primary contrasts are Q1 versus
C0, Q1 versus C1, Q1 versus A1, Q1 versus A2, and Q1 versus Q2. Report effect sizes and
uncertainty intervals, together with practical thresholds declared before data collection.

No aggregate "brain score" is primary. A profile is reported only after axis-level
outcomes for signal, dynamics, behavior, learning, transfer, and resources have been
shown. Ideal and noisy/hardware-aware conditions are never pooled.

## 6. Quantum-sensitive hypothesis tests

If a quantum-brain proposal is tested, it must nominate a measurable observable, a
temporal/spatial scale, a predicted effect direction, and an intervention. Compare it
against at least two alternatives: a classical stochastic model and a spiking model with
matched noise and connectivity. Blind the analysis code to condition labels where
possible. No support is assigned merely because a quantum model fits the data; support
requires a prediction that the alternatives fail under predeclared tests.

## 7. Reproducibility and safety

Release task cards, public/synthetic data, data governance notes, model and compiler
versions, circuits, seeds, optimizer traces, error logs, preprocessing, metrics, and
analysis code. For restricted neural data, release schema, hashes, and a synthetic
surrogate. Human-derived neural data remain de-identified and cannot be used for clinical,
diagnostic, identity, or consciousness claims. All experiments are offline or sandboxed.

## 8. Decision rules

Support for useful quantum assistance requires a Q1 improvement over C0 and C1 on a
predeclared metric under a matched resource budget. Support for a quantum-resource
mechanism additionally requires degradation in A1 or A2 and persistence under Q2.
Support for brain-like imitation requires a multi-axis match including perturbation
response and held-out transfer. No result supports quantum consciousness, whole-brain
equivalence, or a biological quantum-computation claim without independent biological
evidence.
