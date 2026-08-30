# Research Plan Quality Report

- Selected candidate: 0

## Candidate 0 — SCORED

- Total Score: 7.335 / 10

- Selection Score: 7.6013 / 10

- Theory/domain score weights: Theory Auditability=0.35, Boundary and Status Discipline=0.25, Falsifiability and Decision Completeness=0.25, Energy-Condition Defense=0.15

### Synthesis Quality — 8 / 10

The manuscript demonstrates strong synthesis quality by conceptually grouping literature around the distinction between pointwise and averaged energy conditions, and by explicitly separating the formal geometric theorem from the astrophysical mass-gap inference. It integrates survey evidence on quantum violations of NEC/SEC with the need for AANEC, and identifies a clear research gap: the missing explicit averaged null-convergence condition that bridges AANEC to trapped-surface formation. The synthesis moves beyond mere enumeration by constructing a dependency-closure matrix and a preregistered outcome decision matrix that operationalize the conceptual distinctions. However, the synthesis is weakened by the unresolved status of key definitions (A5, D4, A6), which prevents full integration of the formal argument and leaves the literature bridge incomplete. The manuscript honestly acknowledges these gaps as procedural dependencies rather than hiding them, which is appropriate for a proposal, but it limits the depth of synthesis achievable at this stage.

**Grounding warning:** evidence[3].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[4].excerpt is not found in its referenced block and was discarded

**Grounding:** introduction/intro-2 — This statement demonstrates genuine synthesis by identifying a conceptual gap that goes beyond listing papers—it articulates a structural deficiency in how the literature conflates distinct logical dependencies.

**Grounding:** survey_and_research_gap/b4 — The manuscript explicitly frames its literature review as a synthesis that produces a multi-layered gap analysis, showing integration rather than enumeration.

**Grounding:** definitions_and_propositions/def-09 — While honest about unresolved dependencies, these gaps limit the synthesis because the formal argument cannot be fully integrated with the literature until these definitions are supplied.

**Maximum strength:** The manuscript excels at conceptual grouping and integration by constructing a dependency-closure matrix that distinguishes AANEC from the independent averaged focusing condition, and by explicitly separating the formal theorem from astrophysical mass-gap inference. The preregistered outcome decision matrix operationalizes these conceptual distinctions into testable branches, demonstrating that the literature synthesis has been translated into a structured research design rather than remaining as abstract discussion.

**Major weakness:** The synthesis cannot be fully completed because three critical definitions remain unresolved: the explicit mathematical form of the averaged null-convergence condition (A5), the formal definition of the Misner-Sharp compactness parameter (D4), and the stability predicate for non-black-hole remnants (A6). These are not minor notation gaps but structural dependencies that prevent the formal argument from being integrated with the survey literature on energy conditions and trapped-surface theorems.

**Direction:** Prioritize resolving the three unresolved definitions (A5, D4, A6) in the next draft. Even if full proofs are not provided, supply candidate mathematical formulations with explicit justification for why they are independent of AANEC and sufficient for the proposed derivation. This would allow the synthesis to move from identifying gaps to demonstrating how the proposed framework fills them.

**Major weakness:** The manuscript's synthesis of astrophysical literature on the mass gap is thorough in identifying alternative mechanisms (explosion energetics, fallback, EOS, rotation, magnetic fields, binary evolution) but does not deeply engage with specific quantitative models or observational constraints that would allow the formal theorem to be tested against empirical data.

**Direction:** In the next draft, include a brief survey of 2-3 specific astrophysical models that predict the mass gap, and identify what observational signatures would distinguish the geometric compactness bound from these alternatives. This would strengthen the synthesis by showing how the formal theorem could be empirically constrained even if it does not directly predict the gap.

**Polish direction:** Supply candidate mathematical formulations for A5 (averaged null-convergence condition), D4 (Misner-Sharp compactness parameter), and A6 (stability predicate), with explicit justification for their independence from AANEC and their sufficiency for the proposed derivation.

**Polish direction:** Engage 2-3 specific astrophysical models of the mass gap and identify observational signatures that would distinguish the geometric compactness bound from alternative explanations.

**Polish direction:** Consolidate the repeated statements about unresolved dependencies into a single, clearly marked section that serves as a roadmap for the next draft, rather than scattering them throughout the manuscript.

### Organization — 7 / 10

The manuscript is highly structured with clear sectioning, consistent use of ledgers, matrices, and transition paragraphs that guide the reader through a complex formal argument. The logical flow from motivation → survey → research questions → formal problem → methods → expected outcomes → risks → definitions → derivation → appendices is coherent and well-signposted. However, the organization suffers from significant redundancy: the same assumptions (A1–A6), proof obligations (PO1–PO3), lemmas (L1–L6), and the mass-gap demotion caveat are restated nearly verbatim across at least five different sections (Introduction, Problem Definition, Study Design, Expected Outcomes, Forward Derivation, and multiple appendices). This repetition, while perhaps intentional for auditability, makes the document feel circular and inflates its length without advancing the argument. The appendices also partially duplicate main-body content (e.g., the Idea Source Checkpoints appear both as a main section and an appendix). A tighter, more linear organization with cross-references instead of restatement would substantially improve readability.

**Grounding warning:** evidence[2].excerpt is not found in its referenced block and was discarded

**Grounding:** introduction/intro-3 — Strong organizational signposting: the introduction clearly enumerates the three-part contribution structure, giving the reader a roadmap.

**Grounding:** forward_derivation_and_counterexamples/b5 — This is near-verbatim restatement of content already given in the Problem Definition and Study Design sections, illustrating the redundancy problem that weakens organizational flow.

**Grounding:** appendix_idea_evolution/block_1 — The appendix duplicates the main-body 'Idea Source Checkpoints and Direction Selection Audit' section almost entirely, creating organizational bloat.

**Maximum strength:** The manuscript excels in structural signposting: every major section ends with an explicit transition paragraph, and the use of ledgers, matrices, and numbered registries (assumptions, definitions, proof obligations, lemmas) creates a highly auditable organizational framework. The preregistered outcome decision matrix is particularly effective at organizing conditional reasoning.

**Major weakness:** Systematic redundancy across sections: the same assumptions (A1–A6), proof obligations (PO1–PO3), lemmas (L1–L6), propositions (P1–P2), and the mass-gap demotion caveat are restated nearly verbatim in the Introduction, Problem Definition, Study Design, Expected Outcomes, Forward Derivation, Risks, Definitions, and multiple appendices.

