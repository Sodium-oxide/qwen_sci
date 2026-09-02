# ExperimentDesign Agent: LONG-HORIZON-ORBITAL-SURVIVAL-BENCHMARK

## 1. Aim and design status

This is a preregistration-ready DESIGN_ONLY protocol. Its aim is to attribute or reject
putative planetary orbital decay by testing signed energy and angular-momentum budgets
against calibrated state-vector observations and by propagating uncertainty into
long-horizon ensembles. It does not execute an ephemeris fit, estimate a new force,
measure a decay rate, or issue a collision-date forecast.

## 2. Model ledger

Every run declares a model instance from S0--S5. The ledger contains: bodies and mass
parameters; coordinate/time scale; initial state and covariance; Newtonian interactions;
relativistic terms; body radii and multipole treatment; spins and obliquities; tide model
and dissipation parameters; stellar mass-loss history; radiation, solar-wind, gas, or
gravitational-wave term when relevant; numerical integrator; tolerance and step policy;
physical validity checks; parameter priors; and expected observable signatures.

A term is not admitted merely because it is physically imaginable. It must have a stated
force/torque law, dimensions, a parameter range, a domain of validity, and a prediction
that differs from a baseline within an observation or synthetic-injection test. A module
that is far below the selected precision is retained in the audit ledger but cannot be
presented as the explanation for a residual.

## 3. Data, partitions, and blinding

The intended data source is a documented public or licensed planetary ephemeris and its
underlying range/Doppler/astrometric summaries where permitted. Freeze the ephemeris
release, time scale, reference frame, tracking data inclusion, state-estimation
conventions, and covariance treatment. Development data validate parsing and units.
Training arcs estimate the declared ledger. At least one independent arc, tracking class,
or body-specific observable is held out from mechanism selection.

For a suspected small semimajor-axis drift, a held-out test may be a later time arc, a
different observing geometry, a spacecraft-ranging product, or a derived observable with
proper covariance treatment. It is invalid to select a tide or drag parameter after
examining every available residual and then describe the same residual as confirmation.

## 4. Forward integration protocol

1. Transform every initial condition into one documented barycentric coordinate and time
   convention; preserve the original state-vector record.
2. Integrate S0 with at least two independently implemented numerical approaches where
   feasible: a high-order adaptive method and a symplectic or variational method suitable
   for the interval.
3. Verify conservation of total energy and angular momentum for the conservative model,
   while distinguishing physical exchange among bodies from numerical drift.
4. Add S1--S4 one at a time and record their signed work/torque accounting, changes in
   osculating elements, and predicted measurement residuals.
5. Fit only the parameters permitted by the frozen ledger on training arcs; evaluate the
   fixed prediction on held-out arcs.
6. Run S5 as an ensemble over state covariance, physical parameters, and model variants;
   report distributions rather than a single authoritative trajectory after chaos-limited
   horizons.

## 5. Primary observables and metrics

Primary observables are range, range rate, angular position, osculating semimajor axis,
eccentricity, inclination, perihelion/node precession, spin rate where relevant, and
residuals in their native observation space. Report uncertainty-aware likelihood or a
specified loss, held-out predictive error, conservation-budget residuals, numerical
convergence, parameter correlation, posterior/prior sensitivity where Bayesian methods
are used, and runtime/resource use. A period or perihelion change alone is not the
primary metric of orbital decay.

## 6. Controls and robustness checks

* Repeat with independently implemented force and observation models.
* Sweep step size, tolerance, coordinate representation, and output cadence.
* Inject synthetic secular drifts, tide parameters, and null signals into simulated
  observations; evaluate recovery and false-positive behavior.
* Change plausible initial-state samples within covariance and retain the full ensemble.
* Vary tidal quality factors, spin states, and mass-loss histories only inside the
  preregistered model domain; report sign changes and degeneracies.
* Withhold an observation interval or class before selecting a mechanism.
* Audit unit conversions, time standards, reference frames, and double counting of
  relativistic or multipole terms.

## 7. Decision rules

Support for a physical secular-decay mechanism requires all of: a declared nonconservative
flux; a statistically and physically coherent fit; improvement on a held-out observable;
stability under integrator and state-vector perturbations; and a signed energy and
angular-momentum budget that closes within documented uncertainty. A model that improves
only an in-sample osculating-element curve is inconclusive. If an apparent drift vanishes
when the integrator, frame, cadence, or state estimate changes, it is classified as a
numerical/estimation artifact pending further evidence.

Support for long-horizon instability means that an ensemble exhibits a stated event class
under a specified stellar and dynamical model. It does not license an exact date or a
claim that all planets will spiral into the Sun. A giant-branch engulfment conclusion
requires a coupled stellar-radius, mass-loss, tide, and drag model.

## 8. Reproducibility and interpretation safety

Release the model ledger, source and binary hashes, ephemeris-release identifier, state
vectors/covariance when permitted, integrator version, compiler/runtime details, force
modules, unit tests, seeds, ensemble draws, convergence diagnostics, failed integrations,
and event logs. Preserve licenses for ephemerides and tracking data. Each report labels
observations, inferred parameters, numerical extrapolations, and stellar-evolution
assumptions separately. No run output may be described as a measured universal law of
orbital decay.
