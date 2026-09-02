# ExperimentDesign Agent: Cross-Modal Test of a Coherence-Weighted Pairing Kernel

## Design-only status

`execution_policy.mode = DESIGN_ONLY`. No human-participant, animal, material,
or laboratory experiment has been run. The separate Q1 result is a numerical
simulation of declared assumptions and cannot substitute for this protocol.

## Central hypothesis

For a common cuprate family and controlled hole-doping series, a model using
both magnetic spectral support `S(p)` and antinodal coherent spectral weight
`Z_AN(p)` predicts the d-wave pairing endpoint more accurately than a matched
spin-only model. The mechanism relation is `lambda_d(p)=lambda0 S(p)Z_AN(p)`;
the comparator is `lambda_d^0(p)=lambda0 S(p)`.

## Measurements and variables

Independent variables are nominal hole doping, temperature, and material family
or layer structure. The primary dependent endpoint is `Tc` obtained from a
pre-specified resistive transition criterion and corroborated by diamagnetic or
thermodynamic evidence where feasible. Mechanistic endpoints are: (i) the
low-energy antiferromagnetic spectral integral from calibrated RIXS or neutron
scattering, (ii) an ARPES antinodal coherent-weight index normalized to a
pre-specified reference window, and (iii) charge-order peak intensity and
correlation length from resonant x-ray scattering. Covariates include disorder,
oxygen ordering, sample mosaicity, measurement temperature, photon energy,
energy resolution, and surface-aging interval.

## Sampling, controls, and calibration

Use at least three independent crystals per doping point across a pre-registered
series spanning underdoped to overdoped material, with measurements randomized
over beamtime blocks and blinded sample identifiers for analysis where the
facility workflow permits it. Calibrate energy and momentum scales daily;
record resolution functions and normalize spectroscopy using the same protocol
within a family. Include an overdoped reference where pseudogap signatures are
weak, repeated standard samples for drift detection, and a spin-only baseline
that is fit only on the training partition.

## Analysis plan

Fit hierarchical measurement-error models rather than correlating raw signals.
The primary comparison is a held-out predictive score for `Tc` or an independently
extracted pairing-scale proxy: spin-only versus spin-times-coherence. Use
material-family random effects, leave-one-doping-out and leave-one-crystal-out
validation, posterior predictive checks, and sensitivity analyses that vary
normalization windows and doping uncertainty. Missing spectra are recorded with
instrumental reason codes; multiple imputation is permitted only for covariates,
never for the primary endpoint or a missing primary spectroscopic observable.

## Falsification and interpretation rules

Reject I-01 if the joint model does not improve held-out performance beyond a
pre-registered practical threshold, if its coherence coefficient changes sign
under reasonable calibration choices, or if a charge-order-only alternative
explains the same endpoints better. A positive result supports only the stated
conditional relation within the selected family and temperature/doping range;
it does not establish a universal boson or settle the microscopic Hamiltonian.

## Safety, ethics, and governance

The work has no clinical or human-subject intervention. Facility safety rules
for cryogens, high magnetic fields, vacuum, x-ray radiation, and sample handling
remain mandatory. Preserve raw spectra, calibration files, reduction versions,
and analysis notebooks with immutable identifiers; redact no scientific metadata
that would be needed for reproducibility. Human review is required before
facility scheduling, sample synthesis, model calibration, and publication.

