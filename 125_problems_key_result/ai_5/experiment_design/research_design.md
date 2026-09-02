# ExperimentDesign: CLOSED-LOOP-HUMAN-MACHINE-INTEGRATION-BENCHMARK

## 1. Design status and objective

This is a preregisterable research protocol, not a report of completed human or animal work. It follows a staged safety architecture: simulation, hardware-in-the-loop, and only then an ethics-reviewed human validation study. The objective is to test whether measurable bidirectional coupling creates durable, safe functional gains beyond ordinary assistance or one-way command decoding.

The initial study does not implant devices, edit genomes, stimulate nociceptive pathways, or make claims about consciousness or species status. An implanted-compatible condition is implemented as a signal and latency emulator. Any future clinical translation requires independent institutional review, medical-device approval, informed consent, adverse-event monitoring, and a stopping plan.

## 2. System model

Let the human state be `x_h(t)`, the machine state be `x_m(t)`, the observed physiological signal be `y_h(t)`, the machine action be `u_m(t)`, and the returned feedback be `z_m(t)`. The emulator generates:

`y_h(t) = g(x_h(t)) + eta_h(t)`

`u_m(t) = pi_theta(y_h(t), x_m(t))`

`x_h(t+1) = f_h(x_h(t), u_m(t), z_m(t), w_h(t))`

where `g` is a signal model, `pi_theta` is the decoder or controller, `f_h` is the user adaptation model, and `w_h` is task and physiological disturbance. Noise, missing channels, delay, calibration drift, and adversarial perturbations are varied within safe, preregistered ranges.

The benchmark treats integration as a vector of observables rather than one scalar. A system is functionally integrated for a task only if it improves held-out performance and recovery while retaining agency, safe disengagement, and acceptable privacy-security risk.

## 3. Staged architecture

### Stage A: simulation-first

Use synthetic physiological signals and openly licensed prerecorded signal traces where permitted. Simulate wearable inertial signals, electromyography-like channels, electroencephalography-like channels, and an intracortical-compatible population code without representing a real person. Generate task intentions, fatigue, signal drift, feedback delay, and missingness from a fixed seed. Evaluate all controller variants over repeated seeds and held-out users generated from different parameter distributions.

### Stage B: hardware-in-the-loop

Connect the software stack to a non-human test fixture or robotic simulator with a physical emergency stop. The fixture may include an exoskeleton actuator surrogate, a robotic arm surrogate, and a tactile feedback transducer, but no human contact is required. Inject bounded latency, sensor dropout, model drift, and spoofed sensor packets. The safety supervisor must remain outside the adaptive controller and must be able to remove actuator commands.

### Stage C: ethics-reviewed human validation

Only after Stage A and B meet safety thresholds may a separate protocol recruit adults for low-risk wearable or non-invasive tasks. The first human study should use surface electromyography, inertial sensing, eye tracking, or electroencephalography and a low-force virtual or tabletop task. No implant or invasive stimulation is part of this protocol. Participants must be able to stop at any time, and all data collection and model updates require explicit consent. Clinical populations would require a separate medical protocol.

## 4. Experimental factors and conditions

The core factorial design uses the following factors:

1. **Interface:** wearable physical assistance; non-invasive physiological control; implanted-compatible simulated signal; bidirectional simulated feedback.
2. **Feedback:** none; visual or task feedback with a controlled delay; low-risk bidirectional sensory cue in simulation or approved non-invasive human validation.
3. **Adaptation:** frozen decoder; user-only adaptation; machine-only adaptation; joint adaptation.
4. **Governance:** ordinary controller; transparent state display and rationale; explicit user veto; local processing plus independent emergency stop.
5. **Stressors:** baseline; signal drift; channel dropout; delayed feedback; task perturbation; spoofed input in the security test.

The primary comparison is bidirectional versus unidirectional feedback under the same signal quality, task demands, controller capacity, and training budget. The secondary comparison is joint adaptation versus user-only and machine-only adaptation. Conditions are counterbalanced where learning and fatigue permit; simulated and hardware-in-the-loop conditions use matched random seeds.

## 5. Tasks

The task suite is designed to distinguish assistance from coupling:

- **Intention decoding:** classify or continuously estimate target selection from physiological signals.
- **Reach and grasp:** control a virtual or fixture-mounted robotic arm to acquire, transport, and release objects with variable mass and position.
- **Gait assistance surrogate:** track gait phase and apply bounded assistance in a simulator; measure stability and energy proxy rather than claiming a human metabolic result.
- **Sensory prediction:** predict device state from returned cues and quantify whether feedback reduces state-estimation error.
- **Agency and veto:** introduce rare, announced and unannounced controller deviations; test whether the user detects, vetoes, and safely recovers from them.
- **Machine-off transfer:** remove assistance and measure retained task strategy, error, and recovery.
- **Perturbation recovery:** apply bounded target shifts, latency changes, dropout, and workload changes after training.
- **Security test:** replay, spoof, or corrupt signals in the fixture and simulator only; record whether the independent safety supervisor blocks unsafe commands.

