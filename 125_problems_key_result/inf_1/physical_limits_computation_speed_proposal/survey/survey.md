# Survey Agent Report: Is There an Upper Limit to Computer Processing Speed?

## Scope and scientific reframing

The question is not whether a single number can be assigned to “computer
speed.”  It is whether a **specified physical computing system** has a
resource-bounded ceiling on a **specified useful computation**.  The
distinction is essential.  A transistor count, a processor clock, a gate
rate, a sampling throughput, and an application time-to-solution are
different quantities.  They are connected by architecture and algorithm,
but none is a universal substitute for the others.

This survey therefore studies the following scoped question:

> Given a workload, correctness target, reliability target, physical
> architecture, energy budget, thermal environment, spatial scale, and
> communication topology, which physical and implementation constraints form
> a defensible upper envelope for useful computational throughput?

The scope includes conventional CMOS and post-CMOS digital systems,
reversible or near-reversible logic, and quantum information processors.  It
does not claim a numerical limit for all possible computers, or a date on
which any technology reaches a limit.

## Evidence map

### S1. Scaling trends are not physical laws

Moore’s 1965 observation describes component-density economics and
manufacturing trends, not a conservation law [S1].  Dennard scaling explains
why earlier feature shrinkage could improve density, speed, and power
together under ideal scaling assumptions [S2].  Its breakdown, leakage,
interconnect delay, variability, yield, packaging, and heat removal mean that
“smaller transistors” cannot be used as an unqualified proxy for useful
throughput.  The end of a historical scaling relationship is not itself proof
of one hard processing-speed number [S3].

### S2. Physical bounds apply to defined processes

For a closed quantum system, quantum-speed-limit results lower-bound the
time needed to evolve between distinguishable states under stated Hamiltonian
and resource assumptions [S4, S5].  The Margolus–Levitin family relates an
idealized orthogonalization rate to energy above the ground state.  It does
not by itself bound an entire computer: a workload also involves
initialization, routing, memory access, control, measurement, error handling,
and output.

Landauer’s principle supplies a minimum heat cost for logically irreversible
bit erasure at temperature \(T\), not a universal energy cost for every
logical operation [S6].  A system can approach reversible logical operations
in principle, but practical clocks, error correction, I/O, and finite-time
control introduce additional costs.  Finite signal velocity likewise imposes
latency across a nonzero device extent.  These constraints act on different
parts of a computation and should not be collapsed into a single
energy-only argument.

### S3. Quantum computing changes algorithms, not the need for a resource account

Quantum processors can give strong complexity advantages for particular
problems and computational models.  They do not imply exponential speedup for
arbitrary workloads.  The cross-validated review by Deffner and Campbell
explicitly treats quantum speed limits as bounds on quantum evolution and
control, while Preskill identifies noise and reliable circuit depth as central
constraints on near-term devices [S4, S7].  DiVincenzo’s implementation
criteria further show that scalable computing requires physical
initialization, control, measurement, and communication capabilities [S8].

Random-sampling demonstrations are valuable task-specific milestones, but
their interpretation is not a universal “processor speed” score.  The
Hangleiter–Eisert review separates the demonstrated sampling task, classical
simulation assumptions, verification, and claims of computational advantage
[S9].  A photonic experiment can therefore motivate an architecture card; it
cannot prove that physical speed ceilings disappeared.

### S4. Reliability changes physical speed into logical useful throughput

Fault tolerance encodes logical information in many physical components and
consumes space, time, measurement, decoding, and control resources.  Recent
cross-validated literature demonstrates progress in error correction and
lower-overhead codes, but also makes the overhead explicit [S10–S12].
Accordingly, a physical gate rate and a logical algorithm completion rate must
be reported separately.

## Evidence-backed subhypotheses

| ID | Subhypothesis | Direct evidence role | Constraint on later claims |
|---|---|---|---|
| SH-1 | A density or clock trend is not a universal throughput limit. | S1–S3 | Do not equate Moore’s Law ending with a fundamental terminal speed. |
| SH-2 | Quantum-speed limits bound selected state transformations under stated assumptions. | S4–S5 | Do not convert a QSL into a whole-computer rate without a system model. |
| SH-3 | Erasure, temperature, thermal extraction, and finite signal propagation can separately constrain realized throughput. | S4, S6 | Name which operations are irreversible and which paths carry information. |
| SH-4 | Quantum advantage is workload-specific and can be limited by fault-tolerance overhead. | S7–S12 | Do not infer general exponential processing speed from a sampling result. |
| SH-5 | A defensible comparison must state workload, accuracy, reliability, wall-clock boundary, and physical resource envelope. | Synthesized from SH-1–SH-4 | Reject benchmark-only or gate-rate-only claims. |

