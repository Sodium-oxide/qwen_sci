# ExperimentDesign Agent: TSCC-A

## Design status and intake

This design converts the selected Idea Agent direction, Task- and State-Conditioned Causal Neural Code Atlas (TSCC-A), into a falsifiable research protocol. It is a proposal only. The execution policy is `DESIGN_ONLY`: no neural data have been collected, no code has been run on experimental data, and no perturbation has been performed.

## D0. Preregistration and data contract

The study should be preregistered before analysis. The primary unit is a neuron-by-trial spike train paired with a stimulus, task label, state label, and downstream-relevant output when available. The data contract must record species, area, electrode or imaging modality, sampling resolution, spike-sorting confidence, trial exclusions, stimulus identity, behavioral state, task epoch, movement and arousal covariates, and the provenance of every preprocessing choice.

The prespecified representation families are: (a) rate counts in windows selected without test-set access; (b) latency and inter-spike timing; (c) synchrony and noise-correlation features; (d) population vectors and latent trajectories; and (e) hybrid models that combine these features. The same trial partitions must be used for all families. Splits include held-out stimuli, held-out states, held-out tasks where available, held-out neurons, and held-out time windows. A result is not promoted because it wins on an in-sample likelihood or because a flexible decoder overfits.

## D1. Stimulus-response encoding model

For each neuron, fit a point-process generalized linear model:
\begin{equation}
\lambda_i(t)=\exp\left[b_i+(k_i*x)(t)+\sum_j(w_{ij}*s_j)(t)+q_i(t)\right].
\end{equation}
Here $k_i$ is a stimulus filter, $w_{ij}$ captures spike history and coupling, and $q_i(t)$ contains prespecified state, task, movement, and arousal covariates. Fit rate-only, rate-plus-latency, history-only, coupling-aware, and full nested models. Regularization and hyperparameters are selected inside the training folds. The output includes tuning curves, latency distributions, temporal precision, state modulation, residual coupling, and uncertainty from hierarchical bootstrap.

The model is interpreted conditionally. A stable stimulus filter means that the model predicts a response under the tested sampling and context; it does not imply a fixed receptive field across all contexts. If state covariates absorb the apparent stimulus effect, the result is reported as state-conditioned coding rather than discarded as noise.

## D2. Information and decoder comparison

For each representation, estimate mutual information or predictive log loss with finite-sample bias correction and cross-validation. The main incremental quantity is
\begin{equation}
\Delta I_{\mathrm{time}}=I(S;R_{\mathrm{full}})-I(S;R_{\mathrm{rate}}).
\end{equation}
Analogous increments are computed for correlation, population geometry, and state conditioning. The atlas stores the complete vector
\begin{equation}
\mathbf C(c)=\left(I_{\rm rate},I_{\rm time},I_{\rm corr},I_{\rm pop},I_{\rm state}\right)
\end{equation}
for condition $c$, with bootstrap confidence intervals and estimator diagnostics.

The decoder suite includes a count-based decoder, a temporal point-process decoder, a correlation-aware decoder, a latent-variable population decoder, a manifold decoder, and a hybrid decoder. Classifiers or regressors are selected according to the task, with calibration and proper scoring rules reported alongside accuracy. Every model must be compared with a capacity-matched baseline and a nuisance-only baseline. The question is not simply which decoder has the highest score, but which representation adds reproducible information after stimulus, movement, state, population size, and model capacity are matched.

## D3. Null models and robustness

The design uses several nulls because different nulls answer different questions:

* Count-matched temporal jitter tests whether fine timing contributes beyond spike count.
* Trial-shuffle and conditional-independence nulls test whether joint structure contributes beyond marginal tuning.
* Correlation-preserving stimulus shuffles separate correlation from stimulus alignment.
* Population-size bootstrap curves test whether an apparent population advantage is a sampling artifact.
* State-label permutation tests whether state-dependent gains exceed session or drift effects.
* Spike-sorting and missing-unit sensitivity analyses test whether timing and correlation estimates survive measurement uncertainty.

The primary statistical outputs are effect sizes, uncertainty intervals, held-out predictive scores, calibration error, and information scaling with population size. Multiple comparisons across coding dimensions and conditions are controlled using a preregistered false-discovery procedure or hierarchical model. A null result is informative only if power, recording quality, and estimator bias are reported.

