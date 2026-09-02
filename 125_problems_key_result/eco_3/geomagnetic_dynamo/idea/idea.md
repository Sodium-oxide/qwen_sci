# Idea Agent: GEODYNAMO-X

## Problem reconstruction

The Survey Agent shows that the ordinary statement “Earth's rotation creates the magnetic field” combines three different claims: rotation organizes conducting-core convection; core motion induces and sustains the internal field; and the field observed at the surface is the sum of internal, external, lithospheric, oceanic, and induced components. The primary idea must test these claims as a coupled causal system.

## Candidate directions

### A. Core-only geodynamo inversion

Infer outer-core flow from secular-variation coefficients while treating the external field as a pre-cleaned input. This is physically interpretable and computationally tractable, but it risks attributing ionospheric and magnetospheric residuals to the core.

### B. Static-reference extrapolation

Fit the main field and linearly extrapolate its spherical-harmonic coefficients. This is a useful engineering baseline for short horizons, but it has no latent fluid mechanism and cannot adapt to source changes or quantify causal uncertainty.

### C. Uncoupled internal-plus-external decomposition

Fit separate internal and external components with independent regressors. This tests whether source separation alone improves reconstruction, but independent components cannot express feedback, shared boundary conditions, or correlated solar and ionospheric disturbances.

### D. High-resolution numerical dynamo

Run an ensemble of rotating spherical-shell dynamo simulations and compare their surface projections with observations. This supplies a physical prior, but its parameters are not automatically identifiable because simulations operate far from Earth's true diffusivity and turbulence scales.

### E. GEODYNAMO-X: coupled core-to-space data assimilation

Represent the core magnetic field and boundary flow as latent states; represent mantle/ocean induction and ionospheric/magnetospheric currents as source-specific nuisance states; and assimilate observatory, satellite, and paleomagnetic constraints through a common observation operator. The experiment combines physical induction dynamics with machine-learned residuals constrained to remain divergence-free and energy-accountable.

## Primary direction

GEODYNAMO-X is selected because it addresses the central gap rather than improving only a fitted field curve. Its core state evolves under rotating convection and induction; its external state responds to solar-wind and ionospheric forcing; its observation model predicts what each instrument should measure; and its uncertainty layer tests which parts of the inferred motion are identifiable. The novelty is not claiming that a neural network discovers a new force. It is making source separation, physical coupling, and forecast validation part of the same falsifiable experiment.

## Central hypothesis

> A coupled core-to-space state-space model, calibrated with physical priors and source-specific observation operators, will produce better calibrated held-out predictions of vector-field change and magnetic-pole motion than static extrapolation, core-only inversion, or uncoupled source separation, while recovering known latent states in synthetic twins.

The hypothesis has two linked parts. First, a model must recover the right latent source in controlled synthetic experiments. Second, it must improve forecast skill on held-out observations without using external-current residuals as a hidden explanation for core motion. A model that predicts well but cannot identify its source remains useful for reconstruction but does not support the causal claim.

## Mechanism sketch

The physical backbone uses the magnetic induction equation in the liquid outer core. The velocity field is constrained by rotating fluid dynamics, buoyancy, pressure, viscosity, and Lorentz force. The magnetic field is projected through a conducting mantle and lithosphere and combined with external current systems at the measurement location. GEODYNAMO-X learns only unresolved closure terms and instrument-specific residuals; it cannot create a magnetic monopole, violate the induction equation, or silently change the source label.

The model predicts three observables separately: (1) the slowly varying internal field and secular variation, (2) external disturbance components, and (3) induced regional signals. The apparent magnetic-pole location is computed from the internal field estimate and uncertainty, not directly optimized as a target. This avoids turning pole motion into a circular training label.

## Discriminating predictions

1. Joint assimilation should reduce held-out vector-field and secular-variation error relative to a static reference, especially during regime changes in external forcing.
2. Explicit external-source states should reduce false core-flow acceleration during geomagnetic storms and substorm-rich intervals.
3. Physical priors should improve extrapolation beyond the training window, even if they do not minimize in-sample field error.
4. Synthetic-twin posterior recovery should reveal which core-flow scales and buoyancy parameters are identifiable; unresolved scales should remain uncertain rather than acquire spurious precision.
5. If the full model has no gain under equal data, parameter count, and forecast protocol, then the claimed value of multi-scale coupling is not supported.

## Risks and maturation

The most serious risk is overfitting a highly flexible latent-state model. The design therefore freezes the forecast split and evaluates a simple baseline, physical baseline, and coupled model under identical observations. A second risk is that the external forcing record is incomplete; the model reports an external-source uncertainty budget rather than treating missing solar-wind input as zero. A third risk is non-identifiability: if multiple internal flows have the same surface signature, the output is a posterior family and not a unique flow map.

The idea is design-ready because it defines a measurable improvement, a falsifiable source-attribution test, a synthetic-twin gate, and a path from historical reconstruction to short-horizon forecast. It is deliberately ambitious about building a unified core-to-space model, but does not claim that the experiment has already been run.
