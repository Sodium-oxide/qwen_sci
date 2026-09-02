# ExperimentDesign Agent: DSE Validation Protocol

## Research brief

**Selected direction:** DNA Storage Serviceability Envelope (DSE), `idea-dse-001`.

**Central question:** Does a condition-aware, portable archive packet improve the decision-quality and accepted selective-recovery profile of a DNA archive relative to density-only baselines?

**Execution status:** `DESIGN_ONLY`. This document is a future-study design. It reports no ordered oligonucleotides, physical pools, sequencing, simulations, measurements, or observed results.

## Scope and safety gate

The proposed material is restricted to short, synthetic, noncoding, non-expressive DNA oligonucleotides generated from benign digital payloads. It excludes living cells, pathogens, viral vectors, gene editing, human samples, animal samples, clinical material, and environmental release. Future wet-lab work requires an institutional biosafety and procurement review, but the design itself is a low-risk in-vitro archival study.

## Design architecture

### Archive packet

Each file produces a manifest with (i) payload identifier and cryptographic checksum, (ii) coding and redundancy configuration, (iii) GC/homopolymer and forbidden-motif constraints, (iv) strand/index namespace, (v) declared molecular-channel and storage-condition assumptions, (vi) selective-access method, (vii) read and access-round budget, (viii) decoder version and deterministic parameters, and (ix) exact acceptance rule.

### Study arms

| Arm | Purpose | Coding/access profile |
|---|---|---|
| A: constrained baseline | Establish a transparent reference. | Indexed constrained mapping plus block error correction. |
| B: fountain benchmark | Test robust strand-loss recovery. | Fountain-style droplets with constraints and portable manifest. |
| C: DSE-guided packet | Test the selected idea. | Condition-aware redundancy split, access budget, manifest, and exact acceptance policy. |

### Units and factors

- **Digital payload units:** text, image, executable-independent binary, tabular, and mixed-format cold-data files; all files are fixed before future execution.
- **Molecular units:** uniquely indexed synthetic noncoding oligonucleotide strands; a qualified facility would manufacture a future pool only after review.
- **Primary factors:** coding arm; nominal storage condition; injected/observed channel class; strand dropout; substitution/indel burden; read coverage; access round.
- **Controls:** common payload suite, matched target net payload, common sequence constraints, blinded decoder labels, known checksum, no-template process control, and no-DNA negative control for future assays.

## Measurements and acceptance rule

The primary endpoint is **accepted selective recovery**: the requested file is selected under its declared access route, decoded within the declared read/access budget, and matches its pre-registered checksum exactly. Secondary endpoints are net accepted density, read budget, estimated write/read cost, latency, dropout tolerance, failure localization, and cross-environment decoder reproducibility.

For a file $f$, the planning metric is

`D_net(f) = useful_payload_bits(f) / nucleotides_committed_to_accepted_recovery(f)`.

The DSE does not turn this into a universal scalar. A planned archive is admissible only when all four gates hold: integrity, selectivity, condition coverage, and portable decoder reproduction.

## Analysis plan

1. Freeze payloads, coding parameters, manifests, acceptance thresholds, and analysis code before any future synthesis or simulation.
2. Use synthetic channel traces for planning sensitivity analysis; label all outputs as simulated if executed in a later study.
3. If a future oligo pool is produced, expose matched aliquots to predeclared dry-storage regimes and retain a time-zero reference. Do not extrapolate from short tests to century-scale claims.
4. Sequence with predeclared coverage tiers. Report strand counts, quality filtering, index conflicts, recovered file counts, checksums, and failures rather than only the best successful run.
5. Fit a mixed-effects or Bayesian hierarchical model for accepted recovery with coding arm, channel terms, coverage, and access round as effects. Report uncertainty intervals and preregistered contrasts.
6. Reproduce decoding in an independently configured software environment using only the archive packet and raw reads. A recovery that requires undocumented local state fails portability.

## Decision table

| Future outcome | Interpretation | Next action |
|---|---|---|
| C matches/exceeds A and B on accepted selective recovery at comparable net density | Supports DSE as a useful archive contract. | Expand payload and condition diversity. |
| C improves recovery but costs materially more | DSE may be suitable only for high-value cold archives. | Optimize redundancy allocation and cost boundary. |
| C is no better than B | The contract may improve reporting without improving recovery. | Separate reporting benefit from code benefit. |
| Cross-environment decode fails | Portable manifest is incomplete. | Revise manifest schema and versioning. |
| Selective access causes systematic failures | Access layer is the bottleneck. | Redesign index/access strategy before density optimization. |

## Human review requirements

Confirm future sequence-screening policy, commercial synthesis/sequencing capabilities, data-handling policy, laboratory containment and waste procedures, long-term stability interpretation, and all source-paper applicability. No automatic hardware, cloud, laboratory, or procurement action is authorized by this proposal.
