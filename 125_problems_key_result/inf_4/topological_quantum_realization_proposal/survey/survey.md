# Survey Agent Report

## Research question and scientific reframing

**User question.** Can topological quantum computing be realized?

**Operational question.** What experimental and engineering evidence would justify calling a physical platform a controllable, protected topological-qubit primitive, rather than a device with a suggestive local Majorana-like signal?

The short answer is conditional but substantive. Topological quantum computation is a coherent theoretical route to fault-tolerant information processing. It exploits **non-Abelian anyons**: emergent two-dimensional quasiparticle excitations whose exchanges act by non-commuting unitary transformations on a degenerate many-body state space. When information is encoded nonlocally, local perturbations have reduced ability to distinguish the encoded states. This is a physically meaningful protection mechanism, not merely a geometric metaphor. It does not, however, mean that every material signature associated with a candidate Majorana system is proof of a topological computer.

The prompt's intuition needs two corrections. The relevant objects are not ordinary elementary particles changing between a conventional manifold and a Mobius strip. Rather, the configuration-space paths of identical quasiparticles in two dimensions can be braided. For non-Abelian anyons, braid histories implement matrices on a protected fusion space. Majorana zero modes in solid-state devices are proposed emergent quasiparticle degrees of freedom that can realize an Ising-type non-Abelian sector. They are not a completed computer by default, and topology does not generically remove the need for low temperature, device control, readout engineering, or supplementary fault-tolerance resources.

This survey therefore distinguishes four claims that are often conflated:

1. **Theory claim:** non-Abelian anyons permit a topologically protected computational encoding and braid operations.
2. **Phase claim:** a material/device realizes a gapped topological phase compatible with Majorana or another non-Abelian candidate.
3. **Operation claim:** the device performs controlled nonlocal fusion and/or exchange operations whose outcomes reject local mimics.
4. **Computing claim:** multiple encoded qubits, measurement, control, and an explicit universality route operate with a demonstrated protection advantage.

Only the fourth claim is realization of a useful topological quantum-computing system. The survey identifies how a proposed study can move through the preceding claims without overstating early evidence.

## Evidence map

### The theoretical mechanism

Kitaev introduced anyonic fault-tolerant computation as a model in which information and gates are represented by topological properties of quasiparticle trajectories [1]. Nayak *et al.* review the essential mechanism: non-Abelian quasiparticles possess a multi-particle topological degeneracy; braiding and measurement implement gates; and nonlocal encoding makes the information less sensitive to local perturbations [2]. The APS publisher page was checked directly for the title, authors, DOI, date, and abstract of this review. It specifies that the fault-tolerance proposal rests on non-Abelian braiding statistics and identifies fractional quantum Hall states and thin-film superconductors as candidate settings, rather than reporting a completed architecture.

For Majorana zero modes (MZMs), an idealized mode is self-adjoint, $\gamma=\gamma^\dagger$, and spatially separated pairs can encode a fermion parity degree of freedom. Exchanging two MZMs ideally applies a unitary of the form $U_{ij}=\exp(\pi\gamma_i\gamma_j/4)$, up to convention. The non-commutativity becomes meaningful only with sufficiently many modes and a controlled measurement context. A local spectral feature at a wire end cannot by itself establish this algebra.

There is another important limitation. Majorana/Ising braiding supports a protected Clifford-type subset but is not by itself a universal gate set [11]. A scalable architecture needs a non-Clifford resource, for example magic-state distillation, a protected measurement protocol, or a separately controlled unprotected operation whose error is explicitly budgeted. Thus ``topological'' should be treated as a reduction of selected physical error channels, not as a synonym for fully error-free universal computation.

### Candidate solid-state platforms

Semiconductor-superconductor heterostructures are a principal platform family. With spin-orbit coupling, Zeeman splitting, and proximity-induced pairing, a one-dimensional effective model can enter a topological regime and host end-localized MZMs under idealized conditions [12], [13]. Lutchyn *et al.* review materials progress in InAs/InSb heterostructures, zero-bias tunneling and Coulomb-blockade signatures, and the next experiments needed to test fusion rules and non-Abelian exchange statistics [3]. The Nature publisher page was checked directly for its bibliographic metadata and abstract. Its scope is particularly useful here: it calls fusion and exchange next-generation probes, which cautions against equating early transport signatures with a demonstrated topological qubit.

Milestones in this family include hard induced gaps, parity-sensitive island measurements, and conductance signatures consistent with Majorana phenomenology [4], [5]. Full-shell nanowires provide another route in which magnetic flux and phase winding can be engineered around a semiconductor core [9]. These studies motivate serious platform research. They do not erase material disorder, subgap states, finite-size hybridization, quasiparticle poisoning, imperfect control, or measurement back-action.

