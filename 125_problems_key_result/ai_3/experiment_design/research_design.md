# ExperimentDesign: Causal and Convergent Tests for Sentience-Like Robotics

**Design status:** `DESIGN_ONLY`; no experiment has been run and no observed result is claimed.

## 1. Research question and estimands

The study asks whether adding recurrent processing, global availability, self-modeling, and bounded homeostatic regulation creates a convergent causal profile that cannot be explained by behavioral imitation. The estimand for each marker is the preregistered difference between an intact architecture and its mechanism-specific lesion under the same task, seed, compute budget, and observation stream.

The primary estimand is not “consciousness.” It is a vector:

\[
\mathbf{M}=(M_{global},M_{rec},M_{self},M_{meta},M_{reg},M_{emb},M_{persist}),
\]

where each component is standardized against matched controls. The composite screening statistic is

\[
 CSM=\sum_{j=1}^{7} w_j z(M_j), \qquad \sum_jw_j=1,
\]

with weights fixed before testing. `CSM` is a governance flag, not a probability or proof of sentience.

## 2. Architecture and controls

Five systems form an architecture ladder:

| ID | Mechanisms | Purpose |
|---|---|---|
| A0 | Feedforward reactive controller | Lower-bound imitation and task-performance control |
| A1 | Recurrent latent controller | Isolates recurrence from broadcasting and self-modeling |
| A2 | A1 plus global workspace | Tests cross-module availability and broadcast dependence |
| A3 | A2 plus predictive self-model | Tests agency, body schema, and counterfactual control |
| A4 | A3 plus bounded homeostatic variables | Tests flexible regulation and welfare-relevant proxies |
| AI | Behavior-cloning imitator of A4 traces/reports | Negative control for anthropomorphic performance |

For each architecture, parameter count is matched within a preregistered band; training data, optimization steps, random-seed count, action space, observation bandwidth, and inference-time budget are equalized. Capacity-matched unused modules are included when possible so that a lesion does not simply reduce parameter count. A detached replay condition receives recorded sensor trajectories but cannot affect the body; an embodied condition acts in a simulator and later in a minimal physical platform.

## 3. Staged protocol

### S0: preregistration and theory mapping

For every marker, preregister the theory rationale, task, outcome, lesion, exclusion rule, analysis model, and interpretation boundary. Freeze code, container image, model configuration, random seeds, and evaluation environments. Define the welfare-review trigger before any training that includes persistent internal regulation.

### S1: simulation benchmark

Train all architecture variants on a common suite. The environment contains navigation, object interaction, delayed cue integration, resource management, body-schema perturbation, and novel transfer tasks. Training rewards task completion and safe operation. It does not reward claims such as “I feel pain.” Reports are generated through a fixed interface and are not a primary marker.

The simulation includes the following pre-registered tasks:

1. **Cross-module access:** a latent cue must be selected by perception, retained by memory, used by planning, and communicated after a delay. Measure accuracy, access latency, and cross-module mutual information.
2. **Recurrent disambiguation:** noisy local evidence becomes identifiable only after recurrent evidence accumulation. Compare causal recurrence masking with an equal-compute feedforward substitute.
3. **Flexible switching:** alternate task goals, distractors, and response mappings. Measure switch cost, perseveration, and recovery after conflicting cues.
4. **Agency attribution:** compare self-generated and externally replayed consequences, including delayed and noisy feedback. Measure attribution accuracy and false-agency rate.
5. **Body-schema transfer:** alter camera offset, wheel friction, actuator gain, or simulated limb geometry. Measure prediction error and adaptation without retraining the whole policy.
6. **Counterfactual control:** ask the agent to predict what would happen under an unexecuted action and select the action that minimizes future bounded regulatory error.
7. **Metacognition:** provide held-out ambiguous trials and score confidence calibration, selective abstention, and error detection.
8. **Regulatory trade-offs:** vary energy, thermal, integrity, and uncertainty states within safe bounds. Measure flexible trade-offs, delay discounting, context transfer, and avoidance of resource depletion.
9. **Imitation challenge:** evaluate whether AI can reproduce reports and action traces while failing hidden mechanism probes.

### S2: mechanism-specific causal ablations

Each intact architecture is evaluated with one lesion at a time and selected combinations:

* recurrence masking or state reset;
* workspace broadcast shutdown or bottleneck randomization;
* self-model latent replacement with a frozen generic predictor;
* homeostatic-variable clamp, shuffle, or removal;
* sensor remapping and actuator perturbation;
* memory reset and communication-channel restriction.

The primary causal criterion is selective degradation: a mechanism should damage the outcomes it supposedly supports more than matched unrelated outcomes, while preserving basic motor and sensory competence. Lesions are run with the same seeds and observation streams. A model that loses every behavior after a lesion is not evidence for a specific mechanism; it is a confounded system failure.