## 6. Metrics and estimands

Primary estimands are within-condition differences and interaction effects with 95% confidence intervals or Bayesian credible intervals, reported with participant or generated-user random effects when applicable.

**Utility:** task success, normalized control error, path efficiency, command latency, throughput, and energy or effort proxy.

**Coupling:** mutual information between intended state and machine action; prediction error for device state; improvement after perturbation; adaptation rate; and performance under held-out delay and drift.

**Agency:** correct attribution of self-generated versus controller-generated action, veto success, veto latency, false veto rate, and confidence calibration. A high acceptance rate is not treated as agency evidence.

**Safety:** unsafe-command rate, maximum bounded force or velocity, supervisor intervention rate, emergency-stop latency, recovery time, and safe-disengagement completion. Any violation of a hard safety threshold is analyzed as an adverse event in the protocol, not averaged away.

**Independence:** machine-off task success, retention after a washout interval, aftereffects, and whether performance returns to baseline without rebound errors.

**Robustness:** decoder drift, calibration burden, missing-channel tolerance, delay tolerance, subgroup or generated-user variability, and worst-case rather than only mean performance.

**Privacy and security:** inference accuracy for non-target attributes, mutual information between retained data and sensitive attributes, unauthorized-access rate in a sandbox, spoofing success, time to detect tampering, and false-safe versus false-unsafe decisions.

## 7. Statistical analysis plan

For the simulation and fixture stages, use at least 30 independent seeds per cell and report the full seed list. A mixed-effects model or hierarchical Bayesian model estimates fixed effects for feedback, adaptation, governance, and stressors with random intercepts for generated user, task, and seed. The primary contrast is the feedback effect under matched conditions; multiplicity is controlled by a preregistered hierarchy of primary and secondary outcomes.

For a later human feasibility stage, the sample size must be derived from the variance and effect size observed in Stage B, with a safety-first stopping rule. The human study is not justified by statistical power alone: it also requires acceptable emergency-stop latency, zero uncontrolled actuation in validation trials, and successful data-deletion and consent-revocation tests.

Report mean and worst-decile performance, calibration curves, missing-data patterns, confidence intervals, and individual trajectories. Do not pool wearable, non-invasive, implanted-compatible, and cognitive-augmentation results into one headline number. The results should be presented as a Pareto frontier of utility, agency, independence, privacy, security, and safety.

## 8. Safety, ethics, and governance

The safety supervisor is a deterministic layer with hard bounds on action, speed, force, workspace, and timeout. The adaptive controller cannot modify these bounds. The stop channel is independent of the controller and is tested before every run. All human-facing work uses reversible operation, non-nociceptive cues, low-risk tasks, immediate withdrawal, and no deception about controller behavior beyond separately consented agency probes.

Neural and physiological data are minimized, encrypted in transit and at rest, processed locally when feasible, separated from identity, and deleted on request. Model updates are versioned and disclosed. Access is role-based; raw signals are not used for secondary inference without new consent. Security testing is isolated from clinical systems and never targets a production device.

The protocol distinguishes four claims: a device can assist; a signal can control; a closed loop can co-adapt; and a person-machine system can be said to constitute a new species. Only the first three are potentially testable here, and the fourth is explicitly outside the study's evidence. Genomic or heritable modification is excluded because it has different causal, medical, and governance risks.

## 9. Reproducibility and decision rules

Release controller code, synthetic-data generators, fixed seeds, condition manifests, metric definitions, safety logs, and analysis scripts. Pre-register exclusions and report all failed and stopped runs. A positive result requires: (i) a preregistered improvement in held-out task utility; (ii) no unacceptable agency or safety loss; (iii) successful independent disengagement; (iv) robustness to at least one unseen drift or delay condition; and (v) no material increase in non-target privacy inference under the chosen governance condition.

A negative or mixed result is scientifically valuable. If feedback helps only in calibration, the claim is “training aid,” not integration. If joint adaptation raises acute throughput but degrades machine-off transfer or veto success, the claim is “performance-dependent coupling with governance risk.” If the safest configuration is wearable and reversible, that is a result about engineering tradeoffs, not a failure to build a species.

## 10. Author handoff

The Author may report the survey evidence, the benchmark idea, the staged design, formal observables, risks, and decision rules. The Author must label the work as `DESIGN_ONLY`, must not invent participant counts or results, and must preserve the boundary between functional coupling and biological species. The final paper should include a limitations section that identifies untested implanted, cognitive, genomic, and long-term clinical claims.
