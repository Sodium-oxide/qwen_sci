# Osmotic and Macromolecular Crowding Gradients Discriminate Membrane-Bounded from Phase-Separated Compartmentalization via Cryo-Electron Tomography

**Keywords:** membrane-bounded organelles, phase-separated condensates, hyperosmotic perturbation, macromolecular crowding, cryo-electron tomography, boundary sharpness, internal densification, computational methodology

## Abstract

This research plan proposes a design-only computational methodology to discriminate between membrane-bounded organelles and phase-separated condensates by modeling sequential osmotic and macromolecular crowding gradients. Macromolecular crowding is a fundamental driver of cellular organization, altering thermodynamic stability and molecular mobility [cite_42ed299a53990c06]. The central hypothesis posits that under controlled hyperosmotic perturbation, membrane-bounded organelles resist internal densification and maintain sharp lipid-defined boundaries, whereas fluid-like phase-separated condensates undergo continuous density shifts and boundary coarsening. This distinction is proposed to hold provided that global cytoskeletal integrity is maintained and non-specific macromolecular precipitation is excluded. The computational framework simulates cellular compartments as experimental units, applying sequential gradient perturbations to evaluate differential boundary sharpness and internal density profiles.

The planned contribution establishes a rigorous theoretical boundary for identifying compartmentalization mechanisms without empirical execution. The design anticipates four prespecified outcome branches: support for the proposed mechanism, partial or heterogeneous responses, null or contradictory findings, and uninformative or invalid results due to confounding factors. These branches map directly to the simulation's ability to distinguish the proposed mechanisms while controlling for alternative explanations such as cytoskeletal compression or salting-out artifacts. By formalizing these conditions, the methodology provides a structured approach to computational synthesis, bridging the gap between descriptive structural biology and mechanistic validation.

## Introduction

### The Physical Reality of Cellular Crowding

The intracellular milieu is not a homogeneous aqueous solution but a densely packed, structurally heterogeneous environment governed by macromolecular crowding. This physical reality imposes rigorous constraints on molecular interactions, transport phenomena, and the thermodynamic stability of biomolecular assemblies. In such crowded conditions, the excluded volume effect elevates the effective chemical potential of solutes, favoring states with reduced excluded volume and thereby promoting compaction, oligomerization, and phase separation. Computational and experimental evidence confirms that increased levels of macromolecular crowding, alongside physiological ionic strength, directly impact protein conformation and target recognition. Consequently, classical dilute-solution models fail to capture the non-ideal thermodynamics that drive intracellular organization, necessitating a framework that explicitly accounts for steric interference and entropic forces. [@cite_42ed299a53990c06] [@cite_8d46403814b99258]

### Divergent Mechanisms of Compartmentalization

Within this crowded landscape, cellular architecture relies on two fundamentally distinct strategies for compartmentalization: membrane-bounded organelles and fluid-like phase-separated condensates. Membrane-bounded organelles achieve isolation through lipid bilayers that act as impermeable barriers, restricting molecular flux to specific transport mechanisms and maintaining sharp boundaries. In contrast, biomolecular condensates emerge from liquid-liquid phase separation (LLPS), driven by multivalent, weak interactions among intrinsically disordered regions and nucleic acids. These condensates function as dynamic, liquid-like phases that coexist with the surrounding cytosol, exchanging components continuously while enriching specific molecular species. While both mechanisms facilitate spatial segregation, they diverge sharply in their response to environmental perturbations and their capacity for rapid compositional switching. [@cite_7161cfcb40366dd0] [@cite_afcca09a0a820cb3]

### The Identifiability Gap in Discriminating Observations

Despite the established dichotomy between membrane-bound and phase-separated compartments, a critical identifiability gap persists in distinguishing these modes of organization under controlled stress conditions. Current observational datasets lack explicit discriminating metrics that consistently differentiate discrete membrane-bounded compartmentalization from fluid-like biomolecular demixing. Specifically, the required evidence slots for 'input_or_condition' and 'candidate_mechanism' remain uncovered in relevant evidence clusters concerning fundamental thermodynamics and non-equilibrium landscapes. Without quantitative thresholds or mechanistic models for dispersed-to-aggregated transitions, it remains challenging to isolate the specific physical principles governing how osmotic pressure gradients modulate macromolecular crowding to drive distinct organizational outcomes in these two compartment types.

### Proposed Contribution: Osmotic Discrimination Strategy

This proposal advances a design-only computational strategy to resolve this identifiability gap by exploiting differential responses to controlled hyperosmotic perturbation. The central hypothesis posits that membrane-bounded organelles resist internal densification and maintain sharp lipid-defined boundaries under osmotic stress, whereas fluid-like phase-separated condensates undergo continuous density shifts and boundary coarsening. This distinction is bounded by conditions where global cytoskeletal integrity is maintained and non-specific macromolecular precipitation is excluded. By modeling osmotic and macromolecular crowding gradients, this approach aims to identify discriminating observations—specifically differential boundary sharpness and internal spatial density profiles—that favor discrete membrane-bounded compartmentalization over fluid-like demixing. This contribution transitions the field from descriptive cataloging to predictive biophysics by establishing a mechanistic link between osmotic pressure gradients and compartment-specific organizational transitions.

## Background, Survey, and Research Gap

### The Physical Reality of Crowding and Demixing

The intracellular milieu operates as a densely packed, structurally heterogeneous environment where macromolecular crowding imposes rigorous physical constraints on molecular interactions, transport phenomena, and the thermodynamic stability of biomolecular assemblies. Unlike dilute aqueous solutions, the cellular interior features a high volume fraction of macromolecules that generate excluded volume effects, elevating the effective chemical potential of solutes and favoring states with reduced excluded volume. This shift in activity coefficients promotes compaction, oligomerization, and phase separation, driving reactions and equilibria that appear unfavorable in dilute buffers to proceed spontaneously within the cell. The cytoplasm functions as a dynamic, heterogeneous porous medium rather than a simple Newtonian fluid, where the fluctuating meshwork of proteins and nucleic acids creates a tortuous path for diffusing molecules. Empirical investigations utilizing inert tracers demonstrate that diffusion coefficients within the bulk cytoplasm are orders of magnitude lower than those predicted by the Stokes-Einstein equation, revealing that molecular motion is coupled to the mechanical state of the cytoplasm. This physical reality establishes the baseline conditions under which all cellular processes operate, rendering dilute approximations increasingly inaccurate as one approaches physiological densities. [@cite_42ed299a53990c06]