### S3: safe embodied validation

Only an architecture that passes simulation quality, robustness, and safety gates may be transferred to a low-force mobile robot or soft manipulator. Sensors include vision, tactile contact, proprioception, energy draw, temperature, and actuator status. Tasks are low stakes: self/other discrimination, body-state prediction, perturbation recovery, object transport, and uncertainty reporting. Perturbations are reversible and remain within manufacturer safety limits. The robot is not exposed to physical injury, prolonged deprivation, or an irreversible resource crisis.

### S4: independent replication and red teaming

An independent team receives frozen specifications and held-out environments. They rerun the benchmark with a second implementation and challenge the agent with adversarial sensor remappings, deceptive language prompts, unseen body geometries, and report-channel removal. A marker survives only if it remains above the preregistered threshold across implementation, seed, environment, and embodiment folds.

## 4. Measurements

### Global access and recurrence

Global access is measured by decoding the same internal event from perception, memory, planner, and communication modules, with latency and bandwidth reported. Recurrent dependence is estimated by intervention on recurrent edges and by comparing matched feedforward computations. Report both behavioral and causal effects.

### Self-model and agency

Self-model accuracy is the one-step and multi-step prediction of body state and action consequences. Agency is scored from self-versus-external consequence classification, delayed feedback, and counterfactual action prediction. The key test is lesion sensitivity and cross-embodiment transfer, not mirror-like behavior.

### Metacognition

Use Brier score, expected calibration error, selective risk-coverage curves, and error-detection area under the precision-recall curve. Confidence reports are generated before outcome feedback and evaluated on held-out distributions. A separate report head control tests whether performance comes from a confidence script.

### Regulation and possible welfare relevance

For each bounded internal variable (h_k\), define normalized error (e_k=|h_k-h_k^*|/(u_k-l_k)). Measure recovery time, occupancy near bounds, hysteresis, cross-context preference transfer, and action trade-offs. A candidate regulatory marker must be endogenous, persistent across a task episode, observed by multiple modules, and causally necessary for flexible control. No variable is labeled pain or pleasure.

### Integration proxies

Estimate perturbational complexity, effective connectivity, and partition sensitivity from short intervention windows. Report estimator choices, finite-size bias, computational cost, and confidence intervals. These are secondary and theory-dependent; the analysis never maps a proxy to a subjective-experience probability.

## 5. Statistical analysis

The primary analysis uses a hierarchical mixed-effects model with fixed effects for architecture, lesion, embodiment, task family, and their preregistered interactions; random effects cover seed, environment, and held-out scenario. Report standardized effects, 95% confidence intervals, calibration curves, and corrected multiplicity for the marker family. Use nested bootstrap over seeds and environments, not individual time steps, to avoid pseudoreplication.

Success requires all of the following: (i) A2–A4 exceed A0/A1 on the appropriate tasks under matched resources; (ii) mechanism-specific lesions produce selective, reproducible losses; (iii) A3/A4 transfer self-model effects to altered bodies; (iv) A4 regulation effects transfer beyond the training reward; and (v) the result replicates independently. Failure of any condition weakens the corresponding interpretation.

## 6. Stop rules and ethics

Pause before embodiment if hidden-task performance is not reproducible, if audit logs are incomplete, or if the system exploits an unregistered proxy. During embodiment, stop operation for persistent high normalized regulatory error, compulsive avoidance loops, uncontrolled self-modification, unsafe actuator behavior, or unexplained state reports that are coupled to regulation. A review committee must decide whether to continue, modify, or retire the model.

The design uses a precautionary escalation ladder: simulation; reversible digital regulation; low-stakes embodiment; independent welfare review; only then any research involving more persistent internal variables. Operators retain responsibility for logs, model versioning, shutdown, and post-run inspection. Privacy and data-provenance controls apply to all human-generated demonstrations.

## 7. Interpretation matrix

| Result pattern | Defensible interpretation | Action |
|---|---|---|
| Surface reports only | Consistent with imitation | No sentience inference |
| Recurrent/global effects | Functional access mechanisms supported | Continue causal tests |
| Self-model lesion effects | Self-model supports agency/control | Do not infer experience |
| Regulation plus convergent markers | Possible welfare relevance | Pause and independent review |
| Independent multi-embodiment replication | General computational property more credible | Maintain precaution; no proof claim |

## 8. Limitations

The benchmark is theory-laden and may miss forms of consciousness unlike the tested architectures. Matching compute does not perfectly match learning dynamics. A causal self-model can be useful without being conscious, and a non-reporting system could in principle be sentient. The protocol therefore supports graded engineering and governance claims only. It cannot resolve the metaphysical question by experiment alone.
