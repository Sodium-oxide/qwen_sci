# Kinematic Decoupling of Fission Recycling in Kilonovae: A Delayed Neutron Release Mechanism for Third r-Process Peak Shifts and Anisotropic Curtaining

**Keywords:** Kilonova, r-process, Fission Recycling, Delayed Neutron Release, Lanthanide Curtaining, Actinide Spectral Lines, Ejecta Expansion, Third r-process Peak

## Abstract

Neutron star mergers produce r-process ejecta whose composition is governed by fission recycling, a mechanism that couples superheavy nucleus fragmentation to the third abundance peak and lanthanide opacity. Existing models treat this coupling statically, leaving unresolved how viewing-angle-dependent lanthanide curtaining and third-peak shifts arise simultaneously. This proposal advances a formal theory that unifies these observables through the kinematic delay of beta-delayed and isomer-delayed fission neutron release relative to ejecta expansion. The central relation asserts that when the effective fission timescale exceeds the dynamical expansion timescale, delayed neutron release spatially segregates actinides and modulates opacity in a manner that produces distinct temporal evolution of actinide spectral lines. This formalization replaces the instantaneous fission equilibrium assumption with a dynamic timescale competition, bounding validity against geometric and magnetic asymmetry confounders.

The contribution is scoped to a static formal relation between the fission timescale, third-peak abundance, and lanthanide opacity, supported by evidence that lanthanide-rich dynamical ejecta obscure disk wind emission at specific viewing angles and that fission fragment deposition correlates with abundance patterns in metal-poor stars. Candidate lemmas establish the timescale comparison and its abundance consequences, while proof obligations for spectral uniqueness remain unverified pending quantitative definitions of actinide line evolution and asymmetry metrics. The design anticipates outcome branches ranging from mechanistic support to null or uninformative results, with a no-information branch indicating that the dependency does not update theorem status rather than refuting the relation. This structure provides a testable formal bridge between microphysical fission kinetics and macroscopic kilonova observables without claiming observed results.

## Introduction

### Background

Binary neutron star mergers are established as a primary astrophysical site for the rapid neutron-capture process, driven by the ejection of extremely neutron-rich material that powers radioactive decay and produces the characteristic red color of kilonova transients. The final electron fraction in these ejecta is primarily determined by the competition between neutrino absorption reactions on neutrons and protons, reaching a quasi-equilibrium value dependent on the relative luminosities and energy distributions of electron neutrinos and antineutrinos. Furthermore, the presence of heavier r-process elements, particularly lanthanides, increases ejecta opacity by several orders of magnitude compared to iron-group elements, leading to longer, dimmer, and redder light curves. This opacity enhancement, driven by dense line forests of triply and quadruply ionized species, leads to redshifted emission and prolonged cooling times, contrasting sharply with lanthanide-poor outflows that exhibit faster, bluer transients due to lower opacity and higher ionization states. [@cite_30c88fe46f23448d] [@cite_612290131318c0d4] [@cite_c5afe6a1f3d54206] [@cite_bbb76a303fab42b5]

### Research Gap

Despite the strong consensus surrounding compact binary coalescences, significant uncertainties persist regarding the precise microphysical conditions governing nucleosynthetic pathways, particularly the timing of fission neutron release. The position of the third r-process peak can be systematically shifted depending on when fission neutrons are released relative to the freeze-out of neutron capture equilibrium. However, current models often treat fission recycling as an instantaneous equilibrium process, failing to account for the kinematic delay in beta-delayed and isomer-delayed fission neutron release relative to the ejecta expansion. This oversight leaves a critical gap in our ability to link the modification of the third r-process peak freeze-out abundance with viewing-angle-dependent lanthanide curtaining. Additionally, the broad forest of lanthanide lines makes it difficult to determine the exact fraction of individual lanthanides in the ejecta, further complicating the isolation of temporal spectral signatures from purely geometric or magnetic ejecta asymmetries. [@cite_2e146bff5b4a005e] [@cite_b89745a07eed477d]

### Proposed Contribution

This research plan proposes a formal theoretical framework in which the kinematic delay in beta-delayed and isomer-delayed fission neutron release relative to ejecta expansion unifies the modification of the third r-process peak freeze-out abundance with viewing-angle-dependent lanthanide curtaining. By relaxing the instantaneous fission equilibrium assumption and treating the effective fission timescale as a dynamic variable competing with relativistic expansion, the proposed mechanism predicts a distinct temporal evolution of actinide spectral lines. This spectral evolution is hypothesized to be uniquely sensitive to the fission timescale and cannot be replicated by purely geometric or magnetic ejecta asymmetries. The design assumes that the effective fission timescale is comparable to or longer than the ejecta expansion timescale in high-entropy, low-density trajectories, and that actinide spectral line evolution is uniquely sensitive to this delay.

### Scope and Transition

The scope of this proposal is bounded by the requirement that the effective fission timescale for superheavy nuclei must not be strictly shorter than the expansion timescale, and that geometric or magnetic asymmetries alone cannot perfectly replicate the predicted actinide spectral shifts. The formal reasoning plan requires qualified human review to resolve missing quantitative definitions for the effective fission timescale, ejecta expansion timescale, and specific spectral lines. The subsequent section will detail the formal definitions, candidate propositions, and proof obligations necessary to operationalize this kinematic decoupling mechanism.

## Background, Survey, and Research Gap

### Established Nucleosynthetic Context

The identification of neutron star mergers as a primary astrophysical site for the rapid neutron-capture process is a settled empirical fact, anchored by the multi-messenger detection of GW170817 and its kilonova counterpart AT2017gfo. The observed rapid rise, subsequent decay, and color evolution of the transient are consistent with a radioactively-powered event resulting from the ejection of neutron-rich material, specifically involving multiple ejecta components of differing lanthanide abundance (W2765302758). The very red color of the kilonova associated with GW170817 indicates that neutron star mergers are an important r-process site, capable of producing elements heavier than iron (W2802275066). Furthermore, the light curve evolution and spectral features of AT2017gfo are consistent with a kilonova powered by the radioactive decay of r-process nuclides, confirming that neutron-star mergers produce such events (W2765595587). This establishes the macroscopic physical regime within which the proposed formal theory operates. [@cite_30c88fe46f23448d] [@cite_492ec5910d5efd57] [@cite_612290131318c0d4]

### Opacity Mechanisms and Viewing-Angle Dependencies

The electromagnetic manifestation of these mergers is strictly governed by the presence of heavy r-process elements, particularly lanthanides, which increase ejecta opacity by several orders of magnitude compared to iron-group elements, leading to longer, dimmer, and redder light curves (W2084800078). The color of kilonova transients is determined by the electron fraction, where values greater than or approximately equal to 0.25 result in lanthanide-free ejecta that produce blue optical light curves (W2013598075). Crucially, the presence of a small amount of overlying neutron-rich dynamical ejecta acts as a lanthanide curtain, obscuring optical emission from disk winds at certain viewing angles (W2013598075). Strong lines in lanthanide opacities significantly alter kilonova light curves and spectra in optical and infrared wavelength bands (W2943010605). These established opacity mechanisms provide the empirical foundation for linking microphysical nucleosynthetic yields to macroscopic, angle-dependent observables. [@cite_2bf3a687e25803e4] [@cite_2e146bff5b4a005e] [@cite_bbb76a303fab42b5]

