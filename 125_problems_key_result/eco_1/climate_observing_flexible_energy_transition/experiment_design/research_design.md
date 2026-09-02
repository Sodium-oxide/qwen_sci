# ExperimentDesign Agent: CO-FET research design

## Study question and mode

The design tests whether a coordinated data-to-decision framework can identify robust mitigation portfolios under climate, socioeconomic, technology, and governance uncertainty. It is a prospective computational experiment in `DESIGN_ONLY` mode. No measured emissions reduction, reliability result, or policy outcome is reported.

## Scenario ensemble

The study uses connected regions with energy nodes, climate-risk zones, and exposed populations. Planning decisions are staged over milestone periods and operational dispatch is resolved at finer time steps. Scenarios vary climate trajectories, demand and vulnerability, renewable availability, technology costs, outages, storage degradation, transmission build rates, observation missingness, calibration error, and reporting delay. Development, stress-test, and held-out scenario sets are separated before optimization.

## Model components

Net emissions are represented by

\[
G_t=\sum_{r,k}g_kE_{r,t,k}-R_t,
\]

with gross emissions, cumulative emissions, and removal dependence reported separately. Climate risk is indexed by hazard, exposure, vulnerability, and effective adaptation. The power-system model enforces nodal balance, storage state of charge, transmission limits, ramping, reserve, curtailment, and bounded demand response. These equations are already formalized and numbered in the Author report.

## Robust policy optimization

Each portfolio is evaluated with cumulative emissions, residual multi-sector risk, unserved energy, affordability burden, access-group burden, and implementation cost. The central comparison uses Pareto analysis and minimax regret over the scenario set. Reliability and burden limits are pre-declared. Weights are documented and varied; no hidden global score is used.

The controls are carbon-only optimization, technology-only cost minimization, observation-first investment, delayed action, a perfect-forecast upper bound, and naive renewable capacity substitution. The primary treatment is CO-FET with the same physical constraints and scenario information.

## Value of information and triggers

Observation investments are scored by expected and worst-case regret reduction after accounting for their cost. A measurement is decision-relevant only if it changes a mitigation, grid, or risk-management action or reduces uncertainty at a decision boundary. Staged triggers record indicator, baseline, uncertainty interval, threshold, lead time, owner, and rollback option. Hysteresis prevents noisy repeated switching.

## Ablations

- remove observation upgrades;
- remove grid flexibility;
- remove risk and equity constraints;
- remove adaptive triggers.

The contribution of each layer is estimated from changes in regret, risk, reliability, affordability, and distributional burden. Model-structure ensembles test whether a result is tied to one simulator.

## Analysis and interpretation

The analysis freezes definitions, provenance, accounting boundaries, thresholds, weights, and reliability limits before fitting or optimizing. It then calibrates baselines, optimizes all policies, evaluates held-out and extreme scenarios, runs ablations, conducts sensitivity and model-discrepancy analyses, and reports Pareto fronts, scenario envelopes, trigger behavior, and falsification outcomes.

Support for CO-FET requires lower held-out worst-case regret and acceptable risk, reliability, affordability, and equity outcomes. The observation layer is dropped if its upgrades never change decisions or regret. The flexibility layer is dropped if capacity-only portfolios satisfy all constraints in all declared scenarios. The trigger layer is dropped if it increases switching, delay, or regret. A null result remains scientifically informative because it identifies the failed link in the chain.

## Reproducibility and safeguards

The executable study should publish the scenario manifest, schemas, emissions factors, risk functions, grid model, policy baselines, random seeds, ablation scripts, synthetic scenarios, and model-version events. It must report leakage, removal permanence, land, water, mineral, biodiversity, local consultation, and energy-access assumptions. Model output is decision support, not a legal mandate; actual deployment requires accountable institutions and local review.

