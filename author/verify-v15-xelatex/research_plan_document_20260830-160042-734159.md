# AANEC-Relaxed Trapped Surface Theorem and Stellar Mass-Gap Derivation

**Keywords:** Averaged Null Energy Condition, trapped surface, compactness threshold, black hole remnants, stellar collapse, mass gap, global hyperbolicity, Raychaudhuri equation

## Abstract

This research proposes a qualified AANEC-relaxed trapped-surface theorem for spherically symmetric stellar collapse, replacing pointwise energy conditions with the Averaged Null Energy Condition and an explicit averaged null-convergence assumption. The central contribution is a formal derivation linking Misner-Sharp compactness to trapped-surface formation via Raychaudhuri-type focusing, thereby excluding stable non-black-hole remnants above a model-dependent compactness threshold. This theoretical framework addresses the tension between classical singularity theorems and quantum field violations by leveraging the robustness of AANEC, which lacks known physically reasonable counterexamples in standard curved spacetimes. The proposed work remains an unverified formal conjecture, pending the resolution of mathematical definitions for the explicit averaged focusing condition and the stability predicates for exotic compact objects.

Crucially, the observed lower stellar mass gap is treated not as a direct prediction of the theorem, but as an astrophysical consistency constraint subject to confounding mechanisms such as supernova explosion energetics, fallback, and binary evolution. The study outlines a formal proof strategy that identifies candidate counterexamples, such as regular black hole models, which must satisfy all assumptions including global hyperbolicity and complete null generators to falsify the exclusion bound. Expected outcomes are designed to distinguish whether the compactness threshold is a universal geometric feature of AANEC-satisfying matter or a boundary condition sensitive to exotic stress-energy configurations. The transition to subsequent sections involves the rigorous definition of the compactness parameter and the closure of specific proof obligations regarding the averaged focusing condition.

## Introduction

### The Collapse of Pointwise Conditions

Classical singularity theorems, including Penrose's trapped-surface result, rely on pointwise energy conditions to guarantee that null geodesic congruences focus. However, quantum field theory systematically violates these pointwise constraints; phenomena such as the Casimir effect demonstrate that energy density can be locally negative. This creates a foundational tension: the mathematical assumptions driving singularity formation do not hold universally for realistic matter. The proposed research addresses this by relaxing the strict pointwise Null Energy Condition to the Averaged Null Energy Condition (AANEC). While AANEC provides a more robust physical baseline that may survive semiclassical corrections, the upstream formal reasoning identifies a critical gap: AANEC alone is insufficient to guarantee the local or integrated focusing required for trapped-surface formation. Consequently, the proposal introduces an explicit, independent averaged null-convergence condition as a necessary geometric hypothesis to bridge this logical gap. [@cite_0ed84243cf171bc4]

### Mechanism Replacement and Formal Scope

The central contribution is a mechanism replacement that derives a trapped-surface threshold via Raychaudhuri-type focusing, governed by the AANEC and the added averaged focusing condition. This formal chain is intended to bound stable non-black-hole remnants through TOV-like stellar-structure assumptions, establishing a model-dependent compactness threshold. The scope of this formal theorem is strictly restricted to classical general relativity, spherically symmetric collapse, and regular matter fields. It is explicitly separated from the astrophysical inference of the observed 2-5 solar mass gap. The observed gap is treated as an astrophysical consistency constraint rather than a direct prediction of the theorem, acknowledging that explosion energetics, fallback, and equation-of-state uncertainties are the dominant drivers of remnant demographics. By decoupling the formal geometric bound from the messy astrophysical reality, the proposal maintains rigorous claim discipline while addressing the theoretical limits of singularity formation. [@cite_7a407c865faafd11] [@cite_c369df652181e8f7]

### Claim Separation Matrix

| Domain | Formal Theorem (P1, P2) | Astrophysical Inference (Mass Gap) |
|---|---|---|
| **Primary Driver** | AANEC + Explicit Averaged Focusing | Explosion Energetics + EOS + Fallback |
| **Key Variable** | Misner-Sharp Compactness (C) | Progenitor Mass + Metallicity |
| **Failure Mode** | Counterexample satisfying all A1-A6 | Continuous mass distribution observed |
| **Status** | Proposed / Unverified | Design Assumption / Consistency Constraint |

### Transition to Formalization

The viability of the proposed mechanism rests on the rigorous definition of the added averaged focusing condition and the Misner-Sharp compactness parameter. The current upstream reasoning identifies these as unresolved dependencies requiring human input. The subsequent section will formalize these definitions and establish the specific proof obligations necessary to evaluate whether the AANEC-relaxed framework successfully excludes stable exotic compact objects without violating the boundary conditions of spherical symmetry and global hyperbolicity.

## Background, Survey, and Research Gap

### Theoretical Foundations and the Energy Condition Bridge

The formal derivation proposed in this route rests on a specific relaxation of classical energy conditions, motivated by the recognized incompatibility between pointwise positivity and quantum field effects. Survey evidence establishes that pointwise energy conditions are systematically violated by quantum fields, necessitating weaker statements such as quantum energy inequalities or averaged energy conditions for broader validity. This background supports the transition from standard Null Energy Condition assumptions to the Averaged Null Energy Condition (AANEC). However, the survey also highlights a critical unresolved bridge: while AANEC is a candidate for a universal property of gravitating matter, its satisfaction alone may not imply the local or integrated focusing required for Penrose-type trapped-surface formation. The proposed mechanism therefore introduces an explicit averaged null-convergence/focusing condition as an independent geometric hypothesis, rather than assuming it follows from AANEC. This distinction is vital because the mathematical form of this additional condition remains undefined in the current design, creating a primary gap between the physical motivation and the formal proof obligation. [@cite_0ed84243cf171bc4]

### Alternative Mechanisms and Boundary Variables

The observed stellar mass gap between approximately 2 and 5 solar masses is often cited as a potential discriminator for black-hole formation thresholds. However, survey synthesis indicates that this empirical feature is not uniquely determined by general-relativistic compactness bounds. Alternative explanations dominate the astrophysical inference chain: the gap's location and sharpness may arise from maximum neutron-star mass limits, supernova explosion energies, fallback dynamics, rotation, magnetic fields, binary evolution, or pair-instability processes. For instance, the location of the lower edge of the black-hole mass gap is dictated by near-final core mass, which is robust against variations in metallicity but sensitive to explosion energetics. Consequently, the survey identifies a gap in the 'boundary_variable' slot: no single source currently isolates a geometric compactness threshold that cleanly separates black holes from non-black-hole remnants without confounding stellar-physics mechanisms. This lack of a clean boundary variable means that the proposed theorem must be treated as a restricted mathematical result, not a direct explanation of the observed mass distribution. [@cite_7a407c865faafd11]

### Observational Inference Chains and Qualifications

