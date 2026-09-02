# ExperimentDesign Agent: PEC Evaluation Protocol

## Research brief

The selected PEC direction asks whether a declared useful-computation
throughput claim becomes more interpretable and more falsifiable when its
physical and logical constraints are represented as linked cards. This is a
computational/theoretical study design only. It does not run hardware, access
cloud quantum processors, simulate circuits, measure temperature, benchmark a
processor, or report an observed performance result.

## Scope and safety gate

| Field | Design decision |
|---|---|
| Discipline template | computational digital with mathematics theory components |
| Execution policy | DESIGN_ONLY |
| Observed results | [] |
| Digital execution | Future analysis may use independently curated public device specifications and reproducible workload traces after source review. |
| Human review | Required before any hardware, cloud, laboratory, or publication use. |
| Prohibited automated actions | Device control, parameter tuning, cloud-job submission, claims of quantum advantage, and physical thermal testing. |

## Unit of analysis

\[
U=\langle W,\epsilon,\rho,A,\text{transition},\text{signal},
\text{thermal},\text{memory},\text{reliability},\text{I/O}\rangle.
\]

One unit is a declared workload-and-architecture claim, not a processor in the
abstract. The protocol compares a base unit and a candidate unit only when
their output semantics, correctness definition, reliability criterion, and
wall-clock boundaries are compatible.

## Variables and operationalization

| Role | Variable | Operational definition | Required evidence |
|---|---|---|---|
| Independent | Architecture class | CMOS/accelerator, reversible proposal, superconducting/ion/neutral-atom/photonic quantum architecture, or clearly documented hybrid. | Primary technical source and version. |
| Independent | Workload class | Arithmetic, memory-bound kernel, optimization, simulation, or random-sampling task; input distribution and output form named. | Workload specification. |
| Mediator | Transition time | Physical gate, switching, or state-evolution time with control assumptions. | Device/control documentation and applicability note. |
| Mediator | Signal latency | Longest declared critical communication path and signal-velocity model. | Topology and path evidence. |
| Mediator | Thermal boundary | Temperature, power/heat-extraction limit, and which erasures or dissipative operations are counted. | Package/cooling boundary or explicit unknown. |
| Mediator | Logical overhead | Physical-to-logical qubit/bit ratio, cycle count, decoding, retry, and postselection cost. | Error model and code/algorithm source. |
| Dependent | Useful throughput | Accepted output instances divided by declared end-to-end wall-clock time. | Correctness and reliability acceptance rule. |
| Control | I/O boundary | Initialization, data loading, readout, verification, and classical control included or excluded. | Boundary statement. |

## Formal reasoning obligations

For each unit, the proposer must supply the following non-optional
obligations:

1. **Transition obligation.** State whether a quantum-speed-limit,
   technology-specific switching model, or neither is applicable. For an ideal
   orthogonal quantum-state transition, retain both Mandelstam-Tamm and
   Margolus-Levitin assumptions:

   \[
   \tau_{\mathrm{QSL}}\geq
   \max\left\{\frac{\pi\hbar}{2\Delta E},
   \frac{\pi\hbar}{2(E-E_0)}\right\}.
   \]

2. **Transport obligation.** For a critical information path of length \(L\),
   disclose \(\tau_{\mathrm{signal}}\geq L/v_{\mathrm{sig}}\), the medium, the
   topology, serialization, and any classical-controller path.

3. **Thermodynamic obligation.** If \(n_{\mathrm{erase}}\) logically
   irreversible bits are erased at temperature \(T\), declare the ideal floor
   \(Q_{\mathrm{erase}}\geq n_{\mathrm{erase}}k_{\mathrm{B}}T\ln2\), then
   separately report finite-time and package-level losses rather than
   substituting the floor for realized dissipation.

4. **Reliability obligation.** Map every reported physical operation to
   logical operations, error-correction cycles, decoding, retries,
   postselection, and probability of accepted output.

5. **End-to-end obligation.** Identify all excluded stages. A claim cannot
   call itself useful throughput if input preparation, readout, verification,
   or classical postprocessing is silently omitted.

## PEC cards and decision rule

Each unit receives six cards: TRANSITION, SIGNAL, THERMAL_MEMORY,
RELIABILITY, IO_VERIFICATION, and WORKLOAD_SEMANTICS. A card is marked
SUPPORTED, INAPPLICABLE_WITH_RATIONALE, UNKNOWN, or CONTRADICTED.

The protocol permits no scalar readiness score. It returns one of the
following conditional statuses:

| Status | Meaning | Required action |
|---|---|---|
| CONTRACT_EVALUABLE | All card fields and exclusions are explicit. | Permit specialist review, not a performance conclusion. |
| BOUND_SUPPORTED_IN_SCOPE | Future evidence supports the stated envelope for the named unit. | Preserve scope; do not extrapolate across workloads or architectures. |
| RELIABILITY_ACCOUNT_INCOMPLETE | Logical cost, error model, or accepted-output rule is missing. | Hold the throughput claim. |
| THERMAL_OR_IO_BOUNDARY_MISSING | Dissipation, cooling, preparation, readout, or verification is undeclared. | Narrow or redesign the claim. |
| QUANTUM_ADVANTAGE_OVERGENERALIZED | A task-specific demonstration is asserted as a general processor rate. | Separate the task, classical comparator, and utility claim. |
| INCONCLUSIVE | Available evidence cannot discriminate the envelope. | Report no upper-limit direction. |

## Future validation matrix

The following is a plan, not performed work.

| Future evidence modality | Can test | Cannot establish alone |
|---|---|---|
| Published device specification review | Whether the disclosed transition, topology, and environment fields are populated. | A verified end-to-end useful rate. |
| Controlled benchmark on a fixed workload | Bounded performance under a documented correctness and I/O boundary. | A universal physical ceiling. |
| Error-correction resource analysis | Physical-to-logical space-time overhead under an explicit noise model. | Actual hardware fidelity under a different model. |
| Thermal/packaging assessment | Compatibility of a named power and cooling boundary. | The minimum thermodynamic cost of all computation. |
| Independent replication | Whether a scoped result transfers under the same contract. | Transfer to an unlisted architecture, workload, or scale. |

## Counterexamples and robustness checks

The protocol must actively seek counterexamples: a reversible workload with
few erasures; a communication-dominated distributed system; a
memory-dominated conventional workload; a quantum sampling task whose
classical comparator improves; and a fault-tolerant architecture that trades
more physical qubits for less time. If a term is inapplicable, it must be
flagged rather than numerically forced. Sensitivity analysis must vary energy,
temperature, path length, error rate, code distance, readout time, and
acceptance probability within source-supported intervals.

## Human review requirements

Qualified device physicists, computer architects, quantum-information
specialists, thermal engineers, and reproducibility reviewers must verify
source applicability, assumptions, parameter units, algorithmic complexity
claims, error models, and all experimental or cloud-execution decisions.