**Direction:** Adopt a 'define once, reference everywhere' strategy: establish the assumption ledger, definition ledger, and proof-obligation registry in a single canonical location (e.g., the Definitions section or an early formal framework section), then use cross-references in all subsequent sections. Consolidate the mass-gap demotion into a single boundary statement referenced by pointer. Remove or merge the duplicate appendix sections.

**Major weakness:** The appendix structure partially duplicates main-body content rather than serving a distinct supplementary role. The 'Idea Source Checkpoints' appendix repeats the main section of the same name, and the 'Energy-Condition Taxonomy' appendix overlaps with the boundary matrix already in the Study Design section.

**Direction:** Either merge the duplicate appendices into their corresponding main-body sections or restructure the appendices to contain only genuinely supplementary material (e.g., extended proofs, additional witness details, or historical audit trails) that is not covered in the main text.

**Polish direction:** Consolidate all repeated assumption, definition, lemma, and proof-obligation content into single canonical ledgers placed early in the document, and replace all subsequent restatements with explicit cross-references (e.g., 'Under assumptions A1–A6, as defined in Section X...').

**Polish direction:** Merge or eliminate the duplicate appendix sections (Idea Source Checkpoints appendix, Energy-Condition Taxonomy appendix) by folding their unique content into the corresponding main-body sections and removing the redundant copies.

**Polish direction:** Add a single-page 'Document Map' or 'Reading Guide' at the end of the Introduction that summarizes the section sequence, indicates where each ledger and matrix is canonically defined, and explains the cross-referencing convention used throughout.

### Readability — 6 / 10

The manuscript is highly structured and disciplined in scope, but its readability is significantly hampered by extreme repetition, over-reliance on meta-structural scaffolding (registries, ledgers, matrices, and 'no-information' status tags), and a tendency to restate the same caveats across nearly every section. Sentence-level clarity is generally good when the prose is allowed to flow, but the pacing is glacial because the same disclaimers about AANEC, the mass gap, and missing definitions are repeated verbatim or near-verbatim dozens of times. Jargon handling is appropriate for the intended audience of mathematical physicists, but the density of procedural labels (e.g., 'Proof Obligation Registry PO1, PO2, PO3 (Unverified)') interrupts the reading flow and makes the document feel more like a database schema than a research proposal. The strongest contribution to readability is the clear separation of the formal theorem from the astrophysical mass-gap inference, which is stated early and maintained consistently. The major weakness is the relentless repetition of scope delimiters and 'no-information' tags, which obscures the actual scientific argument and makes it difficult for a reader to identify what is genuinely new versus what is procedural bookkeeping.

**Grounding warning:** evidence[1].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[3].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[4].excerpt is not found in its referenced block and was discarded

**Grounding warning:** major_weaknesses[3].evidence_refs[1] references an unknown section_id/block_id and was discarded

**Grounding:** introduction/intro-3 — Excellent clarity in stating the scope separation, which is the manuscript's strongest readability asset.

**Grounding:** risk_limitations_and_review/rlr_no_information — This exact caveat (or close variants) appears at least 5 times across different sections, creating significant redundancy.

**Maximum strength:** The manuscript excels at clearly separating the formal geometric theorem from the astrophysical mass-gap inference, and this separation is stated early, maintained consistently, and articulated in accessible language. This is the single most important readability asset because it prevents the reader from conflating the mathematical claim with observational demographics.

**Major weakness:** Extreme repetition of scope delimiters, caveats, and 'no-information' status tags across nearly every section. The same disclaimers about AANEC not implying focusing, the mass gap being a consistency constraint, and the missing definitions for A5 and D4 are restated verbatim or near-verbatim dozens of times.

**Direction:** Consolidate all scope delimiters, caveats, and 'no-information' dependencies into a single dedicated section (e.g., 'Scope, Limitations, and Unresolved Dependencies') and reference that section from elsewhere rather than restating the full text. Use cross-references or brief inline pointers (e.g., 'see Scope section') instead of full restatements. This will reduce the document length by an estimated 30-40% and dramatically improve pacing.

**Major weakness:** Over-reliance on meta-structural scaffolding (registries, ledgers, matrices, and status tags) that interrupts the reading flow. Headers like 'Proof Obligation Registry PO1, PO2, PO3 (Unverified)' and 'Decision Status: No-information' appear repeatedly and add cognitive load without advancing the scientific argument.

**Direction:** Move all registries, ledgers, and matrices to appendices or supplementary material. In the main text, use narrative prose to describe the proof obligations and dependencies, with brief references to the appendices for full details. Replace status tags like '(Unverified)' and '(No-information)' with inline qualifiers (e.g., 'This obligation remains unresolved pending human input') that flow naturally within sentences.

**Major weakness:** The abstract and introduction are overly long and contain significant redundancy. The abstract attempts to summarize the entire proposal including scope delimiters and outcome branches, which dilutes its impact and makes it difficult to identify the core contribution.

**Location:** pending review

**Direction:** Shorten the abstract to 150-200 words, focusing on: (1) the problem (pointwise energy conditions fail, averaged conditions are needed), (2) the approach (AANEC plus explicit averaged focusing condition), (3) the expected contribution (candidate theorem for trapped-surface formation in spherical collapse), and (4) the scope limitation (does not explain the mass gap). Move all discussion of outcome branches, proof obligations, and dependencies to the main text.

**Polish direction:** Consolidate all scope delimiters, caveats, and 'no-information' dependencies into a single dedicated section and replace repetitive restatements with cross-references or brief inline pointers.

**Polish direction:** Move all registries, ledgers, and matrices to appendices or supplementary material, and replace meta-structural headers with narrative prose in the main text.

**Polish direction:** Shorten the abstract to 150-200 words, focusing on the problem, approach, expected contribution, and scope limitation, and move all discussion of outcome branches and dependencies to the main text.

### Academic Rigor — 7 / 10