Observational proxies for black-hole formation rely on dynamical mass measurements and gravitational-wave population inference, both of which impose qualifications on the theoretical claims. Gravitational-wave data alone for binary neutron star candidates cannot definitively rule out objects more compact than neutron stars, such as black holes or quark stars, despite component masses consistent with neutron stars. This limitation underscores that observational 'gaps' are often statistical depletions rather than hard physical walls. Furthermore, the derived mass distributions remain sensitive to uncertainties in explosion and unbinding energies across different progenitor masses, leaving key physical parameters unconstrained. These observational ambiguities reinforce the need for a formal theorem that operates independently of stellar-evolution uncertainties, but they also warn against over-interpreting the theorem's relevance to the observed 2-5 solar mass gap. The gap may be a consequence of supernova engine physics rather than a direct manifestation of the proposed AANEC-based trapped-surface threshold. [@cite_07d6df5d6978a1fc]

### Research Gap Synthesis and Missing Premises

| Gap Category | Missing Premise | Impact on Formal Argument |
| :--- | :--- | :--- |
| Formal Claim | Mathematical form of A5 (explicit averaged focusing) | Prevents verification of whether AANEC + A5 implies trapped-surface formation (PO1 unresolved). |
| Boundary Variable | Isolation of geometric compactness from stellar physics | Mass-gap inference remains non-discriminating; alternative explanations (explosion energy) cannot be ruled out. |
| Definition | Formal definition of Misner-Sharp compactness C | Prevents precise calculation of the threshold C_max required for stable remnant exclusion (D4 needs_human_input). |

### AANEC Integral Formulation

\int_{\lambda_1}^{\lambda_2} T_{ab} k^a k^b d\lambda \ge 0 [@cite_0ed84243cf171bc4]

### Transition to Formal Definitions

The synthesis above establishes that the proposed contribution relies on a two-step relaxation: first, replacing pointwise energy conditions with AANEC to accommodate quantum violations; and second, adding an explicit averaged focusing condition to restore the trapped-surface proof. However, the survey reveals that the mathematical specification of this second step is missing, as is the precise definition of the compactness parameter C. These gaps prevent the immediate closure of proof obligations PO1 and PO3. The next section must therefore define the symbol domains and formal assumptions required to bridge the gap between the averaged energy condition and the geometric focusing threshold, explicitly acknowledging that the stability predicate for non-black-hole remnants remains a design assumption rather than a derived consequence.

## Research Questions and Planned Contributions

### Research Questions and Scope

This section states the operational research questions and the planned contributions that the later argument operationalizes. The central question is whether replacing pointwise energy conditions with the Averaged Null Energy Condition (AANEC) and an explicit averaged null-convergence/focusing assumption yields a rigorous trapped-surface theorem for spherically symmetric stellar collapse. A secondary question examines whether this geometric bound can exclude stable non-black-hole remnants above a model-dependent compactness threshold. The contribution is scoped strictly to classical General Relativity with regular matter fields and global hyperbolicity. It explicitly rejects the premise that this theorem quantitatively derives the observed 2-5 solar mass gap, which is treated instead as an astrophysical consistency constraint subject to alternative stellar-physics explanations such as explosion energetics and binary evolution. [@cite_0ed84243cf171bc4]

### Planned Contributions and Decision Matrix

The planned contributions are structured as a decision matrix linking formal derivations to counterexample searches. This matrix clarifies how the theoretical work interacts with the proposed geometric bounds.

| Contribution Target | Required Formal Evidence | Failure Condition |
|---------------------|--------------------------|-------------------|
| AANEC-Relaxed Trapped Surface Theorem | Closure of Raychaudhuri focusing and compactness threshold derivations | AANEC satisfied but explicit averaged focusing condition fails |
| Exclusion of Stable Non-Black-Hole Remnants | Consistency check against bounded compactness or TOV-like limits | Existence of a stable ultra-compact object satisfying all geometric assumptions without forming a trapped surface |

### Unresolved Items Delimiting the Questions

The scope of these questions is delimited by several unresolved formal definitions that require human input. Specifically, the exact mathematical form of the explicit averaged null-convergence condition that distinguishes it from standard AANEC remains undefined, as does the formal definition of the Misner-Sharp compactness parameter for the specific metric class under consideration. Furthermore, the formal stability predicate for non-black-hole remnants must be defined to distinguish them from regular black hole models like Hayward or Bardeen. Until these definitions are resolved, it remains unknown whether candidate witnesses genuinely fail the averaged focusing condition or if the condition itself is ill-defined in the current context. Finally, the decision to conduct numerical verification of the Raychaudhuri equation for a discrete subset of test metrics remains an open design question.

## Idea Source Checkpoints and Direction Selection Audit

### Initial Scientific Attraction and Mechanism Replacement

The proposal originates from a mechanism replacement strategy designed to address the fragility of classical trapped-surface theorems when confronted with quantum stress-energy effects. Standard pointwise Null Energy Condition (NEC) assumptions are systematically violated by quantum fields, a tension that motivates the relaxation of these constraints to the Achronal Averaged Null Energy Condition (AANEC). However, the audit reveals that AANEC alone may be insufficient to guarantee the local or integrated focusing required for Penrose-type singularity theorems. The initial scientific attraction lies in bridging this gap by introducing an explicit averaged null-convergence/focusing assumption alongside AANEC. This approach aims to derive a model-dependent compactness threshold that forces trapped-surface formation, thereby excluding stable non-black-hole remnants above a specific mass scale. The direction is selected not as a replacement for stellar-evolution explanations, but as a rigorous formal boundary condition for classical general relativity under averaged energy constraints. [@cite_0ed84243cf171bc4]

### Checkpoint Audit and Defect Exposure

| Audit Dimension | Checkpoint Observation | Implication for Direction Selection |
| :--- | :--- | :--- |
| **Formal Definition** | Misner-Sharp compactness (D4) and averaged focusing (A5) lack explicit mathematical forms. | The theorem remains a conjecture; rigorous derivation is blocked until symbolic definitions are human-confirmed. |
| **Counterexample Status** | Candidate witnesses (CE1, CE2) evade trapped surfaces but fail A5 or A6. | The direction is retained because no valid counterexample satisfies all assumptions; the defect exposes a need for stricter stability predicates. |
| **Empirical Scope** | Observed 2-5 solar mass gap is treated as an astrophysical consistency constraint. | The proposal correctly separates formal GR bounds from supernova engine physics, avoiding unsupported causal claims. |

### Qualified Retention and Explicit Exclusions

The selected direction is retained with the qualification that it constitutes an unverified formal conjecture rather than a proven theorem. The primary defect exposed by the audit is the reliance on undefined geometric hypotheses (A5) and compactness parameters (D4), which prevents the closure of proof obligations PO1 and PO2. Consequently, the proposal explicitly excludes any quantitative derivation of the observed stellar mass gap, acknowledging that explosion energetics, fallback, and equation-of-state uncertainties remain dominant astrophysical explanations. The contribution is limited to establishing a logical dependency: if the averaged focusing condition holds, then stable ultra-compact objects are excluded within the restricted model class. This transition moves the research from speculative mechanism replacement to a formal counterexample search, where the next stage must rigorously test whether AANEC plus A5 yields a trapped surface or admits a witness that satisfies all assumptions while evading collapse.

