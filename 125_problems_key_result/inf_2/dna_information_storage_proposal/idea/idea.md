# Idea Agent Report: DNA Storage Serviceability Envelope

## Candidate synthesis

The Survey handoff rejects the shallow framing “DNA is dense, therefore it is a storage medium.” The research opportunity is to make a DNA archive **serviceable**: a future user must identify the file, choose it without decoding unrelated files, know the storage context, acquire sufficient reads, apply the intended decoder, and verify an exact payload match.

### Selected primary idea: DNA Storage Serviceability Envelope (DSE)

The DSE is an archive-packet and evaluation contract. Every stored payload is coupled to portable metadata that declares: encoding family, sequence constraints, index namespace, redundancy allocation, checksum/hash, expected error channel, physical storage condition, access method, decoder version, and acceptance threshold. A DNA archive is counted as successful only if it satisfies all declared acceptance conditions.

**Research object.** `payload x coding scheme x error channel x storage condition x access pattern x read budget x recovery rule`.

**Central hypothesis.** A DSE-guided packet that allocates redundancy jointly across strand loss, indels/substitutions, selective-access bias, and storage-condition uncertainty will produce a more interpretable and portable accepted-recovery profile than a density-optimized code assessed only by one whole-pool decode.

**Mechanism.** The packet turns hidden coupling into explicit budgets. Coding metadata informs constraint-aware synthesis and decoding; a retrieval budget specifies reads and access rounds; a stability budget bounds stored-state uncertainty; the integrity rule converts assembled reads into an accepted or rejected payload rather than a subjective “mostly recovered” result.

**Falsifiers.** The direction fails if a DSE adds no predictive value for accepted recovery, if condition-aware allocation cannot outperform or match a density-only baseline under predefined channels, if selective recovery cannot be separated from whole-pool recovery, or if portable metadata cannot reproduce decoding across an independent software environment.

## Portfolio decision

| Portfolio item | Decision | Reason |
|---|---|---|
| DSE archive packet | Selected primary | Directly addresses all five accepted Survey gaps and yields a testable design. |
| Ultra-dense unconstrained code | Competitive | Valuable density benchmark, but insufficient for physical and access reliability. |
| Microcapsule-only random access | Competitive | Strong access strategy, but it cannot alone solve coding portability or economics. |
| One universal DNA-storage score | High risk | Attractive for comparison, but risks hiding archive-use assumptions behind one number. |
| “DNA will replace cloud storage” | Rejected | Violates current latency and cost evidence and lacks a declared workload. |
| Living-cell memory | Rejected | Outside the safe in-vitro archive scope. |

## MCTS-style evolution trace

1. **Root: density-first framing.** Defect: raw nucleotides per gram ignore recovery and addressing. Change: define net accepted information density.
2. **Channel branch.** Defect: coding is chosen before the physical error model. Change: introduce degradation and retrieval budgets.
3. **Access branch.** Defect: whole-pool decoding is mislabeled as random access. Change: require a selective-access acceptance path.
4. **Portability branch.** Defect: future decoding depends on undocumented software and sequence constraints. Change: add the portable archive packet.
5. **Selected node.** Defect: a single number can conceal tradeoffs. Change: retain a multidimensional DSE profile and pre-register conditional decisions.

## Primary-direction handoff

The ExperimentDesign Agent should compare a DSE-guided code with a constrained baseline and a fountain-style benchmark, include both virtual molecular-channel stress tests and a future, noncoding synthetic-oligo validation path, and judge success by exact payload acceptance under predeclared budgets. The proposal must remain `DESIGN_ONLY`; it must not claim that any pool has been ordered, synthesized, stored, sequenced, or decoded.
