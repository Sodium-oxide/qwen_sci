# Survey Agent: Can Human Memory Be Stored, Manipulated, and Transplanted Digitally?

## Scientific reframing

The science-fiction wording "upload a memory to the cloud and download it into a machine" combines several different problems. This survey separates them into four testable levels:

1. **Mechanistic representation:** which biological variables participate in encoding, consolidation, retrieval, and reconsolidation of a memory?
2. **Readout:** can a defined memory state be decoded from neural activity or a neural prosthesis?
3. **Manipulation:** can a memory representation be strengthened, weakened, or altered without changing unrelated memories and behavior?
4. **Transfer:** can a representation be transported across a brain, person, or digital substrate and produce content-specific recall rather than a generic response?

The fourth level is much stronger than the second. A classifier that predicts whether a subject will remember a trial does not contain the episodic memory itself. Likewise, activating a mouse engram can produce a learned behavioral expression, but it does not demonstrate that a complete autobiographical episode has been digitized or transplanted into another biological system.

The survey's central question is therefore:

> Can a content-specific memory state be represented digitally with enough fidelity that it can be manipulated, transferred, and independently recognized after reconstruction, while preserving the distinction between neural correlation, behavioral expression, and subjective recollection?

## What memory is

Memory is not one homogeneous storage system. Cognitive neuroscience distinguishes episodic, semantic, procedural, working, and conditioning-related forms, each with different timescales and neural dependencies [E1]. Human episodic memories are reconstructive: retrieval can combine stored traces with schemas, current goals, and post-event information [E9]. A digital representation must consequently specify what is to be preserved: sensory detail, temporal order, affect, semantic identity, behavioral response, or a reportable sense of recollection.

The computer analogy of input, storage, and retrieval is useful as an engineering abstraction, but a biological memory is not a passive file. Encoding changes the state of a network; consolidation redistributes or stabilizes information; retrieval can reactivate and modify the trace. Molecular and systems-level mechanisms operate together across synapses, cells, and circuits [E8]. The target of a digital memory system should therefore be a task-defined memory phenotype and its neural signature, not an assumption that one static neural location contains a complete file.

## Engrams and causal memory manipulation

An engram is an operational label for a set of cells or synapses whose activity is associated with a memory and whose manipulation can influence its expression. Modern engram work has moved beyond correlation by tagging cells during learning and testing whether subsequent activation or inhibition changes memory-related behavior [E2]. In mice, optogenetic stimulation of hippocampal cells tagged during fear learning was reported to trigger memory recall [E3]. Ramirez et al. combined a neutral context with an aversive experience and showed that activating a tagged hippocampal ensemble could produce a fear response in the neutral context, a result widely described as a false-memory-like manipulation [E4].

These studies establish an important causal principle: a selected neural ensemble can participate in the expression of a learned association. They do not establish that the ensemble is a complete, portable representation. The observed behavior can depend on amygdala, hippocampal, cortical, and neuromodulatory systems; optogenetic activation may impose an artificial state; and fear behavior is not equivalent to the full content or phenomenology of a human episodic memory.

Chen et al. reported in 2019 that targeted manipulation of hippocampus-mediated memories could enhance or suppress memory-related behavior in mice [E5]. This source is particularly relevant to the motivating statement, but the correct evidence boundary is precise: the work demonstrates artificial enhancement and suppression of a mouse memory-related behavioral expression under an experimental manipulation. It is not a digital storage or cross-subject transplantation result.

## Human neural readout and prosthetic interfaces

Human studies show that neural activity can be used to predict or modulate memory performance. Hippocampal neural prosthesis work has explored stimulation patterns derived from a person's own encoding-related activity to facilitate later recall [E6]. Closed-loop stimulation studies have also reported memory-related improvements when stimulation is timed to individual neural states or networks [E7]. These results support a practical bridge between neural recording, model-based stimulation, and memory assistance.

The bridge remains task-specific. A prosthesis may improve the probability of remembering a list item or experimental image without storing a freely reportable episode in a general-purpose digital format. The signal used by a prosthesis may be a compressed control variable, a network state, or a stimulation policy. Improving recall is evidence for functional intervention, not proof that the system has copied all memory content.

## What digital storage would require

A digital memory substrate would need at least five properties:

* **Content specificity:** it distinguishes the target memory from other memories and from arousal or motor state.
* **Temporal and relational structure:** it preserves who, what, when, where, and the relations among features.
* **Cross-context reconstruction:** it produces the target memory under new probes, not only the original training cue.
* **Identity and state continuity:** it specifies whether the result is a behavioral imitation, a neural reinstatement, or a subjectively reportable recollection.
* **Error accounting:** it quantifies omissions, insertions, confabulations, and changes caused by retrieval itself.

These requirements imply a high-dimensional, distributed representation. A useful digital object may be a generative model of memory-relevant neural dynamics rather than a raw recording. However, a generative model that produces a plausible story can hallucinate details. Fidelity must be tested against held-out neural, behavioral, and report-level evidence.

## Manipulation and transplantation

Manipulation is already possible in limited animal-model senses: activating tagged ensembles, changing excitability, modulating consolidation, or delivering closed-loop stimulation can change later memory expression [E3]-[E7]. The effect can be beneficial or harmful, and it can be selective only within a constrained paradigm. Human memory is additionally shaped by language, social context, self-model, and reconstruction [E1], [E9].