## Problem Definition, Assumptions, and Hypotheses

### Scope and Admissible Domain

This section fixes the formal problem addressed by the route: whether a trapped-surface/compactness bound for stable non-black-hole stellar remnants can be established in classical general relativity when pointwise energy conditions are replaced by averaged conditions supplemented by an independent geometric focusing hypothesis. The admissible domain is restricted to spherically symmetric collapse of massive stars with isotropic pressure, regular matter fields, global hyperbolicity, and complete null generators in the relevant region. This scope is deliberately narrower than a general proof that massive stars form black holes, and it does not claim to quantitatively derive the observed 2-5 solar-mass gap. The gap is treated as an astrophysical consistency constraint that may instead be governed by explosion energetics, fallback, equation-of-state physics, pair-instability processes, rotation, magnetic fields, nonspherical dynamics, or binary evolution. The formal contribution is therefore a qualified theorem/conjecture whose validity domain must be stated before any derivation or counterexample search is attempted. [@cite_0ed84243cf171bc4] [@cite_72d7ff391b29c495] [@cite_7a407c865faafd11]

### Formal Object and Domain

**Definition.** Let g denote the spacetime metric, T the stress-energy tensor, k the tangent vector to a null geodesic congruence, theta the expansion scalar of that congruence, M the mass of the collapsing matter or remnant, r the areal radius, and C a Misner-Sharp-type compactness parameter defined on the chosen spherical metric class. The formal object of study is a pair (g, T) on a globally hyperbolic, spherically symmetric spacetime with isotropic pressure, together with a family of complete null generators k in the region where collapse is assessed. The problem is to decide whether, within this domain, the conjunction of AANEC, a separate averaged null-convergence/focusing condition, and a stable-equilibrium compactness bound entails a model-dependent threshold C_threshold (equivalently M_threshold) above which a trapped surface must form and stable non-black-hole remnants are excluded. The definition of C and the precise mathematical form of the averaged focusing condition are unresolved upstream dependencies; they are declared here as required inputs, not as established formulas.

### Numbered Problem Relation

$$
int_{lambda_1}^{lambda_2} T_{ab} k^a k^b dlambda >= 0
$$ [@cite_0ed84243cf171bc4]

### Reading of the Relation and Its Limits

The displayed relation states the Averaged Null Energy Condition along a null generator segment parameterized by affine parameter lambda. It is included to fix the energy-condition input of the problem, not to assert that this condition alone yields focusing. AANEC controls an integral of the null-null component of the stress-energy tensor, whereas a Raychaudhuri-type trapped-surface argument requires a sign condition on the integrated Ricci term and, ultimately, a negative expansion of the outgoing congruence. The route therefore separates two hypotheses: AANEC, which supplies averaged positivity of T_{ab} k^a k^b, and an explicit averaged null-convergence/focusing condition, which must be stated independently and is not treated here as a consequence of AANEC. This separation is essential because quantum stress-energy may violate pointwise energy conditions while satisfying averaged or inequality-constrained versions, and because AANEC alone may not provide the local or integrated focusing needed for Penrose-type arguments. [@cite_0ed84243cf171bc4]

### Assumption Ledger for This Route

A1 (user-declared): classical general relativity with spherically symmetric collapse and isotropic pressure. A2 (user-declared): matter satisfies AANEC along complete null generators. A3 (user-declared): spacetime is globally hyperbolic and sufficiently regular for trapped-surface arguments. A4 (user-declared): null generators in the relevant region are complete. A5 (user-declared, mathematically unresolved): an explicit averaged null-convergence/focusing condition holds along the relevant generators; this is an independent geometric hypothesis, not a consequence of A2 alone. A6 (user-declared): non-black-hole remnants are modeled as stable equilibrium objects obeying a bounded compactness or TOV-like limit. The status of A5 and of the compactness definition required by A6 is a design dependency: without a closed mathematical form for A5 and a precise definition of C, the problem is well-posed only at the level of a proposed criterion, not a verified theorem.

### Decision Matrix for Failure Conditions

| Condition | Consequence for the formal problem | Required response before derivation |
|---|---|---|
| A5 remains undefined or is shown to follow from A2 | The proposed focusing step lacks an independent premise or collapses into the AANEC-only case | Supply or rule out an explicit averaged convergence inequality |
| AANEC holds but pointwise/quantum violations prevent local focusing | Raychaudhuri-based trapped-surface inference is not licensed | Restrict domain to regimes where integrated focusing is guaranteed |
| Null generators are incomplete | Completeness premise fails | Exclude the region or redefine the generator family |
| Stable remnant predicate is circular with compactness bound | Counterexample search becomes definitional | State stability independently of the threshold |
| Observed mass gap is dominated by stellar-engine physics | Formal bound is not a mass-gap explanation | Keep theorem and astrophysical inference separate | [@cite_0ed84243cf171bc4] [@cite_7a44e6730c44cb39] [@cite_c369df652181e8f7]

### Proposed Problem Statement

**Proposition (proposed).** Proposed proposition P1: In spherically symmetric stellar collapse satisfying AANEC, global hyperbolicity, regular matter fields, complete null generators, and an explicit averaged null-convergence/focusing condition, reaching a model-dependent compactness threshold forces trapped-surface formation. Proposed proposition P2: Stable non-black-hole remnants above a compactness-dependent mass scale are excluded within the restricted model class defined by AANEC and averaged focusing. These are candidate formalizations, not proved results. The proof obligations are: (i) state A5 as a precise inequality involving T, k, and theta; (ii) define C on the chosen metric class; (iii) derive the integrated Raychaudhuri step from A1-A5; (iv) connect trapped-surface formation to the stable-equilibrium bound in A6; and (v) search for a witness satisfying all assumptions while evading a trapped surface. Counterexample criteria are equally part of the problem: a valid counterexample must satisfy A1-A6 simultaneously, not merely violate the conclusion by stepping outside the declared domain.

## Study Design and Methods

### Protocol Scope and Unit of Analysis

This proposal adopts a formal mathematics and theoretical physics design in which the unit of analysis is a structured search over proof obligations and candidate counterexamples. The protocol does not execute numerical simulations, hardware tests, clinical interventions, or field observations. Instead, it evaluates whether the proposed AANEC-relaxed trapped-surface theorem and its stellar remnant corollary remain internally consistent when restricted to spherically symmetric, non-rotating collapse with isotropic pressure. The methodological focus is on maintaining a strict boundary between formal geometric reasoning and astrophysical inference. While the formal theorem targets the existence of trapped surfaces under averaged focusing conditions, the observed lower stellar mass gap is treated exclusively as an astrophysical consistency constraint rather than a direct consequence of the theorem. This separation prevents the conflation of mathematical bounds with the complex, confounder-dominated dynamics of stellar evolution, ensuring that any astrophysical gaps remain subject to alternative explanations such as explosion energetics or binary interactions.