### Why local signatures are insufficient

A robust zero-bias conductance peak, a gap closing/reopening, or a field-dependent parity feature can be informative. None alone uniquely identifies a non-Abelian topological mode. Smooth confinement and disorder can yield trivial Andreev bound states with deceptively similar local spectral signatures; Pan and Das Sarma analyze such mechanisms explicitly [6]. This does not imply that all candidate observations are trivial. It establishes a stronger evidentiary rule: an inference to topology must be supported by observables that constrain the competing trivial explanation, ideally through nonlocal correlations, controllable parameter dependence, intentionally trivial controls, and a predeclared decision logic.

The risk is methodological, not rhetorical. If a research program calls every favorable local feature a Majorana, it will select devices by the very signal that a trivial mechanism can imitate. A realization protocol must instead ask what result would *falsify* the claim, what control device should remain trivial, and whether an independently chosen readout tests a distinct consequence of the proposed phase.

### Architectural requirements beyond phase identification

An experimentally compelling topological-qubit primitive requires more than a phase diagram. Aasen *et al.* describe milestones for a Majorana-based qubit, including Majorana-island operations, parity measurements, and measurement-based processing [7]. Karzig *et al.* outline scalable Majorana architectures and make explicit the system requirements that sit between a device-scale signature and protected computation [8]. A 2023 topological-gap protocol demonstrates how a broad conductance map can be used to evaluate a candidate phase region [10]; it is a useful screening protocol, not a stand-alone proof of braiding or logical computation.

Across the sources, five requirements recur:

| Requirement | What it establishes | What it does **not** establish alone |
|---|---|---|
| A reproducible gapped phase region | A candidate physical regime and excitation protection scale | Non-Abelian statistics |
| End-to-end nonlocal correlation | A spatially distributed degree of freedom consistent with encoding | Correct exchange algebra |
| Controlled parity/fusion measurement | An operational measurement primitive | A universal, protected gate set |
| Exchange/braiding protocol with controls | A discriminating test of non-Abelian operation | Scalable logical performance |
| Error/protection scaling versus size, temperature, and time | Whether protection improves a relevant error channel | A full system-level fault-tolerance threshold |

This leads to a central survey conclusion: the field needs an **evidence chain** whose links are independently falsifiable. It should not pursue a single magic diagnostic.

## Subhypotheses and evidence coverage

### SH-1: A clean, gapped topological regime can be identified in a candidate device family

The supporting theory is strong, but any criterion such as $V_Z^2>\mu^2+\Delta^2$ is derived under assumptions about a uniform, effectively one-dimensional model. In a real device, chemical-potential inhomogeneity, disorder, multi-band occupancy, finite-size overlap, and soft-gap behavior change the inference. Evidence must therefore include a phase-sensitive map and held-out device conditions, not a fitted point. **Coverage:** partial-to-strong for candidate identification; insufficient for computation.

### SH-2: The candidate low-energy degree of freedom is nonlocal and not adequately explained by a local trivial state

This is a higher bar. Paired-end correlations, parity constraints, controlled device-length dependence, and intentionally trivial controls can raise or lower the credibility of nonlocality. The competing mechanism must be modeled before inspecting the conclusion. **Coverage:** substantial design need; no single universally decisive measurement supplied by the reviewed sources.

### SH-3: A controlled fusion or exchange operation yields an outcome consistent with non-Abelian algebra

Fusion and exchange are the operation-level tests that connect MZMs to topological computing [2], [3]. But a positive-looking outcome must be compared with a local or classical control pathway that follows the same pulses and readout as closely as possible. The operation should be repeated under reordered paths because non-Abelianity is about order-dependent transformations. **Coverage:** theoretical mechanism well supported; practical demonstration remains a primary research challenge.

### SH-4: The encoded operation is protected in the engineering sense relevant to computation

Protection predicts a relation between error channels and design variables, not merely a favorable fidelity value. A study should quantify error versus separation, thermal exposure, operation time, charge-noise proxy, and poisoning rate, and should separate a claimed topological suppression from ordinary control optimization. **Coverage:** supported as a requirement; platform-specific scaling remains to be measured in any future study.

### SH-5: A route from protected primitives to universal computation is explicit and auditable

The study must state which logical operations are topologically protected, which require a supplemental non-Clifford resource, where its error enters, and what cross-over condition makes the full architecture favorable. **Coverage:** theory supports the distinction; a platform-specific threshold requires a future system model and experiment.

## Research gaps admitted to the ledger