### Divergent Strategies for Compartmentalization

Within this crowded landscape, the cell employs two primary strategies for spatial organization: membrane-bounded organelles and liquid-liquid phase separation (LLPS)-driven condensates. Membrane-bounded compartments rely on lipid bilayers to establish impermeable barriers that strictly regulate molecular flux via active transport machineries, providing stable isolation but limited plasticity. In contrast, biomolecular condensates emerge from the thermodynamic demixing of macromolecules driven by multivalent, weak interactions involving intrinsically disordered regions (IDRs), folded domains, and nucleic acids. These membrane-less compartments represent dynamic, liquid-like phases that coexist with the surrounding cytosol, exchanging components continuously while enriching specific molecular species. The distinction is not merely physical containment but reflects divergent strategies for regulating molecular localization and functional coordination. While membranes achieve isolation through barriers, LLPS achieves compartmentalization through differential partition coefficients governed by solution thermodynamics. This dichotomy creates a critical need to understand how these two modes of organization interact, particularly under environmental stress where the boundaries between discrete compartments and fluid-like demixing may blur. [@cite_7161cfcb40366dd0] [@cite_afcca09a0a820cb3]

### Methodological Constraints in Structural Characterization

Advanced imaging modalities, particularly cryo-electron tomography (cryo-ET), have revolutionized the capacity to visualize ultrastructure at near-physiological conditions. By rapidly vitrifying samples, cryo-ET preserves the native hydration and conformational states of biomolecules, circumventing dehydration and chemical fixation artifacts. Recent innovations, such as focused ion beam (FIB) milling, enable the precise thinning of intact cells into electron-transparent lamellae, facilitating high-resolution tomographic reconstruction of intracellular compartments. Despite these strides, cryo-ET primarily provides static snapshots of molecular density distributions. Translating raw imaging data into mechanistic insights remains constrained by calibration gaps and resolution mismatches. The integration of cryo-fluorescence microscopy creates powerful correlative platforms but introduces fundamental methodological challenges: the validation of fluorescence signals as proxies for true nanoscale molecular organization. Fluorescent markers provide highly sensitive readouts of protein presence, but their intensity does not linearly correlate with local concentration due to factors such as fluorophore maturation efficiency, photobleaching, and quenching effects in dense phases. Consequently, mapping fluorescence intensities to true nanoscale molecular densities requires rigorous calibration against independent reference measures, which are currently lacking in standardized protocols. [@cite_9ae4c49700eea560] [@cite_c2d09a021a2238e3]

### Survey Evidence Gaps in Discriminating Compartmentalization Modes

| Gap Category | Missing Evidence Slot | Consequence for Mechanistic Modeling |
| :--- | :--- | :--- |
| Input/Condition | Defined inputs or condition changes with reported effects on biomolecular organization. | Inability to link specific osmotic or crowding perturbations to observable organizational transitions. |
| Mechanism | Explicit mechanisms proposed or tested for producing organizational outcomes. | Failure to distinguish between thermodynamic demixing and mechanical compression or precipitation artifacts. |
| Discriminating Observation | Measurements that differ predictably under competing mechanisms. | Lack of logical power to favor, weaken, or distinguish between membrane-bound and phase-separated models. |

### The Unresolved Bridge: Osmotic Perturbation and Boundary Definition

The central research gap lies in the absence of discriminating observations that distinguish conditions favoring discrete membrane-bounded compartmentalization from those favoring fluid-like biomolecular demixing. Specifically, the Survey evidence plan identifies a missing 'input_or_condition' slot regarding how osmotic pressure gradients modulate macromolecular crowding to drive transitions. While hyperosmotic shock is known to increase crowding, its differential impact on lipid-defined boundaries versus protein-RNA condensates remains poorly characterized. Current literature lacks quantitative thresholds and mechanistic models for dispersed-to-aggregated transitions in native, crowded environments. The proposed direction posits that membrane-bounded organelles resist internal densification and maintain sharp boundaries under controlled perturbation, whereas phase-separated condensates undergo continuous density shifts and boundary coarsening. However, this distinction is contingent on excluding confounders such as global cytoskeletal collapse and non-specific macromolecular precipitation. Without explicit boundary condition definitions and validated discriminating observations, the field cannot move beyond descriptive correlations to predictive models of multiscale organization. [@cite_7161cfcb40366dd0]

### Transition to Design Strategy

Addressing these gaps requires a design-only computational strategy that models osmotic and macromolecular crowding gradients to discriminate compartmentalization modes. The proposed approach integrates simulated density profiles and boundary discontinuities, bounded by conditions where global cytoskeletal collapse and non-specific salting-out are controlled. This transition from identifying the evidentiary void to specifying the computational design framework sets the stage for the subsequent formal argument. The next section will detail the specific hypotheses and operational definitions required to test this discrimination, ensuring that the proposed methodology addresses the identified lack of discriminating observations and mechanistic clarity.

## Research Questions and Planned Contributions

### The Identifiability Gap in Compartmentalization Mechanisms

The central research question asks whether osmotic and macromolecular crowding gradients can provide a computational discriminator between membrane-bounded organelles and fluid-like phase-separated condensates. Macromolecular crowding is a fundamental paradigm shift in biophysics, moving beyond dilute solution approximations to recognize that the cytoplasm is a densely packed environment that modulates molecular availability and reaction networks [W4392638806]. While the distinction between lipid-defined boundaries and liquid-liquid phase separation (LLPS) is theoretically established, the Survey evidence plan identifies a critical identifiability gap: a lack of explicit discriminating observations that distinguish conditions favoring discrete membrane-bounded compartmentalization from those favoring fluid-like biomolecular demixing. This proposal addresses that gap by positing that hyperosmotic perturbation induces divergent structural responses—volume reduction without internal densification in membrane-bound systems versus continuous density shifts and boundary coarsening in condensates. [@cite_42ed299a53990c06]

### Planned Contributions to Computational Methodology