The manuscript demonstrates strong fidelity to scholarly standards in its careful separation of formal geometric claims from astrophysical inference, explicit acknowledgment of unresolved definitions, and systematic treatment of energy conditions. It properly cites prior work on quantum violations of pointwise energy conditions and fairly represents the astrophysical complexity of the mass gap. However, the rigor is undermined by the repeated admission that critical mathematical definitions (the explicit averaged focusing condition A5 and the Misner-Sharp compactness parameter D4) remain unresolved, preventing the theorem from being audited or falsified. While this honesty is commendable for a proposal, it means the core proof obligations cannot be evaluated, and the dependency on 'human input' is invoked repeatedly without providing even candidate formulations. The citation apparatus is present but opaque—29 registered keys are mentioned but the reference list contains no actual bibliography entries, making it impossible to verify proper attribution or fair representation of specific prior theorems.

**Grounding warning:** major_weaknesses[2].evidence_refs[1] references an unknown section_id/block_id and was discarded

**Grounding:** introduction/intro-2 — Demonstrates rigorous identification of a specific, defensible research gap rather than overclaiming novelty

**Grounding:** formal_problem_and_hypotheses/block-2 — Shows methodological transparency by explicitly flagging an unresolved premise, but also reveals a critical gap that prevents the theorem from being operationalized

**Grounding:** expected_outcomes/eoc_astrophysical_boundary — Exemplifies rigorous scope discipline by preventing conflation of formal geometry with astrophysical observation

**Maximum strength:** Exceptional scope discipline and conditional reasoning: the manuscript systematically separates the formal geometric theorem from astrophysical inference, explicitly demotes the mass gap to a consistency constraint, and provides a preregistered decision matrix with no-information branches that withhold conclusions rather than overclaim. This represents a model of honest proposal design that rewards falsifiability and scope clarity.

**Major weakness:** Critical mathematical definitions are repeatedly flagged as unresolved (A5: explicit averaged focusing condition; D4: Misner-Sharp compactness parameter) without even candidate formulations being provided, making the core proof obligations unauditable

**Direction:** Provide at least one candidate mathematical formulation for A5 (e.g., an integrated Raychaudhuri-type inequality with specified affine parameter range and expansion scalar dependence) and for D4 (e.g., the standard Misner-Sharp mass formula C = 2M(r)/r with explicit metric dependence), even if marked as provisional. This would convert 'no-information' branches into testable hypotheses.

**Major weakness:** The reference list is incomplete: 29 citation keys are registered but no actual bibliography entries are provided, making it impossible to verify proper attribution or assess whether prior work is fairly represented

**Location:** pending review

**Direction:** Populate the References section with full bibliographic entries for all 29 cited works, ensuring that key theorems (e.g., Penrose singularity theorem, quantum energy inequalities) and astrophysical population studies are properly attributed.

**Polish direction:** Supply candidate mathematical formulations for A5 and D4, even if provisional, to convert no-information dependencies into testable proof obligations

**Polish direction:** Complete the References section with full bibliographic entries for all 29 citation keys

**Polish direction:** Consolidate the repeated 'no-information' declarations into a single upfront dependency ledger rather than scattering them across multiple sections

### Clarity — 7 / 10

The manuscript is unusually disciplined about scope, conditional reasoning, and the separation of formal theorem from astrophysical inference, which substantially aids reader comprehension. Definitions, assumptions, lemmas, and proof obligations are consistently labeled and cross-referenced, and the decision matrix makes outcome branches unambiguous. However, clarity is materially degraded by three recurring issues: (1) the central technical objects—the explicit averaged null-convergence condition (A5) and the Misner-Sharp compactness parameter (D4)—are repeatedly flagged as unresolved or needing human input, so the core mechanism cannot be unambiguously understood; (2) the same caveats and scope disclaimers (e.g., mass gap as consistency constraint, list of astrophysical confounders) are reiterated verbatim across nearly every section, creating redundancy that obscures the argumentative spine; and (3) the derivation chain is presented as a scaffold with placeholder equations rather than a worked technical description, leaving the reader without a concrete sense of how AANEC plus the added focusing condition operationally yields a trapped surface. The result is a proposal whose logical architecture is clear but whose technical content remains too underspecified for a reader to unambiguously understand the methods.

**Grounding:** formal_problem_and_hypotheses/block-2 — The core added premise (A5) is explicitly undefined, preventing readers from understanding the mechanism that distinguishes this theorem from standard AANEC-based arguments.

**Grounding:** definitions_and_propositions/def-05 — The Misner-Sharp compactness threshold, which is the operational trigger for the entire theorem, lacks a formal definition, so the key technical quantity cannot be unambiguously understood.

**Grounding:** forward_derivation_and_counterexamples/b4 — The derivation chain is presented as a placeholder rather than a worked technical argument, leaving the reader without concrete understanding of how the focusing step operates.

**Maximum strength:** The manuscript excels at structural clarity through its systematic use of labeled ledgers (assumptions A1-A6, definitions D1-D7, lemmas L1-L6, proof obligations PO1-PO3), dependency-closure matrices, and a preregistered outcome decision matrix. This architecture makes the logical dependencies, scope boundaries, and conditional reasoning unambiguously traceable, which is a significant strength for a research plan.

**Major weakness:** The two central technical objects—the explicit averaged null-convergence condition (A5) and the Misner-Sharp compactness parameter (D4)—are repeatedly declared unresolved or needing human input, so the core mechanism cannot be unambiguously understood.

**Direction:** Provide at least a candidate mathematical formulation for A5 (e.g., an explicit integral inequality on Ricci contraction along complete null generators with specified affine-parameter range) and a concrete definition of the Misner-Sharp compactness for the chosen spherically symmetric metric class, even if marked as provisional. This would transform the proposal from a scaffold into a testable technical claim.

**Major weakness:** Excessive repetition of scope disclaimers and lists of astrophysical confounders across nearly every section creates redundancy that obscures the argumentative spine.

**Direction:** Consolidate the mass-gap demotion and confounder list into a single dedicated subsection (e.g., in the introduction or a standalone scope section) and use cross-references in subsequent sections. This would reduce redundancy while preserving the important scope boundary.

**Major weakness:** The derivation chain is presented as a scaffold with placeholder equations rather than a worked technical description, leaving the reader without a concrete sense of how the focusing step operates.

**Direction:** Provide a more detailed sketch of the derivation, even if provisional: specify the form of the Raychaudhuri equation used, explain how the averaged convergence assumption enters, and show how negative expansion of both null congruences is established. This would give readers a concrete technical understanding of the mechanism.

**Polish direction:** Provide candidate mathematical formulations for A5 (explicit averaged null-convergence condition) and D4 (Misner-Sharp compactness parameter), even if marked as provisional or subject to revision.

