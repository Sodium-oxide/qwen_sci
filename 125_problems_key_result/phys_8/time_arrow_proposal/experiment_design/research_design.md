# ExperimentDesign Agent: RAAT Research Design

## Design status and safety boundary

This is a computational research design. It specifies no physical experiment, no access to restricted instrument data, and no inferred real-world result. Every generated trajectory is planned synthetic benchmark data. The cosmology component is a conceptual boundary-condition ledger and may not be presented as an observation of the early universe.

## Research brief

**Primary question:** under what conditions can finite trajectory data support attribution of a time arrow to nonequilibrium entropy production rather than to an observation map, a preparation asymmetry, or model misspecification?

**Primary claim under test:** an attributed dissipative arrow must be resolution-stable within a declared range, consistent with the applicable path-probability or fluctuation relation, and robust against protocol and nuisance controls.

## Generator families

| Family | Planned role | Known latent truth | Required control |
|---|---|---|---|
| E0: stationary detailed-balance Markov process | Negative control | Zero steady-state entropy production | Time-reversal-symmetric sampling and observation map |
| E1: driven ring or chemical-reaction network | Positive control | Nonzero affinity and entropy-production ledger | Protocol reversal and rate perturbations |
| E2: partially observed driven network | Resolution test | Same underlying generator as E1 with hidden states | Multiple observation maps and state aggregation |
| E3: open quantum dephasing model | Quantum bridge | Declared system-environment split and channel parameters | Basis, measurement, and bath sensitivity |
| E4: cosmological coarse-graining toy comparator | Boundary-condition context | Explicit low-gravitational-entropy proxy only | No claim of cosmological measurement |

## Variables and formal estimands

For an observed trajectory $x_{0:T}$ and its reversal $\tilde{x}_{0:T}$, RAAT will estimate the forward/reverse log-likelihood asymmetry

$$
A_{\Delta}=\frac{1}{N}\sum_{n=1}^{N}\log\frac{p_{\theta}(x^{(n)}_{0:T}\mid\Delta,\mathcal{O})}{p_{\theta}(\tilde{x}^{(n)}_{0:T}\mid\Delta,\mathcal{O})},
$$

where $\Delta$ is sampling resolution, $\mathcal{O}$ is the observation map, and $\theta$ is the declared generator parameterization. For a continuous-time Markov model, the planned reference entropy-production rate is

$$
\dot{S}_{\mathrm{tot}}=\sum_{i,j}p_i k_{ij}\log\frac{p_i k_{ij}}{p_j k_{ji}}\geq0.
$$

The design will evaluate agreement between $A_{\Delta}$ and the corresponding entropy ledger only where the model's assumptions hold. It will not define an entropy estimate in a partially observed process as automatically equal to physical dissipation.

## Analysis plan

1. Version each generator, initial distribution, driving protocol, observation map, reversal map, and random seed policy.
2. Produce planned synthetic trajectory ensembles at several $\Delta$ values and state-aggregation levels.
3. Fit predeclared candidate models; compute likelihood asymmetry, fluctuation-relation residuals, record-persistence summaries, and out-of-sample predictive scores.
4. Inject controlled misspecification: hidden states, protocol-time offsets, temperature mismatch, and asymmetric measurement noise.
5. Use paired bootstrap intervals over trajectories and predeclared decision rules, not post-hoc visual selection.
6. Classify each condition as `DISSIPATIVE_SUPPORT`, `DESCRIPTIVE_ASYMMETRY_ONLY`, `NON_IDENTIFIABLE`, or `MODEL_INVALID`.

## Decision rules

`DISSIPATIVE_SUPPORT` requires all of the following: a stable sign and magnitude across valid resolutions; agreement with the generator's entropy ledger within predeclared tolerance; no reversal under symmetric protocol controls; and better held-out support than the closest artifact model. `DESCRIPTIVE_ASYMMETRY_ONLY` applies when records or coarse variables are predictive but the physical attribution cannot be supported. `NON_IDENTIFIABLE` applies when candidate mechanisms yield indistinguishable observables. `MODEL_INVALID` applies when the required reversal operation, bath model, or observation symmetry cannot be justified.

## Human-review requirements

An expert in stochastic thermodynamics must verify local detailed balance, the reversal convention, and entropy accounting. A quantum-open-systems reviewer must verify the E3 system-environment partition. A cosmology reviewer must verify that the E4 proxy is never interpreted as measured gravitational entropy or as a derivation of the past hypothesis.

