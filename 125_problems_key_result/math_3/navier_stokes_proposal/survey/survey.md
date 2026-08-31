# Survey Agent Report: 3D Navier-Stokes Existence and Smoothness

## Scope and status question

This survey addresses the incompressible three-dimensional Navier-Stokes Cauchy problem on either R^3 or the periodic three-torus.  For a velocity field u and pressure p, with viscosity nu > 0,

    partial_t u + (u dot grad)u + grad p = nu Delta u,       div u = 0.

The Millennium formulation asks for a proof of one of two alternatives for smooth divergence-free finite-energy initial data: global smooth existence and uniqueness, or a finite-time singularity.  The question is not whether Navier-Stokes is useful as a physical model.  It is whether the nonlinear PDE has a global classical solution for every datum in the stated 3D class.

The evidence gathered here supports the following status decision:

> OPEN_PENDING_FORMAL_RECOGNITION.  The literature contains global weak solutions, local classical solutions, partial regularity, and many sufficient continuation criteria.  It does not contain a cross-validated, conventionally accepted complete proof or counterexample in this survey record.

Two-engine discovery did return 2025--2026 repository papers declaring a solution.  They are retained as CLAIM_UNDER_AUDIT, not theorem evidence.  A repository landing record and an abstract claiming a global bound do not establish the coercive estimate, admissible function class, limiting argument, or full Clay formulation needed for closure.

## Evidence map

| Evidence family | What it establishes | What it does not establish |
|---|---|---|
| Leray weak theory | Global finite-energy weak solutions satisfying an energy inequality | Global smoothness, uniqueness, or absence of singularities |
| Caffarelli-Kohn-Nirenberg theory | Suitable weak solutions have a quantitatively small singular set | The singular set is empty |
| Critical continuation criteria | Regularity follows if a named scale-critical norm stays finite | The norm stays finite for arbitrary smooth data |
| Blow-up rescaling and Liouville work | A hypothetical singularity has constrained local and ancient-profile behavior | Every possible profile is excluded |
| Thin, rotating, or structured 3D settings | Global regularity for special geometries or data classes | The unrestricted 3D problem |
| Turbulence simulations and geometric observations | Candidate mechanisms of vortex-stretching depletion | A theorem uniform over all smooth solutions and scales |

## Established analytic structure

The scaling

    u_lambda(x,t) = lambda u(lambda x, lambda^2 t)

preserves the equation.  It identifies spaces such as L-infinity_t L^3_x as critical.  The basic energy inequality controls the L^2 norm of u and viscous dissipation, but it does not directly prevent critical-scale concentration.  The vorticity equation displays the obstruction:

    partial_t omega + (u dot grad)omega - nu Delta omega = (omega dot grad)u.

The right side is vortex stretching.  A smooth solution can be continued past T whenever a sufficient critical condition is proved, for example through a Prodi-Serrin condition or the endpoint L-infinity_t L^3_x criterion.  Such theorems are conditional bridges: they are powerful precisely because proving their antecedent for arbitrary data is still unresolved.

Partial regularity is equally important.  Epsilon-regularity statements show that small scale-invariant velocity-pressure quantities imply local smoothness.  Therefore any first singularity must carry a non-vanishing, scale-invariant concentration.  This converts a vague blow-up scenario into a compactness-and-rigidity problem.  It does not make the compactness limit automatically nontrivial, nor does it provide a Liouville theorem for every limit class.

## Source registry and use rules

The frozen registry contains twelve sources.  S1--S9 are admissible theorem or survey evidence; S10 is a physical-mechanism input and may motivate a lemma but cannot replace one; S11--S12 are public solution declarations under audit and are excluded from proof support.

1. S1: C. Fefferman, Clay problem formulation, 2000.
2. S2: J. Leray, global weak-solution construction, 1934.
3. S3: L. Caffarelli, R. Kohn, and L. Nirenberg, partial regularity, 1982.
4. S4: L. Escauriaza, G. Seregin, and V. Sverak, endpoint critical regularity, 2003.
5. S5: C. Kenig and G. Koch, critical-space compactness and rigidity viewpoint, 2010.
6. S6: G. Koch, N. Nadirashvili, G. Seregin, and V. Sverak, Liouville theorems for ancient solutions, 2009.
7. S7: T. Tao, localization and compactness equivalences for the global problem, 2011.
8. S8: T. Barker and C. Prange, quantitative concentration near hypothetical singularities, 2021.
9. S9: R. Farwig, historical and modern survey of the problem, 2020.
10. S10: D. Buaria, A. Pumir, and E. Bodenschatz, numerical self-attenuation observation, 2020.
11. S11: a 2026 Zenodo solution declaration, claim under audit.
12. S12: a 2026 arXiv solution declaration, claim under audit.

Direct official Clay and publisher-page inspection could not be completed because the user-selected in-app browser failed before connecting.  DOI metadata was cross-matched by OpenAlex and AnySearch where available.  This limitation is carried forward as a human-review item.

## Accepted research gaps

**G1 -- Energy-to-critical bridge.** No known unconditional estimate upgrades finite energy and dissipation to the scale-critical control that standard continuation theorems require.

**G2 -- Vortex-stretching coercivity.** Local geometric depletion observations are not yet a uniform inequality that dominates stretching by viscous dissipation at every potential concentration scale.

**G3 -- Critical-element closure.** Rescaling arguments constrain prospective singularities, but the exact compact limit class and the nontriviality/rigidity chain must be preserved without importing the desired regularity result.

**G4 -- Pressure and nonlocality.** Pressure reconstruction and far-field strain can re-enter a localized argument.  A local estimate that silently discards them cannot close the global problem.

**G5 -- Claim-audit completeness.** A public proof declaration must provide precise spaces, every scale-invariant bound, compactness passage, and an implication to the unrestricted formulation.  Neither S11 nor S12 supplied those items in this workflow.

## Survey handoff

The downstream idea stage must anchor every proposed route to G1--G4, must retain the distinction among PROVED, CONDITIONAL, FINITE, HEURISTIC, and CLAIM_UNDER_AUDIT, and must not present a numerical vortex geometry observation as a global theorem.  The most promising route is to turn the singularity alternative into a finite list of formally typed obligations: concentration extraction, pressure-safe localization, a non-circular depletion estimate, compactness, and an ancient-solution rigidity theorem.