The contribution of this design-only computational methodology is threefold. First, it operationalizes a differential boundary condition definition for simulated cellular compartments, explicitly modeling the impermeability of lipid bilayers against the dynamic exchange of LLPS condensates. Second, it establishes a quantitative framework for simulated density profiles and boundary discontinuities, moving beyond qualitative co-localization to measurable spatial gradients. Third, it integrates controls for global cytoskeletal integrity and non-specific precipitation, which are identified as primary confounders that obscure the specific phase-separation mechanism. By synthesizing cryo-electron tomography (cryo-ET) capabilities with computational modeling, the design aims to resolve nanoscale spatial density profiles that are otherwise obscured by fixation artifacts or resolution mismatches [W4375948977].

### Design Boundaries and Operational Constraints

| Design Element | Operational Definition | Constraint / Boundary Condition |
| :--- | :--- | :--- |
| **Perturbation** | Simulated hyperosmotic gradient | Must exclude global cytoskeletal collapse |
| **Readout** | Simulated density profile | Requires quantitative boundary sharpness metric |
| **Confounder** | Non-specific precipitation | Exclusion criteria required for salting-out artifacts |
| **Mechanism** | Lipid impermeability vs. demixing | Distinct response to water flux inhibition |

The proposed mechanism relies on the assumption that aquaporin inhibition specifically blocks water flux without inducing non-specific protein aggregation. However, the quantitative metric for boundary sharpness and the mathematical model for global cytoskeletal integrity remain undefined in the current design phase. These unresolved items delimit the scope of the research questions, requiring human confirmation of measurement and analysis prerequisites before the design can yield interpretable evidence. [@cite_9ae4c49700eea560]

### Transition to Formal Problem Definition

This section establishes the intellectual labor of defining the research gap and the proposed computational strategy. The transition to the next stage requires formalizing the boundary conditions for the hypothesis. Specifically, the claim fails if membrane-bounded organelles exhibit continuous density gradients due to cytoskeletal compression, or if phase-separated condensates maintain sharp boundaries. The subsequent section will define the mathematical criteria for these failure conditions, ensuring that the distinction between membrane-bound and phase-separated states is rigorously tested against the alternative explanations of non-specific salting-out and global cellular collapse.

## Idea Source Checkpoints and Direction Selection Audit

### The Scientific Attraction of the Mechanism-Replacement Route

The selected direction, "Osmotic and Macromolecular Crowding Gradients Discriminate Membrane-Bounded from Phase-Separated Compartmentalization via Cryo-Electron Tomography," addresses a critical identifiability gap in contemporary cell biology: the absence of quantitative observables that consistently distinguish discrete membrane-bounded compartments from fluid-like biomolecular demixing. This proposal is scientifically attractive because it leverages a robust physical asymmetry. Established evidence confirms that macromolecules function within a crowded environment populated by numerous different molecules rather than acting in isolation, which fundamentally alters thermodynamic stability and promotes phase separation. Furthermore, multivalent interactions involving intrinsically disordered regions are known to drive liquid-liquid phase separation (LLPS). By proposing a design-only computational methodology to model osmotic gradients and water-flux inhibition, the route aims to exploit the distinct boundary conditions of these two compartment types. Specifically, it posits that lipid bilayer impermeability restricts membrane-bounded organelles to volume reduction without internal densification, whereas phase-separated condensates undergo continuous density shifts and boundary coarsening. This mechanism-replacement approach offers a predictive framework for resolving the ambiguity between functional LLPS and aberrant aggregation. [@cite_42ed299a53990c06] [@cite_7161cfcb40366dd0]

### Defects and Unsupported Links Exposed by Checkpoints

Despite its theoretical appeal, the audit snapshots reveal significant methodological defects and unsupported links that currently limit the proposal's rigor. First, the operational definitions for the core constructs—"membrane_bounded_organelle" and "phase_separated_condensate"—remain unresolved and require explicit human methodology review. Second, the hypothesis relies on critical assumptions that lack formal mathematical modeling or empirical validation within the current design. For instance, the claim that cryo-electron tomography (cryo-ET) can resolve nanoscale spatial density profiles without fixation artifacts is contested by evidence indicating that correlative workflows suffer from registration uncertainties and resolution mismatches. Similarly, the assumption that aquaporin inhibition specifically blocks water flux without inducing global cytoskeletal collapse is not supported by a defined control metric. The checkpoints also expose a lack of quantitative thresholds for distinguishing the primary mechanism from confounders, such as non-specific protein aggregation or global cellular collapse induced by hyperosmotic shock. Without predefined criteria for boundary sharpness and internal density gradients, the proposed discriminating observations cannot logically separate the declared mechanism from alternative explanations. [@cite_9ae4c49700eea560] [@cite_c2d09a021a2238e3]

### Qualified Retained Direction and Explicit Exclusions

The direction is retained as a valid design-only computational strategy, provided that the following exclusions and boundary conditions are strictly enforced to prevent invalid inference:

1. Exclusion of Uncontrolled Confounders: The analysis must explicitly model and exclude scenarios where global cytoskeletal compression mechanically alters membrane-bound organelles, or where non-specific salting-out produces identical density profiles across all compartments. If these confounders are not mathematically isolated, the proposed observables (boundary discontinuity and density gradient) yield no information about the specific phase-separation mechanism.
2. Rejection of Direct Empirical Validation: Given the absence of observed results and the unresolved measurement calibration, this route is restricted to computational synthesis. Claims regarding the actual in vivo behavior of specific organelles (e.g., mitochondria or TDP-43 condensates) are excluded unless supported by the proposed simulation parameters.
3. Requirement for Explicit Boundary Definitions: The claim is bounded by the condition that the distinction between compartment types holds only when global cytoskeletal integrity is maintained and non-specific precipitation is excluded. Any outcome where membrane-bound organelles exhibit continuous density gradients due to mechanical compression, or where condensates maintain sharp boundaries, falsifies the specific mechanism-replacement hypothesis within this design scope. [@cite_3480a6462f7a2d86]

## Problem Definition, Assumptions, and Hypotheses

### The Formal Discrimination Problem

