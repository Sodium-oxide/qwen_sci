# ExperimentDesign Agent: FateLedger Study Design

## Design status

**Execution policy: DESIGN_ONLY.** This artifact specifies an analysis protocol and no analysis, simulation, parameter fit, observation, laboratory intervention, telescope operation, or data release has been executed for this proposal. The observed-results field is intentionally empty. All numerical thresholds below are pre-registration targets to be calibrated before use, not reported outcomes.

## Research brief

**Selected idea:** FateLedger: A Multi-Scale Cosmic-Fate Falsifiability Atlas.  
**Research object:** the relation between finite-redshift cosmological evidence, declared late-time continuation assumptions, and distinct expansion or vacuum-decay fate classes.  
**Primary claim:** a model's evidence status must include its asymptotic assumptions and observational identifiability; no report may turn a local fit into a terminal-time assertion without both.

The design treats the following outcomes separately:

1. background expansion classification;
2. a conditional fate event and time integral;
3. observational identifiability;
4. vacuum-stability status.

The primary background labels are ASYMPTOTIC_DILUTION_COMPATIBLE, FINITE_TIME_DISRUPTION_CONDITIONAL, TURNAROUND_CONDITIONAL, TURNAROUND_NOT_SUPPORTED_IN_DECLARED_MODEL, and FUTURE_BEHAVIOR_OBSERVATIONALLY_UNIDENTIFIABLE. The vacuum ledger uses VACUUM_STABILITY_UNRESOLVED, VACUUM_DECAY_MODEL_CONDITIONAL, or NO_VACUUM_MODEL_ASSESSED. A label is a bounded inference result, not a prediction that an event has occurred.

## Scope, safety, and human review

This is routed to the mathematics-theory plus computational-digital templates. It is non-clinical and non-interventional. It may use only public, documented cosmological likelihoods, summary measurements, covariance matrices, and synthetically generated benchmark data after a data-governance check. Human review is mandatory for:

* selection of public releases and licensing;
* interpretation of systematics and compatibility of likelihood implementations;
* mapping a phenomenological parameterization to a physical late-time continuation;
* any claim about particle-physics vacuum lifetime;
* all release-ready scientific conclusions.

No automated pipeline is authorized to label the universe's actual fate as resolved.

## Formal analysis objects

For each background model \(M_j\), register an assumption card

\[
A_j = \{D_j, C_j, \Theta_j, F_j, V_j\},
\]

where \(D_j\) is the observational validity domain, \(C_j\) is the asymptotic continuation class, \(\Theta_j\) are model parameters and priors, \(F_j\) is the named fate-event definition, and \(V_j\) lists known validity limitations. The card must be machine-readable and visible in every final figure or table. A local \(w_0,w_a\) interpolation that has no physical continuation is assigned continuation-not-declared; the workflow then forbids a time-to-event output.

For a declared continuation, the planned time-to-event computation is

\[
t_{\mathrm{event}}-t_0 =
H_0^{-1}\int_{1}^{a_{\mathrm{event}}}\frac{da}{aE(a)}.
\]

Here \(a_{\mathrm{event}}=\infty\) for a possible asymptotic or Big-Rip limit, and it is the first positive root of \(E(a)\) for a turnaround candidate. The integral will be marked undefined, divergent, or conditional whenever its assumptions fail. This prevents a numerical integrator from producing a deceptively precise date in an invalid model.

The proposed observational distinguishability statistic for two models is a posterior-predictive divergence:

\[
\Delta_{jk} = \sum_{q\in Q} \left[
\mathbf{m}_{jq}-\mathbf{m}_{kq}\right]^\mathsf{T}
\mathbf{C}_{q}^{-1}
\left[\mathbf{m}_{jq}-\mathbf{m}_{kq}\right],
\]

where \(Q\) is the predeclared set of probes, \(\mathbf{m}_{jq}\) is the predicted observable vector, and \(\mathbf{C}_{q}\) contains measurement and systematic uncertainty for probe \(q\). A human-approved threshold and calibration against mock catalogs must be fixed before model labels are evaluated. The point of the statistic is comparative predictive separation, not a proof that any model is true.

## Variables and claim map

| Type | Variable or construct | Operationalization | Role |
|---|---|---|---|
| Independent | Model family \(M_j\) | Flat LambdaCDM, constant-w, physically defined scalar-field continuations, selected modified-gravity models with documented equations | Determines \(E(a)\) and fate mapping |
| Independent | Asymptotic continuation card \(C_j\) | Constant, field-potential, stable de Sitter-like, sustained phantom, negative-potential, or not declared | Prevents invalid extrapolation |
| Dependent | Background fate status | Mutually controlled label emitted by FateLedger | Primary output |
| Dependent | Identifiability status | Calibrated separation or unresolved label | Primary output |
| Dependent | Conditional event time | Integral plus uncertainty only when card and model define it | Secondary output |
| Control | Data release and likelihood version | Frozen Planck, DESI, SN, growth data identifiers and covariance | Reproducibility |
| Control | Priors and nuisance model | Versioned prior table and systematic choices | Sensitivity control |
| Separate dependent | Vacuum status | Particle-physics assumption panel, not a background likelihood result | G2/G5 safeguard |