**Polish direction:** Consolidate repeated scope disclaimers and confounder lists into a single dedicated subsection with cross-references, reducing redundancy.

**Polish direction:** Expand the derivation scaffold into a more detailed technical sketch, specifying the Raychaudhuri equation form, how averaged convergence enters, and how negative expansion is established.

### Coherence — 8 / 10

The manuscript is unusually disciplined about internal consistency: it repeatedly separates AANEC from an independent averaged focusing hypothesis, demotes the 2–5 solar mass gap to an astrophysical consistency constraint, and routes unresolved definitions (A5, D4, A6) into explicit no-information branches rather than silently assuming them away. The same assumption ledger (A1–A6), proof obligations (PO1–PO3), and lemma registry (L1–L6) are carried coherently from the introduction through the study design, expected outcomes, risks, and appendices. The main coherence weakness is a mild internal tension around the Misner-Sharp compactness parameter: it is simultaneously flagged as needs_human_input and then given a concrete placeholder formula C = 2M/r that is subsequently used in the derivation scaffold and exclusion bound. This creates a small drift between the declared unresolved status and the operational use of the symbol. A secondary, minor issue is occasional redundancy across sections (the AANEC-vs-SEC distinction and the mass-gap demotion are restated many times), which slightly blurs the through-line but does not introduce contradictions.

**Grounding:** formal_problem_and_hypotheses/block-2 — Anchors the central coherence move: AANEC is explicitly decoupled from the focusing premise, preventing the common slide from averaged energy to automatic focusing.

**Grounding:** expected_outcomes/eoc_decision_matrix — Shows coherent routing of unresolved definitions into a no-information branch rather than smuggling them into conclusions.

**Grounding:** definitions_and_propositions/def-04 — Introduces a concrete compactness formula while D4 is still marked needs_human_input, creating a mild drift between declared status and operational use.

**Maximum strength:** A tightly maintained separation between AANEC and an independent averaged focusing hypothesis, consistently carried through assumptions, lemmas, proof obligations, outcome branches, and the risk ledger. The mass gap is coherently demoted from theorem output to astrophysical consistency constraint across every section that touches it.

**Major weakness:** Mild drift around the Misner-Sharp compactness parameter: D4 is declared needs_human_input, yet a concrete placeholder C = 2M/r is introduced and then used in the derivation scaffold and exclusion bound.

**Direction:** Either (a) keep C = 2M/r explicitly labeled as a working placeholder and route every downstream use (exclusion bound, counterexample matrix) through a conditional that re-asserts the no-information status until D4 is closed, or (b) promote D4 to a provisional definition with a clearly bounded validity domain (e.g., spherical symmetry, specific gauge) and adjust the proof obligations accordingly.

**Major weakness:** Repeated restatement of the AANEC-vs-SEC distinction and the mass-gap demotion across introduction, survey, study design, expected outcomes, risks, and appendices.

**Direction:** Consolidate the AANEC/SEC/focusing taxonomy and the mass-gap demotion into a single canonical section (e.g., the appendix boundary matrix and a short cross-reference in the introduction), and let later sections cite that canonical statement instead of re-deriving it.

**Polish direction:** Resolve the D4 drift by either (a) tagging every use of C = 2M/r as provisional and routing the exclusion bound through the no-information branch until D4 is closed, or (b) promoting C = 2M/r to a provisional definition with an explicit validity domain and adjusting PO3 accordingly.

**Polish direction:** Consolidate the AANEC/SEC/focusing taxonomy and the mass-gap demotion into one canonical section with cross-references, reducing repetition in the introduction, study design, and expected outcomes.

**Polish direction:** Add a one-paragraph 'coherence map' near the end of the introduction that explicitly traces A1–A6, PO1–PO3, and the mass-gap demotion to their canonical locations in later sections.

### Comprehensiveness — 8 / 10

The manuscript demonstrates exceptional breadth across the theoretical, methodological, and astrophysical dimensions of the research area. It systematically covers energy-condition taxonomy (NEC, ANEC, AANEC, SEC), geometric focusing mechanisms (Raychaudhuri equation, null convergence), stellar evolution boundary variables (compactness, explosion energetics, fallback, EOS), and formal proof obligations. The explicit separation of the formal theorem from the astrophysical mass-gap inference, along with the detailed treatment of alternative stellar-physics mechanisms as confounders, shows comprehensive awareness of the multi-layered research landscape. The inclusion of counterexample boundary analysis, outcome decision matrices, and human-review checklists further demonstrates thorough coverage of validation obligations. However, the manuscript's comprehensiveness is slightly limited by the unresolved formal definitions (A5, D4, A6) that prevent full operationalization of the proposed framework, and the restricted model class (spherical symmetry, isotropic pressure) explicitly excludes rotating, magnetized, and nonspherical collapse scenarios that are astrophysically significant.

**Grounding warning:** evidence[3].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[4].excerpt is not found in its referenced block and was discarded

**Grounding:** introduction/intro-2 — Demonstrates comprehensive identification of the theoretical gap between energy conditions and geometric focusing, showing awareness of the multi-layered problem structure.

**Grounding:** survey_and_research_gap/b3 — Shows comprehensive coverage of astrophysical boundary variables and alternative mechanisms that could confound the formal theorem's explanatory relevance.

**Grounding:** formal_problem_and_hypotheses/block-2 — Reveals a comprehensiveness limitation: the explicit acknowledgment that a key premise remains undefined prevents full operationalization of the proposed framework.

**Maximum strength:** The manuscript's strongest contribution is its comprehensive separation of the formal geometric theorem from the astrophysical mass-gap inference, with explicit treatment of alternative stellar-physics mechanisms (explosion energetics, fallback, EOS, rotation, magnetic fields, nonspherical dynamics, binary evolution) as confounders rather than direct falsifiers. This disciplined scope management demonstrates exceptional awareness of the multi-layered research landscape and prevents overclaiming against well-documented alternative explanations.

**Major weakness:** The manuscript explicitly acknowledges that three critical formal definitions remain unresolved: the mathematical form of the explicit averaged null-convergence condition (A5), the formal definition of the Misner-Sharp compactness parameter (D4), and the stability predicate for non-black-hole remnants (A6). These are not minor notation gaps but structural dependencies that prevent the theorem from being operationalized, audited, or falsified.

