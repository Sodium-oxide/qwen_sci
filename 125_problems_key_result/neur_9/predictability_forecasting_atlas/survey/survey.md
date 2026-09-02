# Survey: Is It Possible to Predict the Future?

## Scientific reframing

The phrase “predict the future” is scientifically useful only after the target is typed. This Survey separates: (i) deterministic state prediction, where a model estimates a future state from an information-rich initial condition; (ii) probabilistic forecasting, where a distribution over future outcomes is required; and (iii) scenario projection, where outcomes are conditional on an explicitly specified forcing or intervention. The actionable question is:

> Under what combinations of system dynamics, observation quality, model class, and distribution shift does an intelligent forecasting system retain calibrated predictive information as lead time increases?

This framing preserves the ambition of the question. It predicts that advanced machines can extend useful horizons, discover structure, and produce better probabilities, while rejecting the stronger claim that computation can make every future event knowable.

## Evidence policy and scope

The Survey covers dynamical-systems predictability, numerical weather and climate prediction, probabilistic forecast evaluation, machine-learning forecasting, orbital mechanics, economic time series, and public-health time series. Claims about future performance remain design hypotheses. No forecast was run, no future event was observed, and no proposed result is presented as data.

The evidence registry was checked through public article pages and open scholarly records in the in-app browser on 2026-09-01. The registry uses direct evidence for the specific claim supported by each source; search snippets and popular summaries are not treated as primary evidence.

## Evidence map

### 1. Predictability is a property of a system-information pair

Lorenz’s classic analysis showed that finite deterministic nonlinear systems can have nonperiodic trajectories and sensitive dependence on initial conditions [E1]. His later work connected atmospheric forecast limits to the growth of small initial errors [E2]. The implication is not that weather is random in the strongest sense. It is that a deterministic law can still yield limited long-range state prediction when the initial state is measured only approximately. Forecastability therefore depends on the target, the information available at initialization, and the lead time.

ECMWF describes two practical sources of decreasing forecast skill: uncertainty in the initial conditions and necessary approximations in the numerical model [E3]. Its ensemble prediction system perturbs both initial conditions and model tendencies to represent forecast uncertainty. This is a mature operational argument for treating a forecast as a distribution whose spread should change with horizon, not as a single number that hides uncertainty.

### 2. Different futures require different language

The IPCC’s assessment of regional climate information explicitly combines observations, ensembles of different model types, process understanding, expert judgment, and uncertainty characterization [E6]. A climate projection is conditional on forcing assumptions and is not interchangeable with an exact prediction of a particular storm or date. A weather forecast targets an evolving state on a shorter horizon; a climate projection targets distributions or trends under a scenario. Economic and public-health forecasts add feedback, policy response, reporting delay, and behavior change.

The first survey conclusion is therefore definitional: an intelligent machine may predict some variables accurately, forecast other variables probabilistically, and only project long-range conditional possibilities for still other targets. “The future” is not one statistical object.

### 3. Probability quality matters as much as point accuracy

Gneiting and Raftery formalized strictly proper scoring rules for predictive distributions [E4]. A proper rule rewards a forecaster for stating probabilities close to the distribution that generated the outcome, rather than for making overconfident guesses. Brier score, logarithmic score, continuous ranked probability score, reliability, sharpness, and interval coverage are complementary tools.

The M4 forecasting competition demonstrated that forecast quality depends on the data family, horizon, aggregation, and method, and that simple statistical methods remain strong baselines [E8]. Deep probabilistic methods such as DeepAR show how a model can represent a distribution over many related series rather than a single deterministic trajectory [E9]. These sources motivate a benchmark where model accuracy and calibration are evaluated together, with strong persistence, climatology, autoregressive, and mechanistic baselines.

### 4. Intelligent machines can extend a useful horizon

GraphCast was introduced as a machine-learning weather model trained on reanalysis data. Its abstract reports global forecasts of hundreds of weather variables over more than ten days and higher verification skill than a leading operational deterministic system on most of its stated targets, while producing forecasts quickly [E5]. This is a concrete demonstration that changing the model class can improve a bounded prediction task. It is not evidence that weather becomes indefinitely predictable, and it does not transfer automatically to economics or public health.

The relevant scientific question is not “AI or no AI?” It is whether an AI or hybrid model retains skill after normalization by each domain’s characteristic timescale, whether its probability statements remain calibrated under regime change, and whether it adds information beyond a well-tuned baseline. Speed is a deployment advantage; it is not itself information about the future.

### 5. Distribution shift is part of the future

