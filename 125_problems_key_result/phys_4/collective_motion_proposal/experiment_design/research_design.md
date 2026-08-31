# ExperimentDesign Agent: MOSAIC Cross-Scale Benchmark

## Design status and objective

**Execution policy: DESIGN_ONLY.** No animal tracking, bacterial culture, drone flight, simulation run, or result is performed or reported here. The design tests whether a conditional, shared latent-state description of collective motion generalizes more credibly than either a single universal rule or entirely disconnected domain models.

## Study type

A preregistered, retrospective multi-domain benchmark using legally usable public trajectory or velocity-field data, followed by optional future controlled digital-twin validation. The initial domains are: (A) three-dimensional bird or fish tracks; (B) two-dimensional fish-school tracks; (C) bacterial/microswimmer velocity fields; and (D) robot-swarm logs or validated simulator trajectories. Domains may be replaced only if their preprocessing, consent/licensing, and observability records are stored.

## Research brief

| Element | Operational form |
|---|---|
| Central hypothesis | A shared conditional latent-state model with explicit delay and geometry moderators matches or exceeds domain-specific forecast and regime-prediction performance within a preregistered margin. |
| Null | No harmonized latent description transfers; domain-specific models win decisively or shared variables are not invariant. |
| Unit | A time window of trajectories or a velocity field with matched contextual metadata. |
| Primary outcomes | Angular forecast log score, velocity-field error where applicable, regime classification calibration, and out-of-domain predictive gap. |
| Secondary outcomes | Polarization, connected correlation, correlation length, turning/propagation lag, density heterogeneity, vorticity or defect statistics. |

## Variables and measurement model

The design never equates a proxy with a mechanism. It stores the measurement model used to infer each proxy.

- **Activity/persistence (A):** speed distribution, directional persistence, and run-time or autocorrelation proxies.
- **Coupling (K):** fitted sensitivity of heading/velocity update to candidate neighbor summaries, accompanied by uncertainty and alternative kernels (metric, fixed-count, visual/occlusion, field-mediated).
- **Noise (N):** residual directional or velocity variation conditional on model state; measurement noise is separately estimated from track quality.
- **Delay (D):** lag between a local directional perturbation proxy and best-supported response in neighboring agents or field cells.
- **Geometry/context (G):** boundary distance, obstacle configuration, density, flow/environment proxies, and acquisition modality.

Dimensionless summaries are reported only as data-specific normalization choices, for example an alignment-to-noise ratio, a delay-to-turning-time ratio, and a confinement-to-interaction-range ratio. The exact normalization is preregistered per data modality and cannot be retrospectively tuned to produce collapse.

## Candidate models

1. **M0, domain-specific baseline:** independently fitted state-space or interaction-kernel models for each domain.
2. **M1, polarization-only baseline:** predicts from global order and density, testing whether richer observables matter.
3. **M2, MOSAIC conditional model:** hierarchical latent states shared across domains, domain-specific observation maps, and moderators A, K, N, D, G.
4. **M3, ablation models:** M2 without delay; without geometry; without coupling uncertainty; and without multi-observable state vector.

## Data split, inference, and release gates

Windows are blocked by time and whole-group episode, not randomly shuffled individual points. One domain is held out in turn for transfer testing. If an intervention or perturbation label exists, all instances of a label are held out together for the causal-stress test. Hyperparameters may be selected only within the development domains. The final held-out windows are opened once.

The primary endpoint is the difference in predictive score between M2 and M0. The study pre-registers a practical non-inferiority margin appropriate to each output scale and reports confidence intervals or posterior intervals, calibration, and failure decomposition. M2 receives a **conditional-transfer supported** label only if it satisfies all of the following: (i) prediction is not practically worse than M0 on a held-out domain; (ii) performance improves over M1; (iii) no ablation shows that the claimed shared variable is dispensable; (iv) track-quality and geometry sensitivity analyses do not reverse the result. Otherwise it receives **conditional-transfer not supported**.

## Controls and robustness

- Match observation windows by sampling rate, group size range, and track completeness where possible.
- Repeat analyses with metric, topological, and visually constrained neighbor candidates.
- Shuffle temporal order, group membership, and velocity headings as negative controls, preserving the appropriate marginal distributions.
- Use synthetic truth-known sequences only to validate recovery of known kernels and noise; do not use them as evidence for biology.
- Quantify sensitivity to tracking uncertainty, smoothing, finite field of view, missing individuals, and derivative estimation.
- Report each domain separately before any pooled conclusion.

## Ethics, safety, and human review

The first phase uses public, consented, licensed, or synthetic data only. Any new animal observation requires protocol, welfare, permitting, privacy/location-risk, and local ethics review. Any bacterial or microswimmer acquisition requires appropriate laboratory supervision and biological-safety procedures. Any drone validation remains a future human-supervised engineering activity with airspace, safety, and hardware review. These requirements are not satisfiable by this document or by the agent.

## Decision branches

| Observation after future execution | Supported conclusion | Prohibited conclusion |
|---|---|---|
| M2 transfers with delay and geometry retained | A conditional state description is promising for these measured domains. | One universal microscopic interaction law has been established. |
| M2 predicts within domains but not held-out domains | Mechanism semantics or observation maps are domain-limited. | Cross-scale universality is established. |
| M1 performs comparably to M2 | The extra variables did not add demonstrated predictive value. | Correlation alone proves causal coupling. |
| Negative controls perform similarly | The pipeline has insufficient discriminative validity. | A fitted interaction kernel is biological mechanism. |