**Direction:** Prioritize resolution of the three missing definitions (A5, D4, A6) through human formalization or literature synthesis. For A5, specify the exact integrated form, affine parameter range, and relation to the expansion scalar. For D4, provide the precise formula for effective mass within radius r in the chosen metric class. For A6, formally distinguish stable non-black-hole remnants from regular black-hole models (e.g., Hayward, Bardeen) by specifying the stability predicate and horizon classification criteria.

**Major weakness:** The manuscript's scope is deliberately restricted to spherically symmetric, non-rotating collapse with isotropic pressure, explicitly excluding rotating, magnetized, nonspherical, and anisotropic collapse scenarios. While this restriction is methodologically sound for a candidate theorem, it limits the comprehensiveness of the research plan's coverage of astrophysically realistic collapse scenarios.

**Direction:** While maintaining the restricted model class for the candidate theorem, add a dedicated section outlining the methodological pathway for extending the AANEC-relaxed framework to rotating (axisymmetric) collapse, magnetized plasmas, and nonspherical dynamics. Specify which assumptions would need revision (e.g., spherical symmetry → axisymmetry, isotropic pressure → anisotropic stress tensor) and what new proof obligations would arise. This would demonstrate comprehensive awareness of the extension landscape without overclaiming the current theorem's scope.

**Polish direction:** Resolve the three missing formal definitions (A5, D4, A6) by providing explicit mathematical formulations or citing specific literature sources that supply these definitions. For A5, specify the integrated null-convergence condition with explicit affine parameter bounds and relation to the Raychaudhuri equation. For D4, provide the Misner-Sharp mass formula for the chosen metric class. For A6, formally define the stability predicate distinguishing horizonless remnants from regular black-hole models.

**Polish direction:** Add a dedicated 'Extension Pathways' section that outlines how the AANEC-relaxed framework could be generalized to rotating, magnetized, and nonspherical collapse scenarios. Specify which assumptions would need revision and what new proof obligations would arise, even if the current theorem does not address these cases.

**Polish direction:** Strengthen the connection between the formal theorem and observational constraints by specifying how the compactness threshold (once defined) could be compared to observational data from gravitational-wave catalogs (e.g., GW190814) and X-ray binaries. Even if the mass gap is treated as a consistency constraint rather than a prediction, outline the methodology for testing the theorem's implications against observed remnant distributions.

### Critical Analysis — 8 / 10

The manuscript demonstrates exceptional critical analysis in its treatment of the boundary between formal geometric theorems and astrophysical inference. It rigorously separates the candidate AANEC-relaxed trapped-surface theorem from the observed 2-5 solar mass gap, treating the latter as a consistency constraint rather than a theorem-derived prediction. The energy-condition taxonomy is carefully constructed, distinguishing NEC, ANEC, AANEC, SEC, and the proposed explicit averaged focusing condition with clear logical boundaries. The counterexample boundary matrix is particularly strong, distinguishing genuine falsifiers from scope delimiters and assumption-violation cases. However, the analysis is somewhat undermined by the repeated acknowledgment of unresolved definitions (A5, D4, A6) that prevent the theorem from being fully auditable, and the comparative assessment of alternative stellar-physics mechanisms, while thorough in listing them, lacks depth in evaluating their relative explanatory power against the proposed geometric bound.

**Grounding warning:** evidence[3].excerpt is not found in its referenced block and was discarded

**Grounding:** introduction/intro-2 — This demonstrates sophisticated critical analysis by explicitly separating formal geometric claims from empirical astrophysical observations, preventing overclaiming.

**Grounding:** study_design_and_methods/sdm-boundary-matrix — The energy-condition boundary matrix shows careful critical evaluation of what each condition can and cannot imply, preventing logical conflation.

**Grounding:** expected_outcomes/eoc_astrophysical_boundary — This shows sophisticated understanding of the relationship between formal theorems and empirical explanations, maintaining logical separation.

**Maximum strength:** The manuscript excels in maintaining rigorous logical boundaries between formal geometric theorems and astrophysical inference, with a sophisticated energy-condition taxonomy and counterexample classification system that prevents overclaiming and logical conflation.

**Major weakness:** The critical analysis repeatedly acknowledges unresolved definitions (A5, D4, A6) that prevent the theorem from being fully auditable, yet does not critically evaluate whether these gaps undermine the research plan's viability or represent fundamental obstacles to the proposed mechanism.

**Direction:** Add a critical evaluation section that assesses whether the unresolved definitions represent tractable procedural dependencies or fundamental obstacles, and evaluate the likelihood that human input can resolve them in a way that preserves the theorem's logical structure.

**Major weakness:** The comparative assessment of alternative stellar-physics mechanisms (explosion energetics, fallback, equation-of-state physics, rotation, magnetic fields, binary evolution) is thorough in listing them but lacks depth in evaluating their relative explanatory power against the proposed geometric bound.

**Direction:** Add a comparative analysis section that evaluates the explanatory power of each alternative mechanism against the proposed geometric bound, identifying which observations or predictions would discriminate between them.

**Polish direction:** Add a critical evaluation of whether the unresolved definitions (A5, D4, A6) represent tractable procedural dependencies or fundamental obstacles to the theorem's viability, and assess the likelihood that human input can resolve them while preserving the logical structure.

**Polish direction:** Develop a comparative analysis section that evaluates the explanatory power of alternative stellar-physics mechanisms against the proposed geometric bound, identifying discriminating observations or predictions.

**Polish direction:** Reduce redundancy in the repeated acknowledgment of unresolved definitions across multiple sections, consolidating these discussions into a single comprehensive treatment.

### Novelty and Insights — 7 / 10

The manuscript offers a genuinely useful conceptual reframing: it explicitly decouples the Averaged Null Energy Condition (AANEC) from the geometric focusing needed for trapped-surface formation, and it demotes the observed 2–5 solar mass gap from a theorem-derived prediction to an astrophysical consistency constraint. This separation is a fresh and disciplined contribution that clarifies what a classical GR theorem can and cannot explain. The proposal also introduces a structured dependency-closure matrix and a preregistered outcome decision protocol, which are novel organizational insights for a theory-only research plan. However, the novelty is tempered by the fact that the central mathematical mechanism—the explicit averaged null-convergence/focusing condition (A5) and the Misner-Sharp compactness threshold (D4)—remains undefined, so the core conceptual reframing cannot yet be operationalized into a concrete new theorem or bound. The survey synthesis is competent but largely consolidates known tensions between pointwise and averaged energy conditions rather than producing a genuinely new mathematical synthesis.