### Fission Recycling and the Third r-Process Peak

The synthesis of elements at the third r-process peak and beyond is heavily influenced by fission recycling. The proposed mechanism for the rare earth peak involves a pileup of material formed dynamically during the end phase of the r process, where a feature in the nuclear mass surface causes a hangup during the decay back to stability (W2529651270). In simulated black hole-torus systems, viscously driven outflows typically account for approximately 20–25% of the initial accretion-torus mass, while neutrino-powered winds contribute at most another approximately 1%, although neutrino heating enhances the viscous ejecta (W2157732302). The final electron fraction in the ejecta is primarily determined by the competition between neutrino absorption reactions on neutrons and protons, reaching a quasi-equilibrium value dependent on the relative luminosities and energy distributions of electron neutrinos and antineutrinos (W1996162015). These nuclear and thermodynamic constraints dictate the abundance patterns that ultimately feed into the opacity drivers responsible for the observed kilonova spectra. [@cite_b89745a07eed477d] [@cite_403b23aaa35e6b92] [@cite_c5afe6a1f3d54206]

### Unresolved Gap: Direct Observation of Kinematic Decoupling

Despite the robust understanding of lanthanide opacity and fission recycling, a critical research gap remains in the direct observational linkage between the temporal evolution of actinide spectral lines and the kinematic decoupling of fission recycling. The required slot for direct observation remains uncovered in the relevant evidence cluster concerning viewing-angle dependencies, lanthanide curtaining, and three-dimensional geometry effects. The available paper roles do not support the evidence strength required by this slot. Specifically, while geometric asymmetries in the ejecta (e.g., shock-heated polar winds, tidal tails) or magnetic field configurations can produce viewing-angle-dependent lanthanide curtaining and abundance variations without requiring delayed fission recycling (W2586770524), there is a lack of direct spectroscopic evidence isolating the temporal evolution of actinide lines from these purely geometric or magnetic confounders. [@cite_3a00f5f9e5201ba0]

### Unresolved Gap: Phenomenon of Relativistic Outflows

A parallel gap exists in the phenomenological mapping of relativistic outflows, central engine evolution, and multi-messenger progenitor decoupling. The required slot for the phenomenon remains uncovered in this relevant evidence cluster. The structured survey artifacts identify an unresolved research constraint regarding how the kinematic delay in beta-delayed and isomer-delayed fission neutron release relative to ejecta expansion formally unifies the modification of the third r-process peak freeze-out abundance with viewing-angle-dependent lanthanide curtaining. Without resolving this gap, the mechanism fails if the effective fission timescale for superheavy nuclei is strictly shorter than the expansion timescale, or if geometric/magnetic asymmetries alone can perfectly replicate the predicted actinide spectral shifts without invoking delayed fission timescales.

### Transition to Formal Theory

The absence of direct observational isolation of the actinide temporal signature necessitates a formal theoretical approach. The proposed contribution addresses this gap by introducing a unified fission recycling relation that treats the fission timescale as a dynamic variable competing with relativistic expansion, while bounding the validity domain against geometric confounders. This formal argument will establish the precise conditions under which delayed neutron release from beta-decaying and isomer-trapped superheavy nuclei decouples the late-stage r-process from the prompt relativistic outflow, spatially segregating actinides and altering the opacity evolution to produce anisotropic spectral absorption features. The subsequent sections will define the formal propositions, assumptions, and proof obligations required to rigorously test this mechanism against the declared boundary conditions.

## Research Questions and Planned Contributions

### Background and Research Gap

The synthesis of heavy elements in neutron star mergers relies on the rapid neutron-capture process (r-process), where extreme neutron densities drive nuclear flows far from stability. A defining feature of this environment is fission recycling, where superheavy nuclei fragment, releasing neutrons that alter the final abundance distribution. Current observational and theoretical frameworks establish that the presence of lanthanides increases ejecta opacity, producing distinct red kilonova signatures. However, a critical gap remains in linking the microphysical timing of fission neutron release to macroscopic observables. Specifically, the interplay between the effective fission timescale and the dynamical expansion timescale of the ejecta is not formally constrained. This uncertainty prevents a definitive separation of kinematic fission delays from purely geometric or magnetic ejecta asymmetries, which also influence viewing-angle-dependent opacity features. [@cite_30c88fe46f23448d]

### Operational Research Questions

To address this gap, the proposed research operationalizes the following formal questions:
1. Under what conditions does the effective fission timescale exceed the ejecta expansion timescale, leading to kinematic decoupling of neutron release?
2. How does this decoupling quantitatively modify the third r-process peak freeze-out abundance and lanthanide opacity?
3. Can the resulting temporal evolution of actinide spectral lines be uniquely distinguished from signatures produced by geometric or magnetic field asymmetries?

### Planned Contributions

The primary contribution is a unified formal theory of fission recycling that treats the effective fission timescale as a dynamic variable competing with relativistic expansion. We propose a mathematical framework that links the delayed release of neutrons from beta-decaying and isomer-trapped superheavy nuclei to modifications in the third r-process peak and anisotropic lanthanide curtaining. This theory predicts a distinct temporal evolution of actinide spectral lines that cannot be replicated by static geometric or magnetic asymmetries. By formalizing these relations, the work provides a rigorous basis for interpreting multi-messenger kilonova observations and constraining nuclear properties of superheavy elements.

### Unresolved Items and Scope

The operational definitions for the key variables governing this theory require formal specification. Specifically, the mathematical expressions for the effective fission timescale, ejecta expansion timescale, actinide spectral line evolution, third r-process peak abundance, viewing angle, lanthanide curtaining, geometric asymmetries, and magnetic field configuration are currently undefined. Resolving these definitions is a prerequisite for the formal derivation and proof obligations outlined in the subsequent sections.

## Idea Source Checkpoints and Direction Selection Audit

### Scientific Attraction and Survey Anchoring

The selected direction, premise_inversion, targets a specific structural deficit in current kilonova modeling: the absence of direct observational constraints linking viewing-angle-dependent lanthanide curtaining to the temporal evolution of actinide spectral lines. The scientific attraction lies in relaxing the standard instantaneous_fission_equilibrium assumption. By treating the fission timescale as a dynamic variable competing with relativistic expansion, the proposal seeks to unify third r-process peak modifications with anisotropic opacity signatures. This approach is anchored in established evidence that lanthanide opacities, driven by dense line forests, fundamentally alter radiative transfer regimes, shifting emission to the infrared and creating viewing-angle dependencies. The hypothesis posits that delayed neutron release from beta-decaying and isomer-trapped superheavy nuclei spatially segregates actinides, producing spectral signatures that geometric or magnetic asymmetries alone cannot replicate. [@cite_2bf3a687e25803e4] [@cite_2e146bff5b4a005e]

