# ExperimentDesign: ECAA

## Design status

This is a preregistration-ready, DESIGN_ONLY proposal. No animals or humans have been tested in this package, no model has been fitted, and observed_results is empty. The design asks how cognition generalizes across species without forcing every animal into a human sensory or motor mold.

## Research question and predictions

The operational question is whether cross-species cognition has a shared flexibility component, how much performance is domain-specific, and whether ecology, body plan, social learning, and developmental history explain the residual structure.

The primary predictions are: (P1) a partially shared latent factor will explain covariance among flexible learning, reversal, inhibition, and transfer tasks; (P2) species-specific factors will explain substantial additional variance in tool manufacture, acoustic-social processing, numerical memory, camouflage, and object manipulation; (P3) observational learning and cooperation will improve selected problem-solving outcomes where social access is relevant; and (P4) performance rankings will reverse across domains rather than form one universal order.

## Species and data layers

The core comparison includes New Caledonian crows, rooks, chimpanzees, bottlenose dolphins, and octopuses, subject to the availability of approved facilities or existing datasets. The study is not a requirement that all five species complete an identical task. Each species receives a common computational core expressed through species-appropriate sensory and motor interfaces, plus ecological modules.

The preferred data source is a federated combination of existing approved behavioral datasets and new noninvasive or low-burden observations. The minimum inclusion metadata are species, individual identity, age class, sex where appropriate, rearing and training history, task version, motivation measure, sensory access, response modality, and trial-level outcome. Wild observations can supply ecological validity but must be separated from controlled laboratory trials.

Planned target coverage is 30 individuals per species for the common core where feasible, with repeated sessions and at least 20 individuals per species for each ecological module. These are planning targets, not enrollment or observed sample sizes. Rare or endangered species are not recruited solely to fill a matrix. Existing data can replace new observations when measurement metadata are adequate.

## Two-layer task battery

### Computational core

The core contains reversal learning, detour or inhibition, transfer to a changed surface or response rule, delayed matching, causal intervention, and a flexible switching task. The computational requirement is held constant while the interface changes. A crow can manipulate a twig or object; an octopus can explore a tactile object; a dolphin can use an acoustic or operant interface; and a chimpanzee can use a touchscreen or object array. The primary outcome is a learning curve and transfer cost, not a raw first-trial success.

### Ecological modules

Corvid modules quantify material selection, tool shaping, hook manufacture, and tool transfer to a changed substrate. Chimpanzee modules quantify numerical working memory, object choice, social learning, and sequence transfer. Dolphin modules quantify acoustic discrimination, imitation, individual recognition, and socially learned response rules. Octopus modules quantify object transport, shelter selection, camouflage choice, tactile exploration, and flexible barrier opening. Rook modules quantify cooperation, role coordination, and physical problem solving.

Ecological modules are not converted into a universal leaderboard. They estimate domain expertise and its relation to ecology. A high score on one module can be scientifically important without implying high scores on all other modules.

## Social-learning manipulation

Each species receives, when welfare and facility conditions permit, individual-learning and observational-learning conditions. A third condition tests cooperation for species in which joint access and partner coordination are natural and safe. Demonstrators and observers are counterbalanced where possible. The critical outcome is not immediate copying alone; it is whether the observer learns a more efficient rule or transfers the observed solution to a novel context.

Social opportunity, dominance access, neophobia, motivation, and demonstrator reliability are recorded. A failure to copy is not interpreted as a failure of social cognition if the response modality prevents faithful imitation. The design therefore distinguishes emulation of environmental outcomes from imitation of body movements.

## Behavioral and neural measurements

Behavioral measures include accuracy, latency, error type, number of actions, exploration diversity, switch cost, reversal trials to criterion, delayed retention, transfer success, and learning slope. Motivation is estimated from approach latency, participation rate, reward consumption, and session termination behavior. Sensory and motor demands are recorded per task.

Where facilities and existing data permit, noninvasive neural measures include MRI or diffusion MRI in species for which validated protocols exist, functional imaging or near-infrared measures in suitable settings, EEG or local electrophysiology from existing approved datasets, and autonomic or movement measures. Neural data are secondary to the behavioral architecture because cross-species homology is uncertain. A pallial or cortical area is not assumed to be a one-to-one counterpart of a mammalian cortical region.

## Latent cognitive model

Let $Y_{ikd}$ denote the outcome of individual $i$ on task item or trial $k$ in domain $d$. A logistic item-response form for binary success is

\begin{equation}
\operatorname{logit}(p_{ikd})=\alpha_{kd}+\lambda_d\theta_i+\gamma_d E_i+\delta_d S_i+\rho_d M_{ik}+u_{lab}+u_i,
\label{eq:item}
\end{equation}

where $p_{ikd}$ is success probability, $\alpha_{kd}$ is item difficulty, $\theta_i$ is shared flexibility, $E_i$ is ecological-affordance exposure, $S_i$ is social-learning condition, $M_{ik}$ is motivation or participation, and $u_{lab}$ and $u_i$ are laboratory and individual random effects. The loading $\lambda_d$ tests whether a common flexibility trait contributes to domain $d$, while $\gamma_d$ and $\delta_d$ quantify domain-specific moderation.

