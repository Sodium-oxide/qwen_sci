# Survey Agent Report: Can DNA Act as an Information Storage Medium?

## Research framing

**Question.** Can synthetic DNA serve as a practical information-storage medium rather than merely a molecular demonstration of binary encoding?

**Operational reformulation.** Under a declared archive lifetime, retrieval pattern, file-integrity requirement, and cost/latency boundary, can an in-vitro DNA archive preserve and selectively recover digital payloads with an end-to-end recovery guarantee that conventional archival media cannot match?

The answer is already **yes at the medium level**: arbitrary digital information has been encoded into DNA and read back with sequencing. Church, Gao, and Kosuri stored a 5.27-megabit book in DNA and recovered it by next-generation sequencing [S1]. Subsequent work demonstrated scalable random access, rewritability, fountain-code recovery, large-scale pools, error-aware reconstruction, and stability-aware storage [S3--S12]. The unresolved research question is therefore not whether A/C/G/T can represent bits. It is whether a DNA system can offer a defensible archive service: economical writing, auditable integrity, selective access, and reliable recovery after realistic storage and handling.

## Evidence map

### What is established

1. **Representation and density.** DNA's four-base alphabet can encode arbitrary digital data. Sequence constraints, index overhead, and redundancy lower usable density relative to a purely symbolic two-bits-per-nucleotide maximum, so reported molecular density must be separated from usable system density [S1, S2, S9].
2. **End-to-end demonstrations exist.** DNA synthesis writes oligonucleotide pools; storage preserves the pool; sequencing produces noisy, uneven reads; decoding reconstructs payloads. Church et al. established this pipeline [S1], and Bornholt et al. presented an archival-system architecture [S3].
3. **Error correction is central, not optional.** Synthesis and sequencing create substitutions, insertions, deletions, strand dropouts, and coverage skew. Channel characterization and coding schemes demonstrate that recovery can be made robust when these errors are modeled and redundancy is allocated deliberately [S4, S6, S7, S11].
4. **Selective retrieval has progressed.** PCR-addressed and compartmentalized approaches show random or multiplexed access is technically feasible, while also exposing index overhead, amplification bias, crosstalk, and repeated-access limits [S5, S10, S15].
5. **Durability depends on physical form and handling.** DNA's longevity is not a universal property of every sample. Temperature, water activity, oxidation, encapsulation, and repeated processing affect molecular preservation and must be included in the archive contract [S8].
6. **The main bottleneck is systems economics.** Current synthesis remains slow and expensive relative to electronic storage; sequencing, preparation, and decoding also influence access latency and operating cost [S7, S9, S12--S14].

### Evidence boundaries

- A proof that a file was stored in a small DNA pool does not establish low cost, petabyte-scale capacity, or repeated random access.
- High theoretical density does not equal net archive density after addressing, constraints, redundancy, physical packaging, and retained metadata.
- A successful decode under one synthesis/sequencing pipeline does not prove portability across vendors, storage environments, or error distributions.
- DNA storage is best aligned with cold, high-value, infrequently accessed archives; this survey does not treat it as a replacement for RAM, SSDs, or interactive databases.

## Subhypotheses and evidence coverage

| ID | Subhypothesis | Evidence status | Primary anchors |
|---|---|---|---|
| SH-1 | DNA can losslessly represent arbitrary digital payloads in an in-vitro archive workflow. | Directly supported | S1--S5 |
| SH-2 | Constrained coding plus redundancy can tolerate realistic molecular-channel errors. | Directly supported, but channel-dependent | S4, S6, S7, S11 |
| SH-3 | Selective access can be made repeatable without decoding an entire archive. | Supported but scale/handling limited | S5, S10, S15 |
| SH-4 | DNA offers a credible preservation advantage only under a stated physical-storage regime. | Supported, boundary-sensitive | S8, S9 |
| SH-5 | Writing, reading, and recovery can become a practical archival service rather than isolated demonstrations. | Open | S7, S9, S12--S14 |

## Gap ledger

### GAP-SERVICE-001: no common end-to-end service metric

The literature reports density, write cost, read coverage, recovery success, or access demonstrations in different combinations. There is no generally adopted contract that jointly declares payload size, redundancy, physical condition, selective-access burden, recovery probability, latency, and cost. This makes apparently successful systems difficult to compare.

### GAP-CHANNEL-002: code selection is insufficiently coupled to storage condition