### Defects Exposed by Checkpoints and Counterexamples

The frozen audit reveals critical gaps between the physical intuition and its formalization. The counterexample CE1 is rejected because it violates the core assumption that the effective fission timescale is comparable to or longer than the expansion timescale, rendering it a boundary case rather than a valid refutation. Conversely, CE2 remains unverified but highlights a severe defect: the assumption of unique spectral sensitivity lacks quantitative definition. The idea checkpoints expose that without rigorous operational definitions for variables such as Lambda_Spectral and Kappa_Lanthanide, the mechanism cannot distinguish kinematic delays from seed-nuclei distribution variance. The formal reasoning plan requires human review because the current definitions do not support the claimed non-degeneracy in parameter space, leaving the uniqueness assumption vulnerable to geometric confounders.

### Qualified Retention and Explicit Exclusions

The direction is retained as a candidate formalization only under strict scope limitations. The proposal is explicitly excluded from claiming that delayed fission is the sole driver of actinide spectral evolution; instead, it asserts that kinematic delays produce a distinct temporal signature that is currently unmodeled. The retention depends on resolving the dependency on the definition ledger, specifically the need for quantitative metrics for geometric asymmetries and magnetic field configurations. Until these operational definitions are supplied, the mechanism remains a proposed relation rather than an established theory. The next stage must focus on deriving a criterion that isolates the temporal signature of delayed neutron release from static geometric effects, ensuring that the formal proof obligations are grounded in measurable, distinct observables.

## Problem Definition, Assumptions, and Hypotheses

### Formal Problem and Domain

The formal problem addressed in this section is the kinematic decoupling of fission recycling from the dynamical expansion of neutron-star merger ejecta. The proposed theory domain consists of high-entropy, low-density trajectories where the effective fission timescale tau_fission and the ejecta expansion timescale tau_expansion are dynamically comparable. Within this domain, the central problem is to determine whether delayed neutron release from beta-decaying and isomer-trapped superheavy nuclei can unify the modification of the third r-process peak freeze-out abundance with viewing-angle-dependent lanthanide curtaining. This formalization replaces the standard instantaneous fission equilibrium assumption with a dynamic timescale competition, bounding the validity of the resulting abundance and opacity predictions against geometric and magnetic confounders. [@cite_2bf3a687e25803e4] [@cite_30c88fe46f23448d] [@cite_8beeacaea00bd823]

### Core Formal Definitions

**Definition.** The argument consumes the following scoped definitions: tau_fission is the effective fission timescale governed by beta-decay half-lives and nuclear isomeric states leading to fission neutron release; tau_expansion is the dynamical timescale of relativistic expansion in high-entropy, low-density trajectories; Y_third_peak is the final abundance distribution of elements at the third r-process peak freeze-out; and Kappa_Lanthanide is the opacity effect caused by lanthanides that suppress blue and ultraviolet light. The viewing angle Theta_View is the orientation of the observer relative to the merger axis. These symbols fix the formal object and the admissible premises consumed by the next argument stage.

### Assumption Ledger

The candidate theorem entry is bounded by two admissible premises. A1: The effective fission timescale tau_fission is comparable to or longer than the ejecta expansion timescale tau_expansion in the high-entropy, low-density trajectories that define the domain. A2: Actinide spectral line evolution Lambda_Spectral is uniquely sensitive to the fission timescale and cannot be mimicked by variations in ejecta geometry Psi_Geometry or magnetic field topology B_Magnetic alone. These assumptions are candidate formalizations; they set the scope of the proposed relation rather than establishing it as a proved theorem.

### Numbered Problem Relation

The core relation that fixes the proposed problem and its failure boundary is the timescale comparison governing kinematic delay: tau_fission >= tau_expansion.

### Candidate Propositions

**Proposition (Candidate).** The candidate theorem entry states two proposed propositions. P1: The kinematic delay in fission neutron release relative to ejecta expansion unifies the modification of the third r-process peak freeze-out abundance Y_third_peak with viewing-angle-dependent lanthanide curtaining Kappa_Lanthanide. P2: Delayed fission recycling produces a distinct temporal evolution of actinide spectral lines that cannot be replicated by purely geometric or magnetic ejecta asymmetries. These propositions are candidate formalizations, not established results.

### Scoped Entry Lemma and Proof Obligations

**Lemma Registry L1, L2, PO1, PO2 (Candidate).** The scoped entry lemma L1 (Candidate) derives the delayed-release consequence from A1 and A2 and connects it to P1 through proof obligation PO1. The companion lemma L2 (Candidate) extends the same premises to the spectral-uniqueness claim P2 through proof obligations PO1 and PO2. PO1 requires a quantitative mapping from tau_fission to Y_third_peak and Kappa_Lanthanide; PO2 requires a demonstration that Lambda_Spectral is not degenerate with Psi_Geometry and B_Magnetic. The failure condition delimiting the domain is that the mechanism does not apply when tau_fission is strictly shorter than tau_expansion, or when geometric and magnetic asymmetries alone perfectly replicate the predicted actinide spectral shifts. A no-information branch for PO1 or PO2 withholds any theorem-status update; it is neither proof of failure nor grounds for declaring the research plan invalid.

## Study Design and Methods

### Protocol Scope and Formal Dependency

This section specifies the proposal protocol and boundary checks for a static formal relation within a mathematical-theory design. The unit of analysis is a formal theory proposition, not an empirical sample. The design assumes the effective fission timescale is comparable to or longer than the ejecta expansion timescale in high-entropy, low-density trajectories. It also assumes actinide spectral line evolution is uniquely sensitive to that timescale and cannot be mimicked by geometric or magnetic asymmetries alone. These assumptions are the premises of the candidate formalization, not observed results. The formal definitions, propositions, and proof obligations are owned by the definition ledger; this route consumes them as incoming premises and derives a decision protocol.

### Design Boundary and Protocol Matrix

| Protocol Element | Design Decision | Boundary Consequence |
|---|---|---|
| Comparator adequacy | Human review required | Baselines and comparisons cannot be finalized without canonical input. |
| Measurement plan | Human review required | Observational calibration and quality control remain outside the formal proposal. |
| Data governance | Human review required | Reproducibility and data management are release-gated, not design-gated. |
| Falsifier CE1 | Assumption violation | A witness with tau_fission < tau_expansion is a scope delimiter, not a refutation of the implication. |
| Falsifier CE2 | Unverified witness | A seed-variance scenario that breaks correlation is plausible but requires formal definitions to verify. |
| Outcome branch | Expected not observed | Prespecified branches map to conditional conclusions; none is triggered by the proposal itself. |

### Counterexample and Boundary Analysis

