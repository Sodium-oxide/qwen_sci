# Survey Agent: Why Do Planetary Orbits Not Generally Decay?

## 1. Scientific reframing

The prompt combines a correct intuition about gravity with an inaccurate general claim
about gradual inward decay. In an isolated Newtonian two-body system, gravity is a
conservative central force. It changes the direction of a planet's velocity but performs
no net work over a closed orbit, so the orbit's mechanical energy and angular momentum
are conserved. There is no medium analogous to air that steadily removes a planet's
orbital energy. An ellipse, not an inward spiral, is the generic Keplerian solution.

The scientifically testable question is therefore:

> Which conservative and nonconservative mechanisms change the orbital elements of a
> planet, at what rate, with what sign, and how can their effects be distinguished from
> numerical integration error and from each other?

This framing distinguishes four claims that are often conflated: bounded Keplerian
motion; secular variation from planet--planet perturbations; genuinely dissipative
torques; and the Solar System's far-future evolution when the Sun loses mass and enters
its giant phases. It also distinguishes a near-collision caused by chaotic excitation of
eccentricity from simple radial orbital decay.

## 2. What established dynamics says

For a point-mass star of mass $M$ and a planet of mass $m$, the relative two-body
equation has a conserved specific energy and specific angular momentum. Negative energy
gives a bound conic and fixes the semimajor axis; angular momentum and energy jointly fix
eccentricity. A time-independent gravitational potential therefore does not contain an
intrinsic drag term. Newtonian gravity by itself cannot make an isolated planet spiral
inward.

The actual Solar System is an interacting many-body system. Planet--planet perturbations
exchange energy and angular momentum among orbits while approximately conserving their
total values in a conservative model. These interactions produce apsidal and nodal
precession, resonances, and very slow secular changes. The system is not a collection of
perfectly fixed ellipses, yet secular variation is not equivalent to monotonic loss of
orbital energy. Laskar's work shows that the Solar System has chaotic components on long
time scales; rare trajectory classes can nevertheless approach collision or ejection
states [4,5]. Such outcomes result from a many-body dynamical pathway, not from a generic
vacuum drag.

## 3. Mechanisms that can change an orbit

### 3.1 Tidal dissipation

Tides convert mechanical energy into heat inside a deformed body and can transfer angular
momentum between spin and orbit. The sign depends on the relation between the body's spin
frequency and orbital mean motion, its internal dissipation, obliquity, eccentricity, and
the full multi-body geometry. The Earth--Moon system illustrates outward lunar evolution
while Earth's spin slows; it is a counterexample to the claim that tidal evolution always
means inward spiral. Stellar and planetary tides can instead shrink an orbit in other
spin-orbit configurations. A model must therefore estimate a signed torque, not assume
``decay.'' Hut's equilibrium-tide treatment is a standard reference point [2].

### 3.2 Stellar mass loss and stellar evolution

Slow, isotropic stellar mass loss weakens the central gravitational field. In the
adiabatic two-body limit, the semimajor axis grows approximately in inverse proportion to
the stellar mass, so this effect is outward rather than inward. The Sun's future
post-main-sequence evolution is a separate regime: its expanding envelope, mass loss,
tides, and possible atmospheric drag can endanger inner planets. Whether a particular
body is engulfed depends on a coupled stellar-evolution and orbital calculation, not on
the present-day proposition that all planetary orbits ``swirl into the Sun.'' Reviews of
post-main-sequence planetary dynamics emphasize this model dependence [6].

### 3.3 Radiation, solar wind, and gravitational radiation

Poynting--Robertson drag is important for small illuminated grains because the
radiation-to-mass ratio is appreciable. It is not a meaningful driver of semimajor-axis
decay for a massive planet. Solar-wind and plasma effects likewise require a stated
cross-section, coupling, and mass regime. General relativity changes orbital precession
in a conservative post-Newtonian description; it does not by itself produce the usual
inward decay of a static two-body orbit. Gravitational-wave emission is dissipative, but
for a star--planet pair its predicted loss is far below the sensitivity relevant to
planetary orbital evolution. These terms should be retained as controlled reference
components, not used rhetorically as an explanation for present planetary infall.

