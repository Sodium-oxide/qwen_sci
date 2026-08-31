# Idea Agent Result: ScaleBridge

## Selected primary direction

**ScaleBridge: a pressure-safe critical-envelope program for excluding first singularities.**

The selected direction does not assert a solution of Navier-Stokes.  It proposes a proof architecture around the first hypothetical singularity.  Rather than asking for a direct global estimate in one step, it asks whether a scale-invariant concentration envelope can be shown to decay after the pressure and nonlocal strain are accounted for.  If it can, epsilon-regularity precludes the singularity; if it cannot, the failed inequality identifies the exact analytic obstruction.

## Scientific object and mechanism

For a parabolic cylinder Q_r(z) = B_r(x_0) times (t_0-r^2,t_0), define the standard scale-invariant local quantities

    C(r,z) = r^-2 integral_Qr |u|^3 dx dt,
    D(r,z) = r^-2 integral_Qr |p - average_Br p|^(3/2) dx dt.

At a suitable weak singular point, an epsilon-regularity criterion forces C+D to remain non-small along a sequence of scales.  The research mechanism is to combine the local energy inequality, a pressure decomposition, and a carefully stated vortex-stretching functional to prove a one-step decay

    E(theta r,z) <= q E(r,z) + controllable_tail(r,z),   q < 1,

for a scale-invariant envelope E.  A proof of this inequality uniformly over all admissible cylinders would bridge G1, G2, and G4.  A merely observed or simulation-based decrease is not enough.

## Portfolio decision

| Candidate | Decision | Reason |
|---|---|---|
| ScaleBridge critical-envelope exclusion | Selected primary | Directly targets G1--G4 and makes every missing implication inspectable |
| Pure critical-element compactness | Competitive | Strong framework, but cannot close without a profile rigidity theorem |
| Geometric vorticity alignment theorem | High-risk | Could supply the decisive coercivity, but must control nonlocal strain and all configurations |
| Finite-grid or molecular cutoff argument | Rejected | Changes the continuum theorem and violates the survey invariant |
| Unchecked public proof declaration | Rejected as theorem input | The proposed bridge has not passed a proof-obligation audit |

## Falsifiability and release policy

ScaleBridge makes clear disconfirming outcomes possible.  A candidate depletion inequality fails if a compatible smooth sequence produces a non-vanishing normalized defect.  A pressure estimate fails if its far-field term cannot be bounded in the declared norm.  A compactness route fails if the limiting profile is trivial, outside the Liouville class, or inherits a hidden regularity assumption.  Any one of these findings is publishable as an obstruction result, but none is a proof or disproof of the Millennium problem.

The only release condition for a candidate proof is an all-PROVED chain: exact local formulation, pressure-safe decay lemma, iteration to epsilon regularity, coverage of all first-singularity scenarios, and composition with the classical continuation theorem.