The boundary analysis distinguishes two candidate witnesses. CE1 posits instantaneous fission recycling where the effective fission timescale is strictly shorter than the expansion timescale. This witness violates the design premise rather than refuting the conclusion under that premise; it therefore functions as a scope delimiter. CE2 posits a parameter space where the timescale premise holds but third-peak modification is driven entirely by seed-nuclei distribution variance, yielding zero correlation with lanthanide opacity. CE2 is an unverified formal witness: its status as a counterexample depends on quantitative definitions of third-peak abundance and lanthanide curtaining that remain unresolved in the definition ledger. The protocol thus treats CE1 as a boundary condition and CE2 as a falsification target contingent on human-supplied formal definitions.

### Reproducibility, Human Decisions, and Transition

Reproducibility and data governance are required for release but are not prerequisites for the formal relation itself; they are recorded as human-review dependencies rather than methodological gaps. The comparison and measurement fields likewise await canonical human input, and this section states that dependency without substituting invented baselines or calibration plans. The concrete transition to the next stage is the resolution of the definition ledger: formal operational definitions for the eight variables must be supplied before the proof obligations and counterexample witnesses can be adjudicated. Until that resolution, the design remains a scoped, source-bounded proposal protocol.

## Expected Outcome Branches and Conditional Conclusions

### Decision Protocol and Scope

This section establishes a prespecified decision protocol for the candidate formalization of delayed fission recycling in neutron star merger ejecta. The protocol maps four expected outcome branches to the relevant formal propositions and proof obligations, defining the allowed conclusion and next action for each branch. The analysis consumes the incoming premises from the forward derivation, specifically the candidate formalizations of the unified fission recycling relation and the spectral signature uniqueness. All outcomes are strictly expected and not observed; the decision matrix serves to bound the interpretation of future formal or empirical evidence without asserting current validity.

### Conditional Outcome Decision Matrix

**Pre-registered Branch (Expected---Not Observed).**

| Outcome Branch | Trigger Condition | Relevant Proposition / Proof Obligation | Allowed Conclusion | Next Action |
| :--- | :--- | :--- | :--- | :--- |
| Supports Mechanism | Prespecified analysis is consistent with the declared relation while planned controls do not favor a stated alternative explanation. | P1, P2; PO1, PO2 | The result would support, but not prove, the declared relation within the design boundary. | Replicate under independently confirmed conditions. Test the most consequential declared boundary condition. |
| Partial or Heterogeneous | Prespecified analysis indicates variation across declared conditions, units, or measurement contexts. | P1, P2; PO1, PO2 | The relation may be conditional or heterogeneous; no universal conclusion is warranted. | Predefine and check plausible moderators. Improve the coverage of conditions and measurement comparability. |
| Null or Contradictory | Prespecified comparison does not support the declared relation or instead favors a declared alternative explanation. | P1, P2; PO1, PO2 | The proposed relation is not supported in this design boundary; absence of support is not proof of absence generally. | Audit construct validity and comparison adequacy. Revise the mechanism or boundary claim before another design iteration. |
| Uninformative or Invalid | Prespecified quality-control, missingness, protocol-deviation, or validity criteria prevent interpretation. | P1, P2; PO1, PO2 | No scientific conclusion is warranted because the planned design did not yield interpretable evidence. | Resolve the identified validity or data-quality failure before repeating the design. Obtain human confirmation of measurement, sampling, and analysis prerequisites. |

### Interpretation of Boundary Conditions

The decision protocol explicitly incorporates the declared boundary conditions for the mechanism. The mechanism fails if the effective fission timescale for superheavy nuclei is strictly shorter than the expansion timescale, or if geometric and magnetic asymmetries alone can perfectly replicate the predicted actinide spectral shifts without invoking delayed fission timescales. These conditions serve as the primary discriminators for the null or contradictory branch, ensuring that the formal propositions remain bounded by the physical constraints of the ejecta environment.

### Transition to Risk and Limitations

The outcome branches and their associated next actions define the conditional conclusions that will be subjected to rigorous risk assessment. The requirement to obtain human confirmation of measurement, sampling, and analysis prerequisites in the uninformative or invalid branch directly feeds into the subsequent review ledger. This transition ensures that the formal decision protocol is integrated with the broader data governance and reproducibility constraints of the research plan.

## Risks, Limitations, and Human Review Requirements

The proposed formal relation linking delayed fission recycling to third r-process peak shifts and anisotropic lanthanide curtaining remains an unverified candidate theorem. The frozen evidence establishes that neutron star merger ejecta generate lanthanide-rich opacity and that fission recycling shapes the third abundance peak, but the specific kinematic decoupling mechanism and its unique spectral signature are not yet proved. This section defines the precise release conditions and human-review boundaries required before the formal reasoning plan can be escalated. [@cite_403b23aaa35e6b92] [@cite_b89745a07eed477d] [@cite_bbb76a303fab42b5]

The primary limitation is the absence of operational definitions for the eight core variables in the formal reasoning plan. Without quantitative metrics for the effective fission timescale, spectral uniqueness, and lanthanide opacity, the proof obligations cannot be discharged. Furthermore, the candidate counterexample analysis is incomplete; one proposed witness violates the premise assumption, and the other lacks the mathematical formalization needed to test the conclusion's negation. These gaps prevent any update to the theorem status.

**Decision Status: No-information.** The theory spine identifies ten no-information decision branches corresponding to the missing definitions and unresolved proof obligations. These branches do not indicate that the mechanism is false; rather, they signal that the dependency closure is incomplete. The release protocol mandates that these procedural dependencies be resolved by a qualified human reviewer before the formal proposition is considered viable for empirical testing or further theoretical derivation.

| Decision Domain | Current Status | Required Human Action | Release Condition |
|---|---|---|---|
| Formal Reasoning Plan | Requires qualified review | Validate candidate formalizations P1 and P2 | Approved symbolic logic and premise consistency |
| Operational Definitions | Needs human input (D1-D8) | Specify quantitative metrics for timescales, opacity, and spectral evolution | Closed dependency matrix for all variables |
| Counterexample Analysis | Unverified (CE2) | Verify non-degeneracy of spectral sensitivity and abundance correlation | Confirmed or rejected formal witness |
| Proof Obligations | Needs human input (PO1-PO2) | Audit derivation steps S1-S3 for logical validity | Signed-off proof sketch or revised lemma |
| Outcome Branches | Expected not observed | Confirm prespecified triggers for supports, null, or invalid branches | Pre-registered analysis protocol finalized |

Transitioning to the next stage requires the complete resolution of the definition ledger. Until the operational definitions for the effective fission timescale and lanthanide curtaining are formalized, the proof obligations remain suspended. The research plan cannot proceed to empirical design or numerical simulation until the human reviewer certifies that the candidate theorem's premises are mathematically well-defined and its counterexample space is bounded.

## Definitions, Propositions, and Proof Obligations

### Scope and Domain of the Formal Ledger

This section owns the primary definition ledger, symbol roles, candidate propositions, and proof obligations for the proposed kinematic decoupling of fission recycling in neutron-star merger ejecta. The domain is restricted to high-entropy, low-density trajectories where the competition between beta-delayed and isomer-delayed fission neutron release and relativistic expansion can be treated as a static formal relation. Established upstream evidence supports the physical relevance of this regime: lanthanide-rich ejecta produce viewing-angle-dependent opacity curtains, and fission recycling robustly shapes the third r-process peak abundance (W2013598075, W2765302758, W2893936582). The formal apparatus constructed here translates these empirical anchors into a dependency-closed theoretical control panel, separating established astrophysical background from the proposed mathematical unification. [@cite_2bf3a687e25803e4] [@cite_492ec5910d5efd57] [@cite_f16e65d18232c78c]