Forecast systems learn from historical relationships. Those relationships can change when climate forcing changes, when a policy alters behavior, when a pathogen evolves, or when a measurement system is redesigned. The Google Flu Trends case is a warning that a high-dimensional proxy can fail when the relationship between proxy and target shifts [E10]. IPCC’s treatment of multiple lines of evidence and contradictions also makes shift and model uncertainty explicit [E6]. A benchmark that uses random train/test splits would conceal exactly the difficulty that makes future prediction scientifically interesting.

## Research gap ledger

The Survey accepts seven gaps for Idea-stage use:

1. **G1 — Typed future is not operationalized.** Deterministic prediction, probabilistic forecasting, and conditional projection are often discussed together, preventing comparable claims [E4, E6, E7].
2. **G2 — No common horizon scale.** A seven-day weather horizon and a seven-year economic horizon cannot be compared without a domain timescale [E1, E2, E3].
3. **G3 — Uncertainty components are confounded.** Initial-state, observation, model, process, and distribution-shift uncertainty are not consistently separated [E3, E6].
4. **G4 — Skill is reported more often than calibration.** Point error or average rank does not guarantee reliable probabilities or tail-event behavior [E4, E8, E9].
5. **G5 — AI gains may be domain-specific.** Learned weather models show bounded gains, but transfer across regimes and domains remains open [E5, E6, E10].
6. **G6 — Computational speed is not information.** Faster inference and larger models can improve access without creating observations of an unobserved future [E1, E3, E5].
7. **G7 — Decision usefulness is under-linked to forecastability.** A statistically skillful forecast may be poorly calibrated or badly timed for an operational decision [E4, E6, E7].

## Survey decision

The strongest downstream opportunity is a Horizon-Conditioned Forecastability and Calibration Atlas: a rolling-origin, multi-domain benchmark that estimates how predictive information and probability quality decay with normalized lead time. It should compare mechanistic, statistical, machine-learning, and hybrid models; perturb the information set; test distribution shift; and report an effective horizon at which a model no longer adds reliable information over a strong baseline.

The direct evidence supports the claim that future knowledge is conditional, typed, probabilistic, and horizon-bounded. It does not support a universal oracle, an exact date for arbitrary events, or a conclusion that quantum or classical computation can defeat the information loss created by chaotic amplification and unobserved interventions.

## Verified sources

**[E1]** E. N. Lorenz, “Deterministic Nonperiodic Flow,” *Journal of the Atmospheric Sciences*, vol. 20, no. 2, pp. 130–141, 1963, doi: 10.1175/1520-0469(1963)020<0130:DNF>2.0.CO;2.

**[E2]** E. N. Lorenz, “The predictability of a flow which possesses many scales of motion,” *Tellus*, vol. 21, no. 3, pp. 289–307, 1969, doi: 10.1111/j.2153-3490.1969.tb00444.x.

**[E3]** European Centre for Medium-Range Weather Forecasts, “Quantifying forecast uncertainty,” ECMWF, accessed Sep. 1, 2026. [Online]. Available: https://www.ecmwf.int/en/research/modelling-and-prediction/quantifying-forecast-uncertainty

**[E4]** T. Gneiting and A. E. Raftery, “Strictly proper scoring rules, prediction, and estimation,” *Journal of the American Statistical Association*, vol. 102, no. 477, pp. 359–378, 2007, doi: 10.1198/016214506000001437.

**[E5]** R. Lam *et al.*, “GraphCast: Learning skillful medium-range global weather forecasting,” *Nature*, vol. 619, pp. 533–538, 2023, doi: 10.1038/s41586-023-06185-3.

**[E6]** IPCC, “Chapter 10: Linking global to regional climate change,” in *Climate Change 2021: The Physical Science Basis*, Cambridge Univ. Press, 2021. [Online]. Available: https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-10/

**[E7]** R. J. Hyndman and G. Athanasopoulos, *Forecasting: Principles and Practice*, 3rd ed. Melbourne, Australia: OTexts, 2021. [Online]. Available: https://otexts.com/fpp3/

**[E8]** S. Makridakis, E. Spiliotis, and V. Assimakopoulos, “The M4 Competition: Results, findings, conclusion and way forward,” *International Journal of Forecasting*, vol. 34, no. 4, pp. 802–808, 2018, doi: 10.1016/j.ijforecast.2018.06.001.

**[E9]** D. Salinas, V. Flunkert, J. Gasthaus, and T. Januschowski, “DeepAR: Probabilistic forecasting with autoregressive recurrent networks,” *International Journal of Forecasting*, vol. 36, no. 3, pp. 1181–1191, 2020, doi: 10.1016/j.ijforecast.2019.07.001.

**[E10]** D. Lazer, R. Kennedy, G. King, and A. Vespignani, “The parable of Google Flu: Traps in big data analysis,” *Science*, vol. 343, no. 6176, pp. 1203–1205, 2014, doi: 10.1126/science.1248506.
