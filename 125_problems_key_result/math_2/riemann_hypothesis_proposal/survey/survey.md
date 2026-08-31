# Survey Agent Report: Is the Riemann Hypothesis True?

## Status decision

The Riemann Hypothesis (RH) is treated in this project as **OPEN; no complete proof accepted by this workflow**. The Survey found rigorous finite-height zero verification, explicit zero-free-region improvements, and many equivalent reformulations. It did not find a cross-validated peer-reviewed record that closes the universal statement that every nontrivial zero of the Riemann zeta function has real part one-half. A recent 2025 survey retrieved by both scholarly engines describes recent attempts rather than a settled proof. This is an evidence-status decision, not a claim that new manuscripts are necessarily false.

The user's assertion that there has been a recent major breakthrough is important, but it must be classified. A certified finite advance, a theorem with a fully checkable proof, and a repository manuscript declaring a proof are different things. The dual-engine search returned several 2026 repository records that assert proofs or major closures. Their returned venue metadata identifies repositories such as Zenodo, and no peer-reviewed theorem record was returned with them. They are preserved as `CLAIM_UNDER_AUDIT` examples, excluded from the theorem evidence registry, and do not alter the project's OPEN status. This should be rechecked against official prize and journal sources when the requested in-app browser becomes available; it failed here with a Windows ACL error.

## Mathematical evidence map

### E1. The statement and analytic object

The Riemann zeta function is initially defined by \(\zeta(s)=\sum_{n\ge1}n^{-s}\) for \(\Re(s)>1\) and has a meromorphic continuation with a simple pole at \(s=1\). Its nontrivial zeros lie in the critical strip \(0<\Re(s)<1\). RH asserts that every such zero \(\rho\) satisfies \(\Re(\rho)=1/2\). The completed xi-function
\[
\xi(s)=\tfrac12s(s-1)\pi^{-s/2}\Gamma(s/2)\zeta(s)
\]
is entire and obeys \(\xi(s)=\xi(1-s)\). These facts impose symmetry but do not prove that all zeros are on the critical line.

### E2. Equivalent criteria are proof targets, not finite certificates

Li-type positivity criteria translate RH into positivity of an infinite sequence of coefficients; generalized formulations relate those coefficients to Weil-style quadratic functionals [S5--S8]. The Nyman--Beurling and related criteria likewise retain a universal approximation or positivity statement. An equivalence preserves difficulty: confirming finitely many coefficients, test functions, or approximation dimensions does not establish the all-index or limiting assertion.

### E3. Rigorous numerical work is powerful but finite

Platt gives a rigorous algorithm isolating nontrivial zeta zeros up to a stated height, with an independent verification of RH in that finite range [S1]. Later work uses verification up to height \(3\cdot10^{12}\) to derive finite-range prime-counting estimates [S2]. These are mathematically substantive results, but a hypothetical off-line zero can still occur above the verified height.

### E4. Analytic advances narrow regions without closing the strip

Recent explicit zero-free regions near \(\Re(s)=1\) improve analytic control for specified heights [S4]. They do not exclude zeros from the whole critical strip. A zero-free region and a critical-line theorem have different targets; conflating them is a common route from a genuine advance to an invalid RH claim.

### E5. Recent proof claims require audit

Repository claims found during the survey make cross-disciplinary mappings from physical models, econometric representations, probabilistic arguments, or finite computation to RH. Such work may be an interesting conjectural program. Its self-declared conclusion is not proof evidence until an exact map is defined, a theorem applies with verified hypotheses, no circular assumption is imported, and all unbounded quantifiers are closed.

## Accepted research gaps

| Gap ID | Accepted gap | Why it blocks a proof | Downstream requirement |
|---|---|---|---|
| G1 | Finite checks do not exclude an off-line zero at unbounded height. | RH has an infinite universal quantifier. | Maintain a tail-exclusion obligation. |
| G2 | Equivalent criteria hide all-index or all-test-function requirements. | Reformulation can conceal the hard step. | Encode quantifiers in a proof-obligation graph. |
| G3 | Claimed breakthroughs can use an unproved external-model bridge. | Theorem transfer requires a hypothesis-preserving map. | Audit every bridge and reject circular closure. |
| G4 | Numerical output is theorem-grade only with error and completeness certificates. | High precision alone is not a proof. | Use interval bounds and independent verifiers. |

## Survey handoff

The Idea Agent may propose formal derivations and future certified computations. It must not report a proof, a new zero computation, or a breakthrough result. Every recent proof declaration remains a named audit target until all proof obligations are independently discharged.
