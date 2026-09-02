# ExperimentDesign Agent Output: SOPSL Computational Protocol

## Study type and boundary

**Template:** `computational_digital`.

This is a design-only quantum-information analysis. It uses synthetic density operators and explicit transformations; it does not create, transmit, measure, or control physical photons. It cannot establish a new particle, test a facility, or claim a symmetry violation.

## Research brief

| Element | Design specification |
|---|---|
| Research object | One-photon quantum states with declared polarization/helicity, propagation, and optional OAM labels. |
| Central claim | Self-conjugate particle identity and operationally opposite states are different questions. |
| Unit of analysis | One state--transformation--measurement-context tuple. |
| Primary outputs | Density-matrix invariance, trace distance, probability-vector difference, Stokes predictions, classification and sensitivity record. |
| Alternative explanation | An apparent difference may be a global phase, a basis convention, an undefined antiunitary map, or an unmodeled measurement imperfection. |
| Decision rule | Issue a physical-state label only if basis, operator, observable, and numerical checks are declared. |

## State contract and transformations

Use a finite, declared basis `|k_direction, lambda, ell, r>`, where `lambda` is helicity, `ell` is an optional OAM-mode index, and `r` labels an agreed transverse-mode family. A state is represented by a positive semidefinite, trace-one density operator `rho`. The charge-conjugation test uses the standard self-conjugate one-photon action `C|psi> = exp(i phi_C)|psi>`; hence `C rho C-dagger = rho`. The phase is not an observable distinction.

Parity/helicity, counterpropagation, polarization swap, and structured-mode transformations must be defined as separate operators. For a declared momentum/helicity basis, parity reverses momentum and flips helicity. Time reversal is retained as an antiunitary review item rather than given a generic matrix. OAM sign may be compared with a declared axis and mode convention; the protocol must not claim a convention-independent parity law for arbitrary structured beams.

## Model cards

`C0` is the self-conjugate charge-conjugation baseline. `C1` tests a helicity pair at fixed propagation. `C2` tests counterpropagating modes with explicitly stated laboratory analyzers. `C3` tests a polarization/Stokes pair. `C4` tests OAM sign pairs in a declared mode family. `C5` is a parity/transformation convention card. `C6` is a noise/tomography-sensitivity card. `C7` marks any nonstandard photon model as out of scope unless separately reviewed.

## Analysis and decision labels

For each tuple calculate the trace distance `D(rho,sigma) = 1/2 ||rho-sigma||_1`, predicted probabilities for the declared projectors, and, where polarization is used, the Stokes components. A zero distance under charge conjugation supports only the expected self-equivalence of the input model; it is not a new confirmation of QED. A nonzero distance after a helicity, direction, or OAM transformation means only that the selected state/measurement context can distinguish the transformed states.

| Label | Conditional criterion | Permitted conclusion |
|---|---|---|
| `IDENTITY_EQUIVALENT` | Transformation changes only a global phase or leaves all declared density-matrix predictions invariant. | No distinct antiparticle/state is established. |
| `MEASUREMENT_DISTINGUISHABLE` | Declared observables yield a stable nonzero difference for two states. | The states differ operationally in this context, not in particle species. |
| `CONVENTION_DEPENDENT` | Label changes with basis, axis, gauge, or observer convention without invariant observable contrast. | Withhold an “opposite” particle claim. |
| `NON_IDENTIFIABLE` | Basis, transformation, observable, or uncertainty model is missing. | No classification is allowed. |
| `MODEL_INVALID` | Density matrix, unitarity/antiunitarity, or standard-model scope checks fail. | Discard the scenario. |

## Controls, reproducibility, and review

Hold the mode basis, normalization, axis convention, transformation convention, and projector set fixed within each comparison. Vary state purity, mode leakage, detector-efficiency proxy, and tomography noise only as synthetic sensitivity inputs. Store the matrices, source IDs, code version, random seed, numerical tolerance, and classification log. A quantum-optics specialist must review the basis and observable assumptions; a field-theory specialist must review any charge-conjugation, parity, or time-reversal implementation. No physical optical setup is authorized by this protocol.