### Formal Dependency and Averaged Focusing

The core derivation relies on replacing pointwise energy conditions with the Averaged Null Energy Condition (AANEC). As noted in the literature, pointwise energy conditions are systematically violated by quantum fields, necessitating the use of weaker averaged statements for broader validity (W3009127927). However, AANEC alone is insufficient to guarantee the local or integrated focusing required for Penrose-type trapped-surface formation. The protocol therefore introduces an explicit averaged null-convergence condition as an independent geometric hypothesis. Because the precise mathematical formulation of this condition and the Misner-Sharp compactness parameter are currently unresolved, the formal derivation is structured around specific proof obligations. The forward derivation posits that the expansion scalar of a null geodesic congruence becomes negative due to the averaged focusing condition, subsequently forcing trapped-surface formation when compactness exceeds a model-dependent threshold. These steps are proposed but unverified, pending the resolution of the formal definitions. [@cite_0ed84243cf171bc4]

### Counterexample and Boundary Analysis

| Decision Path | Condition to Evaluate | Methodological Action | Status |
| :--- | :--- | :--- | :--- |
| Witness Rejection | Candidate fails explicit averaged focusing (A5) | Discard as invalid counterexample; theorem remains unrefuted. | Proposed |
| Boundary Restriction | Candidate satisfies A5 but evades trapped surface | Restrict theorem scope to exclude the specific metric class. | Needs Human Input |
| Astrophysical Decoupling | Mass gap explained by explosion physics | Demote mass gap to a non-discriminating consistency check. | Design Assumption |

### Comparators, Ablations, and Robustness

To ensure the robustness of the proposed formal bounds, the design incorporates ablation checks against known alternative explanations and exotic compact object models. Candidate witnesses, such as regular black holes or highly compact horizonless objects, are evaluated to determine if they genuinely evade the averaged focusing assumptions or merely exploit ambiguities in the stability predicate. The protocol requires that any proposed counterexample must satisfy all declared assumptions, including global hyperbolicity and null generator completeness. Furthermore, the astrophysical application is stress-tested against confounders identified in the survey, such as rotation, magnetic fields, and pair-instability processes. If these astrophysical mechanisms can independently reproduce the observed remnant mass distribution without invoking the compactness bound, the explanatory relevance of the formal theorem is weakened, though the mathematical proposition itself remains unaffected.

### Artifacts, Reproducibility, and Human Decisions

The reproducibility of this theoretical proposal is contingent upon the rigorous documentation of the formal artifacts, including the exact metric classes, stress-energy tensor assumptions, and the precise mathematical definitions of the averaged focusing and compactness parameters. Currently, the data governance and measurement plans for these formal objects require human input to resolve ambiguities in the operational definitions. Without finalized definitions for the Misner-Sharp parameter and the explicit averaging condition, the proof obligations cannot be mechanically verified or refuted. Consequently, the release of any definitive formal claims is paused pending qualified human review of the underlying mathematical structures. This ensures that the proposed theorem is not published as established fact but rather as a clearly scoped conjecture with explicit dependencies on unresolved formal definitions.

## Expected Outcome Branches and Conditional Conclusions

### Interpreting the Proposed Bound

This section maps the conditional outcomes of the proposed AANEC-relaxed trapped-surface theorem without asserting that any result has been obtained. The incoming argument supplies two candidate propositions: a compactness threshold that forces trapped-surface formation, and the consequent exclusion of stable non-black-hole remnants above a model-dependent mass scale. These propositions remain unverified formal targets, and the present section treats their outcomes as decision rules rather than findings. A proof obligation on the averaged focusing assumption must be closed before either proposition can be elevated from a conjecture to a theorem. Until that obligation is discharged, every branch below is an expected consequence of the design, not an observation.

### Conditional Outcome Decision Matrix

| Decision | Trigger Condition | Interpretation | Next Action |
| --- | --- | --- | --- |
| Supports the mechanism | The averaged-focusing premise and compactness criterion jointly imply trapped-surface formation, and no admissible witness survives the assumption checks | The restricted theorem is internally consistent within the declared model class | Test the most consequential boundary condition and seek independent replication of the proof structure |
| Partial or heterogeneous | The implication holds only for a subset of admissible metrics, or the threshold depends sensitively on unstated structural parameters | The bound is conditional rather than universal | Predefine candidate moderators and improve coverage across metric families |
| Null or contradictory | A witness satisfies all assumptions yet evades the trapped-surface conclusion, or the derivation fails to close | The proposed mechanism does not support the exclusion claim in this design boundary | Audit construct validity and revise the mechanism or boundary claim |
| Uninformative or invalid | A required definition, such as the compactness parameter or the averaged-focusing form, remains unspecified | No scientific conclusion is warranted | Resolve the missing formal dependency before repeating the design |

### Boundary Consequences and Alternative Explanations

The supportive branch is narrow by construction. It licenses only the claim that, inside the restricted class of spherically symmetric, isotropic, globally hyperbolic spacetimes with complete null generators, the added averaged-focusing hypothesis can be made to cohere with a compactness threshold. This coherence does not extend to rotating, magnetized, or nonspherical collapse, nor to quantum stress-energy that violates averaged null positivity. The heterogeneous and null branches therefore carry the more informative load: they locate precisely where the proposed mechanism stops constraining the geometry. Candidate witnesses that evade the trapped-surface conclusion are treated as boundary diagnostics, not as established counterexamples, because their status depends on whether they genuinely satisfy the averaged-focusing premise. When that premise is ill-defined, the correct response is the invalid branch, not a substantive rejection of the theorem.

### Separating the Formal Bound from the Astrophysical Gap

A further consequence governs the relation between the formal proposition and the observed lower stellar mass gap. Even if the supportive branch is reached, the theorem does not by itself reproduce the gap; explosion energetics, fallback, equation-of-state physics, pair-instability processes, and binary evolution remain competing explanations that can populate or suppress the gap independently of any compactness bound. The mass-gap inference is therefore a consistency constraint rather than a prediction, and a demonstrated astrophysical model that reproduces the gap without a compactness bound would weaken the theorem's explanatory relevance without falsifying its formal content. This separation is the concrete transition to the next stage: the review ledger must now adjudicate which unresolved formal dependencies and which alternative-explanation risks are severe enough to block release of the proposed contribution. [@cite_7a407c865faafd11] [@cite_f634820e22d7a238] [@cite_fd0f77b2a173c0ab]

## Risks, Limitations, and Human Review Requirements

### Scope Boundaries and Alternative Mechanisms