## Planned evidence bundle

The protocol will begin from the source roles frozen by Survey: Planck CMB constraints (P1); DESI BAO expansion constraints (P2); equation-of-state and probe reviews (P3-P4); conditional Big-Rip and recollapse model studies (P5-P6); vacuum-metastability theory (P7-P8); and long-term observability context (P9). A later execution must record the exact public data version, column definitions, likelihood code, covariance, calibration, and license. Abstract-only metadata are insufficient to select numerical inputs.

The core empirical bundle will contain, subject to human eligibility review:

* CMB primary anisotropy and lensing constraints;
* BAO transverse and radial distance measurements;
* independent supernova distance-modulus compilations;
* growth or weak-lensing summaries when their systematics model is compatible;
* prospective redshift-drift and gravitational-wave standard-siren mock releases only as labelled forecast data.

## Procedure

### Phase 0: Source and model registration

Freeze source versions, public data identifiers, likelihood licenses, priors, nuisance assumptions, and the fate taxonomy. Each model must state whether it is a local phenomenological fit or a globally defined theory. Register which fate labels it can logically emit. An unregistered continuation cannot be inferred later from an appealing posterior plot.

### Phase 1: Observation-domain inference

Fit or sample each eligible model only over the domain stated by its data. Evaluate goodness of fit, posterior predictive residuals, convergence diagnostics, prior sensitivity, and leave-one-probe-out stability. Do not compute a future time in this phase. Report parameter constraints separately from fate classification.

### Phase 2: Controlled continuation mapping

For models with a defined asymptotic law, propagate posterior samples through \(E(a)\), the event definition, and the time integral. For local parameterizations, create at least two physically distinct admissible continuations that agree over the observed domain when possible. If they lead to different fate classes without observable separation, emit FUTURE_BEHAVIOR_OBSERVATIONALLY_UNIDENTIFIABLE.

### Phase 3: Cross-probe discriminator tests

Pre-register comparisons that add BAO, supernovae, growth, redshift drift, or standard sirens one at a time. For each addition, measure change in \(\Delta_{jk}\), posterior-predictive calibration, and sensitivity to systematic shifts. The test is successful only when the added probe changes a predeclared ambiguity for a documented physical reason and remains stable under reasonable nuisance variation.

### Phase 4: Vacuum ledger

Keep this phase separate from the expansion fit. Compile the electroweak-vacuum assumptions, including masses, couplings, renormalization scheme, gravitational treatment, and beyond-Standard-Model alternatives. It may report a model-conditional decay-rate range supplied by reviewed theory; it may not convert that range into a background-expansion conclusion. If assumptions are incomplete, return VACUUM_STABILITY_UNRESOLVED.

## Comparators, ablations, and robustness

The proposed comparators are: (C1) a conventional parameter-constraint report with no assumption card; (C2) a single-probe fate annotation; (C3) a combined-probe fate ledger without the vacuum split; and (C4) FateLedger with all controls. Key ablations remove the asymptotic card, remove the unidentifiable label, remove one probe at a time, replace physical continuations with a local \(w_0,w_a\) extrapolation, and merge the vacuum ledger. Predeclared diagnostics include:

* rate of unsupported end-time statements in blinded report review;
* posterior-predictive coverage and calibration on withheld observable blocks;
* stability of fate labels under prior and nuisance perturbations;
* pairwise fate-class separation using \(\Delta_{jk}\);
* provenance completeness: every fate label must link to its assumptions and source keys;
* contradiction rate between expansion and vacuum statements.

Potential failure modes include data-set inconsistency, hidden common systematics, parameterization dependence, prior domination, an unjustified mapping from effective equation of state to fundamental theory, and extrapolation instability. A failure is informative: it narrows the claim to "not identifiable with the declared evidence" rather than authorizing an ad hoc model change.

## Decision rules and conditional conclusions

| Condition | Planned output |
|---|---|
| A globally defined, data-compatible continuation reaches \(a\rightarrow\infty\) only at infinite proper time and stays accelerating | ASYMPTOTIC_DILUTION_COMPATIBLE, conditional on that model |
| A globally defined, data-compatible continuation reaches a singularity at finite integral time | FINITE_TIME_DISRUPTION_CONDITIONAL, with all assumptions exposed |
| A continuation reaches a positive root of \(E(a)\) | TURNAROUND_CONDITIONAL, with a separate collapse calculation only if model-valid |
| A local fit has divergent, undefined, or nonphysical extrapolation | FUTURE_BEHAVIOR_OBSERVATIONALLY_UNIDENTIFIABLE |
| Particle-physics inputs or model extensions do not support a stable vacuum conclusion | VACUUM_STABILITY_UNRESOLVED |

## Reproducibility and deliverables

An eventual execution should release versioned assumption cards, data manifests, likelihood wrappers, prior table, posterior-predictive scripts, synthetic benchmark generator, result ledger, and a human-readable limitation register. The present deliverable is only this design and an Author handoff. No observed results exist.