The latent trait is decomposed by species and individual ecology:

\begin{equation}
\theta_i=\mu_{species(i)}+\beta_1\mathrm{Age}_i+\beta_2\mathrm{Rearing}_i+\beta_3\mathrm{SocialExposure}_i+\xi_i,
\label{eq:trait}
\end{equation}

where $\mu_{species(i)}$ is a species-level location, age and rearing capture developmental history, social exposure captures opportunities for learning from others, and $\xi_i$ is individual variation. Species-level locations are not interpreted as rankings until measurement invariance and task-interface effects have been assessed.

To distinguish a general factor from a pure mosaic, the covariance of domain scores is modeled as

\begin{equation}
\boldsymbol{z}_i=\boldsymbol{\Lambda}\theta_i+\boldsymbol{\eta}_i,\qquad \operatorname{Cov}(\boldsymbol{\eta}_i)=\boldsymbol{\Psi},
\label{eq:mosaic}
\end{equation}

where $\boldsymbol{z}_i$ is the vector of standardized domain scores, $\boldsymbol{\Lambda}$ contains domain loadings on shared flexibility, and $\boldsymbol{\Psi}$ contains residual domain covariance. A small common factor with large structured residuals supports a mosaic. A dominant common factor with weak residual structure supports more general transfer. Both are compared using held-out predictive performance, posterior predictive checks, and measurement-invariance diagnostics.

## Learning curves and transfer

For each task, performance across trials is modeled with a learning curve such as

\begin{equation}
q_{it}=q_{i0}+\left(q_{i\infty}-q_{i0}\right)\left(1-e^{-\kappa_i t}\right),
\label{eq:learning}
\end{equation}

where $q_{it}$ is expected performance on trial $t$, $q_{i0}$ is initial performance, $q_{i\infty}$ is asymptotic performance, and $\kappa_i$ is learning rate. Transfer cost is the performance drop when the rule, object surface, sensory cue, or response modality changes. An individual that learns a routine quickly but cannot transfer it will not be equated with an individual that learns more slowly but generalizes flexibly.

## Phylogenetic and affordance-aware comparison

Species are not independent data points. A secondary phylogenetic model uses a covariance structure derived from accepted phylogenies, but it does not assume that phylogenetic proximity guarantees cognitive similarity. The primary model includes body plan, sensory modality, manipulation capability, diet or foraging niche, group structure, and developmental exposure as affordance variables. For octopuses and mammals, these variables are essential because the same visual or manual response may not be available to both.

Cross-species item equivalence is evaluated using three levels: computational requirement, perceptual interface, and motor response. A task is eligible for a shared latent analysis only if the computational requirement is matched and the other two levels are modeled. Otherwise it remains an ecological module. This rule prevents an animal from being penalized for lacking a human hand or rewarded merely for having a familiar training interface.

## Analysis sequence and controls

The analysis order is frozen before outcome inspection: data and metadata quality control, motivation and sensory-access checks, learning-curve estimation, item calibration, measurement-invariance tests, latent-factor fitting, domain residual analysis, social-learning contrasts, transfer analysis, and held-out model comparison. Labs and species are held out in separate validation splits where sample size permits.

Controls include reward value, food deprivation or feeding schedule, session duration, age, rearing, human exposure, neophobia, sensory acuity, response latency, and motor difficulty. Experimenters are blinded to the predicted direction during coding when feasible. Wild and captive data are not pooled without an explicit environment term.

## Falsification rules

ECAA is weakened if the shared factor is absent after accounting for reliability and motivation, if a universal one-factor model predicts all held-out domains as well as the mosaic model, if affordance variables fail to explain species-by-task interactions, if social-learning conditions do not alter later transfer, or if results are not measurement-invariant across task interfaces. A single species-specific skill is never treated as evidence for a global intelligence score.

ECAA is strengthened when a reproducible but incomplete shared factor predicts core-task transfer, species-specific factors explain ecological expertise, social learning improves selected novel-context outcomes, and the mosaic model generalizes across labs and interfaces. This pattern would support shared computational ingredients without implying identical minds or human-like concepts.

## Ethics and reproducibility

The design prioritizes existing approved datasets and low-burden behavioral observations. New animal work requires species-specific welfare review, positive-reinforcement training, enrichment, minimal deprivation, stopping rules, and a justification that the question cannot be answered from existing data. No invasive neural manipulation is required for the core test. Human comparison participants, if used for calibration, require informed consent and must not be treated as the normative intelligence standard.

The preregistration stores task code, stimulus and object metadata, reward schedules, interface photographs where permitted, coding manuals, exclusion rules, and analysis software versions. Public releases use de-identified trial-level summaries and report species, individual, lab, and task provenance. Raw video and voice data remain governed by consent and facility policy.

## Planned outputs

The study will produce an affordance-aware cognitive atlas, learning and transfer curves, estimates of shared and domain-specific latent structure, social-learning effects, task-interface sensitivity analyses, and a falsification report. These are planned outputs only. No observed result is supplied in this handoff.