The central problem addressed by this proposal is the formal identification of compartmentalization mechanisms in crowded cellular environments. Distinguishing membrane-bounded organelles from fluid-like phase-separated condensates is currently constrained by a lack of quantitative discriminating observations that remain robust under environmental perturbation. This route proposes a design-only computational strategy to resolve this identifiability gap. The core hypothesis posits that under controlled hyperosmotic perturbation, membrane-bounded organelles resist internal densification and maintain sharp lipid-defined boundaries, whereas fluid-like phase-separated condensates undergo continuous density shifts and boundary coarsening. This differential response is proposed to emerge from the fundamental physical distinction between the two systems: lipid bilayer impermeability restricts membrane-bounded organelles primarily to volume reduction, while osmotic pressure gradients modulate macromolecular crowding and multivalent interactions to drive dispersed-to-aggregated transitions in condensates. [@cite_42ed299a53990c06] [@cite_7161cfcb40366dd0] [@cite_81a08c2c7b9c90d0]

### Proposed mathematical dependency

H_{condensate} \neq H_{membrane} [@cite_7161cfcb40366dd0] [@cite_81a08c2c7b9c90d0]

### Operationalization of the Discriminating Observation

The formal problem requires an operational definition of the discriminating observation. The proposed metric relies on the differential boundary sharpness and internal spatial density profiles measured via cryo-tomography assays. Specifically, condensates are expected to exhibit continuous density gradients and fusion, while membrane-bounded organelles are expected to exhibit sharp density discontinuities and volume reduction without fusion. This distinction holds provided that global cytoskeletal integrity is maintained and non-specific macromolecular precipitation is excluded. The mathematical formulation of this distinction is expressed as the inequality between the Hamiltonian of the condensate phase and the Hamiltonian of the membrane phase. This inequality asserts that the energy landscape governing the condensate boundary responds to osmotic pressure differently than the energy landscape governing the membrane boundary. [@cite_7161cfcb40366dd0] [@cite_8d46403814b99258]

### Assumption Ledger and Boundary Conditions

The validity of the proposed computational strategy is bounded by specific physical and methodological assumptions. The claim fails if membrane-bounded organelles exhibit continuous density gradients and fusion due to cytoskeletal compression, or if phase-separated condensates maintain sharp boundaries, or if non-specific salting-out produces identical density profiles across all compartments. To prevent these failure modes, the design assumes that cryo-ET can resolve nanoscale spatial density profiles without fixation artifacts, that aquaporin inhibition specifically blocks water flux, and that hyperosmotic conditions can be applied without inducing global cytoskeletal collapse or non-specific protein precipitation. These assumptions define the admissible domain of the problem and must be explicitly controlled in the simulation design. [@cite_9ae4c49700eea560] [@cite_c2d09a021a2238e3] [@cite_e2b5e3dbdb69d6a2]

### Transition to Expected Outcomes

The defined problem, operationalized hypothesis, and bounded assumptions establish the criteria for evaluating the proposed computational strategy. The next stage of the research plan will detail the expected outcomes under these conditions, mapping prespecified outcome branches to the relevant hypothesis and design controls. This transition ensures that the formal problem definition directly informs the decision protocol for interpreting simulated density profiles and boundary discontinuities.

## Study Design and Methods

### Design Architecture and Unit of Analysis

This proposal specifies a design-only computational methodology to discriminate membrane-bounded organelles from phase-separated condensates via simulated osmotic and macromolecular crowding gradients. The experimental unit is the simulated cellular compartment, subjected to sequential gradient application. The central hypothesis posits that membrane-bounded organelles resist internal densification and maintain sharp lipid-defined boundaries, whereas fluid-like phase-separated condensates undergo continuous density shifts and boundary coarsening. This distinction holds provided that global cytoskeletal integrity is maintained and non-specific macromolecular precipitation is excluded. The design integrates cryo-electron tomography principles for spatial density profiling, bounded by conditions where cytoskeletal artifacts and salting-out confounders are controlled. Macromolecular crowding acts as a universal modifier of molecular energetics, setting the baseline conditions under which cellular processes operate (W4392638806). [@cite_42ed299a53990c06]

### Variables and Operational Definitions

The study design operationalizes the following variables, with specific definitions pending human methodology review:

*   **Independent Variables:** Simulated osmotic gradient and simulated water flux inhibition (aquaporin inhibition).
*   **Dependent Variables:** Simulated density profile and simulated boundary discontinuity.
*   **Control Variables:** Simulated crowding environment and simulated ionic strength.
*   **Confounders:** Simulated cytoskeletal compression and simulated non-specific precipitation.
*   **Operational Definitions:** The constructs 'membrane_bounded_organelle' and 'phase_separated_condensate' require explicit quantitative definitions for boundary sharpness and internal density gradients, which are currently marked for human input.

### Boundary Conditions and Failure Modes

| Condition | Description | Impact on Hypothesis |
| :--- | :--- | :--- |
| **Cytoskeletal Integrity** | Global cytoskeletal collapse or compression. | **Failure:** Causes apparent boundary blurring and internal density shifts in membrane-bounded organelles, mimicking condensate behavior. |
| **Non-specific Precipitation** | Salting-out or protein aggregation at high osmolyte concentrations. | **Failure:** Produces artificial density gradients in all compartments, obscuring specific phase-separation mechanisms. |
| **Condensate Boundaries** | Phase-separated condensates maintain sharp boundaries. | **Failure:** Contradicts the premise of fluid-like demixing and continuous density shifts. |
| **Organelle Gradients** | Membrane-bounded organelles exhibit continuous internal density gradients. | **Failure:** Contradicts the premise of volume reduction without internal densification. |

The claim fails if membrane-bounded organelles exhibit continuous density gradients and fusion due to cytoskeletal compression, or if phase-separated condensates maintain sharp boundaries, or if non-specific salting-out produces identical density profiles across all compartments.

### Prespecified Outcome Branches

**Pre-registered Branch (Expected---Not Observed).** The design prespecifies four outcome branches based on the comparison of simulated density profiles and boundary sharpness:

1.  **Supports Mechanism:** The prespecified analysis is consistent with the declared relation while planned controls do not favor a stated alternative explanation. This supports, but does not prove, the relation within the design boundary.
2.  **Partial or Heterogeneous:** The prespecified analysis indicates variation across declared conditions, units, or measurement contexts. No universal conclusion is warranted.
3.  **Null or Contradictory:** The prespecified comparison does not support the declared relation or instead favors a declared alternative explanation. Absence of support is not proof of absence generally.
4.  **Uninformative or Invalid:** Prespecified quality-control, missingness, protocol-deviation, or validity criteria prevent interpretation. No scientific conclusion is warranted.

