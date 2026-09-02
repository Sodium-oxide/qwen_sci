# Idea Agent: LONG-HORIZON-ORBITAL-SURVIVAL-BENCHMARK

## Central idea

Build a signed energy-and-angular-momentum budget benchmark for planetary orbital
survival. The benchmark treats a planetary orbit as a state-estimation and dynamical
inference problem, not as a visual spiral. It starts with a conservative multi-body
reference integration and adds physically declared perturbation modules: first
post-Newtonian gravity, tides, stellar mass loss, radiation/solar-wind forces where
appropriate, and a negligible-but-audited gravitational-radiation term. Each module must
state the flux it contributes, its parameter prior, its validity range, and the
observable it could change.

## Scenario classes

* **S0:** Newtonian $N$-body reference with calibrated state vectors and no artificial
  dissipation.
* **S1:** S0 plus conservative first post-Newtonian corrections.
* **S2:** S1 plus parameterized stellar and planetary tide models with spin states and
  dissipation parameters.
* **S3:** S1 plus adiabatic and nonadiabatic stellar mass-loss histories, reserved for
  a stated stellar-evolution interval.
* **S4:** Size- and coupling-dependent radiation, solar-wind, or gas-drag modules;
  massive planets and small bodies are analysed separately.
* **S5:** Ensemble long-horizon integrations with uncertain initial conditions and
  physical parameters, reporting encounter and element distributions rather than a
  singular deterministic future.

## Falsifiable hypotheses

* H0: S0/S1 explain held-out ephemeris arcs within their stated uncertainty without a
  measurable secular semimajor-axis decay for the selected planet.
* H1: A physically declared tide or mass-loss module improves held-out predictions and
  produces a signed, budget-consistent secular effect.
* H2: Apparent decay disappears or changes materially under integrator, step-size,
  coordinate, observation-model, or state-vector perturbations, indicating a numerical
  or estimation artifact.
* H3: Long-horizon ensemble dispersion grows faster than a single nominal trajectory
  remains predictive, so collision or ejection claims must be probabilistic.
* H4: In an adiabatic solar-mass-loss model, planetary semimajor axes tend outward;
  giant-branch engulfment needs additional envelope/tidal physics.
* H5: A perihelion shift or precession signal alone does not establish orbital decay.

## Contribution and boundary

The output is a mechanism-by-observable profile: element drift, spin/orbit
angular-momentum transfer, energy flux, residual improvement, numerical convergence,
prior sensitivity, and long-horizon survival distribution. The project is DESIGN_ONLY.
It neither fits a real ephemeris nor forecasts a collision date. It cannot claim that a
presently tiny residual proves a new force, and it does not convert a simulation ensemble
into an exact future history of the Solar System.
