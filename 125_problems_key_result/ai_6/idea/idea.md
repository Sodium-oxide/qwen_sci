# Idea: GROUP-INTELLIGENCE-EMERGENCE-BENCHMARK

## Idea-agent synthesis

The survey suggests that group intelligence is not produced by simply adding individual intelligence. It emerges when a set of agents supplies complementary information, keeps enough independence for errors to cancel, and uses a communication and coordination protocol that converts partial solutions into a reliable collective action. The proposed contribution is a causal benchmark for this emergence, with human-only, AI-only, and human-AI groups evaluated under the same tasks, budgets, and information constraints.

## Central claim to test

A group will outperform its best member on held-out tasks when functional diversity and error independence are combined with calibrated aggregation and adaptive role allocation. Free discussion can help coordination, but it can also induce correlated errors and premature consensus. A hybrid human-AI group should be strongest when the machine supplies complementary computation or retrieval, reports calibrated uncertainty, and is prevented from suppressing independent human alternatives.

## Research questions

1. Which combinations of functional diversity and individual ability create a group advantage over the best member?
2. When does independent first judgment improve aggregation compared with immediate discussion?
3. How do communication topology, turn-taking, and dissent preservation affect collective accuracy and calibration?
4. Can a human-AI group outperform matched human-only and AI-only groups when the machine is assigned a complementary role rather than authority over the final answer?
5. Does adaptive task allocation create a general group capability, or only optimize one task family?
6. Which measurements distinguish genuine group synergy from extra compute, larger group size, or more time on task?

## Hypotheses

**H0, best-member baseline.** Under matched time, information, and compute budgets, group performance is explained by the best individual or by a simple aggregation baseline; no residual synergy remains.

**H1, functional-diversity complementarity.** Groups with complementary representations, heuristics, sensors, or error profiles outperform homogeneous groups with the same mean individual ability.

**H2, independence tradeoff.** Blind independent first judgments improve aggregate estimation when errors are diverse; unrestricted early discussion can reduce accuracy by correlating errors and shrinking opinion spread.

**H3, calibrated hybrid assistance.** A human-AI group with calibrated uncertainty, explicit abstention, and complementary role allocation outperforms matched human-only and AI-only groups on tasks where human context and machine search or calculation are complementary.

**H4, coordination cost.** Communication improves performance only up to a task- and topology-dependent level; excessive centralization or high-confidence machine advice increases dominance and reduces dissent.

**H5, emergent generalization.** A group-level advantage that survives held-out tasks, changed environments, and controlled communication budgets is stronger evidence of collective intelligence than a gain on one benchmark.

**H6, mechanism observability.** Group performance can be predicted from individual ability, functional diversity, error correlation, communication equality, confidence calibration, and allocation efficiency more accurately than from group size alone.

## Proposed benchmark

The GROUP-INTELLIGENCE-EMERGENCE-BENCHMARK (GIEB) has five manipulable layers:

- **Agents:** human participants in a future approved study, fixed algorithmic agents, and hybrid human-AI groups.
- **Diversity:** homogeneous versus deliberately complementary representations, heuristics, sensors, or model families.
- **Information flow:** independent first answers, sequential discussion, broadcast, sparse network, or adaptive routing.
- **Decision rule:** mean, median, confidence-weighted aggregation, majority, deliberative synthesis, or explicit abstention.
- **Coordination:** fixed roles, random roles, expertise-based roles, or a learned task allocator.

Every group has a matched best-member condition, size-matched aggregation baseline, and compute- and time-budget baseline. The benchmark records both the outcome and the pathway: whose information entered the final answer, which alternatives were discarded, how confidence changed, and whether the group corrected or amplified error.

## Formal decomposition

For task $j$, define group advantage as $A_j=P_{G,j}-P_{\max,j}$, where $P_{G,j}$ is group performance and $P_{\max,j}$ is the best isolated member under the same budget. Let $D_j$ be functional diversity, $R_j$ residual error correlation, $C_j$ coordination cost, and $K_j$ communication and compute budget. The proposed mechanism model is:

`A_j = beta_0 + beta_D D_j - beta_R R_j - beta_C C_j + beta_K K_j + interactions`

The coefficients are estimands, not expected results. Positive $D_j$ is not sufficient if it is accompanied by high $R_j$ or excessive $C_j$. A human-AI gain is called complementary only if removing the machine's distinctive information or replacing it with a same-size generic assistant removes the gain.

## Falsifiers and boundary conditions

The idea is weakened if group advantage disappears after equalizing time and compute, if diversity does not predict held-out performance, or if the hybrid group wins only because the AI has access to information unavailable to human controls. It is rejected as a general account if one communication protocol dominates across all tasks, if group performance is fully explained by the best member, or if the measured group factor fails to generalize. No result establishes a group mind, consciousness, or a social value judgment about demographic categories.

## Expected contribution

GIEB would provide a reproducible vocabulary for distinguishing wisdom of crowds, collective search, coordinated sensing, collective learning, and human-AI hybrid intelligence. It would convert “more intelligent than any individual” into a set of task-level, causal, and falsifiable comparisons. Its design also makes negative results useful: a protocol that improves mean accuracy while inflating confidence and suppressing dissent should be marked as a governance failure, not as unqualified intelligence.

## Handoff to ExperimentDesign

The experiment agent must build a simulation-first benchmark with fixed seeds and matched budgets, then use a non-production human-AI interface for optional low-risk validation after review. The design must measure first independent judgments, communication and role allocation, error correlation, machine calibration and abstention, group-level synergy, cross-task transfer, and minority or dissent survival. It must never report fabricated participants or empirical outcomes.