Transplantation is a stronger claim with several possible meanings:

1. transfer of a stimulus-response classifier;
2. transfer of a neural stimulation policy;
3. transfer of a behavioral association;
4. transfer of a neural state that reinstates a content-specific memory;
5. transfer of a first-person episodic recollection.

Only the first two are close to current digital neurotechnology. The third has partial animal-model analogues. The fourth remains an open empirical target. The fifth cannot be declared solved without an operational theory of subjective recollection and a way to validate content identity independently of the recipient's report.

## Evidence synthesis

The current literature supports four conclusions. First, memory depends on distributed, dynamic systems rather than a single static location [E1], [E2], [E8]. Second, tagged neural ensembles can have causal leverage over memory-related behavior in rodents [E3]-[E5]. Third, human neural interfaces can decode and modulate memory performance in constrained tasks [E6], [E7]. Fourth, neither animal engram manipulation nor human prosthetic assistance has demonstrated a complete digital memory upload, arbitrary digital editing, or memory transplantation between humans.

The most productive scientific position is not that digital memory is impossible. It is that the field needs a fidelity ladder. A system should progress from decoding, to selective manipulation, to cross-context reconstruction, to transfer, and finally to independent content and experience validation. The proposed ExperimentDesign Agent will test the first four levels computationally and specify a future causal validation module without claiming that a human memory has already been transplanted.

## Gap ledger

| Gap ID | Research gap | Evidence state | Resolution target |
|---|---|---|---|
| G1 | No common operational definition separates memory content, behavioral expression, neural reinstatement, and subjective recollection. | Confirmed conceptual gap | Pre-register a multi-level fidelity ladder. |
| G2 | Engram manipulation shows causal behavioral effects but not portable, content-complete representations. | Confirmed mechanistic gap | Compare neural, behavioral, and content-level transfer tests. |
| G3 | Human prostheses improve constrained memory tasks but do not establish general digital storage. | Confirmed translational gap | Test cross-session and cross-context reconstruction with held-out probes. |
| G4 | Neural memory representations are distributed and dynamic across encoding, consolidation, and retrieval. | Confirmed systems gap | Use state-space models and time-dependent engram signatures. |
| G5 | Digital reconstruction can be plausible while introducing omissions or confabulations. | Confirmed measurement gap | Score false-detail, omission, and identity errors independently. |
| G6 | Selective manipulation may alter unrelated memories, affect, or agency. | Confirmed ethical and safety gap | Include collateral-memory and autonomy endpoints. |
| G7 | Cross-subject transfer lacks a validated identity-preserving protocol. | Candidate gap | Separate transfer of policy, association, neural state, and recollection. |
| G8 | No accepted causal criterion defines when a digital memory representation is functionally equivalent to its biological source. | Candidate gap | Require selective intervention and independent content validation. |

## Handoff to Idea Agent

The Survey recommends a **Digital Engram Fidelity Ladder and Causal Transfer Atlas (DEFL-CTA)**. Its primary task is to determine which properties of a memory can be digitally represented and manipulated at each fidelity level, without collapsing a successful decoder into a claim of memory transplantation. Each proposed direction must reference G1-G6, report the target memory class, state the substrate and time scale, and preserve a separate status for neural evidence, behavioral evidence, content evidence, and subjective report.

## Source registry

[E1] L. R. Squire and S. M. Z. Wixted, “The cognitive neuroscience of human memory since H.M.,” *Neuron*, vol. 71, pp. 275-293, 2011.

[E2] S. A. Josselyn and S. Tonegawa, “Memory engrams: Recalling the past and imagining the future,” *Science*, vol. 367, no. 6473, eaaw4321, 2020.

[E3] Y. Liu et al., “Optogenetic stimulation of a hippocampal engram activates fear memory recall,” *Nature*, vol. 484, pp. 381-385, 2012.

[E4] S. Ramirez et al., “Creating a false memory in the hippocampus,” *Science*, vol. 341, pp. 387-391, 2013.

[E5] B. K. Chen et al., “Artificially enhancing and suppressing hippocampus-mediated memories,” *Current Biology*, vol. 29, pp. 1885-1894.e4, 2019, doi: 10.1016/j.cub.2019.04.065.

[E6] R. E. Hampson et al., “Developing a hippocampal neural prosthetic to facilitate human memory encoding and recall,” *Journal of Neural Engineering*, vol. 15, no. 3, 036014, 2018.

[E7] M. Ezzyat et al., “Closed-loop stimulation of temporal cortex rescues functional networks and improves memory,” *Nature Communications*, vol. 9, 365, 2018.

[E8] E. R. Kandel et al., “The molecular and systems biology of memory,” *Cell*, vol. 157, pp. 163-186, 2014.

[E9] D. L. Schacter, “The seven sins of memory: Insights from psychology and cognitive neuroscience,” *American Psychologist*, vol. 54, pp. 182-203, 1999.

[E10] M. Ienca and R. Andorno, “Towards new human rights in the age of neuroscience and neurotechnology,” *Life Sciences, Society and Policy*, vol. 13, no. 5, 2017.