The proposed formal theorem operates strictly within a classical general-relativistic model class defined by spherical symmetry, isotropic pressure, global hyperbolicity, and complete null generators. Its central risk is the conflation of this mathematical exclusion with astrophysical explanation. The observed 2-5 solar mass gap cannot be uniquely attributed to the compactness bound because explosion energetics, fallback, equation-of-state physics, pair-instability processes, and binary evolution independently regulate remnant masses. Furthermore, while quantum fields systematically violate pointwise energy conditions, necessitating averaged formulations like AANEC, the transition from averaged conditions to trapped-surface formation requires an explicit averaged null-convergence/focusing hypothesis. This additional assumption is not a consequence of AANEC alone, creating a logical gap where the theorem may fail if the focusing condition is unmet or if exotic compact objects evade the averaged-focusing assumptions without violating the underlying energy condition. [@cite_789b47fb0241d9ae] [@cite_7a407c865faafd11] [@cite_c369df652181e8f7] [@cite_cc5bc07a219047b4] [@cite_f634820e22d7a238] [@cite_0ed84243cf171bc4]

### Human-Review and Release Decision Matrix

| Decision Domain | Review Requirement | Release Condition |
|-----------------|--------------------|-------------------|
| Formal Reasoning Plan | Qualified human review of the entire proof strategy and counterexample search | Approval of the logical chain from AANEC to trapped-surface formation |
| Misner-Sharp Compactness (D4) | Human input required to specify the exact formula for effective mass within radius r | Definition verified against the chosen metric class |
| Averaged Focusing (A5) | Human input required to define the mathematical form distinguishing A5 from AANEC | Proof obligation PO1 closed for all admissible metrics |
| Stability Predicate (A6) | Human input required to distinguish stable non-black-hole remnants from regular black holes | Counterexamples CE1 and CE2 evaluated against the formal stability bound |
| Numerical Verification | Human decision required on whether to execute discrete metric tests for Raychaudhuri focusing | Resolution of open design questions regarding computational validation |

### Counterexample Validity and Design Consequences

The counterexample search identifies two boundary cases that challenge the exclusion of high-compactness remnants. CE1 proposes a hypothetical static, spherically symmetric metric that satisfies AANEC but potentially violates the explicit averaged focusing condition (A5). Because A5 lacks a formal mathematical definition, it remains unknown whether CE1 genuinely evades the theorem or merely exposes an ill-defined premise. CE2 considers regular black hole models, such as the Hayward or Bardeen metrics, which satisfy energy conditions and lack singularities. However, these models typically contain trapped surfaces, classifying them as black holes rather than the stable non-black-hole remnants targeted by the exclusion claim. Resolving these ambiguities requires human review to determine whether the failure of these witnesses stems from a violation of the independent focusing constraint or a definitional conflict regarding stability bounds. Until these formal definitions are locked, the theorem remains a proposed conjecture rather than a verified result.

### Transition to Next Stage

**Human-review checklist.** Before advancing to the formal derivation and experimental design phases, the following prerequisites must be satisfied:
1. Finalize the mathematical definition of the Misner-Sharp compactness parameter C for the specific metric class.
2. Specify the explicit averaged null-convergence/focusing condition A5 and verify its independence from AANEC.
3. Formally define the stability predicate A6 to exclude regular black holes from the non-black-hole remnant category.
4. Determine whether numerical verification of the Raychaudhuri equation is required for a discrete subset of test metrics.

## Definitions, Propositions, and Proof Obligations

### Scope and Symbolic Conventions

This section fixes the compactness, symbol-domain, and threshold conventions that the remaining theory routes cite rather than redefine. The model class is deliberately narrow: classical general relativity on a spherically symmetric, globally hyperbolic spacetime with isotropic pressure, where the relevant null generators are complete and the matter content obeys the averaged null energy condition. Two independent geometric inputs are declared rather than derived. The first, AANEC, is an integral positivity statement on the stress-energy tensor along null directions. The second, the averaged null-convergence condition, is a proposed focusing hypothesis on the expansion scalar of the congruence; it is treated as an additional assumption and not as a consequence of AANEC alone. The literature on energy conditions in quantum field theory motivates this separation, because pointwise positivity fails generically for realistic fields and only averaged or inequality-bounded statements survive in the semiclassical regime (W3009127927). Accordingly, every threshold below is model-dependent and conditional on the simultaneous closure of the proof obligations listed at the end of this ledger. [@cite_0ed84243cf171bc4]

### Definition Ledger and Symbol Domains

**Definition.** The following table assigns each symbol a domain and a status. Entries marked 'candidate formalization' are usable as working conventions; entries marked 'needs human input' are placeholders whose precise form is a proof obligation, not a settled fact. The Misner-Sharp compactness C is the central unresolved symbol: the paper's threshold claims depend on it, yet the supplied record does not fix the effective-mass formula or the metric gauge from which it is drawn, so C must not be evaluated numerically until its definition is confirmed.

### Averaged Null Energy Condition

$$
int_{-infty}^{+infty} T_{ab} k^{a} k^{b} d lambda >= 0
$$ [@cite_0ed84243cf171bc4]

### Reading the AANEC Relation

Equation (1) states the averaged null energy condition along a complete null generator with tangent k^{a} and affine parameter lambda. It constrains the integrated projection of the stress-energy tensor onto the null direction but says nothing directly about the pointwise sign of T_{ab}k^{a}k^{b}, which may be negative on finite segments. This is precisely why AANEC cannot, on its own, guarantee the local focusing needed for a trapped surface, and why the averaged null-convergence condition is carried as a separate premise. The convention adopted here is that lambda ranges over the full generator, consistent with the completeness assumption A4. [@cite_0ed84243cf171bc4]

### Proposed Compactness-Threshold Convention

$$
P2 : exists a stable non-black-hole remnant with C >= C_{max}  =>  false
$$

### Threshold as a Convention, Not a Computed Bound

Equation (2) fixes the logical form of the exclusion claim rather than its numerical content. The quantity C_{max} is a model-dependent threshold whose value is inherited from the averaged-focusing chain developed in the forward-derivation route; this ledger only records that any exclusion must be expressed as a comparison between the Misner-Sharp compactness C and such a bound. Because the definition of C is unresolved, C_{max} cannot be evaluated here, and the relation is proposed rather than established. The convention also separates the formal bound from the astrophysical 2-5 solar-mass gap: the latter is treated as an external consistency constraint that may be reproduced by explosion energetics, fallback, equation-of-state physics, rotation, magnetic fields, nonspherical dynamics, or binary evolution, none of which are encoded in equation (2).

### Proposed Propositions

**Proposition (proposed).** Proposition P1 (trapped-surface threshold). In spherically symmetric stellar collapse satisfying AANEC, global hyperbolicity, regular matter fields, complete null generators, and the explicit averaged null-convergence/focusing condition, reaching a model-dependent compactness threshold forces trapped-surface formation. Proposition P2 (remnant exclusion). Stable non-black-hole remnants above a compactness-dependent mass scale are excluded within the restricted model class defined by AANEC and averaged focusing. Both statements are candidate formalizations, not established theorems. P1 is the mechanism claim; P2 is the consequence drawn by combining P1 with the TOV-like stability premise A6. The dependency is one-directional: P2 inherits every failure mode of P1, and neither is asserted beyond the declared model class.