### 3.4 Planet--planet perturbations and resonances

Secular perturbations redistribute angular momentum and can raise eccentricity or change
inclination. Mean-motion resonances can protect bodies from close encounters or, in other
contexts, drive diffusion. A robust long-horizon calculation reports the evolving orbital
elements, close-approach statistics, resonance diagnostics, and total budget errors. It
does not classify every excursion in perihelion as a secular orbital decay.

## 4. Evidence map

| Evidence or model class | What it supports | What it does not support |
|---|---|---|
| High-precision planetary ephemerides [3] | Present state vectors and tested short-to-intermediate-time dynamics | A direct empirical forecast to stellar-evolution time scales |
| Newtonian and post-Newtonian dynamics [1] | Conservative energy/angular-momentum accounting and precession | Dissipation without a specified nonconservative term |
| Tidal theory [2] | Signed spin--orbit angular-momentum exchange conditional on parameters | Universal inward migration |
| Chaotic Solar-System studies [4,5] | Long-horizon sensitivity and rare instability channels | A deterministic date for a collision from one nominal trajectory |
| Post-main-sequence models [6] | Coupled mass-loss, tidal, and engulfment scenarios | The claim that every planet slowly spirals inward today |

## 5. Definitions

* **Orbital decay:** a sustained negative change in semimajor axis caused by a specified
  nonconservative energy/angular-momentum flux; not merely orbital precession.
* **Secular variation:** long-period or cumulative change in orbital elements caused by
  perturbations, which need not have a fixed sign.
* **Dissipation:** conversion of organized mechanical energy to internal heat, radiation,
  or another exported degree of freedom.
* **Adiabatic mass loss:** stellar mass change slow relative to the orbital period, for
  which an orbital action is approximately conserved.
* **Chaos:** sensitive dependence on initial conditions; it limits trajectory-specific
  forecasts without implying immediate instability.
* **Engulfment:** interaction of an orbiting body with an expanded stellar envelope or
  atmosphere during stellar evolution; distinct from present-day vacuum drag.

## 6. Survey gaps and research questions

The important gaps are quantitative attribution of very small secular rates, separation
of physical drift from ephemeris and integration systematics, uncertainty propagation
over chaos-limited horizons, and a clean bridge between present ephemerides and future
stellar-evolution models. The study asks:

* RQ1: Which invariants prevent generic orbital spiraling in the conservative reference
  problem?
* RQ2: Which perturbations change semimajor axis, eccentricity, and angular momentum,
  and how is their sign identified?
* RQ3: Can held-out ephemeris arcs distinguish a missing nonconservative term from a
  numerical or state-estimation artifact?
* RQ4: How should ensembles replace single-trajectory claims beyond the predictable
  horizon of a chaotic many-body system?
* RQ5: How do solar mass loss and giant-branch evolution alter the meaning of an
  ``eventual collision with the Sun''?

## References used by Survey

[1] C. D. Murray and S. F. Dermott, *Solar System Dynamics*. Cambridge, U.K.:
Cambridge Univ. Press, 1999.

[2] P. Hut, ``Tidal evolution in close binary systems,'' *Astronomy and Astrophysics*,
vol. 99, pp. 126--140, 1981.

[3] R. S. Park *et al.*, ``The JPL planetary and lunar ephemerides DE440 and DE441,''
*The Astronomical Journal*, vol. 161, Art. no. 105, 2021, doi: 10.3847/1538-3881/abd414.

[4] J. Laskar, ``Large-scale chaos in the Solar System,'' *Astronomy and Astrophysics*,
vol. 287, pp. L9--L12, 1994.

[5] J. Laskar and M. Gastineau, ``Existence of collisional trajectories of Mercury,
Mars and Venus with the Earth,'' *Nature*, vol. 459, pp. 817--819, 2009,
doi: 10.1038/nature08096.

[6] D. Veras, ``Post-main-sequence planetary system evolution,'' *Royal Society Open
Science*, vol. 3, Art. no. 150571, 2016, doi: 10.1098/rsos.150571.
