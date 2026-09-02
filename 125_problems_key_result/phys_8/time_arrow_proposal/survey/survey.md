# Survey Agent Report: The Direction of Time as a Multiscale Inference Problem

## Research question and scientific reframing

The question ``Why does time seem to flow in only one direction?'' combines several statements that must not be collapsed into one. Microscopic dynamical laws are often reversible to an excellent approximation; thermodynamic processes display entropy production; observers possess records of a lower-entropy past; and cosmology requires an account of an extraordinarily smooth, low-gravitational-entropy early condition. The Second Law connects these facts but does not by itself specify an absolute moving time or derive the initial condition of the universe.

This survey therefore reframes the topic as follows: **can a resolution-aware, cross-scale inference program distinguish physical entropy production from asymmetry introduced by preparation, hidden variables, coarse graining, or record formation, while representing the cosmological low-gravitational-entropy problem as an explicit boundary condition rather than a solved consequence?** The reframing makes a foundational question empirically tractable without pretending that a finite experiment can settle the origin of the universe's initial state.

## Evidence map

### E1. Statistical and thermodynamic asymmetry

For a suitably specified nonequilibrium process, stochastic thermodynamics defines heat, work, and entropy production on individual trajectories and derives integral and detailed fluctuation relations. Seifert's review provides the formal bridge from time-reversal-symmetric microscopic descriptions to trajectory-level irreversibility under stated bath and dynamics assumptions [seifert2012]. Seifert later emphasizes that partial observation changes what can be inferred and that thermodynamic inference needs explicit access and model assumptions [seifert2018]. Landi and Paternostro review entropy production from classical to quantum regimes [landi2021], while Ciliberto reviews experimental stochastic-thermodynamics tests [ciliberto2017].

**Bounded conclusion:** positive entropy production is a rigorous operational statement only after the system boundary, driving protocol, stochastic dynamics, and observed variables have been specified. It is not a free-standing explanation of every perceived temporal asymmetry.

### E2. Coarse graining, records, and the observational arrow

Gell-Mann and Hartle explain that quasiclassical descriptions necessarily sacrifice microscopic information and connect coarse graining, approximate decoherence, predictability, and thermodynamic entropy [gellmann_hartle2007]. Zurek analyzes environment-induced selection of persistent states and the relation between records, entropy, and predictability [zurek1993]. These sources support a distinction: coarse graining and decoherence help explain why stable classical records and effective macroscopic descriptions arise, but they do not remove the need to state the initial and environmental conditions under which a record-bearing arrow is observed.

**Bounded conclusion:** a time-asymmetric record is neither direct proof of universal dissipation nor merely an observer illusion. It must be tested against a declared description level and a system-environment boundary.

### E3. Cosmological boundary conditions and gravitational entropy

The early universe was hot and close to thermal equilibrium in its matter-radiation sector, yet it was remarkably smooth and therefore low in a gravitational-entropy sense compared with a clumped, black-hole-rich universe. The prompt's simple statement that the Big Bang was a high-entropy state is therefore incomplete. Gell-Mann and Hartle describe a low initial condition in the quasiclassical entropy account [gellmann_hartle2007]. Clifton, Ellis, and Tavakol propose a gravitational-entropy measure and show its expected increase with structure formation in selected cosmological settings [clifton_ellis_tavakol2013]. Aguirre, Carroll, and Johnson analyze rare entropy-decreasing fluctuations and stress the conditional, statistical character of reversal claims [aguirre_carroll_johnson2012].

**Bounded conclusion:** the cosmological arrow is anchored by a low-gravitational-entropy boundary-condition problem. The sources do not establish one universally accepted definition of gravitational entropy or a complete derivation of that condition.

### E4. Quantum and finite-system limits

Strasberg and Winter give a microscopic formulation of thermodynamic quantities for isolated and open quantum systems and derive a compatible integral fluctuation theorem for a broad class of processes [strasberg_winter2021]. Carberry et al. report a colloidal-particle demonstration of a transient fluctuation theorem [carberry2004]. These results motivate a controlled bridge between simulated classical trajectories and open-system quantum models. They do not license an assertion that decoherence alone creates an absolute global arrow.

### E5. Alternative interpretations retained as competing explanations

Rovelli proposes that the arrow may partly depend on the particular coarse graining defining the interacting subsystem [rovelli2017]. This is retained as a competing descriptive hypothesis, not presented as a replacement for entropy-production accounting. A scientifically useful design must separate (i) driven dissipation, (ii) low-entropy boundary conditions, (iii) observer-relevant coarse graining, and (iv) record formation rather than allowing one label to silently stand in for the others.

## Accepted research gaps

| Gap ID | Accepted gap | Evidence basis | Required downstream treatment |
|---|---|---|---|
| G1 | A single operational score for temporal asymmetry is often interpreted as if it uniquely measured physical dissipation. | [seifert2012], [seifert2018], [landi2021] | Compare likelihood asymmetry, entropy-production estimators, and fluctuation-relation residuals under declared model completeness. |
| G2 | The effect of partial observation and coarse graining on arrow inference is not standardized across classical and quantum benchmark settings. | [seifert2018], [gellmann_hartle2007], [strasberg_winter2021] | Use a shared resolution ladder and report hidden-state sensitivity. |
| G3 | Records and decoherence are routinely conflated with entropy production. | [zurek1993], [gellmann_hartle2007], [landi2021] | Maintain separate record, environment, and entropy fields in every model card. |
| G4 | Cosmological discussions often obscure the low-gravitational-entropy initial-condition problem. | [clifton_ellis_tavakol2013], [aguirre_carroll_johnson2012] | Treat cosmology as a boundary-condition ledger and toy-model comparator, not a measured laboratory claim. |
| G5 | A reproducible decision rule is needed for distinguishing true driving from protocol asymmetry or hidden-variable artifacts. | [seifert2018], [carberry2004], [ciliberto2017] | Require negative controls, reversed protocols, and held-out trajectories. |
| G6 | Publicly auditable benchmark artifacts connecting foundations claims to executable inference are scarce. | [seifert2018], [landi2021] | Version generators, observation maps, priors, and conditional conclusions. |

## Evidence plan and claim boundaries

The survey permits the report to state that entropy production can be quantified for specified nonequilibrium models and that fluctuation theorems offer falsifiable constraints. It permits the report to state that cosmological low gravitational entropy is an open boundary-condition problem. It does **not** permit claims that entropy ``makes time move,'' that equilibrium removes microscopic time, that a finite model proves the origin of the cosmic arrow, or that a proposed benchmark has produced observed results.

## Handoff to the Idea Agent

The downstream idea must target one or more accepted Gap IDs, preserve the distinction between physical dissipation and inference artifacts, and label cosmological components as conceptual or synthetic. Candidate ideas may be ambitious in their unification of scales, but they must include a falsifier, a required observation model, and an explicit statement of what a null or non-identifiable result would mean.