### Failure Conditions and Decision Matrix

| Premise or condition | Decision | Consequence for P1 and P2 |
|---|---|---|
| AANEC (A2) violated along a generator | Restrict | Focusing chain loses its energy input; threshold unsupported |
| Averaged null-convergence (A5) fails or is ill-defined | Withhold | P1 cannot be derived; P2 inherits the gap |
| Null generators incomplete (A4 fails) | Restrict | Integrated averaging in equation (1) is undefined |
| Global hyperbolicity or regularity (A3) fails | Withhold | Trapped-surface argument loses its causal footing |
| Object nonspherical, rotating, or anisotropic | Out of scope | Outside the declared model class; not a counterexample |
| Stability premise (A6) not satisfied | Out of scope | Exclusion claim P2 does not apply to the object |
| A witness satisfies A1-A6 yet forms no trapped surface | Reject | P1 and P2 are falsified within the model class |

### Proof Obligations Owned by This Ledger

1. PO1 (focusing form). Supply the explicit mathematical form of the averaged null-convergence condition A5 and show it is distinct from, and not implied by, AANEC. Until this is closed, no candidate witness can be checked against the focusing premise, and the status of any proposed counterexample remains unresolved.
2. PO2 (metric regularity). Fix the gauge and regularity conditions on the metric g under which trapped-surface identification is valid, ensuring compatibility with global hyperbolicity A3.
3. PO3 (compactness definition). Provide the Misner-Sharp effective-mass formula for the chosen metric and define C and C_{max} precisely, so that the threshold in equation (2) becomes computable.
4. Counterexample boundary. The proposed witnesses in the upstream record are classified as boundary cases only because A5 is undefined; they are not validated counterexamples. A valid refutation must satisfy every premise A1-A6 simultaneously while evading trapped-surface formation, a condition that cannot be adjudicated until PO1 and PO3 close.

### Transition to the Derivation Route

With the symbol domains, the AANEC relation, and the threshold convention fixed, the burden shifts to the forward-derivation route, which develops the Raychaudhuri-type focusing chain from equation (1) and the averaged null-convergence premise, and to the counterexample route, which tests whether any admissible metric can satisfy A1-A6 while evading a trapped surface. The unresolved items PO1 and PO3 are the handoff points: the derivation may proceed symbolically, but no numerical threshold or validated counterexample may be reported until the compactness definition and the focusing form are supplied.

## Forward Derivation and Counterexample Search Plan

### Derivation Architecture and Premise Scope

The forward derivation constructs a logical chain from relaxed energy conditions to a compactness-dependent exclusion of stable non-black-hole remnants. Unlike classical Penrose-Hawking theorems that rely on pointwise Null Energy Condition (NEC) violations, this route adopts the Averaged Null Energy Condition (AANEC) as the primary matter constraint. However, AANEC alone is insufficient to guarantee local focusing; therefore, the argument introduces an explicit averaged null-convergence condition (A5) as an independent geometric hypothesis. This distinction is critical: AANEC controls the integral of stress-energy along complete null generators, while A5 controls the convergence of the expansion scalar theta. The derivation proceeds through four proposed steps (S1-S4), moving from Raychaudhuri-type focusing to trapped-surface identification, then to consistency checks against TOV-like stability limits, and finally to the exclusion bound. This structure separates formal theorem work from astrophysical mass-gap inference, treating the latter as a consistency constraint rather than a direct prediction. [@cite_0ed84243cf171bc4]

### Proposed Raychaudhuri Focusing Obligation

$$
d theta / d lambda = - 1/2 theta^2 - sigma_ab sigma^ab + omega_ab omega^ab - R_ab k^a k^b
$$

### Interpretation of Focusing Conditions

The equation above represents the Raychaudhuri equation for a null geodesic congruence with tangent vector k^a. In the spherically symmetric, non-rotating model class defined by assumption A1, the twist tensor omega_ab vanishes. The proposed derivation step S1 requires that the explicit averaged null-convergence condition (A5) ensures the term R_ab k^a k^b remains sufficiently positive to drive the expansion scalar theta negative within finite affine parameter lambda. This is distinct from standard AANEC (A2), which only guarantees the integral of T_ab k^a k^b is non-negative. The proof obligation PO1 remains unresolved because the precise mathematical form of A5 that bridges the gap between averaged energy positivity and local focusing is not yet formally specified in the input. Without closing PO1, the transition from S1 to S2 (trapped surface formation) cannot be rigorously established. [@cite_0ed84243cf171bc4]

### Proposed Exclusion Theorem (P2)

**Proposition (proposed).** Stable non-black-hole remnants above a compactness-dependent mass scale are excluded within the restricted model class defined by AANEC, global hyperbolicity, and explicit averaged focusing.

### Counterexample Decision Matrix

| Witness ID | Assumption A5 (Averaged Focusing) | Assumption A6 (Stable Remnant) | Validity Status | Decision Consequence |
| :--- | :--- | :--- | :--- | :--- |
| CE1 (High-C Regular) | Violated | Ambiguous | Boundary Case | Reject as counterexample; supports theorem if A5 is necessary |
| CE2 (Regular BH) | Unknown | False (Contains Horizon) | Invalid | Out-of-domain; does not negate P2 (non-BH exclusion) |

The decision matrix distinguishes between genuine falsifiers and definition conflicts. Witness CE1 is a hypothetical static, spherically symmetric metric with high compactness C approaching 1. It is constructed to evade trapped surfaces. However, if it evades them while satisfying AANEC, it likely violates the independent A5 focusing constraint. If A5 is violated, CE1 is not a valid counterexample to the theorem as stated. Witness CE2 represents regular black hole models (e.g., Hayward/Bardeen). These typically contain horizons (trapped surfaces), meaning they are black holes, not 'non-black-hole remnants.' Thus, CE2 fails assumption A6 and does not challenge the exclusion of non-black-hole objects.

### Failure Conditions and Limitations

- The theorem fails if AANEC is satisfied but the explicit averaged null-convergence condition (A5) does not imply local focusing due to quantum stress-energy effects or non-minimal couplings.
- The exclusion bound is invalid if 'stable non-black-hole remnant' is defined loosely to include metastable states that evade the TOV-like limit (A6) without forming a horizon.
- Numerical verification of the Raychaudhuri equation for discrete test metrics is currently missing; proof obligation PO1 remains unresolved pending human input on the formal definition of A5.
- The astrophysical mass-gap inference is non-discriminating if explosion energetics, fallback, or binary evolution dominate the observed remnant distribution, independent of the formal compactness bound. [@cite_0ed84243cf171bc4] [@cite_7a407c865faafd11]

# Appendices

## Idea Source Checkpoints and Direction Selection Audit

### Contribution and Scope

