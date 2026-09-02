# Survey: How Does Group Intelligence Emerge?

## Agent role and scope

This is the Survey agent output in the sequence **Survey -> Idea -> ExperimentDesign -> Author**. The phrase “group intelligence” can describe several distinct phenomena: the accuracy of an aggregate estimate, coordinated search, distributed sensing, collective learning, or a human-computer organization that performs better than its components. A single group IQ score cannot cover all of these mechanisms.

The survey reframes the topic as:

> Under what combinations of agent capability, functional diversity, independence, communication, aggregation, coordination, and feedback does a group produce a reliable task-level capability that is greater than the best individual agent and generalizes across tasks?

The study is `DESIGN_ONLY`. It does not claim that every group is intelligent, that a statistical factor is a mind, or that a human-AI group has a new moral or biological status. “Emergence” is operationalized as a group-level performance pattern that cannot be explained by the best individual alone and remains after controlling for group size, task difficulty, and training exposure.

## What must be separated

### Wisdom of crowds

An aggregate can be more accurate than its members when individual errors are sufficiently independent and approximately unbiased. The aggregate is a statistical property, not necessarily a communication process. Social influence can reduce the dispersion that makes aggregation useful. Lorenz et al. used an experiment with 144 participants to show that mild information about others’ estimates could narrow diversity without improving collective accuracy, and could increase confidence without improving correctness [S3]. Thus consensus is not automatically intelligence.

### Collective intelligence factor

Woolley et al. reported two studies with 699 people in groups of two to five and found a general collective intelligence factor that explained performance across a range of group tasks [S1]. The Science abstract states that the factor was not strongly correlated with the average or maximum individual intelligence of group members, but was correlated with social sensitivity, more equal conversational turn-taking, and group composition. This result motivates cross-task measurement, while also leaving open questions about causal mechanisms, task selection, communication structure, and generalization to human-AI teams.

### Functional diversity and complementary search

Hong and Page developed a mathematical framework in which agents have different problem representations and heuristics. Their PNAS article states conditions under which a randomly selected group can outperform a group of individually high-performing agents because functional diversity offsets lower individual ability [S2]. The relevant diversity is not a demographic label by itself; it is difference in representations, search paths, and error patterns. A benchmark should measure functional diversity directly and avoid treating identity as a proxy for competence or algorithmic complementarity.

### Coordination and distributed sensing

Groups may be intelligent because they divide a task, pool partial observations, resolve conflicts, or adapt roles. Their advantage can appear in search and planning even when no individual knows the complete solution. Conversely, communication can create correlated errors, bottlenecks, anchoring, or premature convergence. The causal object is therefore a protocol operating on agents, tasks, and information, not group membership alone.

### Human-computer and hybrid intelligence

The MIT Center for Collective Intelligence explicitly studies how people and computers can be connected so that, collectively, they act more intelligently than any person, group, or computer has done before [S4]. Its research pages identify measurement, collective-intelligence building blocks, generative AI and collective intelligence, and the design of human-AI teams as related projects. Dellermann et al. describe hybrid intelligence as a design problem for complementary human and machine capabilities [S5]. These sources support studying a human-AI group as an engineered organization with explicit interfaces and allocation rules, rather than as a mysterious super-agent.

## A mechanism map

Group performance can be decomposed into seven mechanisms:

1. **Capability:** what each agent can infer or do in isolation.
2. **Functional diversity:** whether agents use complementary representations, heuristics, sensors, or models.
3. **Independence:** whether errors remain sufficiently uncorrelated for aggregation to cancel them.
4. **Communication:** how information, confidence, explanations, and dissent move through the group.
5. **Aggregation:** how partial answers are combined into a decision or plan.
6. **Coordination:** how tasks, roles, resources, and timing are allocated.
7. **Feedback:** whether outcomes update agents and the protocol without destroying useful diversity.

These mechanisms interact. More communication may improve coordination but reduce independence. A highly capable AI may improve average performance but dominate the conversation and suppress human alternatives. A diverse group may generate better search coverage but incur coordination cost. The research gap is a causal account of these tradeoffs across task classes.

