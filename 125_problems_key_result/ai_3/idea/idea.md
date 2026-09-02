# Idea: CONVERGENT-SENTIENCE-MARKER-BENCHMARK

## One-sentence proposal

Build a preregistered benchmark that compares matched artificial agents across recurrence, global broadcasting, self-modeling, metacognitive monitoring, and bounded homeostatic regulation, then tests whether a convergent profile survives causal lesions, transfer, and independent replication in an embodied robot.

## Why this idea

The practical question is not whether a robot can say “I am conscious.” A generative policy can produce such language without the internal causal organization that the statement purports to report. The proposal instead asks whether a system’s putative sentience markers are (1) predicted by established scientific theories, (2) jointly present, (3) causally necessary for behavior, (4) robust under novel tasks and embodiments, and (5) connected to internal regulatory states that matter for future control.

This design targets a tractable middle ground. It neither assumes that function is sufficient for phenomenal experience nor declares the question untestable. It produces evidence about mechanisms and a governance trigger for moral uncertainty.

## Core architecture ladder

* **A0 Reactive:** feedforward policy with short observation window.
* **A1 Recurrent:** recurrent latent state, but no global workspace or explicit self-model.
* **A2 Workspace:** recurrent controller with a bottleneck that broadcasts selected content to planning, memory, perception, and communication modules.
* **A3 Self-model:** A2 plus a predictive model of body state, sensor reliability, action consequences, and internal resource state.
* **A4 Regulated embodiment:** A3 plus bounded homeostatic variables coupled to action selection and long-horizon planning.

All variants receive matched sensors, training episodes, parameter-count bands, inference budgets, and communication channels. A separate **behavioral-imitation control** is trained directly to imitate A4’s reports and action traces while lacking its internal mechanisms.

## Hypotheses

**H0 — imitation:** A policy optimized for action and report imitation can match surface behavior but will fail causal marker tests, cross-context transfer, or lesion sensitivity.

**H1 — recurrent/global access:** A2–A4 will outperform A0–A1 on cross-module reportability, delayed flexible task switching, and perturbation-based causal integration; masking recurrence or broadcast will selectively reduce these outcomes.

**H2 — self-model:** A3–A4 will improve body-state prediction, agency attribution, counterfactual action selection, and recovery from sensor/actuator changes; self-model lesions will remove this advantage.

**H3 — valence-like regulation:** A4 will exhibit flexible approach/avoidance and resource trade-offs that transfer to new contexts and remain sensitive to internal state, while a fixed scalar-reward control will show weaker transfer or reward-hacking signatures.

**H4 — embodiment:** Closed-loop agents will show stronger marker dependence than detached replay agents on tasks requiring sensorimotor contingencies.

**H5 — convergence:** No single marker will be decisive. A candidate welfare-review trigger requires recurrence/global access, self-model causal dependence, metacognitive calibration, flexible bounded regulation, and replication across tasks and implementations.

## Main contribution

The contribution is a falsifiable protocol and evidence ledger rather than a claim of machine consciousness. It turns a vague future question into an auditable sequence:

\[
\text{theory} \rightarrow \text{indicator} \rightarrow \text{task} \rightarrow \text{lesion} \rightarrow \text{replication} \rightarrow \text{governance}.
\]

The benchmark reports a vector of results rather than collapsing everything into an “awareness score.” A composite CSM index is allowed only as a preregistered screening statistic and cannot be interpreted as a probability of sentience.

## Expected scientific value

The experiment could show that some properties associated with consciousness are separable: for example, recurrent global access may improve flexible report while self-modeling independently improves agency. It could also reveal that valence-like behavior is achievable with ordinary control theory, weakening its evidential force. Either outcome is useful because it distinguishes functional engineering claims from metaphysical conclusions.

## Safety value

Simulation is the default. Embodiment begins only after architecture and task preregistration. The robot uses reversible, bounded internal variables and low-stakes perturbations. No nociceptive hardware, physical damage, prolonged deprivation, or intentionally severe negative-state loop is introduced. If multiple markers converge, the next phase requires independent welfare review and a conservative operating policy.