### Primary Definition Ledger and Symbol Roles

**Decision Status: No-information.** The following eight canonical definitions establish the symbol domain for all subsequent lemmas and proof obligations. Each entry remains in a needs_human_input status pending quantitative operationalization, yet their structural roles are fixed for the theory spine.

- **D1 (tau_fission):** Effective fission timescale governed by beta-decay half-lives and nuclear isomeric states leading to fission neutron release.
- **D2 (tau_expansion):** Dynamical timescale of relativistic expansion in high-entropy, low-density trajectories.
- **D3 (Lambda_Spectral):** Time-dependent changes in absorption features of superheavy elements (actinide spectral line evolution).
- **D4 (Y_third_peak):** Final abundance distribution of elements at the third r-process peak freeze-out.
- **D5 (Theta_View):** Orientation of the observer relative to the merger axis.
- **D6 (Kappa_Lanthanide):** Opacity effects caused by lanthanides that suppress blue/UV light (lanthanide curtaining).
- **D7 (Psi_Geometry):** Non-spherical structure of dynamical ejecta (e.g., ellipticity, shock-heated polar winds).
- **D8 (B_Magnetic):** Topology and strength of magnetic fields in the merger environment.

### Threshold Convention for Kinematic Decoupling

**Definition.** To bound the validity domain of the proposed mechanism, we adopt a compactness threshold convention that distinguishes kinematically coupled from decoupled fission recycling. The decoupling regime is formally delimited by the relation tau_fission / tau_expansion >= 1. This threshold is not a derived result but a declared boundary condition for the theory control panel. It partitions the parameter space such that the downstream propositions and lemmas apply only within the decoupled domain. The boundary condition fails if tau_fission < tau_expansion, corresponding to instantaneous fission equilibrium. This threshold convention ensures that the mathematical argument remains scoped to the premise inversion that motivates the research direction.

### Candidate Propositions P1 and P2

**Proposition (Candidate).** **Proposition P1 (Candidate):** The kinematic delay in fission neutron release relative to ejecta expansion unifies the modification of the third r-process peak freeze-out abundance with viewing-angle-dependent lanthanide curtaining.

**Proposition P2 (Candidate):** Delayed fission recycling produces a distinct temporal evolution of actinide spectral lines that cannot be replicated by purely geometric or magnetic ejecta asymmetries.

Both propositions are candidate formalizations. P1 asserts a unification relation between abundance modification and opacity evolution under the decoupling threshold. P2 asserts a non-degeneracy condition: the spectral signature of delayed fission is uniquely sensitive to tau_fission and is not mimicked by Psi_Geometry or B_Magnetic alone. These propositions consume the definition ledger and threshold convention above, and they feed the lemma registry and proof obligations that follow.

### Lemma Registry: Candidate and Unverified Units

**Lemma Registry L1, L2, L3, L4, L5 (Candidate).** The lemma registry translates the propositions into auditable formal units. All entries are proposed or unverified; none is a completed proof.

- **L1 (Candidate):** Under premises A1 and A2, P1 holds within the decoupling threshold. L1 is the primary entry lemma for P1 and is linked to proof obligation PO1.
- **L2 (Candidate):** Under premises A1 and A2, P2 holds. L2 is the entry lemma for P2 and is linked to proof obligations PO1 and PO2.
- **L3 (Candidate):** Forward derivation step S1: neutron release is kinematically delayed relative to expansion in high-entropy, low-density trajectories. L3 depends on A1 and feeds PO1.
- **L4 (Unverified):** Forward derivation step S2: delayed neutron release modifies Y_third_peak and Kappa_Lanthanide. L4 depends on S1 and feeds PO1.
- **L5 (Unverified):** Forward derivation step S3: actinide spectral evolution is distinct from geometric or magnetic asymmetry signatures. L5 depends on A2 and S2 and feeds PO2.

L1 and L2 are candidate lemma registry entries that formalize the propositions. L3, L4, and L5 are unverified derivation units that decompose the argument into auditable steps. The registry does not assert that any lemma has been proved.

### Dependency-Closure Matrix: Proof Obligations and Formal Inputs

**Proof Obligation Registry PO1, PO2 (Unverified).**

| Proof Obligation | Related Lemmas | Required Formal References | Status | If Unavailable |
| :--- | :--- | :--- | :--- | :--- |
| PO1 | L1, L2, L3, L4 | A1, A2, D1, D4, D6, P1, P2, S1, S2 | Unverified | Withhold theorem status update (No-information: PO1) |
| PO2 | L2, L5 | A2, D3, D7, D8, P2, S3 | Unverified | Withhold theorem status update (No-information: PO2) |

PO1 governs the abundance-opacity unification chain. PO2 governs the spectral non-degeneracy chain. Each obligation requires specific definitions and assumptions to be resolved before the corresponding lemmas can be verified. The no-information branches for PO1 and PO2 indicate that unresolved inputs do not constitute proof of failure; they suspend the dependency update until human review confirms the operational definitions.

### Transition to Forward Derivation and Counterexamples

The definition ledger, threshold convention, candidate propositions, lemma registry, and dependency-closure matrix constitute the complete formal control panel for this route. The next stage consumes these units to execute the forward derivation chain (S1 through S3) and to evaluate candidate counterexamples against the declared boundary conditions. Specifically, the forward derivation section will operationalize the unverified steps L3, L4, and L5, while the counterexample analysis will test whether geometric or magnetic asymmetries can replicate the spectral signature asserted in P2 without invoking delayed fission. All downstream reasoning inherits the needs_human_input status of definitions D1 through D8 and the candidate status of propositions P1 and P2. No observed results are claimed; the transition is a procedural handoff of formal dependencies, not an empirical conclusion.

## Forward Derivation and Counterexample Search Plan

### Consumed Premises and Derivation Scope

This section advances the formal argument from the scoped premises supplied by the definitions ledger. The derivation consumes the candidate assumptions A1 and A2 and targets the candidate propositions P1 and P2. The argumentative goal is to expose the dependency structure of the kinematic decoupling mechanism and to adjudicate proposed counterexamples against the domain of admissibility. No new results are claimed; the contribution is a structured plan that converts the candidate formalization into explicit proof obligations and failure boundaries. [@cite_2bf3a687e25803e4] [@cite_2e146bff5b4a005e] [@cite_30c88fe46f23448d] [@cite_bbb76a303fab42b5]

### Assumption and Comparator Ledger

**Proof Obligation Registry PO1, PO2 (Unverified).**