This appendix audits the source checkpoints that shaped the selected mechanism-replacement direction. The proposal advances a qualified AANEC-relaxed trapped-surface bound for non-black-hole stellar remnants. It replaces pointwise energy-condition assumptions with AANEC plus an explicit averaged null-convergence/focusing hypothesis. The observed 2-5 solar mass gap is retained as an astrophysical consistency constraint, not as a theorem-derived prediction. This scope separates formal geometric reasoning from stellar-evolution confounders such as explosion energetics, fallback, equation-of-state physics, rotation, magnetic fields, nonspherical dynamics, and binary interactions. The checkpoint audit therefore preserves the proposal's boundary without treating idea history as empirical evidence. [@cite_0ed84243cf171bc4]

### Checkpoint Decision Matrix

| Checkpoint | Source Role | Retained Decision | Scope Consequence | Open Dependency |
|---|---|---|---|---|
| checkpoint-1 | Candidate direction | AANEC plus explicit averaged focusing replaces pointwise NEC/SEC | Theorem class remains spherical, nonrotating, isotropic, and globally hyperbolic | A5 and D4 require formal completion |
| checkpoint-2 | Selected primary idea | Title narrows to a qualified trapped-surface bound | Mass gap becomes consistency constraint rather than direct derivation | Counterexample criteria remain unverified |
| checkpoint-3 | Direction hypothesis | Alternative stellar-physics mechanisms are named as confounders | Astrophysical inference is separated from formal proof obligations | Stability predicate for A6 needs human review |

The table records audit snapshots only. No temporal order is asserted, because the supplied metadata does not establish iteration timestamps, parent links, or auditable diffs. [@cite_0ed84243cf171bc4] [@cite_72d7ff391b29c495] [@cite_7a407c865faafd11]

### Evidence Anchors and Transition

The retained direction is strengthened by the energy-condition literature, which motivates averaged rather than pointwise positivity when quantum stress-energy can violate classical local bounds. It is also constrained by compact-object observations and stellar-evolution models, which show that mass-gap demographics can be shaped by supernova engines, fallback, pair-instability processes, and binary channels. These sources support the need for a formal validity domain, but they do not prove the proposed bound. The next section should therefore convert the checkpoint audit into a compactness and focusing decision: specify the missing averaged-focusing and Misner-Sharp definitions, then test whether candidate witnesses satisfy all declared assumptions before any exclusion claim is treated as established. [@cite_07d6df5d6978a1fc] [@cite_cbbced417410bc6c] [@cite_f634820e22d7a238] [@cite_fd0f77b2a173c0ab]

## Variables, Symbols, and Operational Definitions

### Core Geometric and Matter Symbols

The formal argument relies on a restricted set of geometric and matter symbols, each tied to a specific operational role within the AANEC-relaxed trapped surface theorem. The spacetime metric g and stress-energy tensor T define the background and source, while the null tangent vector k and expansion scalar theta parameterize the congruence behavior. The mass M and areal radius r are treated as candidate formalizations, with the Misner-Sharp compactness C serving as the critical independent variable. These symbols do not merely label mathematical objects; they encode the boundary between classical general relativity and the averaged energy condition constraints. The operationalization of these variables is essential for distinguishing the proposed theorem from standard Penrose-type singularity proofs, particularly regarding the independence of the averaged focusing condition from the AANEC itself. Without precise symbol-domain conventions, the derivation chain cannot be rigorously audited or falsified.

### Operational Dependency Matrix

| Variable Group | Operational Role | Dependency Status | Decision Consequence |
|---|---|---|---|
| Geometric Core (g, r, k) | Defines background and congruence | Candidate formalization | Enables trapped surface identification |
| Matter Source (T, AANEC) | Energy condition constraint | User-declared assumption | Requires quantum violation check |
| Compactness (C, M) | Threshold discriminator | Needs human input | Determines stable remnant exclusion |
| Averaged Focusing (theta, A5) | Independent geometric hypothesis | Needs human input | Distinguishes from standard NEC proofs |
| Astrophysical Confounders | Alternative explanation vectors | Needs human input | Limits mass-gap inference validity |

### Unresolved Operationalization and Boundary Constraints

Several variables remain operationally undefined, creating specific gaps that prevent the closure of proof obligations. The Misner-Sharp compactness threshold C lacks a model-dependent formula, and the explicit averaged null-convergence condition A5 has no mathematical form distinguishing it from AANEC. Furthermore, the operational definitions for stellar remnant mass, explosion energy, and the equation of state are unspecified, as are the initial conditions for rotation and magnetic fields. These omissions are not merely editorial; they represent the precise boundary conditions where the formal theorem must be restricted or where alternative astrophysical mechanisms dominate. The transition to the next stage requires resolving these dependencies to separate the formal geometric bound from the observational mass-gap inference, ensuring that unverified reasoning is clearly labeled as proposal work rather than established fact.

## Evidence Coverage, Unknown Items, and Review Checklist

### Evidence Coverage

The proposed AANEC-relaxed trapped-surface bound is anchored to a specific evidentiary boundary: pointwise energy conditions are systematically violated by quantum fields, necessitating the use of weaker statements such as quantum energy inequalities or averaged energy conditions for broader validity (W3009127927). This motivates the substitution of pointwise NEC/SEC assumptions with the averaged condition AANEC. However, the formal derivation remains a conjecture and cannot be empirically confirmed by the observed 2-5 solar mass gap. The mass gap is treated strictly as an astrophysical consistency constraint, as its lower edge is dictated by near-final core mass and explosion energetics (W2994776863) and remains subject to equation-of-state uncertainties (W2807309204). Furthermore, gravitational-wave data alone for binary neutron star candidates cannot rule out objects more compact than neutron stars, such as black holes or quark stars (W2766840380). Consequently, the theorem's scope is limited to the restricted model class of classical, spherically symmetric collapse, leaving the empirical identification of the horizon formalism (W2160511150) as an independent observational challenge. [@cite_0ed84243cf171bc4] [@cite_7a407c865faafd11] [@cite_37ecbded9d629353]

### Unknown-Item Consequences

The following table maps the canonical unresolved formal definitions to their specific consequences for the proposed derivation. These items are not resolved in the current design but define the precise boundaries of the conjecture.

| Unresolved Item | Consequence for the Proposed Derivation |
| :--- | :--- |
| Formal definition of Misner-Sharp compactness C (D4) | Prevents the calculation of the specific threshold C_max, rendering the compactness bound model-dependent and unquantified. |
| Mathematical form of explicit averaged focusing (A5) | Obstructs proof obligation PO1, making it impossible to verify whether candidate witnesses genuinely satisfy the independent focusing constraint. |
| Stability predicate for non-black-hole remnants (A6) | Creates ambiguity in distinguishing the proposed stable equilibrium objects from regular black hole models, complicating the exclusion claim P2. |
| Status of candidate witnesses CE1 and CE2 | Remains unverified; without the formal definitions of A5 and D4, it cannot be determined if these witnesses represent valid counterexamples or merely definition conflicts. |

