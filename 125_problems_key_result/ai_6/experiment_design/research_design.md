# ExperimentDesign: GROUP-INTELLIGENCE-EMERGENCE-BENCHMARK

## 1. Design status and objective

This document is a preregistrable protocol proposal, not a report of completed human or machine experiments. It tests how collective performance emerges from agent capability, functional diversity, independent information, communication, aggregation, coordination, and feedback. The benchmark is designed for three populations: synthetic agents, fixed algorithmic agents, and a future ethics-reviewed human-AI feasibility study. No empirical participant count, performance result, or causal effect is asserted here.

The central estimand is group advantage under matched resources. A group is not called intelligent merely because it has more members, more time, more tokens, or more compute. It must outperform the best isolated member and a size-matched aggregation baseline on held-out instances, while the mechanism log shows how complementary information entered the decision.

## 2. Agent and task model

For task $j$, agent $i$ receives an observation $o_{ij}$ and produces an answer $a_{ij}$, confidence $q_{ij}$, explanation or evidence trace $e_{ij}$, and optional abstention $r_{ij}$. A communication protocol maps messages into a group state $m_{j,t}$. The group policy produces a final answer $a_{G,j}$ and confidence $q_{G,j}$.

The benchmark defines the group advantage

`A_j = P(a_G,j is correct) - max_i P(a_i,j is correct)`

using the same task, information, time, and compute budget. For continuous estimation, performance is negative absolute or squared error, with the sign chosen so larger is better. A second baseline uses the best permitted aggregation of independent first answers. A third baseline gives every condition the same external reference information without discussion, isolating information access from social coordination.

## 3. Staged implementation

### Stage A: simulation-first

Construct synthetic agent populations with controllable ability, representation, heuristic, sensor, error correlation, confidence calibration, and communication behavior. Include human-inspired bounded-rational agents, diverse search agents, retrieval or calculation agents, and language-model-like agents only as fixed versions. Do not use hidden online changes in the primary comparison. Generate at least 30 independent seeds per condition and hold out both task instances and agent parameter combinations.

The simulator should expose ground truth for every decision. For search tasks it records visited solution regions and overlap. For distributed sensing it records which observations each agent possessed. For planning it records subgoals, conflicts, and recovery. For estimation it records individual error and confidence. The simulator can therefore test whether a group succeeds by combining complementary information or by inheriting an accidental shortcut.

### Stage B: controlled human-AI interface

After simulation passes the reproducibility and manipulation checks, implement the protocol in a sandbox interface. The interface can show independent first answers, structured discussion, machine confidence, machine abstention, role assignments, and a final synthesis panel. The AI is restricted to the task information and model version assigned to its condition. Its outputs are logged but not silently used to alter the human control condition.

If human participants are later recruited, the study must use informed consent, low-stakes tasks, withdrawal at any time, de-identified logs, and institutional review. The initial study must not evaluate employment, medical, legal, educational admission, or other high-consequence decisions. The design is not a deployment authorization and must not infer general intelligence from participant identity or demographic category.

### Stage C: longitudinal transfer

Only after a cross-sectional study shows a reproducible mechanism should a longitudinal design test learning. It varies task family, communication topology, and role allocation over time. It includes blind-first blocks, machine-off blocks, and protocol-switch blocks. The goal is to determine whether the group develops a reusable coordination policy or merely memorizes a task format. Model updates are versioned, disclosed, and frozen during confirmatory evaluation windows.

## 4. Experimental factors

The core factorial design contains:

1. **Composition:** human-only, AI-only, and hybrid groups; matched group size.
2. **Individual ability:** low, medium, and high calibrated ability distributions.
3. **Functional diversity:** homogeneous representations; complementary heuristics; complementary sensors; diverse model families; or deliberately correlated models.
4. **Independence:** blind-first answers, private confidence, independent retrieval, sequential exposure, or unrestricted exposure.
5. **Communication topology:** no discussion, pairwise network, broadcast, round-robin, and centralized facilitator.
6. **Aggregation:** mean or median, majority, confidence-weighted, independent best-of, deliberative synthesis, and abstention-aware aggregation.
7. **Coordination:** fixed roles, random roles, expertise-based roles, and learned task allocation.
8. **AI governance:** opaque recommendation, confidence and evidence display, calibrated abstention, human veto, and machine as one peer rather than final authority.

The primary interaction is functional diversity by communication protocol. The primary hybrid comparison is calibrated peer AI versus authority AI under matched model access. A secondary interaction tests whether independent first answers protect diversity when the machine is highly confident.

## 5. Task battery

The benchmark includes at least four task families:

- **Estimation:** numerical quantities with known ground truth, varied noise, and a controlled relationship between individual error and confidence.
- **Classification:** visual, textual, or tabular cases in which agents have complementary sensors or features; test calibration and abstention.
- **Search and planning:** constrained route, scheduling, or combinatorial problems with partial solution views and measurable search coverage.
- **Distributed sensing:** each agent sees a different noisy observation of an evolving state; the group must estimate state and forecast change.