### Required Human Inputs for Design Finalization

**Human-review checklist (Review-required).** The following design elements are currently unresolved and require human methodology review before execution:

*   **Analysis Plan:** Batch effects, blinding, missing data handling, randomization, repetitions, and statistical analysis.
*   **Comparison and Robustness:** Specific comparator conditions and robustness checks.
*   **Data Governance:** Data management and reproducibility protocols.
*   **Measurement:** Calibration, measurement plan, and quality control procedures.
*   **Sampling:** Eligibility criteria, sample size/power basis, and source definitions.

These items are marked as needs_human_input in the canonical field statuses.

## Expected Outcome Branches and Conditional Conclusions

### Prespecified Decision Matrix

| Outcome Branch | Prespecified Trigger | Allowed Conclusion | Next Action |
|---|---|---|---|
| Supports Mechanism | Density profiles and boundary discontinuities match the declared relation while controls exclude cytoskeletal compression and salting-out. | The computational design yields evidence consistent with the proposed osmotic discrimination mechanism within the stated boundary. | Replicate under independently confirmed simulation conditions and test the most consequential declared boundary condition. |
| Partial or Heterogeneous | Variation across simulated osmotic gradients, crowding environments, or ionic strengths. | The relation is conditional on specific parameter regimes; no universal conclusion is warranted. | Predefine and check plausible moderators; improve coverage of conditions and measurement comparability. |
| Null or Contradictory | Membrane-bounded organelles exhibit continuous density gradients and fusion, or condensates maintain sharp boundaries, or salting-out produces identical profiles. | The proposed relation is not supported in this design boundary; absence of support is not proof of absence generally. | Audit construct validity and comparison adequacy; revise the mechanism or boundary claim before another design iteration. |
| Uninformative or Invalid | Quality-control, missingness, or protocol-deviation criteria prevent interpretation. | No scientific conclusion is warranted because the planned design did not yield interpretable evidence. | Resolve the identified validity or data-quality failure before repeating the design; obtain human confirmation of measurement, sampling, and analysis prerequisites. | [@cite_42ed299a53990c06] [@cite_7161cfcb40366dd0] [@cite_099ed712535e9d67] [@cite_8d46403814b99258] [@cite_3222d2eeb7add195] [@cite_3480a6462f7a2d86] [@cite_06a078fea514798a] [@cite_90e000f6b0c99ee8]

### Supportive Branch Interpretation

**Pre-registered Branch (Expected---Not Observed).** A supportive outcome occurs when simulated membrane-bounded organelles maintain sharp density discontinuities and resist internal densification under hyperosmotic perturbation, whereas phase-separated condensates exhibit continuous density shifts and boundary coarsening. This result would support, but not prove, the declared relation within the design boundary. The interpretation is constrained by the requirement that global cytoskeletal integrity is maintained and non-specific macromolecular precipitation is excluded. If these boundary conditions are not independently confirmed, the supportive conclusion is invalid. [@cite_42ed299a53990c06] [@cite_7161cfcb40366dd0]

### Null or Contradictory Branch Interpretation

**Pre-registered Branch (Expected---Not Observed).** The claim fails if membrane-bounded organelles exhibit continuous density gradients and fusion due to cytoskeletal compression, or if phase-separated condensates maintain sharp boundaries, or if non-specific salting-out produces identical density profiles across all compartments. A null or contradictory outcome indicates that the proposed relation is not supported in this design boundary. This result does not prove the absence of the mechanism generally, but it invalidates the current computational strategy as a discriminating observation. The next action requires auditing construct validity and comparison adequacy, followed by revising the mechanism or boundary claim. [@cite_3222d2eeb7add195] [@cite_3480a6462f7a2d86]

### Uninformative or Invalid Branch Interpretation

**Pre-registered Branch (Expected---Not Observed).** An uninformative or invalid outcome arises when prespecified quality-control, missingness, protocol-deviation, or validity criteria prevent interpretation. No scientific conclusion is warranted because the planned design did not yield interpretable evidence. This branch is distinct from a null result; it signifies a failure of the design to generate data capable of testing the hypothesis. The immediate next action is to resolve the identified validity or data-quality failure before repeating the design, and to obtain human confirmation of measurement, sampling, and analysis prerequisites. [@cite_06a078fea514798a] [@cite_90e000f6b0c99ee8]

## Risks, Limitations, and Human Review Requirements

### Scope Boundaries and Mechanistic Risks

This research plan proposes a design-only computational methodology to distinguish membrane-bounded organelles from phase-separated condensates under hyperosmotic stress. The scope is strictly bounded by the requirement that global cytoskeletal collapse and non-specific macromolecular precipitation are excluded. These boundary conditions are not merely operational details; they define the logical limits of the proposed mechanism. If hyperosmotic shock induces global cellular collapse, mechanical compression of organelles will mimic the density shifts of condensates, invalidating the comparison. Similarly, if non-specific salting-out occurs at high osmolyte concentrations, artificial aggregation will obscure the specific phase-separation signal. The proposal relies on the assumption that cryo-electron tomography can resolve nanoscale spatial density profiles without fixation artifacts, a premise that requires rigorous validation before any computational synthesis is considered evidence-backed. [@cite_3480a6462f7a2d86] [@cite_3222d2eeb7add195] [@cite_42ed299a53990c06]

### Evidence Gaps and Measurement Validity

A critical limitation is the absence of quantitative metrics for the proposed observables. The current design lacks a defined mathematical model for 'boundary sharpness' and 'internal density gradient' derived from simulated or measured cryo-tomography data. Without these definitions, the hypothesis remains untestable. Furthermore, the operational definitions for the core constructs—'membrane_bounded_organelle' and 'phase_separated_condensate'—are pending human methodology review. The survey evidence indicates that current imaging proxies, such as fluorescence intensity, do not linearly correlate with local molecular concentration due to quenching and steric hindrance. This calibration gap means that even if the computational design is sound, translating it into empirical measurement requires resolving significant validation hurdles. The risk of misinterpretation is high unless explicit calibration protocols against ground-truth density maps are established.

### Decision Matrix for Review and Release Conditions