### Review Checklist

**Human-review checklist.** Release criteria for future claims require qualified human review of the final canonical formal reasoning plan, specifically the closure of proof obligations PO1-PO3. Reviewers must audit the candidate counterexamples to determine if they satisfy all stated assumptions (A1-A6) or fail due to the unresolved definitions of A5 and A6. The proposed outcome branch supports_mechanism must remain marked expected_not_observed until the formal derivation is completed and independently verified. No empirical data from the mass gap or gravitational-wave catalogs may be used to certify the theorem, as these are alternative astrophysical explanations rather than direct tests of the formal trapped-surface bound.

## References
- [@cite_07d6df5d6978a1fc] B. P. Abbott et al.. *Multi-messenger Observations of a Binary Neutron Star Merger **. The Astrophysical Journal Letters, 2017.
- [@cite_0ed84243cf171bc4] Eleni-Alexandra Kontou et al.. *Energy conditions in general relativity and quantum field theory*. Classical and Quantum Gravity, 2020.
- [@cite_1e54e3c2b35110ad] Gabriella Agazie et al.. *The NANOGrav 15 yr Data Set: Constraints on Supermassive Black Hole Binaries from the Gravitational-wave Background*. The Astrophysical Journal Letters, 2023.
- [@cite_2576833bf7ef143a] Gabriella Agazie et al.. *The NANOGrav 15 yr Data Set: Evidence for a Gravitational-wave Background*. The Astrophysical Journal Letters, 2023.
- [@cite_283d00782f1f9ecb] S. Perlmutter et al.. *Measurements of Ω and Λ from 42 High‐Redshift Supernovae*. The Astrophysical Journal, 1999.
- [@cite_357dd780a9e3a378] Ade, PAR et al.. *Planck 2015 results*. ORCA Online Research @Cardiff (Cardiff University), 2016.
- [@cite_364386a3569b6e66] N. Aghanim et al.. *Planck 2018 results*. Astronomy and Astrophysics, 2020.
- [@cite_37ecbded9d629353] Abhay Ashtekar et al.. *Isolated and Dynamical Horizons and Their Applications*. Living Reviews in Relativity, 2004.
- [@cite_42e341ff6471ce89] B. P. Abbott et al.. *GW170817: Measurements of Neutron Star Radii and Equation of State*. Physical Review Letters, 2018.
- [@cite_572fec0a1e5d74d9] Adam G. Riess et al.. *Observational Evidence from Supernovae for an Accelerating Universe and a Cosmological Constant*. The Astronomical Journal, 1998.
- [@cite_5ea4dc0e1b288757] M. Kowalski et al.. *Improved Cosmological Constraints from New, Old, and Combined Supernova Data Sets*. The Astrophysical Journal, 2008.
- [@cite_63476e0b002da386] Matt Luckcuck et al.. *Formal Specification and Verification of Autonomous Robotic Systems*. ACM Computing Surveys, 2019.
- [@cite_72d7ff391b29c495] Evan O’Connor et al.. *Global comparison of core-collapse supernova simulations in spherical symmetry*. Journal of Physics G Nuclear and Particle Physics, 2018.
- [@cite_789b47fb0241d9ae] Coenraad J. Neijssel et al.. *The effect of the metallicity-specific star formation history on double compact object mergers*. Monthly Notices of the Royal Astronomical Society, 2019.
- [@cite_7a407c865faafd11] R. Farmer et al.. *Mind the Gap: The Location of the Lower Edge of the Pair-instability Supernova Black Hole Mass Gap*. The Astrophysical Journal, 2019.
- [@cite_7a44e6730c44cb39] Luca Baiotti et al.. *Accurate evolutions of inspiralling neutron-star binaries: Prompt and delayed collapse to a black hole*. Physical review. D. Particles, fields, gravitation, and cosmology/Physical review. D. Particles and fields, 2008.
- [@cite_7ae92f06684c60ef] N. Suzuki et al.. *THEHUBBLE SPACE TELESCOPECLUSTER SUPERNOVA SURVEY. V. IMPROVING THE DARK-ENERGY CONSTRAINTS ABOVEz> 1 AND BUILDING AN EARLY-TYPE-HOSTED SUPERNOVA SAMPLE*. The Astrophysical Journal, 2012.
- [@cite_977568cf7b8a55bf] B. P. Abbott et al.. *GW170817: Observation of Gravitational Waves from a Binary Neutron Star Inspiral*. Physical Review Letters, 2017.
- [@cite_98c5e596c0c34b68] B. P. Abbott et al.. *GW151226: Observation of Gravitational Waves from a 22-Solar-Mass Binary Black Hole Coalescence*. Physical Review Letters, 2016.
- [@cite_bfae3a92efd1d48f] Bill Paxton et al.. *MODULES FOR EXPERIMENTS IN STELLAR ASTROPHYSICS (MESA): PLANETS, OSCILLATIONS, ROTATION, AND MASSIVE STARS*. The Astrophysical Journal Supplement Series, 2013.
- [@cite_c369df652181e8f7] Bill Paxton et al.. *MODULES FOR EXPERIMENTS IN STELLAR ASTROPHYSICS (MESA): BINARIES, PULSATIONS, AND EXPLOSIONS*. The Astrophysical Journal Supplement Series, 2015.
- [@cite_cbbced417410bc6c] R. Abbott et al.. *GW190521: A Binary Black Hole Merger with a Total Mass of 150 M ⊙*. Physical Review Letters, 2020.
- [@cite_cc5bc07a219047b4] Bill Paxton et al.. *Modules for Experiments in Stellar Astrophysics ( ): Convective Boundaries, Element Diffusion, and Massive Star Explosions*. The Astrophysical Journal Supplement Series, 2018.
- [@cite_d3016ce6d1faa8ec] B. P. Abbott et al.. *Observation of Gravitational Waves from a Binary Black Hole Merger*. Physical Review Letters, 2016.
- [@cite_e228b5fd31e37646] Edward N. Taylor et al.. *Galaxy And Mass Assembly (GAMA): stellar mass estimates*. Monthly Notices of the Royal Astronomical Society, 2011.
- [@cite_e7b42f305bc08498] Stef van Buuren et al.. *MICE: Multivariate Imputation by Chained Equations in R*. University of Twente Research Information, 2010.
- [@cite_ecea60a2300e4892] Areti Angeliki Veroniki et al.. *Methods to estimate the between‐study variance and its uncertainty in meta‐analysis*. Research Synthesis Methods, 2015.
- [@cite_f634820e22d7a238] R. Abbott et al.. *GW190814: Gravitational Waves from the Coalescence of a 23 Solar Mass Black Hole with a 2.6 Solar Mass Compact Object*. The Astrophysical Journal Letters, 2020.
- [@cite_fd0f77b2a173c0ab] R. Abbott et al.. *Population of Merging Compact Binaries Inferred Using Gravitational Waves through GWTC-3*. Physical Review X, 2023.