**Grounding warning:** evidence[5].excerpt is not found in its referenced block and was discarded

**Grounding:** introduction/intro-2 — This is the strongest conceptual insight: identifying and formalizing the missing bridge between AANEC and focusing as an independent hypothesis is a fresh reframing that clarifies the logical structure of singularity theorems.

**Grounding:** introduction/intro-3 — This scope discipline is a valuable insight that prevents overclaiming and cleanly separates formal GR from stellar-population astrophysics, improving the intellectual honesty of the proposal.

**Grounding:** idea_origin_and_selection/origin-2 — This is the major weakness: the central novel mechanism is declared but not formalized, so the conceptual reframing cannot yet yield a concrete new theorem or testable bound.

**Maximum strength:** The explicit separation of AANEC from the geometric focusing hypothesis, and the demotion of the mass gap to an astrophysical consistency constraint, constitute a genuinely fresh conceptual reframing that clarifies the logical dependencies of trapped-surface theorems and prevents overclaiming.

**Major weakness:** The central novel mechanism—the explicit averaged null-convergence/focusing condition (A5)—is declared as an independent geometric hypothesis but its mathematical form is never supplied.

**Direction:** Supply a precise mathematical statement for A5 (e.g., an integrated Ricci contraction bound along complete null generators with explicit affine-parameter range and relation to the expansion scalar), and show how it is logically independent of AANEC. Provide at least one worked example where A5 holds and one where it fails, to demonstrate its discriminating power.

**Major weakness:** The Misner-Sharp compactness parameter (D4) and its threshold formula are marked as needs_human_input, preventing any concrete threshold calculation or stability bound.

**Direction:** Fix the metric class (e.g., Painlevé-Gullstrand or Lemaître–Tolman–Bondi for spherical collapse) and supply the exact Misner-Sharp mass formula M(r) for that class, then derive the compactness threshold C_threshold explicitly. Show how the threshold depends on the equation of state or pressure profile.

**Major weakness:** The stability predicate for non-black-hole remnants (A6) is not formally separated from regular black-hole models such as Hayward or Bardeen, which contain horizons.

**Direction:** Define the stability predicate explicitly in terms of horizonless equilibrium (e.g., no trapped surfaces, bounded compactness, and a well-defined TOV-like limit), and show how it excludes horizon-bearing regular black-hole models by construction.

**Polish direction:** Supply the explicit mathematical form of the averaged null-convergence/focusing condition (A5) and demonstrate its logical independence from AANEC with a concrete example.

**Polish direction:** Fix the metric class and supply the exact Misner-Sharp mass formula M(r) and compactness threshold C_threshold for that class.

**Polish direction:** Define the stability predicate for non-black-hole remnants explicitly in terms of horizonless equilibrium and bounded compactness, excluding horizon-bearing regular black-hole models by construction.

### Future Directions — 7 / 10

The manuscript articulates a disciplined, conditional research trajectory with clear proof obligations, counterexample search protocols, and explicit no-information branches that honestly delimit what can be concluded before upstream definitions are supplied. Its strongest contribution is the preregistered outcome decision matrix that maps each branch (supports_mechanism, partial_or_heterogeneous, null_or_contradictory, uninformative_or_invalid, no-information dependency) to specific next actions, which is unusually well-specified for a theory proposal. However, the future directions are largely internal to the formal program: they do not articulate how the restricted spherical/isotropic theorem would be extended to rotating, magnetized, or nonspherical collapse, how the averaged focusing condition might be derived from or constrained by quantum energy inequalities, or how the formal compactness bound could be confronted with population-synthesis or gravitational-wave observations beyond a generic 'consistency constraint' framing. The plan also leaves the most critical open problems (the mathematical form of A5, the metric-dependent Misner-Sharp threshold, and the stability predicate) as unresolved human-input dependencies without specifying candidate functional forms, literature anchors, or criteria for selecting among alternatives. This makes the next steps actionable within the current scope but insufficiently concrete for the field to build on the program without further specification.

**Grounding warning:** evidence[1].excerpt is not found in its referenced block and was discarded

**Grounding:** forward_derivation_and_counterexamples/b6 — Shows actionable next steps for counterexample adjudication, but leaves the refinement of A5 and D4 unspecified, reducing concrete utility for the field.

**Grounding:** study_design_and_methods/sdm-robustness-checks — Identifies a clear extension trajectory but does not specify how the theorem's premises or proof obligations would be modified for these cases.

**Grounding:** appendix_evidence_and_review/appendix-review-criteria — States a critical open problem but offers no candidate forms, literature anchors, or selection criteria, limiting actionability.

**Maximum strength:** The preregistered outcome decision matrix with explicit branch triggers, allowed conclusions, and next actions provides a model for conditional reasoning in theory proposals, honestly separating formal status from astrophysical inference and routing no-information dependencies without invalidating the plan.

**Major weakness:** The most critical open problems (mathematical form of A5, metric-dependent Misner-Sharp threshold, stability predicate) are declared as unresolved human-input dependencies without candidate functional forms, literature anchors, or selection criteria.

**Direction:** Provide at least one candidate mathematical form for A5 (e.g., an integrated Raychaudhuri focusing condition with specified affine parameter range and expansion scalar relation), anchor the Misner-Sharp threshold to a specific metric class (e.g., interior Schwarzschild or Oppenheimer-Snyder), and specify the stability predicate via a TOV-like bounded compactness condition with literature references. Include criteria for selecting among alternatives and falsification tests for each candidate.

**Major weakness:** The future directions do not articulate how the restricted spherical/isotropic theorem would be extended to rotating, magnetized, or nonspherical collapse, or how the averaged focusing condition might be derived from or constrained by quantum energy inequalities.

**Direction:** Add a dedicated subsection on extension trajectories that specifies how A5 and the compactness threshold would be modified for axisymmetric or magnetized collapse, and how quantum energy inequalities (e.g., QEIs or ANEC bounds from semiclassical gravity) might constrain or derive the averaged focusing condition. Include concrete milestones for each extension.

**Polish direction:** Specify candidate functional forms for A5, the Misner-Sharp threshold, and the stability predicate, with literature anchors and selection criteria.