| Risk/Review Item | Trigger Condition | Required Action | Release Gate |
| :--- | :--- | :--- | :--- |
| **Canonical Risk Gate** | Final plan requires qualified human review. | Expert validation of the design-only computational approach. | Approval of the methodology before any simulation execution. |
| **Life Science Review** | Proposed perturbations involve biological systems (osmotic shock, aquaporin inhibition). | Ethical and safety review of proposed biological protocols. | Confirmation that no live-cell experiments are conducted without prior clearance. |
| **Metric Definition** | Lack of quantitative definition for boundary sharpness. | Development of a mathematical criterion for density discontinuities. | Publication of the metric definition in the analysis plan. |
| **Artifact Control** | Ambiguity in excluding cytoskeletal compression artifacts. | Specification of control conditions for cytoskeletal integrity. | Validation that controls can distinguish mechanical compression from phase separation. | [@cite_9ae4c49700eea560] [@cite_e2b5e3dbdb69d6a2]

### Human Review Requirements

**Human-review checklist (Review-required).** The following items require explicit human confirmation before the research plan can proceed to the simulation phase:
1. **Risk Gate Approval:** The final canonical risk gate requires qualified human review to validate the design-only computational strategy.
2. **Life Science/Ethics Review:** The proposed biological perturbations (hyperosmotic shock, aquaporin inhibition) trigger a LIFE_SCIENCE_OR_VETERINARY_REVIEW. This review must confirm that the design remains theoretical and that any future experimental translation adheres to safety and ethical standards.
3. **Operational Definitions:** The definitions for 'membrane_bounded_organelle' and 'phase_separated_condensate' must be formally approved by a methodology expert to ensure construct validity.

## Model System, Controls, Assays, and Replicates

### Simulated Cellular Compartments and Sequential Gradient Application

The proposed methodology operates exclusively as a design-only computational strategy, with the simulated cellular compartment serving as the experimental unit and sequential gradient application structuring the time axis. This architecture models two distinct classes of biomolecular organization: membrane-bounded organelles and phase-separated condensates. The core mechanism posits that osmotic pressure gradients modulate macromolecular crowding and multivalent interactions, driving dispersed-to-aggregated transitions in condensates, while lipid bilayer impermeability restricts membrane-bounded organelles to volume reduction without internal densification. Because macromolecules function in a crowded environment populated by numerous different molecules rather than acting in isolation, the computational model must explicitly parameterize the simulated crowding environment and ionic strength as control variables. The independent variables are the simulated osmotic gradient and water flux inhibition, while the dependent variables are the simulated density profile and boundary discontinuity. Operational definitions for the two compartment classes remain pending human methodology review, but the design assumes that Cryo-ET can resolve nanoscale spatial density profiles without fixation artifacts, and that aquaporin inhibition specifically blocks water flux. [@cite_42ed299a53990c06] [@cite_8d46403814b99258]

### Design Controls and Confounder Mitigation

| Condition | Control Type | Mitigation Strategy | Evidence Anchor |
| :--- | :--- | :--- | :--- |
| Hyperosmotic Shock | Primary Perturbation | Sequential application to model crowding gradients | Selected Direction |
| Water Flux Inhibition | Independent Variable | Simulated aquaporin ablation to isolate osmotic effects | Assumption |
| Cytoskeletal Compression | Confounder | Explicit modeling of global cytoskeletal integrity | Alternative Explanation |
| Non-specific Precipitation | Confounder | Threshold-based exclusion of salting-out artifacts | Boundary Condition |

The design explicitly addresses two major alternative explanations that threaten the identifiability of the proposed mechanism. First, global cytoskeletal collapse under hyperosmotic stress may mechanically compress membrane-bounded organelles, causing apparent boundary blurring and internal density shifts that mimic phase-separated condensate behavior. Second, non-specific protein salting-out or precipitation at high osmolyte concentrations causes artificial aggregation and density gradients in all compartments, obscuring the specific phase-separation mechanism. The proposed computational controls must therefore include explicit predicates for the absence of these artifacts. The claim fails if membrane-bounded organelles exhibit continuous density gradients and fusion due to cytoskeletal compression, or if phase-separated condensates maintain sharp boundaries, or if non-specific salting-out produces identical density profiles across all compartments. [@cite_3222d2eeb7add195] [@cite_3480a6462f7a2d86]

### Cryo-ET Assay Integration and Replication Logic

The discriminating observation relies on differential boundary sharpness and internal spatial density profiles measured via a proposed cryo-tomography assay. Condensates are expected to exhibit continuous density gradients and fusion, while membrane-bounded organelles are expected to exhibit sharp density discontinuities and volume reduction without fusion. The computational synthesis integrates cryo-fluorescence microscopy and cryo-electron tomography measurements of spatial density profiles under osmotic gradients, contrasted against water-flux ablation and swelling stress boundaries. However, the quantitative metric for defining boundary sharpness in simulations and the mathematical modeling of global cytoskeletal integrity remain open design questions requiring human input. Replication logic for the simulated experimental unit must be predefined to ensure coverage of conditions and measurement comparability, as the relation may be conditional or heterogeneous across different biological contexts. The design does not yet specify the exact instrument settings for cryo-tomography or the formal predicate for fixation artifact absence, which are critical for validating the proxy measurements against ground truth. [@cite_9ae4c49700eea560] [@cite_e2b5e3dbdb69d6a2] [@cite_42ed299a53990c06]

# Appendices

## Idea Source Checkpoints and Direction Selection Audit

### Mechanism Replacement Rationale

The selected direction, mechanism_replacement, advances the proposal by shifting the comparative focus from mere structural presence to dynamic boundary resistance under controlled hyperosmotic perturbation. This pivot responds directly to the identifiability gap where existing observations fail to distinguish discrete membrane-bounded compartmentalization from fluid-like biomolecular demixing. The core hypothesis posits that membrane-bounded organelles resist internal densification and maintain sharp lipid-defined boundaries, whereas phase-separated condensates undergo continuous density shifts and boundary coarsening. This distinction is contingent upon maintaining global cytoskeletal integrity and excluding non-specific macromolecular precipitation, which are declared as strict boundary conditions for the computational design. [@cite_42ed299a53990c06]

### Evidentiary Anchors for Boundary Sharpness