## Gap ledger

| Gap ID | Verified research gap | Why existing evidence is insufficient | Downstream admissible direction |
|---|---|---|---|
| GAP-SCOPE-001 | “Processing speed” is reported with incompatible denominators. | Clock, gate, sample, FLOP, and time-to-solution measures are not directly interchangeable. | Define a workload- and correctness-bounded throughput contract. |
| GAP-COMPOSE-002 | Physical limits are usually discussed one at a time. | A QSL, Landauer bound, and propagation delay govern different mechanisms. | Build a compositional resource-envelope model, not a claimed universal constant. |
| GAP-LOGICAL-003 | Logical throughput is often detached from physical overhead. | QEC changes qubit count, cycle count, decoding, and I/O requirements. | Require a physical-to-logical overhead map. |
| GAP-ADVANTAGE-004 | Task-specific quantum advantage is often communicated as general speed. | Sampling demonstrations do not establish utility across workloads. | Separate algorithmic advantage, device rate, verification, and useful output. |
| GAP-THERMAL-005 | Dissipation and heat extraction are weakly coupled to reported performance. | Minimal erasure heat is not realized package-level thermal power. | Add explicit thermal and cooling boundary cards. |

## Survey conclusion and handoff

There are upper limits, but they are **conditional envelopes rather than one
technology-independent number**.  The most useful downstream research program
is to make every speed claim reproducible as a tuple:

\[
\langle \text{workload},\ \text{accuracy},\ \text{reliability},\
\text{architecture},\ E,\ T,\ L,\ \text{communication},\
\text{thermal boundary},\ \text{I/O boundary} \rangle.
\]

The Idea Agent must preserve all five gap identifiers, attach any proposed
metric to a falsifier, and must not claim that quantum information processing
escapes energy, information-density, transmission, thermodynamic, or
reliability constraints.

## Evidence register

- **S1:** G. E. Moore, “Cramming more components onto integrated circuits,”
  *Electronics*, 1965.
- **S2:** R. H. Dennard *et al.*, “Design of ion-implanted MOSFETs with very
  small physical dimensions,” *IEEE J. Solid-State Circuits*, 1974,
  doi: 10.1109/JSSC.1974.1050511.
- **S3:** M. M. Waldrop, “The chips are down for Moore’s law,” *Nature*,
  2016, doi: 10.1038/530144a.
- **S4:** S. Deffner and S. Campbell, “Quantum speed limits: from
  Heisenberg’s uncertainty principle to optimal quantum control,” *J. Phys.
  A*, 2017, doi: 10.1088/1751-8121/aa86c6.  OpenAlex/AnySearch
  cross-validated; DOI publisher page checked in the in-app browser.
- **S5:** N. Margolus and L. B. Levitin, “The maximum speed of dynamical
  evolution,” *Physica D*, 1998, doi: 10.1016/S0167-2789(98)00054-2.
- **S6:** R. Landauer, “Irreversibility and heat generation in the computing
  process,” *IBM J. Res. Dev.*, 1961, doi: 10.1147/rd.53.0183.
- **S7:** J. Preskill, “Quantum computing in the NISQ era and beyond,”
  *Quantum*, 2018, doi: 10.22331/q-2018-08-06-79.  OpenAlex/AnySearch
  cross-validated.
- **S8:** D. P. DiVincenzo, “The physical implementation of quantum
  computation,” *Fortschr. Phys.*, 2000, doi:
  10.1002/1521-3978(200009)48:9/11<771::AID-PROP771>3.0.CO;2-E.
  OpenAlex/AnySearch cross-validated.
- **S9:** D. Hangleiter and J. Eisert, “Computational advantage of quantum
  random sampling,” *Rev. Mod. Phys.*, 2023, doi:
  10.1103/RevModPhys.95.035001.  OpenAlex/AnySearch cross-validated.
- **S10:** A. G. Fowler *et al.*, “Surface codes: Towards practical
  large-scale quantum computation,” *Phys. Rev. A*, 2012, doi:
  10.1103/PhysRevA.86.032324.
- **S11:** S. Bravyi *et al.*, “High-threshold and low-overhead
  fault-tolerant quantum memory,” *Nature*, 2024, doi:
  10.1038/s41586-024-07107-7.  OpenAlex/AnySearch cross-validated.
- **S12:** L. Z. Cohen *et al.*, “Low-overhead fault-tolerant quantum
  computing using long-range connectivity,” *Sci. Adv.*, 2022, doi:
  10.1126/sciadv.abn1717.  OpenAlex/AnySearch cross-validated.
