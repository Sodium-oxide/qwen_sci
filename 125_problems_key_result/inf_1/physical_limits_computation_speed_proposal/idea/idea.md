# Idea Agent Portfolio: Physical Compute-Envelope Contracts

## Incoming evidence constraints

The Survey Agent accepts five linked gaps: incompatible speed denominators,
non-composed physical bounds, missing physical-to-logical overhead accounting,
overgeneralized quantum advantage, and weak thermal linkage. The idea search
must preserve those identifiers and must not transform a device-transition
bound into a universal upper speed.

## Candidate routes

| Candidate | Innovation operation | Strength | Rejection or limitation |
|---|---|---|---|
| Clock Race | Compare maximum device frequencies across technologies. | Simple, familiar metric. | Rejected: clock frequency ignores useful work, communication, reliability, and energy. |
| Energy-only Ceiling | Use energy-time or Margolus-Levitin reasoning as one upper number. | Has a fundamental physics anchor. | Rejected: energy alone does not identify information density, communication, I/O, or logical overhead. |
| Quantum Escape Narrative | Treat qubits and sampling demonstrations as removing silicon limits. | Captures an important architectural transition. | Rejected: violates the Survey invariant that advantage is workload-specific and physically embodied. |
| Compute-Envelope Contract | Require a layered resource envelope for each useful throughput claim. | Composes physics, architecture, reliability, and algorithmic semantics. | Selected primary direction. |
| Fault-Tolerance-only Score | Normalize physical gate rates by an error-correction multiplier. | Addresses a real missing denominator. | Competitive: insufficient without thermal, communication, and workload cards. |

## Selected primary idea: PEC

**Physical Compute-Envelope Contract (PEC).** A proposed upper-limit statement
is not a scalar. It is a reproducible contract:

\[
\mathcal{C}=\langle W,\epsilon,\rho,A,E,T,L,\mathcal{N},
\mathcal{H},\mathcal{M},\mathcal{I}\rangle,
\]

where \(W\) is the workload and output representation, \(\epsilon\) an
accuracy or distributional error target, \(\rho\) a reliability target, \(A\)
the physical and algorithmic architecture, \(E\) the accessible energy
resource, \(T\) the thermal boundary, \(L\) the physical extent,
\(\mathcal{N}\) the communication topology, \(\mathcal{H}\) the heat-removal
boundary, \(\mathcal{M}\) the memory/information-density description, and
\(\mathcal{I}\) the I/O and observation boundary.

For one contract, define useful throughput as

\[
R_{\mathrm{useful}} = \frac{\text{accepted workload instances}}{
\text{end-to-end wall-clock time}},
\]

or another explicitly declared denominator. The proposal then maps resource
cards to an envelope:

\[
R_{\mathrm{useful}} \leq
\min \{R_{\mathrm{transition}}, R_{\mathrm{signal}}, R_{\mathrm{thermal}},
R_{\mathrm{memory}}, R_{\mathrm{reliable}}, R_{\mathrm{I/O}}\}.
\]

This is a claim-accounting framework, not an assertion that these six terms
form a universal tight theorem. Each term has an applicability condition and
an evidence type.

### Central hypothesis

For a fixed workload and validity domain, a PEC that requires each speed
claim to close its transition, communication, thermodynamic/thermal,
information-density, logical-reliability, and I/O cards will discriminate
unsupported speedup claims more reliably than device clock rate, transistor
count, physical gate rate, or a single sampling benchmark alone.

### Falsifiers

The idea fails if a pre-registered workload comparison finds that:

1. a complete PEC card set cannot distinguish a physically unsupported claim
   from a supported one;
2. one mandatory card adds no explanatory or decision value across the stated
   workload family;
3. a claimed limiting term is not applicable under its declared assumptions;
4. an independently verified logical throughput exceeds the documented
   envelope without an identified accounting error or changed contract; or
5. the protocol cannot represent a valid quantum advantage demonstration
   without treating it as universal-purpose speed.

## MCTS-style evolution trace

1. **Root: Will atoms end computing speed?** Defect: conflates integration
   density with end-to-end computation.
2. **Branch: energy-based physical limit.** Defect: leaves spatial extent,
   signal propagation, and logical fidelity unrepresented.
3. **Branch: quantum speed advantage.** Defect: treats state-evolution speed
   and algorithmic advantage as an all-workload processor rate.
4. **Bridge: physical-to-logical resource ledger.** Defect: still lacks a
   stable workload/output denominator.
5. **Selected PEC.** Adds a contract, a claim-to-card map, disallowed
   inferences, and conditional decision statuses.

## Portfolio decision

PEC is selected because it is directly aligned to GAP-SCOPE-001,
GAP-COMPOSE-002, GAP-LOGICAL-003, GAP-ADVANTAGE-004, and GAP-THERMAL-005; it
has measurable falsifiers; and it can be translated into a
computational/theoretical design without running a device, simulation, or
benchmark. The Fault-Tolerance-only Score is retained as a competitive
submetric within the reliability card.