**Polish direction:** Add a dedicated subsection on extension trajectories for rotating, magnetized, or nonspherical collapse, and for deriving A5 from quantum energy inequalities.

**Polish direction:** Specify how the formal compactness bound could be confronted with population-synthesis or gravitational-wave observations beyond a generic 'consistency constraint' framing.

### Theory Auditability — 8 / 10

The manuscript excels at turning its central proposal into an auditable chain: it labels assumptions (A1–A6), definitions (D1–D7), candidate lemmas (L1–L6), propositions (P1–P2), and proof obligations (PO1–PO3), and it explicitly links them through a dependency-closure matrix and a preregistered outcome decision matrix. It is unusually honest about scope and about what must be checked next, repeatedly flagging 'no-information' dependencies (the mathematical form of A5, the formal Misner–Sharp threshold D4, and the stability predicate A6) and routing them to upstream resolution rather than pretending the theorem is complete. The strongest contribution is the explicit separation of AANEC from an independent averaged focusing hypothesis and the construction of a counterexample/boundary matrix that tells a reader exactly what must be verified to upgrade a candidate witness into a genuine falsifier. The main weakness is that several core labels remain placeholders: the averaged focusing condition A5 is declared but not formalized, the Misner–Sharp compactness is given only as a schematic C = 2M/r with a 'needs_human_input' caveat, and the lemma registry entries are largely cross-references rather than self-contained statements. This slightly reduces auditability because a reader cannot yet trace a fully specified symbolic chain from premises to conclusion without external human input.

**Grounding warning:** evidence[2].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[3].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[4].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[6].excerpt is not found in its referenced block and was discarded

**Grounding:** formal_problem_and_hypotheses/block-2 — Shows the plan labels the critical missing premise and routes it to human resolution, preserving auditability rather than smuggling in an unstated assumption.

**Grounding:** definitions_and_propositions/def-04 — Provides a concrete but schematic threshold relation; auditability is preserved by the explicit 'needs_human_input' flag in the next block.

**Maximum strength:** The manuscript builds a labeled, dependency-closed audit trail from assumptions through candidate lemmas to proof obligations and a preregistered decision matrix, while honestly marking unresolved definitions as 'no-information' dependencies rather than completed results.

**Major weakness:** The explicit averaged null-convergence/focusing condition (A5) is declared as an independent geometric hypothesis but is never given a precise mathematical form anywhere in the manuscript.

**Direction:** Supply a concrete, self-contained formula for A5 (e.g., an integrated Ricci-contraction bound along complete achronal null generators with explicit affine-parameter range and relation to the expansion scalar), and show how it is logically independent of AANEC.

**Major weakness:** The Misner–Sharp compactness parameter is given only as a schematic C = 2M/r with a 'needs_human_input' flag, and the stability predicate for non-black-hole remnants (A6) is not formally separated from horizon-bearing regular black-hole models.

**Direction:** Provide the explicit Misner–Sharp mass function for the chosen spherically symmetric metric class and a formal stability predicate (e.g., a TOV-like bounded-compactness condition) that excludes horizon-bearing configurations by definition.

**Polish direction:** Replace the schematic A5 and C = 2M/r placeholders with fully specified mathematical definitions, including affine-parameter ranges, metric dependence, and the relation to the expansion scalar theta.

**Polish direction:** Expand each candidate lemma (L1–L6) from a cross-reference into a self-contained statement with explicit premises, conclusion, and the exact proof-obligation it discharges.

**Polish direction:** Add a short 'audit checklist' at the end of the definitions section that maps every symbol and assumption to its downstream lemma and proof obligation in one table.

### Boundary and Status Discipline — 9 / 10

The manuscript demonstrates exceptional discipline in separating candidate, unverified, expected-not-observed, no-information, and review-required statuses from established claims. It consistently marks the AANEC-relaxed trapped-surface theorem as a candidate formalization, explicitly demotes the astrophysical mass gap to a consistency constraint rather than a theorem-derived prediction, and routes missing definitions (A5, D4, A6) to no-information branches that withhold theorem-status updates without invalidating the plan. The preregistered outcome decision matrix cleanly distinguishes supportive, partial, null, uninformative, and no-information branches, each with prespecified triggers and allowed conclusions. The dependency-closure matrix and proof-obligation registry maintain rigorous traceability between assumptions, lemmas, and unresolved inputs. The strongest contribution is the systematic separation of formal geometric claims from astrophysical inference, preventing overclaiming while preserving a clear audit trail for future proof or counterexample work. A minor weakness is occasional redundancy in restating the no-information status and scope limitations across multiple sections, which slightly dilutes the argument's forward momentum without adding new logical content.

**Grounding warning:** evidence[1] references an unknown section_id/block_id and was discarded

**Grounding warning:** evidence[2].excerpt is not found in its referenced block and was discarded

**Grounding warning:** major_weaknesses[1].evidence_refs[1] references an unknown section_id/block_id and was discarded

**Grounding:** risk_limitations_and_review/rlr_no_information — Precisely defines the no-information status and its logical consequences, preventing misinterpretation of missing definitions as falsification.

**Grounding:** definitions_and_propositions/def-02 — Attaches review-required status to a critical definition, ensuring that downstream proof obligations cannot proceed without human resolution.

**Grounding:** forward_derivation_and_counterexamples/b5 — Consistently routes unresolved dependencies to no-information status, maintaining logical separation between proposed and established results.

**Maximum strength:** The manuscript achieves exemplary boundary and status discipline by systematically separating candidate formalizations from established results, routing missing definitions to no-information branches, and demoting astrophysical observations to consistency constraints. The preregistered outcome decision matrix and dependency-closure matrix provide a rigorous audit trail that prevents overclaiming while preserving clear proof obligations.

**Major weakness:** Redundant restatement of no-information status and scope limitations across multiple sections (abstract, introduction, expected outcomes, risk/limitations, appendices) without adding new logical content or advancing the argument.

**Direction:** Consolidate repeated scope limitations and no-information statements into a single comprehensive boundary-discipline section, using cross-references in other sections to avoid redundancy while maintaining logical traceability.

**Polish direction:** Create a consolidated 'Boundary and Status Discipline' section that centralizes all scope limitations, no-information dependencies, and status attributions, replacing scattered repetitions with a single authoritative reference point.

**Polish direction:** Add a visual summary (e.g., a status-attribution flowchart or dependency graph) showing how candidate claims, unverified lemmas, no-information dependencies, and review-required definitions relate to each other and to the final theorem status.