The structured ledger accepts five gaps. `GAP-01` is the lack of a multi-axis realization criterion. `GAP-02` is the ambiguity of local MZM-like signals. `GAP-03` is the missing bridge from a favorable operation to engineered protection. `GAP-04` is the under-specified universality route for Ising/Majorana operations. `GAP-05` is the need to elevate cross-device reproducibility and falsification controls to first-class endpoints.

The survey rejects two shortcuts. A news claim or public announcement is not treated as a proof of a topological computer without a primary record and scrutiny against the evidence chain. And no source supports the simplified proposition that topology removes cooling or error correction: it changes the error model and may reduce overhead, but it does not abolish finite-temperature excitations, readout errors, control faults, or the need for a universal-computation resource.

## Survey conclusion and handoff

Topological quantum computing can be realized in principle, and candidate physical platforms are sufficiently mature to support focused experimental research. It has not been established here as an already realized, general-purpose computing technology. The best next research object is not ``a better zero-bias peak.'' It is a **Braiding-Readiness Evidence Ledger**: a precommitted, multi-axis protocol that accepts a topological-qubit claim only when phase, nonlocality, controlled operation, protection scaling, universality accounting, and falsification controls cohere.

The Survey Agent hands the Idea Agent a constrained brief. All candidates must trace to `GAP-01` through `GAP-05`; must distinguish phase evidence from operation evidence; must include a control that could support the null explanation; must state a route to non-Clifford resources; and must remain a `DESIGN_ONLY` proposal. The accompanying `survey_evidence_plan.json`, `survey_gap_ledger.json`, and `survey_idea_handoff.json` are the canonical structured evidence boundary.

## References

[1] A. Y. Kitaev, ``Fault-tolerant quantum computation by anyons,'' *Annals of Physics*, vol. 303, no. 1, pp. 2-30, 2003, doi: 10.1016/S0003-4916(02)00018-0.

[2] C. Nayak, S. H. Simon, A. Stern, M. Freedman, and S. Das Sarma, ``Non-Abelian anyons and topological quantum computation,'' *Reviews of Modern Physics*, vol. 80, pp. 1083-1159, 2008, doi: 10.1103/RevModPhys.80.1083.

[3] R. M. Lutchyn *et al.*, ``Majorana zero modes in superconductor-semiconductor heterostructures,'' *Nature Reviews Materials*, vol. 3, pp. 52-68, 2018, doi: 10.1038/s41578-018-0003-1.

[4] S. M. Albrecht *et al.*, ``Exponential protection of zero modes in Majorana islands,'' *Nature*, vol. 531, pp. 206-209, 2016, doi: 10.1038/nature17162.

[5] H. Zhang *et al.*, ``Quantized Majorana conductance,'' *Nature*, vol. 556, pp. 74-79, 2018, doi: 10.1038/nature26142.

[6] H. Pan and S. Das Sarma, ``Physical mechanisms for zero-bias conductance peaks in Majorana nanowires,'' *Physical Review Research*, vol. 2, 013377, 2020, doi: 10.1103/PhysRevResearch.2.013377.

[7] D. Aasen *et al.*, ``Milestones toward Majorana-based quantum computing,'' *Physical Review X*, vol. 6, 031016, 2016, doi: 10.1103/PhysRevX.6.031016.

[8] T. Karzig *et al.*, ``Scalable designs for quasiparticle-poisoning-protected topological quantum computation with Majorana zero modes,'' *Physical Review B*, vol. 95, 235305, 2017, doi: 10.1103/PhysRevB.95.235305.

[9] S. Vaitiekenas *et al.*, ``Flux-induced topological superconductivity in full-shell nanowires,'' *Science*, vol. 367, eaav3392, 2020, doi: 10.1126/science.aav3392.

[10] Microsoft Quantum, ``InAs-Al hybrid devices passing the topological gap protocol,'' *Physical Review B*, vol. 107, 245423, 2023, doi: 10.1103/PhysRevB.107.245423.

[11] S. Bravyi, ``Universal quantum computation with ideal Clifford gates and noisy ancillas,'' *Physical Review A*, vol. 71, 022316, 2005, doi: 10.1103/PhysRevA.71.022316.

[12] R. M. Lutchyn, J. D. Sau, and S. Das Sarma, ``Majorana fermions and a topological phase transition in semiconductor-superconductor heterostructures,'' *Physical Review Letters*, vol. 105, 077001, 2010, doi: 10.1103/PhysRevLett.105.077001.

[13] Y. Oreg, G. Refael, and F. von Oppen, ``Helical liquids and Majorana bound states in quantum wires,'' *Physical Review Letters*, vol. 105, 177002, 2010, doi: 10.1103/PhysRevLett.105.177002.