| Ledger Entry | Role in Derivation | Admissibility Status |
|---|---|---|
| A1: tau_fission >= tau_expansion | Establishes the kinematic delay premise for S1. | Candidate formalization; operational definitions pending. |
| A2: Unique spectral sensitivity | Separates the fission-delay signature from geometry and magnetic confounders. | Candidate formalization; non-degeneracy metrics pending. |
| Admissible Comparator: Instantaneous fission equilibrium | Tests whether the delay premise is necessary for the predicted abundance shift. | Valid only when A1 holds. |
| Admissible Comparator: Geometric/magnetic asymmetry | Tests whether the spectral signature is uniquely attributable to fission timing. | Valid only when A2 holds. |

### Numbered Derivation Relation

tau_fission >= tau_expansion ==> Delta Y_third_peak correlated with Kappa_Lanthanide ==> Lambda_Spectral distinct from Psi_Geometry and B_Magnetic

### Lemma Chain and Proof Obligations

1. Candidate Lemma L3 (proposed): Under A1, neutron release is kinematically delayed relative to expansion. This is the entry condition for the derivation and requires PO1 to formalize the timescale comparison.
2. Unverified Lemma L4: The delayed neutron release modifies the third r-process peak abundance and lanthanide opacity. This step requires PO1 to establish the correlation between Delta Y_third_peak and Kappa_Lanthanide.
3. Unverified Lemma L5: The resulting actinide spectral evolution is distinct from geometric or magnetic asymmetry signatures. This step requires PO2 to demonstrate that Lambda_Spectral cannot be mimicked by Psi_Geometry or B_Magnetic alone. [@cite_2bf3a687e25803e4] [@cite_b89745a07eed477d]

### Counterexample Decision Matrix

| Witness | Premise Status | Conclusion Status | Classification | Decision |
|---|---|---|---|---|
| CE1: Instantaneous recycling (tau_fission < tau_expansion) | False | Unknown | F1: Assumptions not satisfied | Out-of-domain boundary case; not a valid counterexample to P1. |
| CE2: Seed-nuclei variance drives abundance shift | True | False (negated) | F2: No information | In-domain witness; validity hinges on unquantified A2. |

CE1 fails to refute P1 because a counterexample to an implication requires a true premise and a false conclusion. CE2 posits a scenario where the premise holds but the conclusion fails; however, its validity cannot be established because the quantitative metrics for the uniqueness assumption A2 are missing.

### Failure Conditions and Dependency Boundaries

**Decision Status: No-information.** Proposed Failure Condition: The kinematic decoupling mechanism fails if the effective fission timescale for superheavy nuclei is strictly shorter than the expansion timescale, or if geometric and magnetic asymmetries alone can perfectly replicate the predicted actinide spectral shifts without invoking delayed fission timescales.

Dependency Boundary: The derivation currently yields no theorem status update because the formal definitions D1 through D8 and the proof obligations PO1 and PO2 are unresolved. These no-information branches indicate that the argument cannot be adjudicated until the operational metrics for tau_fission, tau_expansion, Lambda_Spectral, Y_third_peak, Kappa_Lanthanide, Theta_View, Psi_Geometry, and B_Magnetic are supplied. [@cite_403b23aaa35e6b92] [@cite_8beeacaea00bd823]

### Transition to Expected Outcomes

The derivation plan establishes that the proposed mechanism is logically coherent only within a narrow parameter space defined by A1 and A2. Because the current evidence status is expected-not-observed, the next stage must map these formal dependencies to prespecified outcome branches. The transition to the decision protocol requires resolving the missing operational definitions to determine whether the planned comparisons can distinguish the kinematic delay signature from its admissible alternatives.

## Computational Evidence (Numerical Simulation; Non-empirical)

Q1 (final v0) answers: Can the time-dependent evolution of actinide spectral line fluxes constrain the fission neutron release timescale and distinguish kinetic decoupling from static geometric or electron-fraction abundance variations? Model family: parabolic_1d. Execution mode: NUMERICAL_SIMULATION. Result kind: SIMULATED. Empirical claim status: NOT_EMPIRICAL. Model-internal hypothesis relation: INCONCLUSIVE. Model-internal result summary: The baseline one-dimensional diffusion-reaction simulation completed and was numerically verified. The final field remained near 10^-18, with finite-field, explicit-stability, and zero-boundary-residual checks passing. This is a model-internal numerical result and does not establish observational confirmation. Numerical quality: NUMERICALLY_VERIFIED. Applicability conditions: The evolved scalar u is a surrogate for actinide spectral-line source density rather than a full isotopic abundance network.; Unresolved radiative transport is closed by a constant effective diffusion coefficient.; Expansion is represented by a linear dilution loss with timescale formed from R_domain and v_ejecta rather than a moving mesh.; The initial actinide-line proxy is spatially uniform at the approved u_initial value.; The approved explicit time step is coarse relative to the approved fission-release timescale, so the delayed source is numerically smeared.. Limitations: The surrogate does not resolve a full r-process isotopic network or actinide-specific line formation.; The effective diffusion coefficient is a declared closure assumption, not a literature measurement.; The coarse approved time step cannot resolve all structure on the approved fission-release timescale.; Spherical symmetry is assumed in the reduced radial surrogate and cannot represent multidimensional lanthanide curtaining.; Actinide opacity and atomic-data uncertainties are not explicitly represented.. Iteration lineage: v0: INCONCLUSIVE (The baseline one-dimensional diffusion-reaction simulation completed and was numerically verified. The final field remained near 10^-18, with finite-field, explicit-stability, and zero-boundary-residual checks passing. This is a model-internal numerical result and does not establish observational confirmation.). Supplementary mathematical-model PDF: quantitative_mathematical_models.pdf#Q1.

Q2 (final v0) answers: What is the posterior probability distribution of the fission neutron release timescale when gravitational-wave, kilonova photometric, and spectroscopic abundance constraints are combined? Model family: MONTE_CARLO. Execution mode: NUMERICAL_SIMULATION. Result kind: SIMULATED. Empirical claim status: NOT_EMPIRICAL. Model-internal hypothesis relation: INCONCLUSIVE. Model-internal result summary: Q2 Numerical quality: NOT_REPORTED. Applicability conditions: The approved tau_f value of 2.3 s is used as the center of a positive bounded sensitivity prior from 1.15 s to 3.45 s.; The approved ejecta-mass value of 0.04 solar_mass is represented by a positive bounded interval from 0.03 to 0.05 solar_mass.; The approved electron-fraction value of 0.16 is represented by a broad physically admissible interval from 0.08 to 0.24.; The approved inclination value is represented by the converted 19 to 42 degree interval in radians.; The current executable observable is the sampled tau_f value; nuisance variables are retained as declared prior variables for later likelihood extension.. Limitations: The current trusted adapter evaluates a scalar observable and does not implement a full likelihood.; The declared N_chains and N_temperatures controls are retained for provenance but are not independently executed by the standard adapter.; The output is a numerical simulation result and not empirical evidence.; The nuisance priors are sampled but are not combined through a multi-messenger likelihood in this adapter.. Iteration lineage: v0: INCONCLUSIVE (Q2). Supplementary mathematical-model PDF: quantitative_mathematical_models.pdf#Q2.