### Falsifiability and Decision Completeness — 8 / 10

The manuscript excels at pre-registering decision logic, explicitly separating formal theorem status from astrophysical inference, and defining a no-information branch for unresolved upstream dependencies. It provides a clear preregistered outcome decision matrix with prespecified triggers, allowed conclusions, and next actions for supportive, partial, null, uninformative, and no-information branches. However, the core falsifiability is weakened by the fact that the central geometric hypothesis (A5: explicit averaged null-convergence/focusing condition) and the key threshold parameter (D4: Misner-Sharp compactness) remain formally undefined, making it impossible to definitively test or falsify the theorem until these dependencies are resolved. While the manuscript honestly acknowledges these gaps and routes them to a no-information branch rather than claiming failure, this means the actual falsification protocol cannot be executed in the current state.

**Grounding warning:** evidence[1].excerpt is not found in its referenced block and was discarded

**Grounding warning:** evidence[4].excerpt is not found in its referenced block and was discarded

**Grounding:** expected_outcomes/eoc_branch_logic — Shows honest handling of unresolved dependencies by withholding status updates rather than claiming failure, but also reveals that falsifiability is currently blocked by missing definitions.

**Grounding:** formal_problem_and_hypotheses/block-2 — Identifies a critical dependency that prevents falsification testing, as the central geometric hypothesis cannot be verified without its formal definition.

**Grounding:** expected_outcomes/eoc_astrophysical_boundary — Demonstrates excellent scope discipline by separating formal mathematical claims from astrophysical observations, preventing conflation of distinct evidentiary domains.

**Maximum strength:** The manuscript provides an exceptionally clear pre-registered decision protocol that explicitly separates formal theorem status from astrophysical inference, defines multiple outcome branches with prespecified triggers and next actions, and honestly routes unresolved dependencies to a no-information branch rather than claiming failure or success. The falsification criteria are well-defined: a valid counterexample must satisfy all assumptions A1-A6 while avoiding trapped-surface formation.

**Major weakness:** The central geometric hypothesis (A5: explicit averaged null-convergence/focusing condition) and the key threshold parameter (D4: Misner-Sharp compactness) remain formally undefined, preventing actual execution of the falsification protocol.

**Direction:** Prioritize formalization of A5 and D4 as the first step in the research plan. Provide candidate mathematical formulations for the averaged focusing condition (e.g., specific integral bounds on Ricci contraction along null generators) and the Misner-Sharp compactness parameter for the chosen metric class. Even provisional definitions would enable preliminary falsification testing and counterexample screening.

**Major weakness:** The stability predicate for non-black-hole remnants (A6) is not formally separated from regular black-hole models such as Hayward or Bardeen, creating ambiguity in counterexample classification.

**Direction:** Provide an explicit formal definition of the stability predicate that distinguishes horizonless stable equilibrium objects from regular black-hole models. Specify the bounded compactness or TOV-like limit that defines stability for non-black-hole remnants.

**Polish direction:** Formalize the explicit averaged null-convergence condition (A5) with a candidate mathematical expression, such as an integral bound on Ricci contraction along null generators, and provide the formal definition of Misner-Sharp compactness (D4) for the chosen metric class.

**Polish direction:** Provide an explicit formal definition of the stability predicate (A6) that clearly distinguishes horizonless stable equilibrium objects from regular black-hole models like Hayward or Bardeen.

**Polish direction:** Add a concrete example of a candidate counterexample that satisfies all assumptions A1-A6 (once formalized) but avoids trapped-surface formation, to illustrate what a valid falsifier would look like.

### Energy-Condition Defense — 9 / 10

The manuscript demonstrates exceptional discipline in distinguishing NEC, ANEC/AANEC, null convergence/Ricci contraction, SEC, and an independently assumed averaged focusing condition. It repeatedly refuses to conflate AANEC with the geometric focusing needed for Raychaudhuri-type arguments, explicitly marks SEC as not a substitute for AANEC, and treats the averaged focusing hypothesis (A5) as an independent premise rather than a consequence of AANEC. The boundary matrix and dependency-closure matrix make the logical separations operational, and the no-information branches honestly withhold theorem status when definitions are missing. The only deduction is that the explicit mathematical form of A5 and the precise Misner-Sharp threshold remain unresolved, which slightly limits the defensive closure of the boundary.

**Grounding:** formal_problem_and_hypotheses/block-4 — Directly states the non-interchangeability of the five conditions, which is the core of the energy-condition defense.

**Grounding:** study_design_and_methods/sdm-boundary-matrix — Explicitly denies that AANEC suffices for focusing, preventing a common conflation in the literature.

**Grounding:** appendix_variables_and_definitions/b1 — Clarifies that SEC failure does not invalidate the averaged-condition strategy, and that SEC cannot replace AANEC.

**Maximum strength:** The manuscript maintains a rigorous, multi-layered separation of energy conditions and focusing hypotheses, with explicit boundary matrices, dependency-closure matrices, and no-information branches that prevent conflation and overclaiming. The defense is not decorative; it is operationalized through proof obligations and counterexample screening criteria.

**Major weakness:** The explicit averaged null-convergence/focusing condition (A5) lacks a formal mathematical definition, which prevents full verification of whether candidate witnesses satisfy or evade it.

**Direction:** Supply the exact integrated form of A5, including the affine parameter range, the relation to the expansion scalar, and the class of null generators to which it applies. This will enable definitive adjudication of counterexamples.

**Major weakness:** The Misner-Sharp compactness parameter (D4) is marked as needing human input, preventing precise threshold calculation.

**Direction:** Provide the explicit formula for the Misner-Sharp compactness parameter in the spherically symmetric, isotropic-pressure model class, including the effective mass function within radius r.

**Polish direction:** Formalize the explicit averaged null-convergence condition (A5) with a precise mathematical expression, including the affine parameter range and its relation to the expansion scalar theta.

**Polish direction:** Supply the formal definition of the Misner-Sharp compactness parameter C for the spherically symmetric, isotropic-pressure model class, including the effective mass function.

**Polish direction:** Add a brief cross-reference table mapping each energy condition (NEC, ANEC, AANEC, SEC, null convergence, A5) to its logical role, boundary check, and consequence of violation, consolidating the scattered boundary matrices into a single authoritative reference.