The proposed differential relies on established biophysical mechanisms where osmotic pressure gradients modulate macromolecular crowding. Multivalent interactions drive dispersed-to-aggregated transitions in condensates, while lipid bilayer impermeability restricts membrane-bounded organelles to volume reduction without internal densification. This mechanistic relation is grounded in the understanding that macromolecules function in a crowded environment populated by numerous different molecules rather than acting in isolation. The design utilizes cryo-electron tomography as the reference modality to resolve nanoscale spatial density profiles, specifically targeting the simulated boundary discontinuity and internal density gradients as the primary observables. [@cite_42ed299a53990c06] [@cite_7161cfcb40366dd0]

### Audit of Design Constraints and Open Dependencies

The audit snapshot confirms that the direction selection remains a design-only computational methodology. Critical operational definitions for both membrane_bounded_organelle and phase_separated_condensate are explicitly marked as requiring human methodology review. Furthermore, the exclusion of confounding artifacts, such as cytoskeletal compression and non-specific salting-out, is currently bounded by unquantified thresholds. These unresolved parameters constitute the primary procedural dependencies for the next stage of the research plan, dictating that the computational strategy cannot be validated until the quantitative metrics for boundary sharpness and cytoskeletal integrity are formally defined.

## Variables, Symbols, and Operational Definitions

### Variable Architecture and Operational Scope

This appendix establishes the variable architecture for the proposed design-only computational methodology, which aims to discriminate between membrane-bounded organelles and phase-separated condensates under hyperosmotic stress. The experimental unit is defined as a simulated cellular compartment subjected to sequential gradient application. The independent variables, simulated_osmotic_gradient and simulated_water_flux_inhibition, drive the system state, while the dependent variables, simulated_density_profile and simulated_boundary_discontinuity, capture the resulting organizational response. Control variables, simulated_crowding_environment and simulated_ionic_strength, are maintained to isolate the osmotic mechanism. Confounders, simulated_cytoskeletal_compression and simulated_nonspecific_precipitation, are explicitly modeled to test the boundary conditions of the central hypothesis. The operational definitions for the core constructs, membrane_bounded_organelle and phase_separated_condensate, currently require human methodology review to ensure formal consistency with cryo-electron tomography constraints.

### Variable Taxonomy and Operational Status

| Variable Group | Variable Name | Operational Role | Status | Required Human Input |
| :--- | :--- | :--- | :--- | :--- |
| Independent | simulated_osmotic_gradient | Drives hyperosmotic stress | Design Assumption | Specific shock parameters (unknown-28) |
| Independent | simulated_water_flux_inhibition | Blocks aquaporin-mediated flux | Design Assumption | Specific inhibition method (unknown-34) |
| Dependent | simulated_density_profile | Measures internal densification | Design Assumption | Quantitative profile definition (unknown-36) |
| Dependent | simulated_boundary_discontinuity | Measures boundary sharpness | Design Assumption | Quantitative sharpness metric (unknown-35) |
| Control | simulated_crowding_environment | Maintains baseline macromolecular crowding | Design Assumption | None |
| Control | simulated_ionic_strength | Maintains electrostatic screening | Design Assumption | None |
| Confounder | simulated_cytoskeletal_compression | Tests mechanical collapse artifact | Design Assumption | Integrity control criteria (unknown-39) |
| Confounder | simulated_nonspecific_precipitation | Tests salting-out artifact | Design Assumption | Precipitation control criteria (unknown-40) |
| Construct | membrane_bounded_organelle | Target class for sharp boundaries | Needs Human Input | Formal definition (unknown-37, unknown-42) |
| Construct | phase_separated_condensate | Target class for continuous gradients | Needs Human Input | Formal definition (unknown-38, unknown-43) |

### Instrument and Protocol Dependencies

The computational model relies on simulated data analogous to cryo-electron tomography (cryo-ET) outputs. Consequently, the operational definitions for instrument settings (unknown-30) and the predicate for fixation artifact absence (unknown-31) are critical for validating the simulated density profiles. The hypothesis assumes that aquaporin inhibition specifically blocks water flux (unknown-32) and that hyperosmotic conditions do not induce global cytoskeletal collapse or non-specific protein precipitation. These assumptions define the boundary conditions for the claim; if cytoskeletal compression (unknown-41) or salting-out artifacts (unknown-29) are not rigorously excluded, the distinction between membrane-bounded and phase-separated compartments becomes unidentifiable. The condition safety predicate (unknown-33) further constrains the applicability of the simulated osmotic gradients.

## Evidence Coverage, Unknown Items, and Review Checklist

### Evidence Coverage and Source Boundaries

The design-only computational strategy is anchored in established biophysical principles. Macromolecular crowding functions as a universal modifier of molecular energetics, shifting activity coefficients and promoting compaction or phase separation through excluded volume effects (W4392638806). Osmotic gradients directly modulate this crowding, driving dispersed-to-aggregated transitions in phase-separated condensates via steric exclusion, as supported by computational models of protein dynamics under crowded conditions (W2037475414). Conversely, membrane-bounded organelles are constrained by lipid bilayer impermeability, restricting their response to volume reduction without internal densification. This mechanistic distinction relies on cryo-electron tomography to resolve nanoscale spatial density profiles in near-native conditions (W4375948977). However, the transition from qualitative imaging to quantitative density profiling requires rigorous validation, as cryo-ET proxies are subject to limitations and potential artifacts (W3167557279). [@cite_42ed299a53990c06] [@cite_8d46403814b99258] [@cite_9ae4c49700eea560] [@cite_c2d09a021a2238e3]

### Unresolved Operational Parameters

The current proposal lacks specific operational definitions required to execute the computational design. The following canonical fields remain unresolved and require human input to establish the precise boundary conditions for the simulated compartments:

- The specific biological system and osmotic perturbation parameters are undefined, preventing the calibration of the simulated osmotic gradient.
- The phenotype or pathway readout, specifically the quantitative metrics for boundary sharpness and internal density gradients, requires formal mathematical definition.
- The positive and negative controls, including the specific criteria for aquaporin inhibition and the exclusion thresholds for non-specific precipitation, are not supplied.
- The technical and biological replication strategy for the simulated cellular compartments must be established to ensure statistical robustness.

### Release Criteria for Future Claims

Scientific claims regarding the discriminative power of osmotic and crowding gradients cannot be released until the operational parameters detailed above are resolved. The proposal remains a design-only methodology; no empirical results have been observed. Release criteria require the formalization of the boundary condition definitions to ensure that the simulated mechanisms are distinguishable from non-specific artifacts, such as global cytoskeletal collapse or salting-out. Furthermore, the computational models must be explicitly calibrated against the declared observables before any mechanistic conclusions can be drawn.