# Appendices

## Energy-Condition Taxonomy, Symbols, and Boundary Defense

### Scope of the Boundary Defense

This appendix isolates the mathematical and physical prerequisites that the proposed kinematic-decoupling mechanism inherits from the upstream formalization. The central argument rests on a timescale comparison between effective fission neutron release and ejecta expansion, not on a gravitational focusing theorem. Consequently, the energy-condition taxonomy below functions as a defensive boundary rather than a derivation engine. It clarifies which relativistic assumptions are imported, which remain independent, and which cannot be substituted for one another. The route treats the expansion timescale as a prescribed dynamical control variable; it does not claim that a null-energy or strong-energy condition has been proved to produce the required expansion profile. This separation prevents the proposal from conflating astrophysical ejecta kinematics with general-relativistic singularity or trapped-surface arguments.

### Energy-Condition Boundary Matrix

| Condition | Formal Requirement | Role in This Proposal | Logical Boundary |
|---|---|---|---|
| NEC (Null Energy Condition) | T_{ab} k^a k^b \geq 0 for every null vector k^a | Provides the minimal stress-energy sign condition for Raychaudhuri focusing if invoked | Does not by itself fix the ejecta expansion timescale; it is a pointwise inequality on the stress tensor |
| ANEC / AANEC (Averaged Null Energy Condition) | \int_{\gamma} T_{ab} k^a k^b d\lambda \geq 0 along a complete null geodesic \gamma | Would strengthen a global focusing or horizon argument; not required by the present timescale-comparison premise | AANEC alone does not establish a trapped surface, a singularity, or the specific delay in fission neutron release assumed here |
| Null convergence / Ricci contraction | R_{ab} k^a k^b \geq 0 for every null vector k^a | The geometric form used in focusing arguments; connects curvature to null geodesic congruences | Stress-energy to Ricci contraction requires Einstein equations plus an explicit relation between T_{ab} and R_{ab}; it is not an automatic interchange with NEC |
| SEC (Strong Energy Condition) | (T_{ab} - \tfrac{1}{2} g_{ab} T) u^a u^b \geq 0 for every timelike u^a | Would constrain timelike convergence and deceleration of a cosmological or bulk flow | SEC is not a substitute for AANEC and does not encode the null-direction physics relevant to light-trapping or lanthanide curtaining |
| Independent focusing hypothesis | Explicit assumption that a congruence of null geodesics contracts under the adopted ejecta model | Reserved for any later theorem that needs geodesic convergence | Must be stated separately; it cannot be inferred from the fission-recycling premise without additional geometric hypotheses |

### Symbolic Dependency Map

**Definition.** The formal symbols are partitioned by their dependency role. The expansion timescale \tau_{expansion} is an externally supplied dynamical parameter that sets the freeze-out clock; it is not derived from an energy condition. The effective fission timescale \tau_{fission} is the microscopic delay governed by beta-decay half-lives and nuclear isomeric states, and it enters the central proposition only through the comparison \tau_{fission} \gtrsim \tau_{expansion}. The abundance and opacity observables Y_{third\_peak} and Kappa_{Lanthanide} are downstream consequences of the delayed neutron release, while Lambda_{Spectral} and Theta_{View} parameterize the viewing-angle-dependent spectral response. The confounders Psi_{Geometry} and B_{Magnetic} enter as competing explanations that must be excluded before the uniqueness claim is accepted. This dependency map keeps the nucleosynthetic mechanism logically distinct from any gravitational focusing argument.

### Transition to the Next Stage

The boundary defense above establishes what the proposal does not assume: it does not require a proved null convergence theorem, nor does it exchange SEC for AANEC. The next stage must therefore supply the missing operational definitions for \tau_{fission}, \tau_{expansion}, Y_{third\_peak}, Kappa_{Lanthanide}, Lambda_{Spectral}, Theta_{View}, Psi_{Geometry}, and B_{Magnetic} before any formal lemma can be advanced beyond candidate status. Until those quantities are fixed, the energy-condition taxonomy remains a guardrail against overclaiming, and the central kinematic-delay proposition stays in the unverified proposal regime.

## Idea Source Checkpoints and Direction Selection Audit

### Audit of Selected Direction and Premise Inversion

The proposed research direction, titled "Kinematic Decoupling of Fission Recycling in Kilonovae," emerges from a premise inversion strategy that relaxes the standard instantaneous fission equilibrium assumption. This shift treats the effective fission timescale as a dynamic variable competing with relativistic ejecta expansion, thereby unifying third r-process peak shifts with anisotropic lanthanide curtaining. The selected direction targets two specific evidence gaps: the lack of direct observational constraints on viewing-angle dependencies and the unresolved phenomenon of relativistic outflows decoupling from multi-messenger progenitor models. By reframing fission recycling as a kinematically delayed process, the proposal aims to distinguish actinide spectral evolution from purely geometric or magnetic asymmetries. [@cite_2bf3a687e25803e4] [@cite_30c88fe46f23448d]

### Available Idea Source Checkpoints

| Checkpoint ID | Source File | Direction Mode | Key Hypothesis Feature |
| :--- | :--- | :--- | :--- |
| checkpoint-1 | idea_candidate.json | premise_inversion | Formal unification of third peak shifts and curtaining |
| checkpoint-2 | idea_portfolio.json | premise_inversion | Emphasis on distinct temporal evolution of actinide lines |
| checkpoint-3 | idea_result.json | premise_inversion | Detailed boundary conditions for geometric confounders |

### Interpretation of Audit Snapshots

The available checkpoints represent audit snapshots rather than a temporal iteration sequence, as their chronological order remains unknown. Checkpoint-1 establishes the core formal relation, positing that kinematic delays in beta-delayed and isomer-delayed fission neutron release modify the third r-process peak freeze-out abundance. Checkpoint-2 refines the observational consequence, highlighting that this delay produces a distinct temporal evolution of actinide spectral lines. Checkpoint-3 provides the most detailed boundary conditions, explicitly stating that the mechanism fails if the effective fission timescale is strictly shorter than the expansion timescale or if geometric asymmetries alone can perfectly replicate the predicted spectral shifts. These snapshots collectively anchor the proposal's focus on isolating the actinide temporal signature from confounding ejecta geometries.

### Alignment with Survey Evidence Gaps

The premise inversion directly addresses the evidence role deficit identified in the survey's gap ledger, specifically the uncovered slot for direct observation in the context of viewing-angle dependencies and three-dimensional geometry effects. By proposing a mechanism that predicts distinct actinide spectral line evolution, the direction provides a testable formal relation that can be constrained by future multi-messenger observations. The alignment with the unmapped gap phenomenon regarding relativistic outflows further strengthens the argument, as the kinematic decoupling of fission recycling offers a new theoretical lens for interpreting the decoupling of central engine evolution from progenitor models. [@cite_30c88fe46f23448d] [@cite_f16e65d18232c78c]

## Evidence Coverage, Unknown Items, and Review Checklist