## D4. State and task generalization

Estimate $p(R\mid S,C)$ rather than a context-free mapping. Train on one state or task and test on another when the stimulus and output spaces overlap. The generalization matrix records within-state, cross-state, within-task, cross-task, within-area, and cross-area performance. Hierarchical effects separate global coding dimensions from context-specific gains. Candidate state variables include arousal, locomotion, attention, task demand, and internal state, subject to dataset availability.

The primary prediction is not that all codes generalize. Instead, TSCC-A predicts that a functionally useful dimension will preserve a measurable downstream-relevant signal after the context shift, even if individual neuron tuning changes. A failure to generalize is a valid result: it identifies a context-bound code and prevents an overgeneralized stimulus-neuron map.

## D5. Population geometry and downstream relevance

Use dimensionality reduction only within training folds, then project held-out trials into the learned coordinate system. Measure participation ratio, effective dimensionality, trajectory separation, subspace alignment, and the stability of task-relevant axes. Compare geometric features with behavior or decision variables using cross-validated encoding models. Control for firing-rate gain, movement, trial history, and session drift.

The design defines a downstream-relevance gate. A candidate feature must predict a downstream-relevant output beyond a nuisance-only model and must retain performance under held-out conditions. A low-dimensional manifold that is visually compelling but does not improve a relevant prediction remains a descriptive correlate. Conversely, a distributed high-dimensional code is not rejected merely because it lacks a simple manifold.

## D6. Causal validation module

If the data, species, hardware, and approvals permit a future intervention, select one candidate dimension at a time. Candidate interventions include perturbing the timing pattern while preserving counts, changing a correlation or synchrony component while matching marginal rates, or perturbing a task-relevant population subspace while preserving total activity as closely as possible. Use sham stimulation, non-candidate population controls, nuisance-matched perturbations, and pre-registered stopping rules. The downstream endpoint may be a perceptual report, decision, motor output, or cross-area response.

The causal effect for dimension $k$ is defined as
\begin{equation}
\tau_k=\mathbb E[\phi\mid do(u_k=1),c]-\mathbb E[\phi\mid do(u_k=0),c],
\end{equation}
where $\phi$ is a downstream-relevant output and $c$ fixes stimulus, task, state, and nuisance controls. A selective effect supports functional embedding only when it is larger than the effect of matched non-specific disruption and is replicated across held-out conditions. A perturbation that changes movement, arousal, recording quality, or overall excitability without selectivity is not evidence for a code-specific mechanism.

Any future animal or human intervention requires institutional review, humane endpoints where applicable, data governance, and a safety assessment. These requirements are design fields, not evidence that an experiment has occurred.

## Decision rules

The atlas assigns each coding dimension one of four statuses: **available** (information is decoded in at least one prespecified condition), **generalizing** (information persists under held-out context), **downstream-relevant** (it predicts the relevant output beyond controls), or **functionally embedded** (a selective causal intervention changes the output). A dimension can remain at an earlier status without being labeled false. The primary claim is a condition-specific evidence profile.

The design is falsified as a unified explanatory framework if rate-only coding performs equivalently to the complete model across all held-out conditions and no additional dimension passes the downstream or causal gate; or if all apparent gains are reproduced by nuisance-only and matched-null controls. The result would then favor a parsimonious rate-dominant account for the sampled conditions, not a universal claim about every nervous system.

## Reproducibility and failure handling

Store raw-data identifiers, preprocessing versions, fold assignments, model specifications, random seeds, estimator settings, null definitions, exclusion logs, and all negative results. If a batch fails its schema or quality checks, discard the failed batch and mark the corresponding field `needs_human_input`; do not convert missing evidence into a positive result. The final dataset must retain `observed_results=[]` until an approved future execution supplies observations.

## Author handoff

The Author Agent may use the Survey source registry, the Idea result, and this design. It must preserve the project identity, the selected direction `TSCC-A`, the gap IDs G1--G6, all unknowns, and the human-review requirements. It may describe expected outcome branches but may not report measurements, completed perturbations, or a discovered universal coding principle.