## References
- [@cite_06a078fea514798a] Daniel J. Klionsky et al.. *Guidelines for the use and interpretation of assays for monitoring autophagy (3rd edition)*. Autophagy, 2016.
- [@cite_099ed712535e9d67] Pierre‐François Lenne et al.. *Sculpting tissues by phase transitions*. Nature Communications, 2022.
- [@cite_1c127d341410ff21] Philippe Fuchs et al.. *Single organelle function and organization as estimated from Arabidopsis mitochondrial proteomics*. The Plant Journal, 2019.
- [@cite_1c132ef29e72d6e9] Michaela Hundertmark et al.. *LEA (Late Embryogenesis Abundant) proteins and their encoding genes in Arabidopsis thaliana*. BMC Genomics, 2008.
- [@cite_23d8490f53d19692] Alessandro Magazzù et al.. *Investigation of Soft Matter Nanomechanics by Atomic Force Microscopy and Optical Tweezers: A Comprehensive Review*. Nanomaterials, 2023.
- [@cite_27424f858dfe0741] Luiza Mendonça et al.. *Correlative multi-scale cryo-imaging unveils SARS-CoV-2 assembly and egress*. Nature Communications, 2021.
- [@cite_2745d1358ffa670f] Inês C. R. Barbosa et al.. *Directed growth and fusion of membrane-wall microdomains requires CASP-mediated inhibition and displacement of secretory foci*. Nature Communications, 2023.
- [@cite_2a1fb5ca9ad51ca0] Satoru Takahashi et al.. *Quantitative 3D correlative light and electron microscopy of organelle association during autophagy*. Cell Structure and Function, 2022.
- [@cite_3222d2eeb7add195] Habib‐ur‐Rehman Athar et al.. *Salt stress proteins in plants: An overview*. Frontiers in Plant Science, 2022.
- [@cite_3480a6462f7a2d86] Michael Mak et al.. *Interplay of active processes modulates tension and drives phase transition in self-renewing, motor-driven cytoskeletal networks*. Nature Communications, 2016.
- [@cite_380d2027763fbe55] Jie Wu et al.. *Immunoelectron microscopy: a comprehensive guide from sample preparation to high-resolution imaging*. Discover Nano, 2025.
- [@cite_42ed299a53990c06] Caterina Alfano et al.. *Molecular Crowding: The History and Development of a Scientific Paradigm*. Chemical Reviews, 2024.
- [@cite_47500d77448c984f] Wael Kamel et al.. *Global analysis of protein-RNA interactions in SARS-CoV-2-infected cells reveals key regulators of infection*. Molecular Cell, 2021.
- [@cite_59fcef4c8e2a3df0] Corrado Viotti et al.. *Endocytic and Secretory Traffic in Arabidopsis Merge in the Trans-Golgi Network/Early Endosome, an Independent and Highly Dynamic Organelle*. The Plant Cell, 2010.
- [@cite_5f0e3f49aeade942] Pál Pacher et al.. *Nitric Oxide and Peroxynitrite in Health and Disease*. Physiological Reviews, 2007.
- [@cite_652883e502229617] H. Hilgenkamp et al.. *Grain boundaries in high- Tc superconductors*. Reviews of Modern Physics, 2002.
- [@cite_661c925fe33fdb40] Jianwei Miao et al.. *Atomic electron tomography: 3D structures without crystals*. Science, 2016.
- [@cite_7161cfcb40366dd0] Manisha Poudyal et al.. *Intermolecular interactions underlie protein/peptide phase separation irrespective of sequence and structure at crowded milieu*. Nature Communications, 2023.
- [@cite_81a08c2c7b9c90d0] Haiyang Yu et al.. *HSP70 chaperones RNA-free TDP-43 into anisotropic intranuclear liquid spherical shells*. Science, 2021.
- [@cite_8d46403814b99258] Qian Wang et al.. *The Effect of Macromolecular Crowding, Ionic Strength and Calcium Binding on Calmodulin Dynamics*. PLoS Computational Biology, 2011.
- [@cite_90e000f6b0c99ee8] Joshua A Welsh et al.. *Minimal information for studies of extracellular vesicles (MISEV2023): From basic to advanced approaches*. Journal of Extracellular Vesicles, 2024.
- [@cite_9ae4c49700eea560] Lindsey N. Young et al.. *Bringing Structure to Cell Biology with Cryo-Electron Tomography*. Annual Review of Biophysics, 2023.
- [@cite_a7f02af046543f4e] Stephanie L. Fowler et al.. *Tau filaments are tethered within brain extracellular vesicles in Alzheimer’s disease*. bioRxiv (Cold Spring Harbor Laboratory), 2023.
- [@cite_afcca09a0a820cb3] Rico Schieweck et al.. *Pan-cellular organelles and suborganelles—from common functions to cellular diversity?*. Genes & Development, 2024.
- [@cite_b2ed4a49c99e7a61] Joana Azeredo et al.. *Critical review on biofilm methods*. Critical Reviews in Microbiology, 2016.
- [@cite_b9fbc4f4f2aa2591] Philip J. Withers et al.. *X-ray computed tomography*. Nature Reviews Methods Primers, 2021.
- [@cite_c269da6b5c5c4e09] Steffen Klein et al.. *SARS-CoV-2 structure and replication characterized by in situ cryo-electron tomography*. Nature Communications, 2020.
- [@cite_c2d09a021a2238e3] Mickaël Lelek et al.. *Single-molecule localization microscopy*. Nature Reviews Methods Primers, 2021.
- [@cite_c447068df54b10f5] Jacob Roberts et al.. *Controlled Collapse of a Bose-Einstein Condensate*. Physical Review Letters, 2001.
- [@cite_e2b5e3dbdb69d6a2] Nikita Balyschew et al.. *Streamlined structure determination by cryo-electron tomography and subtomogram averaging using TomoBEAR*. Nature Communications, 2023.
- [@cite_e5a596bb5117f86b] Konstantinos Papadimitriou et al.. *Stress Physiology of Lactic Acid Bacteria*. Microbiology and Molecular Biology Reviews, 2016.
