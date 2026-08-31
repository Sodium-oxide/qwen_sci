# ExperimentDesign Agent: Formal Derivation and Proof-Obligation Plan

## Boundary

This is a mathematical research design, not an executed proof.  It does not run a PDE solver, compute a singularity, invoke a proof assistant, or claim a theorem.  Its execution policy is DESIGN_ONLY and its observed-results list is empty.

## Research brief

The design operationalizes ScaleBridge for smooth divergence-free data on R^3 and records a periodic analogue only after every localization step is rechecked.  The target is an unconditional continuation theorem.  The alternative output is a rigorous obstruction identifying why a proposed depletion mechanism cannot be made uniform.

## Variables and operational quantities

| Role | Quantity | Operational definition |
|---|---|---|
| State | u, p, omega | Velocity, pressure, and curl u in a stated solution class |
| Independent scale | r, theta r | Parabolic-cylinder radius and fixed shrink factor |
| Concentration readout | C(r,z), D(r,z) | Scale-invariant local L^3 velocity and L^(3/2) pressure quantities |
| Mechanism readout | V(r,z) | r times the positive local vortex-stretching integral |
| Control terms | cutoff error, far-field pressure, exterior strain | Terms retained explicitly in the localized identity |
| Decision variable | E(r,z) | A declared weighted combination of C, D, V, and tail terms |

## Formal derivation spine

For smooth solutions, take curl of Navier-Stokes to obtain

    partial_t omega + (u dot grad)omega - nu Delta omega = (omega dot grad)u.

Multiplying by omega and integrating formally yields the enstrophy balance

    1/2 d/dt ||omega||_2^2 + nu ||grad omega||_2^2
    = integral (omega dot grad u) dot omega.

This identity identifies vortex stretching but is not a global estimate: the right-hand side has no known sign.  A localized derivation introduces a cutoff phi supported in Q_r and must retain flux, commutator, pressure, and exterior Biot-Savart terms.  The design treats any omitted term as a failed obligation, not as a harmless technicality.

The desired new lemma has the schematic form

    E(theta r,z) <= q E(r,z) + K Tail(r,z),  0 < q < 1,

with constants independent of the candidate singular scale.  Tail is admissible only if it is shown to be summable or absorbed under assumptions weaker than the desired regularity conclusion.  If iteration makes E smaller than the known epsilon-regularity threshold, the point is regular.  Covering every first singularity then gives continuation.

## Obligations and gates

O1. State the exact solution class, domain, scaling, and local continuation theorem.

O2. Derive the local energy inequality and pressure decomposition with every cutoff term.

O3. Establish the relevant epsilon-regularity criterion in the same normalization used by E.

O4. Prove a first-concentration selection lemma: a singularity supplies a non-small normalized sequence.

O5. Prove the new pressure-safe vortex-stretching depletion inequality with a uniform q less than one.

O6. Prove tail absorption or summability without assuming a critical continuation bound.

O7. Iterate O5--O6 to cross the epsilon threshold, or construct a nontrivial ancient limit with all hypotheses of the selected rigidity theorem.

O8. Compose the result with O1 and conduct an independent proof audit.  Any failed O5, O6, or O7 blocks a global-regularity claim.

## Counterexample protocol

A candidate counterexample to ScaleBridge is not a counterexample to Navier-Stokes.  It must be classified by exact object: a smooth solution sequence, a suitable weak limit, a discretized flow, or a formal ansatz.  The protocol verifies divergence freedom, scaling normalization, pressure convention, temporal domain, nontriviality, and every bound passed to a compactness theorem.  A violation of the proposed decay becomes an obstruction record.  Only an actual finite-time singularity in the Millennium class would resolve the problem negatively.