Each family has training, familiar evaluation, and held-out evaluation subsets. A fifth optional family evaluates creative synthesis with an external rubric, but it is not used as the sole evidence for emergence because its ground truth is less direct. Task order, time limit, communication budget, and compute budget are recorded. Human-facing versions should use low-consequence content and avoid sensitive personal data.

## 6. Metrics

### Group capability

Report absolute group performance, best-member performance, independent-aggregation performance, group advantage, task completion time, and compute or message cost. For each result, report the distribution across groups, not only the mean. The group advantage is interpreted only when the best-member and resource baselines are valid.

### Diversity and independence

Measure representation distance, heuristic distance, sensor complementarity, solution-region coverage, proposal novelty, residual error correlation, and mutual information between agent errors. Diversity is useful only when it supplies information that can be combined. High disagreement without complementary signal is not automatically beneficial.

### Communication and coordination

Record message count, latency, turn-taking equality, interruption rate, proposal survival, dissent survival, centralization, role-switch frequency, and coordination cost. For hybrid groups, report machine exposure, acceptance, correction, override, abstention, and influence on the final answer. A machine that speaks often may dominate without adding information.

### Calibration and robustness

Report Brier score, expected calibration error, confidence inflation after discussion, subgroup error, performance under message dropout, corrupted advice, delayed communication, distribution shift, and adversarial but non-harmful misleading proposals. The benchmark should measure whether the group knows when it is wrong.

### Mechanism and fairness safeguards

Record whether independent human alternatives survive into the final answer, whether minority proposals are evaluated, and whether performance gains rely on unequal voice or unobserved information. Demographic variables, if collected in a future human study, are covariates and governance checks, not proxies for functional diversity or intelligence.

## 7. Causal comparisons and analysis

Let $Y_{g,j,s}$ be task performance for group $g$, task $j$, and seed or participant block $s$. A hierarchical analysis estimates

`Y_g,j,s = beta_0 + beta_D D_g + beta_R R_g + beta_C C_g + beta_K K_g + beta_T T_j + interactions + b_g + c_s + epsilon`

where $D_g$ is functional diversity, $R_g$ is residual error correlation, $C_g$ is coordination cost, $K_g$ is communication and compute budget, and $T_j$ is task family. The random effects $b_g$ and $c_s$ capture group and seed variation. Confirmatory contrasts are functional diversity versus homogeneous composition, blind-first versus immediate discussion, calibrated peer AI versus authority AI, and adaptive allocation versus fixed allocation.

For each contrast, report effect estimates with confidence intervals or Bayesian credible intervals, standardized effect sizes, and sensitivity to omitted variables. Mediation analyses can test whether communication changes performance through error correlation or proposal coverage, but they are secondary and cannot replace randomized comparisons. All task families and primary outcomes are specified before confirmatory evaluation.

The benchmark also fits a resource-normalized frontier. A group is Pareto-improved only if it increases performance without an unacceptable increase in time, compute, communication, or confidence miscalibration. The frontier prevents an AI group from winning by using substantially more hidden computation. When a resource tradeoff is intentional, it is reported explicitly rather than described as unexplained emergence.

## 8. Security, privacy, and governance

The system records task messages and model outputs, which may reveal participant reasoning or proprietary information. A future human study must minimize collection, separate identity from content, encrypt data, define retention, and support deletion. Explanations are stored only when needed for the stated analysis. No sensitive personal data are necessary for the initial task battery.

Threats include prompt injection into task content, malicious or misleading agent messages, model overconfidence, data leakage through explanations, collusion between agents, and denial of service. The sandbox should constrain tool access, validate message schemas, log model versions, and provide a human veto over external actions. The experiment must not connect to production systems or allow the group to make high-consequence decisions.

Governance is a manipulated factor. The benchmark compares opaque AI advice with visible confidence, abstention, evidence display, and human veto. A protocol that raises accuracy by causing people to accept an overconfident machine without inspection is not an unqualified success. The final report should give separate conclusions for capability, calibration, agency of human members, and governance quality.

## 9. Reproducibility and decision rules

Release synthetic generators, agent configurations, task seeds, communication graphs, aggregation code, model versions, logs, analysis scripts, and metric definitions. The preregistration records exclusions, failed runs, missing messages, task order, and stopping rules. Every group receives a stable identifier, and every final answer is traceable to agent outputs and protocol events.

A strong emergence claim requires: (i) group advantage over the best member and independent aggregation; (ii) replication in at least two task families; (iii) held-out transfer; (iv) a mechanism signal such as increased complementary coverage or reduced error correlation; (v) no reliance on hidden information or unreported resources; and (vi) acceptable calibration and dissent preservation. A negative result is reported if any of these conditions fails.

## 10. Author handoff

The Author may use verified survey evidence, the GIEB idea, this staged protocol, equations, metrics, and decision rules. The Author must label the artifact `DESIGN_ONLY`, must not invent participant counts or findings, and must not treat a collective intelligence factor as a conscious group mind. Demographic composition must not be used as a shortcut for functional ability or value judgment. The final paper should distinguish group-level task capability from claims about personhood, consciousness, or a new species.
