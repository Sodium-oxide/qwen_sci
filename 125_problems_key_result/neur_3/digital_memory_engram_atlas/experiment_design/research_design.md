# ExperimentDesign Agent: Digital Engram Fidelity Ladder and Causal Transfer Atlas

## Design status and intake

This protocol converts the selected Idea Agent direction, Digital Engram Fidelity Ladder and Causal Transfer Atlas (DEFL-CTA), into a falsifiable research design. It is not an execution record. The execution policy is \`DESIGN_ONLY\`: no human or animal neural data have been analyzed in this run, no memory has been uploaded or edited, and no neural stimulation or transplantation has occurred.

The target is not an abstract “memory file.” The study defines a task-specific memory $m$ by the information that a participant or animal encoded, the temporal and relational structure of its features, the neural state associated with encoding and retrieval, and the behavioral or report-level expression expected under held-out probes. Episodic, semantic, procedural, and fear-conditioning memories are not interchangeable endpoints.

## D0. Fidelity ontology and preregistration

Before analysis, preregister the memory class, task, cue set, encoding and retrieval windows, neural modality, subject inclusion rule, context variables, data splits, model capacity, error metrics, and manipulation targets. The fidelity ladder has five levels:

* **L0 - Predictive access:** a model predicts whether a target memory will be recalled or which item was studied.
* **L1 - Behavioral association:** a digital policy or stimulus can produce a target-related response in a constrained task.
* **L2 - Neural reinstatement:** a reconstruction reproduces a target-specific neural state under held-out cues.
* **L3 - Content-preserving reconstruction:** target features, temporal order, and relations are recovered with bounded omissions and false details.
* **L4 - Transfer or recollection claim:** a recipient system expresses the target content under novel probes and passes neural, behavioral, and independent content checks.

The primary endpoint at each level is prespecified separately. A report of improved recall is not counted as L3. A rodent fear response is not counted as human episodic recollection. A generated narrative is not counted as recovered content unless its details are matched against source events using an independent scoring procedure.

## D1. Data contract and memory task

The preferred data source is an ethically approved, de-identified human memory dataset with trial-level stimuli, behavioral responses, confidence, response time, and neural recordings such as intracranial EEG, scalp EEG, MEG, fMRI, or multimodal measurements. If an approved animal engram dataset is used, cell-tagging, stimulation condition, context, and memory-related behavior must be preserved. Data provenance must include subject, session, task, modality, preprocessing, electrode or region metadata, and consent or animal protocol identifiers.

Use a structured episodic task with item identity, temporal order, spatial or relational attributes, and source context. Include repeated encoding and delayed retrieval sessions so that the design can separate learning, consolidation, retrieval, and reconsolidation. Novel probes must test feature combinations not shown as a single cue during encoding. Negative controls include non-target memories, semantically related foils, state-matched but non-memory trials, and motor or arousal-matched trials.

Split the data by subject and session before feature learning. Within each training fold, estimate preprocessing and model hyperparameters. Hold out stimulus items, temporal order probes, relational combinations, sessions, and subjects when the task permits. Missing state labels, poor timing synchronization, low neural quality, or insufficient repeated trials are recorded as \`needs_human_input\`, not converted into negative or positive memory evidence.

## D2. Distributed engram state-space model

Memory is represented as a time-dependent latent state rather than a single cell or electrode. Let $z_t$ be a latent memory-related state, $x_t$ the sensory or task input, $c_t$ the context, and $r_i(t)$ the response of neural channel $i$. A candidate dynamical model is

\begin{equation}
z_t=A_{c_t}z_{t-1}+B_{c_t}x_t+\epsilon_t .
\end{equation}

The neural observation model is

\begin{equation}
\lambda_i(t)=\exp\left(b_i+w_i^\top z_t+v_i^\top q_t\right),
\end{equation}

where $\lambda_i(t)$ is the conditional spiking intensity, $q_t$ contains measured movement, arousal, task, and history covariates, and $\epsilon_t$ captures process uncertainty. For non-spiking modalities, replace the point-process observation with a modality-appropriate likelihood while keeping the latent state and context separation.

Fit nested models: stimulus-only, context-only, memory-state, memory-state plus history, and distributed memory-state models. Compare them using held-out predictive log likelihood, calibration, neural pattern similarity, and temporal generalization. The state-space model is a measurement device, not a claim that the brain literally implements a linear dynamical system. A memory state is accepted only if it predicts target-specific held-out responses beyond state, motor, arousal, and session controls.

## D3. Digital storage and reconstruction

Store a versioned digital representation consisting of the task schema, learned state-space parameters, uncertainty, cue-to-state map, feature relations, provenance, and an explicit list of unknown or unobserved details. Do not store a generated narrative as the sole representation. The digital object must be able to answer held-out queries about:

1. item or event identity;
2. temporal order;
3. source context;
4. relations among people, objects, places, or actions;
5. affective or behavioral response where that is the defined memory target.

Compare four reconstruction systems: a behavioral classifier, a neural-state decoder, a generative latent-state model, and a hybrid model. Evaluate exact content accuracy, relational consistency, temporal-order accuracy, neural reinstatement similarity, confidence calibration, omission rate, false-detail rate, and performance on novel cue combinations. A plausible but unsupported detail is an error, not a successful reconstruction.

Define a content fidelity score for a target memory $m$ as

\begin{equation}
F_{\mathrm{content}}(m)=1-\frac{E_{\mathrm{omission}}(m)+E_{\mathrm{false}}(m)+E_{\mathrm{relation}}(m)}{Z_m},
\end{equation}

where the numerator contains independently scored omission, false-detail, and relational errors, and $Z_m$ is a preregistered normalization. The score is reported with its components; a high behavioral score cannot hide a high false-detail rate. A subjective report is analyzed as one endpoint with confidence and source monitoring, not as the sole ground truth.

## D4. Digital manipulation and collateral effects

Begin with in-silico manipulation of the latent representation. Change one target feature, temporal relation, or contextual attribute while holding other dimensions fixed. Generate predictions for target recall, non-target memories, affect, decision confidence, and neural reinstatement. Use matched edits to a non-target memory, sham edits, and state-only edits. The key question is selectivity: does the edit alter the target while preserving unrelated content and general cognition?

If a future approved neural intervention is feasible, translate one model-defined dimension into a subject-specific stimulation or inhibition policy only after safety and feasibility review. The design requires a target condition, sham condition, non-target condition, and nuisance-matched perturbation. Outcomes include target memory, neighboring memories, source-monitoring errors, false details, confidence, agency, affect, and task strategy. The proposal does not prescribe an executable clinical or animal stimulation recipe.

The manipulation module is considered successful only if the target-specific effect exceeds non-specific disruption and is replicated under held-out cues. A global recall increase, generalized fear response, or altered arousal is not target-specific memory editing.

## D5. Cross-session and cross-subject transfer

Transfer is tested in increasing order of strength:

* Transfer a classifier or retrieval policy across sessions.
* Transfer a task-defined association across models or subjects.
* Transfer a digital latent representation to a recipient model and test neural-state and behavioral alignment.
* In a future approved biological study, test whether a recipient expresses target content under novel probes.

Align representations using only training data and compare against shuffled-subject, non-target, and semantic-similarity baselines. Evaluate content, temporal order, relational structure, neural reinstatement, and collateral effects independently. A recipient that reproduces a motor response but fails target relational probes is classified as policy transfer, not memory transplantation. Cross-subject transfer must retain the fact that two individuals may not share the same subjective episode even if they can perform the same task.

## D6. Causal validation and decision rules

The causal effect of a target memory dimension $k$ on an outcome $\phi$ is written

\begin{equation}
\tau_k=\mathbb{E}[\phi\mid do(u_k=1),c]-\mathbb{E}[\phi\mid do(u_k=0),c],
\end{equation}

where $u_k$ is a targeted representation manipulation and $c$ fixes stimulus, task, state, nuisance variables, and recipient context. A dimension can be promoted to a stronger fidelity level only if:

1. the corresponding content or relation is specified before testing;
2. the effect generalizes to held-out cues or contexts;
3. non-target memories and nuisance outputs remain within their prespecified bounds;
4. the effect exceeds sham and matched non-specific disruption;
5. independent content scoring agrees with neural and behavioral evidence.

For animal engram work, cell tagging and stimulation studies can test causal participation in memory expression, but this module remains a mechanistic bridge and requires animal welfare review. For human neural prostheses or stimulation, informed consent, clinical or institutional approval, safety monitoring, data governance, and an autonomy review are mandatory. No future result may be labeled “transplanted human memory” unless it passes the L4 protocol and its identity claim is explicitly justified.

## Expected branches and failure handling

If L0 succeeds but L1 fails, the digital system has predictive access without a reliable intervention. If L1 succeeds but L2 fails, a behavioral policy may have transferred without neural reinstatement. If L2 succeeds but L3 fails, the system reproduces a neural correlate without content-complete reconstruction. If L3 succeeds within a subject but L4 fails across subjects, storage or reconstruction may be feasible while transplantation is not established. If false details increase after manipulation, the system fails the fidelity gate even if recall accuracy improves.

If a batch violates its data or model contract, discard the failed batch, preserve the failure record, and set the affected fidelity field to \`needs_human_input\`. Keep negative and null results. Store data identifiers, preprocessing, model versions, fold assignments, random seeds, perturbation definitions, independent scoring rubrics, and all unknowns. The final artifact must retain \`observed_results=[]\` until an approved execution generates measurements.

## Human review requirements

Before any real execution, experts must review data-use permissions, consent, privacy and governance, animal welfare or human-subjects approvals, stimulation safety, power, model leakage, content scoring, false-memory risk, agency and autonomy, and the interpretation of neural reinstatement. The project is intended to make digital memory research more testable and ambitious, not to imply that a speculative transfer technology is already clinically available.

## Author handoff

The Author Agent may use the Survey registry, DEFL-CTA Idea result, and this design. It must preserve the L0-L4 fidelity ladder, the distinction between behavioral expression and subjective recollection, all unknowns, all collateral-memory and autonomy requirements, and the \`DESIGN_ONLY\` status. It may write conditional outcome branches but may not report a completed memory upload, a human memory transplant, or an observed neural manipulation.
