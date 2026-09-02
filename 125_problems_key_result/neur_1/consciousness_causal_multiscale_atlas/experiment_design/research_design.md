# ExperimentDesign Agent Report

## Design objective

The selected Idea Agent direction, the **Causal Multiscale Consciousness Atlas (CMCA)**, turns ``Where does consciousness lie?'' into a test of causal organization. It does not search for a single anatomical coordinate. It asks which process is necessary for a specified conscious experience, at what time and scale, and whether the same process survives the removal of reporting demands.

The design separates five constructs: phenomenal experience, access, report, self-awareness, and global conscious state. It then compares theory-specific predictions for global neuronal workspace, integrated information, recurrent processing, higher-order/predictive accounts, and Orch-OR. The final molecular module is intentionally independent: a microtubule-related signal is not allowed to become a consciousness mechanism unless it has a prespecified timing, perturbation, and experience-linked prediction that beats neural-network and decoherence alternatives.

## Execution boundary

This artifact is `DESIGN_ONLY`. It performs no participant recruitment, patient contact, TMS, anesthesia, sleep manipulation, EEG, MEG, fMRI, ECoG, molecular assay, data acquisition, model training, or simulation. It reports no neural, behavioral, molecular, or quantum result. Any future human or laboratory implementation requires qualified personnel, ethics and safety review, consent or lawful data basis, approved equipment procedures, and independent statistical and theory review.

## D0: construct validation and preregistration

Before future data are inspected, the team freezes a construct dictionary. ``Phenomenal experience'' is operationalized by a specified conscious perceptual content and a convergent report/no-report proxy; ``access'' is flexible use of information; ``report'' is a response channel; ``self-awareness'' is a distinct higher-order representation; and ``state'' is a broad capacity for conscious processing. The design does not assume that a verbal response is experience itself.

D0 also freezes theory predictions, candidate and null dynamic models, stimulus and state contrasts, perturbation targets, measurement modalities, quality-control criteria, hold-out partitions, missing-data rules, and model-comparison scoring. Every theory must specify a timing/topology/intervention pattern before primary data are viewed. An exploratory observation may refine a future experiment but cannot be retroactively relabeled a preregistered prediction.

The no-report proxy receives a separate validation step. The future team must show that it tracks the intended conscious manipulation under conditions where report and motor demands are absent or held constant. A physiological or involuntary response is not automatically an experience measure; its validity is part of the study, not an assumption.

## D1: report-matched and no-report content conditions

D1 creates a sensory-matched contrast, such as seen versus unseen or consciously differentiated versus masked content, using both report and no-report versions. The specific paradigm must be selected and approved by a qualified consciousness research team. The design records content, confidence, attention, motor response, arousal, and report timing separately. A no-report condition reduces a major confound but does not magically reveal private experience; its proxy and convergent validation remain essential.

The D1 gate requires that the target contrast not be reducible to motor output, confidence, attention, or decision. If the apparent consciousness signature is present only when participants press a button or verbally describe a stimulus, it is classified as a report marker. If it distinguishes wakefulness from anesthesia but not content, it is classified as a state marker. These classifications keep the study scientifically informative without promoting an ambiguous signal.

## D2: multiscale recording and candidate localization

D2 combines complementary recording scales. Noninvasive electrical or magnetic recording supplies timing and perturbational response; structural and functional imaging supplies spatial registration and network topology; and, only where independently indicated and ethically approved, clinically available recordings can provide finer local timing. The proposal does not prescribe a single instrument or operating protocol. It requires that every modality carry a signal-quality, artifact, and registration record.

The future feature vector includes posterior recurrence, frontoparietal/global broadcasting, thalamocortical coupling where measurable, higher-order/metacognitive variables, effective connectivity, and a PCI-like perturbational complexity measure. A passive association is never declared a location or mechanism. The output of D2 is a set of candidate processes and timing windows for D3, not a final answer.

The distinction between state and content is crucial. A complexity measure may increase when the brain is awake and decrease under deep anesthesia while remaining uninformative about whether a particular stimulus was consciously seen. Conversely, a content decoder may classify a perceptual distinction without establishing that the decoded activity is causally necessary. CMCA keeps both outputs and their limitations visible.

## D3: targeted causal perturbation

D3 tests candidate processes using a future safety-approved perturbation, such as neuronavigated noninvasive stimulation, with sham and non-candidate target controls. The exact intervention and parameters are determined by qualified investigators and their safety review. The scientific contrast is not simply ``stimulation versus no stimulation.'' It is whether perturbing a proposed recurrent, broadcast, higher-order, or thalamocortical process changes a validated experience-sensitive outcome while preserving a distinction from report, motor, confidence, and attention effects.

For a candidate target $k$, the future causal effect is

$$\tau_k=E[\phi\mid do(u_k=1),c]-E[\phi\mid do(u_k=0),c],$$

where $\phi$ is the validated experience-sensitive proxy and $c$ holds the content and control condition fixed. The intervention operator $do(\cdot)$ denotes an approved causal manipulation, not a software-only correlation. A strong mechanism candidate should show a target-specific effect on $\phi$ beyond the matched control intervention. If it changes report accuracy but not $\phi$, it is evidence for report machinery rather than experience mechanism.

