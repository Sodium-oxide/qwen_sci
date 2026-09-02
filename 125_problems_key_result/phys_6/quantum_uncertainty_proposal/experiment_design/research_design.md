# ExperimentDesign Agent: UBT Research Design

## Research brief and boundary

The selected UBT direction asks whether a calibrated model can separate preparation uncertainty, apparatus error/disturbance, decoherence, and classical readout noise before predicting a qubit information task. The design uses the `computational_digital` template with a quantum-optics or spin-qubit-compatible measurement module. It is strictly a design: it specifies simulations, calibration records, analysis, and a future laboratory protocol, but it does not run hardware, collect photons, operate lasers, or report observations.

## Variables and formal model

The independent variables are the basis incompatibility angle `theta`, input Bloch vector, generalized-measurement strength, channel parameter `lambda`, readout confusion matrix `C`, and optional memory-correlation parameter. Outcomes include preparation spreads, entropic uncertainty, declared error/disturbance measures, channel fidelity or visibility, and an information-task metric. The model preserves four distinct layers:

`rho_in -> instrument M_theta -> channel E_lambda -> readout C -> observed record`.

For an observable `A`, preparation spread is `Delta A^2 = Tr(rho A^2) - Tr(rho A)^2`. The Robertson relation and the entropic bound are analyzed separately from instrument error metrics. Readout correction is constrained by calibrated `C`, not by unconstrained inversion.

## Design modules

1. **Synthetic identifiability module.** Generate reference records from declared single-qubit states, calibrated POVMs/instruments, a specified dephasing or depolarizing channel, and a confusion matrix. Test whether the four terms can be recovered under identifiable settings.
2. **Calibration module.** Define state-preparation, basis, POVM/instrument, channel, and readout calibration data requirements before analysis.
3. **Held-out prediction module.** Fit UBT on a training grid of settings and compare it with an aggregate-noise baseline on held-out basis angles, states, and channel strengths.
4. **Memory module.** If an ancilla is available, state the correlation model and use conditional entropies; do not infer that memory removes uncertainty.
5. **Mitigation module.** Compare a declared mitigation or encoded-control strategy against the same channel. Attribute any benefit to modeled noise reduction, not to removal of incompatible-observable limits.

## Decision rules

The primary decision is whether UBT offers out-of-sample predictive improvement and calibration consistency. A design is not considered informative when different parameter settings create indistinguishable observed distributions, when the confusion matrix is ill-conditioned without an uncertainty-aware treatment, or when the selected error metric is not declared before result interpretation. These cases are reported as non-identifiability or needed human input, not converted into positive evidence.

## Human review and laboratory safety

Any future physical implementation requires a qualified operator and local laboratory authorization. The design forbids automatic operation of optical sources, laser alignment, high voltage, microwave controls, cryogenic equipment, or experimental data collection. A quantum-information and experimental-methods reviewer must confirm the instrument model, calibration protocol, statistical assumptions, and the appropriate uncertainty definition before execution.