Codes are usually evaluated against an assumed synthesis/sequencing channel. Physical aging, packaging, repeated access, and coverage skew can change that channel. A design needs a declared degradation-and-retrieval budget before selecting redundancy.

### GAP-ACCESS-003: random access remains a system property

Addressing sequences enable selection, but repeated retrieval may introduce amplification bias, crosstalk, and read-depth demands. A useful archive must report the cost and error consequences of *selective* recovery, not only whole-pool decoding.

### GAP-PORTABILITY-004: recovery claims lack transfer criteria

Vendor, synthesis chemistry, library preparation, sequencer, and decoder choices can be tightly coupled. The field needs a portable archive packet that records encoding, constraints, index namespace, checksum, and decoder version sufficiently for future recovery.

### GAP-ECONOMICS-005: theoretical density is routinely disconnected from usable density

Addressing, error correction, constraints, retained metadata, and physical packaging consume resources. Archive decisions require net usable density and accepted-recovery cost rather than an ideal molecular figure alone.

## Survey conclusion and handoff

DNA can act as an information-storage medium. Its scientifically valuable frontier is the transition from **molecular encoding** to **recoverable archival service**. The Idea Agent should prioritize a design that makes successful retrieval conditional on an explicit, portable contract rather than on a single high-density or one-time-decode result.

## Verified source register

- **S1** G. M. Church, Y. Gao, and S. Kosuri, “Next-Generation Digital Information Storage in DNA,” *Science*, 2012, doi:10.1126/science.1226355. Browser-verified at the publisher DOI page: title, authors, journal, date, DOI, and abstract.
- **S2** N. Goldman *et al.*, “Towards practical, high-capacity, low-maintenance information storage in synthesized DNA,” *Nature*, 2013, doi:10.1038/nature11875.
- **S3** S. Bornholt *et al.*, “A DNA-Based Archival Storage System,” *ASPLOS*, 2016, doi:10.1145/2872397.2872407.
- **S4** Y. Erlich and D. Zielinski, “DNA Fountain enables a robust and efficient storage architecture,” *Science*, 2017, doi:10.1126/science.aaj2038.
- **S5** C. E. Organick *et al.*, “Random access in large-scale DNA data storage,” *Nature Biotechnology*, 2018, doi:10.1038/nbt.4079.
- **S6** R. Heckel, G. Mikutis, and R. N. Grass, “A characterization of the DNA data storage channel,” *Scientific Reports*, 2019, doi:10.1038/s41598-019-45832-6.
- **S7** P. L. Antkowiak *et al.*, “Low cost DNA data storage using photolithographic synthesis and advanced information reconstruction and error correction,” *Nature Communications*, 2020, doi:10.1038/s41467-020-19148-3.
- **S8** K. R. Matange, J. Tuck, and A. J. Keung, “DNA stability: a central design consideration for DNA data storage systems,” *Nature Communications*, 2021, doi:10.1038/s41467-021-21587-5.
- **S9** A. Doricchi *et al.*, “Emerging Approaches to DNA Data Storage: Challenges and Prospects,” *ACS Nano*, 2022, doi:10.1021/acsnano.2c06748.
- **S10** B. W. A. Bögels *et al.*, “DNA storage in thermoresponsive microcapsules for repeated random multiplexed data access,” *Nature Nanotechnology*, 2023, doi:10.1038/s41565-023-01377-4.
- **S11** M. Welzel *et al.*, “DNA-Aeon provides flexible arithmetic coding for constraint adherence and error correction in DNA storage,” *Nature Communications*, 2023, doi:10.1038/s41467-023-36297-3.
- **S12** M. Yu *et al.*, “High-throughput DNA synthesis for data storage,” *Chemical Society Reviews*, 2024, doi:10.1039/d3cs00469d.
- **S13** M. H. Raza *et al.*, “An outlook on the current challenges and opportunities in DNA data storage,” *Biotechnology Advances*, 2023, doi:10.1016/j.biotechadv.2023.108155.
- **S14** A. Sensintaffar *et al.*, “Advancing Archival Data Storage: The Promises and Challenges of DNA Storage System,” *ACM Transactions on Storage*, 2025, doi:10.1145/3723166.
- **S15** S. M. H. T. Yazdi *et al.*, “A Rewritable, Random-Access DNA-Based Storage System,” *Scientific Reports*, 2015, doi:10.1038/srep14138.

**Human source review note.** DOI/publisher-page verification of applicability remains required for every source before a real wet-lab study or scholarly submission. The source register supports this proposal; it does not replace expert full-text review.