No single perturbation settles the field. A posterior effect could reflect sensory processing; a frontal effect could reflect metacognition or report; a global effect could reflect arousal. CMCA therefore uses the pattern across target, timing, condition, and control, with out-of-sample prediction in D4.

## D4: theory-specific out-of-sample comparison

The future data are represented in a multiscale state-space model:

$$x_{t+1}=F_{\theta}x_t+B_{\theta}u_t+\eta_t,\qquad y_t=A_{\theta}x_t+\epsilon_t.$$

Here $x_t$ is a latent neural state, $u_t$ is the approved perturbation input, $y_t$ is the observed multimodal signal, $F_{\theta}$ represents state evolution, $B_{\theta}$ represents perturbation coupling, $A_{\theta}$ maps latent state to measurement, and $\eta_t,\epsilon_t$ are process and measurement noise. The parameters and structural restrictions differ by theory. GNW models constrain late broadcast; recurrent models constrain earlier feedback; IIT-inspired models constrain causal integration/differentiation; higher-order/predictive models constrain hierarchical or metacognitive contributions; and Orch-OR adds a molecular bridge only in D5.

The primary theory score is a held-out predictive score,

$$S_m=\log p(D_{\mathrm{holdout}}\mid M_m)-\lambda C(M_m),$$

where $M_m$ is theory model $m$, $D_{\mathrm{holdout}}$ is data not used to select the restrictions, $C(M_m)$ penalizes flexibility, and $\lambda$ is frozen before analysis. The score is not a vote on metaphysics. It measures which specified model predicts the joint condition, timing, topology, and intervention pattern with the least unsupported flexibility. A theory that fits training data but fails held-out no-report or perturbation conditions does not win by post hoc reinterpretation.

The common null contains ordinary sensory, arousal, report, attention, motor, and network-dynamics explanations. It is not ``no consciousness.'' It is the minimum model needed to explain the observed signals without the theory-specific mechanism. This makes a positive comparison stronger and a negative comparison interpretable.

## D5: independent Orch-OR molecular bridge stress test

D5 directly engages the Penrose-Hameroff proposal while respecting its burden of proof. The future team first registers a molecular/quantum observable, its expected timing and scale, the experience-state contrast to which it should respond, and the measurement method. The observable must be independently measured rather than inferred from a neural EEG feature. The study must also specify network, synaptic, thermal, sensor, and decoherence null models.

The relevant test is not ``are there vibrations in microtubules?'' It is whether the specified molecular process changes in a reproducible way with a conscious-state manipulation, precedes or couples to the relevant neural dynamics as predicted, survives controls, and improves theory prediction beyond ordinary biological network models. Tegmark's decoherence analysis provides a serious timescale objection, while Hagan, Hameroff, and Tuszynski show why the conclusion depends on biological assumptions and parameter choices. CMCA makes the disagreement testable rather than settling it rhetorically.

A positive molecular signal would not immediately prove Orch-OR; it would create a candidate bridge requiring replication and causal linkage. A negative D5 result would reject the specified Orch-OR bridge under the tested conditions, not prove that no quantum process exists anywhere in biology. This is the correct granularity for a controversial theory.

## Variables, controls, and primary evidence vector

| Design element | Specification |
|---|---|
| Independent variables | Conscious/unconscious content; report/no-report; state; perturbation target and timing; sham/control target; sensory content; participant/session; molecular condition. |
| Dependent variables | Experience proxy; content decoding; report/confidence; effective connectivity; recurrence; global broadcast; perturbational complexity; causal effect; independently measured molecular signal. |
| Essential controls | Sensory-matched unseen condition; report-matched/no-report pair; sham and non-candidate target; motor/report control; attention/confidence covariates; sensor/vascular artifacts; network and decoherence nulls. |
| Primary endpoint | Causal evidence vector identifying necessary process, scale, and theory-predictive pattern under report controls. |
| Secondary endpoints | State/content/report dissociation; front/back/topology effects; participant replication; held-out theory score; Orch-OR bridge support/rejection code. |

The primary endpoint remains a vector rather than a single consciousness number. A vector preserves whether evidence concerns state, content, report, causal necessity, or molecular bridge. It prevents a large state-complexity effect from masking a failed content or causal test.

## Risks, governance, and human review

The main risk is category error: a neural correlate is called a mechanism, a report is called experience, or a microtubule oscillation is called quantum consciousness. The design counters this with construct separation, no-report controls, causal perturbation, theory preregistration, held-out prediction, and explicit null models. Human experts must review the operational proxy, the perturbation safety, the analysis model, the ethical status of any sleep/anesthesia/clinical component, and the validity of the molecular measurement.

No organoid or nonhuman model is assigned consciousness by this proposal. Any future model-system work would require separate construct validation and ethics review. The current artifact uses no participant or patient data, performs no intervention, and provides no medical diagnosis or treatment.

## Handoff to Author

The Author Agent receives the construct dictionary, theory prediction matrix, CMCA D0--D5 stages, causal equations, BREL-style pass/fail logic, source-bound evidence cards, and human-review register. It may conclude that consciousness is best studied as a distributed causal process and that current theory competition is unresolved. It may not claim a confirmed frontal, posterior, quantum, or microtubule location, and it may not report an experiment that this workflow did not execute.
