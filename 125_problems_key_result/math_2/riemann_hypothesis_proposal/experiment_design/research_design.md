# ExperimentDesign Agent: ProofBridge Mathematical Research Design

## Boundary

**Execution policy: DESIGN_ONLY.** This design contains proposed formal derivations, proof obligations, and future certificate checks. It does not prove RH, evaluate a new Li coefficient, verify a new zeta zero, run code, or report observed mathematical results.

## Research brief

The target is the universal statement that every nontrivial zero of the completed Riemann xi function lies on \(\Re s=1/2\). The selected Idea Agent direction uses Li's criterion as an exact equivalence target. The intended contribution is an auditable route that can distinguish a complete proof from (i) a finite theorem, (ii) a conditional theorem, and (iii) an unverified claimed proof.

Define
\[
\xi(s)=\frac12s(s-1)\pi^{-s/2}\Gamma(s/2)\zeta(s).
\]
For positive integers \(n\), the proposed formal definition is
\[
\lambda_n=\frac{1}{(n-1)!}\left.\frac{d^n}{ds^n}\left[s^{n-1}\log\xi(s)\right]\right|_{s=1}.
\]
Li's criterion supplies the target equivalence
\[
\mathrm{RH}\quad\Longleftrightarrow\quad \lambda_n\ge0\ \text{for every}\ n\ge1.
\]
This expression is a proof target, not a claimed derivation in this project. Any formal library statement of the criterion must include its exact analytic hypotheses and the convention used for summing over zeros.

## Proof-obligation graph

| ID | Obligation | Acceptable evidence | Failure condition |
|---|---|---|---|
| O1 | Define zeta continuation, xi entire extension, and zero multiset. | Formal theorem or independently checked analytic proof. | Hidden pole, multiplicity, or domain assumption. |
| O2 | Establish functional equation and zero symmetries. | Formal derivation from completed xi properties. | Symmetry asserted but not derived. |
| O3 | State and formalize Li equivalence with all quantifiers. | Theorem statement with cited provenance and proof check. | Only a finite or heuristic positivity statement. |
| O4 | Certify finite contribution up to height \(T\). | Complete zero enumeration, interval enclosures, multiplicities, and independent checker. | Floating-point values or incomplete zero count. |
| O5 | Bound the remainder \(R_n(T)\) uniformly for all required \(n\). | Non-circular analytic theorem with constants and domains. | Bound assumes RH or covers only fixed \(n\) or fixed \(T\). |
| O6 | Exclude all off-line zeros or establish all Li positivity. | O1--O5 proved and logically composed. | Any `GAP`, conditional edge, or unstated limit passage. |
| O7 | Audit claimed breakthrough bridge. | Defined map, theorem hypotheses, exact implication, and independent review. | Analogy, dimensional mismatch, or imported conclusion. |

## Finite-plus-tail decomposition

For a symmetric truncation convention, the future proof environment may write a Li coefficient as
\[
\lambda_n=\Lambda_n(T)+R_n(T),
\]
where \(\Lambda_n(T)\) is computed from rigorously isolated zero data with \(|\Im\rho|\le T\), and \(R_n(T)\) contains every remaining zero contribution and any analytically equivalent remainder term. This notation deliberately refuses to hide the difficult part. A certificate for \(\Lambda_n(T)\ge0\) is not a certificate for \(\lambda_n\ge0\) unless O5 supplies a lower bound for \(R_n(T)\) adequate for the stated \(n\). A proof of finitely many \(n\) is not a proof of all \(n\).

## Proposed formal and computational work packages

### WP1: formal analytic backbone

In a proof assistant, encode the domain of \(\zeta\), analytic continuation facts imported from trusted libraries or separately proved lemmas, the completed xi function, and the functional equation. Each imported result has a versioned theorem identifier. The output is `PROVED` only if the system kernel checks the theorem; prose derivations remain `AUDITABLE_DRAFT`.

### WP2: exact Li-object specification

Specify the derivative definition, zero-sum representation, truncation order, zero multiplicity convention, and real-valuedness statement. Prove that the two representations used by a future certificate agree on their stated domain. This prevents a claim from switching formulas where numerical stability or convergence is convenient without proving equivalence.

### WP3: certified finite layer

If a future computation is authorized, it must use interval arithmetic, an argument-principle or equivalent completeness count, explicit truncation error, and two independently implemented verifiers. Inputs include a bounded height \(T\), maximum coefficient index \(N\), precision policy, and source code hash only at release time. Outputs are a finite theorem of the form: all enumerated zeros in the stated region satisfy the stated enclosure; all computed \(\lambda_n\) for \(1\le n\le N\) satisfy stated interval bounds. No output may use the label RH.

### WP4: tail theorem and obstruction analysis

The central research risk is O5. The planned analysis tries to prove a theorem that controls the unobserved contribution uniformly over the needed index range without assuming RH, zero-free critical-line information, or a criterion equivalent to RH. If this is not achieved, ProofBridge publishes an obstruction statement that identifies the exact remaining assumption. This is a valuable mathematical result only if the obstruction itself is proven; otherwise it is a diagnosis.

### WP5: audit of recent breakthrough claims

Each claim is converted into a graph. For every external-model bridge, the audit asks: What are the source and target objects? Is the map defined on the full zero set? Does it preserve the property used in the next theorem? Are all theorem hypotheses established? Does the final symmetry argument exclude both half-planes without smuggling in the desired zero-free region? Does finite verification appear only as a finite lemma? The claim remains `UNVERIFIED_CLAIM` unless every question receives a proof-backed answer.

## Decision rules

| Future outcome | Permitted label | Prohibited label |
|---|---|---|
| O1--O4 pass for stated \(T,N\); O5 open | Certified finite result | RH proved |
| O5 holds only under an extra conjecture | Conditional theorem | Unconditional RH proof |
| O5 is proved but only for finitely many \(n\) | Finite-index theorem | Li criterion established globally |
| Every O1--O6 edge is formally checked | Candidate complete proof pending expert verification | Automatically recognized proof |
| O7 exposes missing map or circularity | Claim audit finding | Disproof of RH or of the claim's author |

## Human review and safety

All key theorems, formalization imports, interval-arithmetic libraries, and claimed-proof audits require qualified analytic-number-theory review. A proof assistant can validate formal steps but cannot decide whether a human statement was formalized with the intended meaning. Code review must be independent of the code author. No live computational work has been performed in this design.