## Operational definitions

For task $j$, let $P_{g,j}$ be group performance, $P_{\max,j}$ the best isolated member performance, and $P_{\mathrm{agg},j}$ the performance of a pre-registered aggregation baseline. Define task-level emergence as a positive and robust increment $P_{g,j}-P_{\max,j}$ on held-out instances, together with a mechanism audit showing that the increment is not only group size or extra compute. Define synergy as the residual after accounting for individual abilities, group size, communication volume, and task difficulty. Define collective generalization as preservation of the group advantage across at least two task families and a held-out environment.

For estimation tasks, independence is measured through residual error correlation. For search tasks, functional diversity is measured by representation distance, trajectory overlap, and coverage of distinct solution regions. For deliberation, communication is measured by turn-taking equality, response latency, dissent preservation, and the fraction of proposals that receive independent consideration. For hybrid groups, machine influence is measured by exposure, acceptance, correction, and abstention rates.

## Evidence gaps

1. Group intelligence factor studies provide important cross-task evidence but do not identify which communication or aggregation mechanisms cause the factor.
2. Functional diversity theory predicts when diverse search can beat selected high-ability agents, but practical communication costs and correlated errors require direct measurement.
3. Wisdom-of-crowds studies warn that social influence can collapse diversity, yet protocols that preserve independent first judgments are not compared systematically with free discussion.
4. Human-AI collective intelligence is often described as a design aspiration; few benchmarks jointly test human contribution, machine calibration, role allocation, and correction of machine error.
5. Group size, communication topology, and compute budget are frequently confounded with composition, making “emergence” hard to interpret.
6. A group may outperform individuals on one task by specialization and fail on another; cross-task and held-out evaluation is needed.
7. Average performance can hide minority-agent suppression, overconfident machine advice, unequal speaking time, and fragile consensus.

## Survey conclusion and handoff

The evidence supports a conditional answer: group intelligence emerges when a group combines useful capability with complementary information, retains enough independence to avoid shared error, and uses communication and aggregation protocols that convert diversity into coordinated action. Consensus is neither necessary nor sufficient. Human-AI systems are a promising testbed because the interface, model confidence, role allocation, and abstention policy can be manipulated directly.

The highest-value next step is a causal benchmark comparing human-only, AI-only, and hybrid groups over estimation, search, planning, and distributed-sensing tasks. It should manipulate functional diversity, independence, communication topology, aggregation, and AI calibration while measuring both performance and the mechanisms that produce it. The benchmark can establish a reproducible group capability; it cannot establish that a group is a person or that intelligence has become an independent substance.

## References used by the Survey agent

[S1] A. W. Woolley, C. F. Chabris, A. Pentland, N. Hashmi, and T. W. Malone, “Evidence for a collective intelligence factor in the performance of human groups,” *Science*, vol. 330, no. 6004, pp. 686-688, 2010, doi: 10.1126/science.1193147.

[S2] L. Hong and S. E. Page, “Groups of diverse problem solvers can outperform groups of high-ability problem solvers,” *Proceedings of the National Academy of Sciences*, vol. 101, no. 46, pp. 16385-16389, 2004, doi: 10.1073/pnas.0403723101.

[S3] J. Lorenz, H. Rauhut, F. Schweitzer, and D. Helbing, “How social influence can undermine the wisdom of crowd effect,” *Proceedings of the National Academy of Sciences*, vol. 108, no. 22, pp. 9020-9025, 2011, doi: 10.1073/pnas.1008636108.

[S4] MIT Center for Collective Intelligence, “Research,” MIT, accessed Sep. 2, 2026. [Online]. Available: https://cci.mit.edu/research/

[S5] D. Dellermann, P. Ebel, M. Söllner, and J. M. Leimeister, “Hybrid intelligence,” *Business & Information Systems Engineering*, vol. 61, pp. 637-643, 2019, doi: 10.1007/s12599-019-00595-2.