### Evidence Coverage and Bounded Use

The proposal is anchored in established multi-messenger observations and theoretical models. Kilonova light curves and spectra, such as those from GW170817/AT2017gfo, confirm the radioactive power and high opacity of neutron-rich ejecta, validating the physical domain of the proposed mechanism. Viewing-angle-dependent lanthanide curtaining and the identification of specific spectral features provide the empirical grounding for the delayed fission hypothesis. However, the transition from these observational anchors to the proposed formal theorem is strictly bounded. The formal reasoning plan remains under qualified human review, meaning the candidate theorems and proof obligations are unverified. Furthermore, the operationalization of the dependent variables lacks quantitative definitions, preventing the direct translation of survey evidence into the formal mathematical structure. [@cite_2bf3a687e25803e4] [@cite_492ec5910d5efd57] [@cite_612290131318c0d4]

### Unknown Items and Review Consequences

The primary dependency for advancing the formal theory is the resolution of missing operational definitions. The effective fission timescale, ejecta expansion timescale, and specific spectral line metrics are currently undefined, which blocks the verification of the proposed lemmas and the evaluation of candidate counterexamples. Because these quantitative metrics are absent, the uniqueness assumption of the spectral signature cannot be formally tested. The consequence is a strict procedural dependency: the mathematical theory route cannot proceed to a verified state until these definitions are supplied and the formal reasoning plan clears the required human review.

### Release Criteria for Future Claims

To release the proposed formal claims from their unverified status, the following criteria must be met: 1) Supply explicit mathematical protocols and units for the effective fission timescale and ejecta expansion timescale. 2) Define the specific spectral lines, instruments, and time-sampling intervals required to measure actinide line evolution. 3) Establish quantitative metrics for lanthanide curtaining and geometric asymmetries to test the uniqueness assumption. 4) Complete the qualified human review of the formal reasoning plan to validate the proof obligations and resolve the status of the candidate counterexamples.

## References
- [@cite_19250ec024f92381] Samuel A. Giuliani et al.. *Colloquium : Superheavy elements: Oganesson and beyond*. Reviews of Modern Physics, 2019.
- [@cite_23391c6e806b23a8] Paolo Giannozzi et al.. *QUANTUM ESPRESSO: a modular and open-source software project for quantum simulations of materials*. Journal of Physics Condensed Matter, 2009.
- [@cite_2bf3a687e25803e4] Daniel Kasen et al.. *Kilonova light curves from the disc wind outflows of compact object mergers*. Monthly Notices of the Royal Astronomical Society, 2015.
- [@cite_2e146bff5b4a005e] Wesley Even et al.. *Composition Effects on Kilonova Spectra and Light Curves. I*. The Astrophysical Journal, 2020.
- [@cite_30c88fe46f23448d] C J Horowitz et al.. *r -process nucleosynthesis: connecting rare-isotope beam facilities with the cosmos*. Journal of Physics G Nuclear and Particle Physics, 2019.
- [@cite_357dd780a9e3a378] P. A. R. Ade et al.. *Planck 2015 results*. Astronomy and Astrophysics, 2016.
- [@cite_364386a3569b6e66] N. Aghanim et al.. *Planck 2018 results*. Astronomy and Astrophysics, 2020.
- [@cite_3a00f5f9e5201ba0] Rodrigo Fernández et al.. *Dynamics, nucleosynthesis, and kilonova signature of black hole—neutron star merger ejecta*. Classical and Quantum Gravity, 2017.
- [@cite_403b23aaa35e6b92] Oliver Just et al.. *Comprehensive nucleosynthesis analysis for ejecta of compact binary mergers*. Monthly Notices of the Royal Astronomical Society, 2015.
- [@cite_492ec5910d5efd57] M. R. Drout et al.. *Light curves of the neutron star merger GW170817/SSS17a: Implications for r-process nucleosynthesis*. Science, 2017.
- [@cite_52593a6c02ca6436] Brian D. Metzger. *Kilonovae*. Living Reviews in Relativity, 2017.
- [@cite_572fec0a1e5d74d9] Adam G. Riess et al.. *Observational Evidence from Supernovae for an Accelerating Universe and a Cosmological Constant*. The Astronomical Journal, 1998.
- [@cite_59237db420df3c57] N. Colonna et al.. *The fission experimental programme at the CERN n_TOF facility: status and perspectives*. The European Physical Journal A, 2020.
- [@cite_612290131318c0d4] N. R. Tanvir et al.. *The Emergence of a Lanthanide-rich Kilonova Following the Merger of Two Neutron Stars*. The Astrophysical Journal Letters, 2017.
- [@cite_63ad9f666f512e23] Bernard R. Brooks et al.. *CHARMM: The biomolecular simulation program*. Journal of Computational Chemistry, 2009.
- [@cite_7f5abb972bd2cf6b] B. P. Abbott et al.. *Prospects for observing and localizing gravitational-wave transients with Advanced LIGO, Advanced Virgo and KAGRA*. Living Reviews in Relativity, 2018.
- [@cite_8beeacaea00bd823] Albino Perego et al.. *Neutrino-driven winds from neutron star merger remnants*. Monthly Notices of the Royal Astronomical Society, 2014.
- [@cite_a1ceb4c5ce38d95f] Arne Vansteenkiste et al.. *The design and verification of MuMax3*. AIP Advances, 2014.
- [@cite_b668987a568d271f] Karl‐Heinz Schmidt et al.. *Review on the progress in nuclear fission—experimental methods and theoretical descriptions*. Reports on Progress in Physics, 2018.
- [@cite_b89745a07eed477d] M R Mumpower et al.. *Reverse engineering nuclear properties from rare earth abundances in the r process*. Journal of Physics G Nuclear and Particle Physics, 2017.
- [@cite_b9eb1a62348944b1] W. J. Pearson et al.. *Effect of galaxy mergers on star-formation rates*. Astronomy and Astrophysics, 2019.
- [@cite_bbb76a303fab42b5] Jennifer Barnes et al.. *EFFECT OF A HIGH OPACITY ON THE LIGHT CURVES OF RADIOACTIVELY POWERED TRANSIENTS FROM COMPACT OBJECT MERGERS*. The Astrophysical Journal, 2013.
- [@cite_c5afe6a1f3d54206] Y.‐Z. Qian et al.. *Nucleosynthesis in Neutrino‐driven Winds. I. The Physical Conditions*. The Astrophysical Journal, 1996.
- [@cite_ca1a0cb6340fb16b] N. P. M. Kuin et al.. *Swift spectra of AT2018cow: a white dwarf tidal disruption event?*. Monthly Notices of the Royal Astronomical Society, 2019.
- [@cite_f16e65d18232c78c] David Radice et al.. *Binary Neutron Star Mergers: Mass Ejection, Electromagnetic Counterparts, and Nucleosynthesis*. The Astrophysical Journal, 2018.
- [@cite_f521f70b773ee578] Matthew R. Mumpower et al.. *Primary fission fragment mass yields across the chart of nuclides*. Physical Review C, 2020.
