# Programming Matter into Engineered Living Materials

## A Survey of Genetic Control, Living–Nonliving Assembly, and Bioelectronic Function

### Abstract

Engineered living materials (ELMs) seek to make material state, structure, and function responsive to biological programs rather than fixed at fabrication. The project context supplied with this survey frames the problem as programming matter through synthetic biology, genomic engineering, and living–nonliving self-assembly, with electrically conductive biofilms, cell-based catalysis, and living photovoltaics as target classes. This survey reviews the resulting design space through four coupled layers: genetic programs, cellular production and regulation, extracellular or hybrid material assembly, and device-scale interfaces. Literature retrieved from OpenAlex and AnySearch was used for discovery; the core bibliography contains records returned by both sources whenever possible, with additional OpenAlex records marked as single-source discovery evidence. The literature shows that programmable protein secretion and biofilm matrices can form multiscale materials; genetically programmed cells can be incorporated into printable microbial inks; and living photovoltaic systems can improve output by manipulating either biological electron-export pathways or the cell–electrode interface. However, a dependable mapping from a genetic design to a material property remains incomplete. The central challenge is therefore not only to encode a desired function, but to measure, model, and maintain the coupling from program to cell state, matrix architecture, interface transport, and long-term material performance. The survey concludes with a design-and-evaluation framework and a set of open problems for reproducible, scalable, and safe ELMs.

**Keywords:** engineered living materials; synthetic biology; biofilms; self-assembly; living photovoltaics; bioelectronics; genetic programming; hybrid materials.

---

## 1. Scope and evidence basis

The supplied `project_context.json` identifies the research object as **Engineered Living Materials and Programmable Biological Systems**. Its intended outcomes are electrically conductive biofilms, single-cell living catalysts for polymerization, and living photovoltaics. The context also correctly emphasizes two interacting disciplinary anchors: materials/biomaterials and genetics/genomics. It explicitly excludes agricultural, crop-science, veterinary, clinical-therapeutic, and pharmaceutical-formulation interpretations as primary scope.

This survey treats an ELM as a system in which living cells are integral to material production, maintenance, sensing, actuation, or adaptation. This definition distinguishes ELMs from conventional biomaterials that contain only inactive biological constituents, and from ordinary microbial cultures that do not create or regulate a material-level function. Foundational reviews describe ELMs as systems that can use biological production and self-organization to assemble materials with designed physicochemical or mechanical properties [1–3]; a sustainability-oriented review surveys how these principles may support energy, remediation, health, and smart-material applications [15], while recent work develops the related concept of engineered living carbon materials [16].

The attached `sh_graph_provenance.json` is used as a *retrieval and scoping artifact*, not as independent proof of the scientific claims below. It identifies conductive biofilms, semi-artificial photosynthesis, and biophotovoltaics as important evidence lanes. During this survey, focused searches were performed for (i) ELMs and self-assembly, (ii) genetically programmable living materials, (iii) conductive biofilms and living photovoltaics, (iv) cell-associated catalysis and polymerization, and (v) cyanobacterial electron transfer. The literature results show that the first, second, third, and fifth lanes have direct core evidence. By contrast, the literal query for “single-cell living catalysts polymerization” retrieved mostly generic polymerization and nonliving single-site catalyst papers; that application should be treated as a research target requiring more focused evidence, not as an established ELM capability established by the present search.

## 2. What it means to program matter

Programming matter in this context is a multilevel control problem. A useful decomposition is:

1. **Information layer:** DNA sequence, regulatory circuit, synthetic receptor, or other inheritable instruction determines what molecular components a cell can produce and when it produces them.
2. **Cell-state layer:** metabolism, growth, secretion, adhesion, stress response, and cell–cell communication determine whether the instruction is expressed in the intended physiological regime.
3. **Assembly layer:** secreted proteins, extracellular polymeric substances, inorganic particles, polymers, or other building blocks organize into a matrix, composite, or hierarchical structure.
4. **Interface/device layer:** transport of electrons, metabolites, photons, forces, or signals across material boundaries determines the externally measured function.
5. **Feedback layer:** measurements of viability, architecture, output, and drift are used to adjust the biological program, process condition, or interface design.

This decomposition prevents a common overclaim: an engineered gene circuit alone does not establish a programmable material. The material-level claim requires evidence that the molecular program is coupled to a reproducible structure and an appropriate functional readout. The ELM literature places synthetic biology and materials design in mutual dependence: biology supplies growth, sensing, self-repair, and molecular synthesis, while materials engineering supplies architecture, mechanics, interfaces, and manufacturing constraints [1–3].

## 3. Genetic programs as material programs

### 3.1 Biofilms and extracellular matrices

Microbial biofilms are a particularly useful starting point because cells naturally produce and inhabit extracellular matrices. These matrices can be repurposed as programmable construction media rather than treated only as biological fouling layers. Chen *et al.* demonstrated that engineered cells can synthesize and pattern tunable multiscale materials, providing an early example of linking cellular programming to a material architecture [4]. Huang *et al.* subsequently reported programmable and printable *Bacillus subtilis* biofilms as ELMs, showing that biofilm production can support both functional programming and fabrication-oriented handling [5].

These studies support a key design principle: genetic programming should target not just an intracellular phenotype but a material-relevant intermediate—such as secretion, adhesion, extracellular fiber formation, mineralization, or matrix composition. The attached provenance record for “Engineered living conductive biofilms as functional materials” likewise places conductivity and material function in this matrix-engineering lane. However, the provenance annotations alone do not provide all necessary quantitative details, such as controls, conductivity measurement conditions, or durability windows; those elements must be verified from the underlying publication before supporting a narrow performance claim.

### 3.2 Hierarchical assembly and printable living materials

Duraj-Thatte *et al.* provide a clear multiscale example. Their microbial ink is produced from genetically engineered cells whose protein monomers assemble into nanofibers and then into networks forming an extrudable hydrogel; programmed *E. coli* cells can be embedded to add functional behavior [6]. This matters because it links a molecularly encoded component to a sequence of assembly transitions that can be processed by three-dimensional printing. The study is not merely a demonstration of cell encapsulation: its central contribution is that the cellular product itself forms much of the printable material.

Synthetic cell–cell signaling offers a complementary route to material architecture. Toda *et al.* engineered synthetic contact-dependent signaling programs that altered cadherin-mediated adhesion and produced self-organizing multicellular structures with features including patterned assembly and regeneration after injury [7]. Although this work is closer to tissue-like organization than to a microbial composite, it establishes the principle that a signal program can drive iterative spatial reorganization. In ELM design, this suggests that temporal control and local communication can be used to program where material is deposited or where function is activated.

### 3.3 Beyond extracellular matrices: genetically targeted chemical assembly

The programming boundary can also be moved inside living systems. Liu *et al.* combined engineered enzyme targeting with polymer chemistry to instruct defined neurons to guide assembly of conductive or insulating polymers at the plasma membrane [8]. This is a distinct strategy from matrix secretion: the biological program specifies where chemical synthesis occurs, while the polymer chemistry supplies a material function. It expands the ELM concept from “cells make a matrix” to “cells specify the site of material construction.”

The implication for living materials is broad but must be phrased carefully. This result demonstrates cell-type-targeted chemical assembly in a particular biological setting; it does not by itself establish scalable manufacturing of autonomous ELMs. Its value for this survey is as a proof of principle that genetic addressability can determine material location and electrical function in a living system.

## 4. Living–nonliving assembly and the interface problem

The most difficult ELM functions often arise at a living–nonliving interface. Such interfaces must preserve cell viability and biological activity while supporting transport, mechanical stability, and device integration. Liu *et al.* argue that synthetic biology and biomaterials have historically progressed largely in parallel, and propose their integration as a route to hierarchically structured materials that sense and respond through interactions between cells and their matrices [3].

An interface should therefore be designed as an active component rather than a passive scaffold. A practical design specification includes at least:

| Interface function | Biological requirement | Material/device requirement | Representative readout |
|---|---|---|---|
| Cell retention | Viability, attachment, nutrient access | Stable porosity and adhesion | Live/dead fraction; retained biomass |
| Molecular exchange | Secretion and diffusion without toxic accumulation | Controlled permeability | Production flux; concentration profiles |
| Mechanical coupling | Survival under processing and loading | Modulus, toughness, shape fidelity | Rheology; compression/cycling stability |
| Electrical coupling | Electron export or electrochemical activity | Low-resistance charge collection | Current density; impedance; stability |
| Optical coupling | Photosynthetic activity under illumination | Light access and electrode geometry | Oxygen evolution; photocurrent |

This interface view explains why self-assembly is not sufficient by itself. A construct can exhibit attractive nanoscale assembly yet fail as an ELM if cells cannot remain active, if the interface blocks transport, or if the architecture cannot be fabricated reproducibly. Consequently, the appropriate unit of design is the **program–cell–matrix–interface system**, not an isolated genetic cassette or isolated scaffold.

## 5. Bioelectronic living materials: conductive biofilms and living photovoltaics

### 5.1 Why electron transfer is a central bottleneck

Conductive biofilms and living photovoltaics place a measurable material function—electron transport—at the center of the design problem. In biophotovoltaics, photosynthetic organisms harvest light but their connection to an electrode is limited by membrane barriers, endogenous electron-transfer pathways, and interfacial contact. Schuergers *et al.* review a synthetic-biology route to engineering living photovoltaics: introducing or improving protein-based extracellular electron-transfer routes in photosynthetic hosts could complement purely abiotic electrode optimization [9].

Two related conclusions follow. First, improving an electrode alone may not solve a biological export bottleneck. Second, a genetically changed microorganism alone may not improve device output if the surrounding interface does not collect the exported charge. Thus, the appropriate causal hypothesis is not “genetic engineering improves photocurrent” in general, but “a specified biological change and a compatible interfacial architecture jointly improve an explicitly defined charge-transfer readout under stated conditions.”

### 5.2 Directly observed biophotovoltaic functions

Saper *et al.* showed that live cyanobacteria can generate stable photocurrent and support downstream hydrogen evolution in a bio-photoelectrochemical configuration after a gentle treatment enabling electron transfer to a graphite electrode [10]. Zhu *et al.* then demonstrated a two-species biophotovoltaic system in which cyanobacteria and an exoelectrogenic *Shewanella* population constrain electron flow through a mediator-linked consortium; the reported setup was designed for durable operation and improved power output [11]. These examples illustrate two different interventions: improving access to endogenous photosynthetic/respiratory electron flows, and allocating distinct biological roles across a consortium.

Reggente *et al.* studied an explicitly engineered living-photovoltaic interface. A polydopamine nanoparticle shell was assembled on *Synechocystis* cells to improve adhesion and charge extraction; the work reports sustained growth under tested conditions and a three-fold photocurrent enhancement relative to non-coated cells at the stated applied bias [12]. This is strong evidence that non-genetic surface engineering can improve a bioelectronic readout, but it does not remove the need to characterize longer-term stability, energy efficiency, and generality across host organisms.

More recent literature illustrates a complementary material strategy: three-dimensional conductive conjugated-polyelectrolyte gels can form cyanobacteria-containing biocomposites that improve interfacial electron transfer and photocurrent relative to bare cells [13]. The study is OpenAlex-only in the present retrieval, so it is included as a high-relevance discovery record rather than cross-validated evidence. It nevertheless sharpens the design question: can a conductive host network reduce the transport bottleneck without compromising optical access, metabolic state, or scalability?

### 5.3 Synthetic biology of cyanobacterial materials

Goodchild-Michelman *et al.* review how synthetic-biology tools can support cyanobacteria-based living materials, with bioconcrete, biocomposites, and biophotovoltaics as application cases [14]. Together with the ELM reviews [1–3], this makes cyanobacteria a useful model platform: they are photosynthetic, genetically tractable, and relevant to carbon-fixing material and energy functions. But the platform should not be oversold. Device-scale performance depends on photon delivery, mass transport, metabolism, electrode geometry, and stability, so a genetic intervention must be tested alongside those variables.

## 6. A unified research framework for programmable living materials

The literature supports framing ELM development as a closed design loop:

```text
Desired material function
        ↓
Material specification and measurement target
        ↓
Genetic / cellular program + matrix / interface design
        ↓
Multiscale assembly and fabrication
        ↓
Viability, structure, and function measurements
        ↓
Model-based diagnosis of drift and failure
        ↺ redesign
```

The specification step is essential. For a conductive biofilm, for example, “conductive” must be resolved into a measurement protocol and desired operational regime: conductivity or impedance, current under a defined potential, electrode area, nutrient conditions, biomass, illumination if applicable, and time-dependent stability. For a living catalyst, the specification must similarly distinguish catalytic rate, product selectivity, cell-specific productivity, material retention, and whether the polymerization chemistry is actually enabled by the living system rather than merely occurring in its presence.

An ELM experiment should therefore report four linked evidence classes:

1. **Program evidence:** construct identity, expression or pathway evidence, and appropriate biological controls.
2. **Assembly evidence:** microscopy, composition, matrix or scaffold architecture, and fabrication history.
3. **Functional evidence:** direct material/device readout with an explicit comparator.
4. **Boundary evidence:** viability, stability, failure conditions, reproducibility, and scale dependence.

This reporting structure creates a traceable bridge from genetic input to material output. It also makes negative results useful: if an interface improves electrical transport but reduces cell growth, that is not simply a failed device; it locates a viability–function trade-off that can guide the next design.

## 7. Open questions and research gaps

### 7.1 From program to property: an incomplete causal map

The field has compelling demonstrations but lacks general predictive mappings from a genetic program to an emergent material property. Many variables intervene between DNA and device output: burden on the host, gene-expression variability, growth phase, matrix composition, diffusion, mechanical stress, and interface geometry. A major research priority is to construct datasets that jointly track program state, cell state, architecture, and performance over time.

### 7.2 Standardized comparators and metrology

Studies often use different hosts, electrodes, media, geometries, and endpoints. This makes it difficult to decide whether a reported advance arises from a biological program, a materials interface, or an operating condition. Shared benchmark protocols should define baseline hosts/materials, electrode conditions, reporting of biomass and area normalization, viability assays, and operational lifetime. For bioelectronic systems, current alone is insufficient without stability, relevant normalization, and electrochemical characterization.

### 7.3 Viability–function–manufacturability trade-offs

An ELM must remain functional long enough to matter, yet the same material modification that improves a device metric can stress cells or limit mass transport. Printable microbial inks [6] and engineered biofilms [5] show that biological material formation and processing can be compatible, but manufacturing-scale reproducibility remains an open question. Future studies should report batch-to-batch variance and describe how the biological state changes through fabrication and storage.

### 7.4 Interface transport and multi-objective optimization

Living photovoltaics demonstrate the interface bottleneck particularly clearly. Protein conduits, mediators, surface coatings, conductive polymers, and multi-species consortia may each improve one transport step, but they may create new limitations in illumination, resistance, metabolism, or durability [9–13]. The important design objective is multi-objective: maximize useful output while maintaining survival, stable assembly, and safe containment.

### 7.5 The evidence gap for living-cell polymerization catalysts

The project statement includes single-cell living catalysts for polymerization. The focused search performed here did not yield a sufficiently direct, cross-validated cluster establishing this exact application in the same way that the searches established microbial ink and biophotovoltaics. This is scientifically valuable information: it marks a targeted literature-expansion task. A follow-up search should use narrower chemistry and organism terms, then separate (a) whole-cell biocatalysis producing polymer precursors, (b) genetically targeted in situ polymer assembly, (c) enzyme-mediated polymerization, and (d) nonliving catalysts merely operating in biological media. These are related but should not be conflated.

### 7.6 Containment, persistence, and governance

Programmability and persistence create safety and governance requirements. ELM research should specify host containment, genetic stability, escape or horizontal-transfer considerations where relevant, waste handling, and the intended environment of use. These requirements are part of material design because uncontrolled persistence or loss of function changes the system’s operational boundary.

## 8. Conclusion

The literature supports a shift from viewing cells as passive additives to viewing them as programmable material processors and responsive components. Biofilms, microbial inks, synthetic multicellular programs, targeted chemical assembly, and living photovoltaics provide complementary examples of how biological information can be coupled to material assembly and function. The most promising route is not a single technology but an integrated architecture: specify a material function, encode an appropriate cellular behavior, engineer the assembly and interface, measure direct output alongside viability and stability, and iterate from diagnosed failure modes.

For the supplied research context, the strongest immediately supported directions are (i) genetically programmed extracellular matrices and printable microbial materials, and (ii) bioelectronic materials that improve cell–electrode charge transfer. The proposed single-cell polymerization-catalyst direction remains promising but needs a more discriminating evidence search and a clearer operational definition. Across all directions, the decisive scientific question is whether a biological program can produce a predictable, measurable, and maintainable material state across relevant scales.

---

## References

1. Nguyen, P. Q., Dorval Courchesne, N.-M., Duraj-Thatte, A., Praveschotinunt, P., & Joshi, N. S. (2018). *Engineered Living Materials: Prospects and Challenges for Using Biological Systems to Direct the Assembly of Smart Materials*. **Advanced Materials, 30**(19), e1704847. https://doi.org/10.1002/adma.201704847. [OpenAlex + AnySearch]
2. Gilbert, C., & Ellis, T. (2019). *Biological Engineered Living Materials: Growing Functional Materials with Genetically Programmable Properties*. **ACS Synthetic Biology, 8**(1), 1–15. https://doi.org/10.1021/acssynbio.8b00423. [OpenAlex + AnySearch]
3. Liu, A. P., Appel, E. A., Ashby, P. D., *et al.* (2022). *The living interface between synthetic biology and biomaterial design*. **Nature Materials, 21**, 390–397. https://doi.org/10.1038/s41563-022-01231-3. [OpenAlex]
4. Chen, A. Y., Deng, Z., Billings, A. N., *et al.* (2014). *Synthesis and patterning of tunable multiscale materials with engineered cells*. **Nature Materials, 13**, 515–523. https://doi.org/10.1038/nmat3912. [OpenAlex + AnySearch]
5. Huang, J., Liu, S., Zhang, C., *et al.* (2019). *Programmable and printable Bacillus subtilis biofilms as engineered living materials*. **Nature Chemical Biology, 15**, 34–41. https://doi.org/10.1038/s41589-018-0169-2. [OpenAlex + AnySearch]
6. Duraj-Thatte, A., Manjula-Basavanna, A., Rutledge, J., *et al.* (2021). *Programmable microbial ink for 3D printing of living materials produced from genetically engineered protein nanofibers*. **Nature Communications, 12**, 6600. https://doi.org/10.1038/s41467-021-26791-x. [OpenAlex + AnySearch]
7. Toda, S., Blauch, L. R., Tang, S. K. Y., Morsut, L., & Lim, W. A. (2018). *Programming self-organizing multicellular structures with synthetic cell-cell signaling*. **Science, 361**(6398), 156–162. https://doi.org/10.1126/science.aat0271. [OpenAlex + AnySearch]
8. Liu, J., Kim, Y. S., Richardson, C. E., *et al.* (2020). *Genetically targeted chemical assembly of functional materials in living cells, tissues, and animals*. **Science, 367**(6484), 1372–1376. https://doi.org/10.1126/science.aay4866. [OpenAlex]
9. Schuergers, N., Werlang, C. A., Ajo-Franklin, C. M., & Boghossian, A. A. (2017). *A synthetic biology approach to engineering living photovoltaics*. **Energy & Environmental Science, 10**, 1102–1115. https://doi.org/10.1039/c7ee00282c. [OpenAlex + AnySearch]
10. Saper, G., Kallmann, D., Conzuelo, F., *et al.* (2018). *Live cyanobacteria produce photocurrent and hydrogen using both the respiratory and photosynthetic systems*. **Nature Communications, 9**, 2168. https://doi.org/10.1038/s41467-018-04613-x. [OpenAlex + AnySearch]
11. Zhu, H., Meng, H., Zhang, W., *et al.* (2019). *Development of a longevous two-species biophotovoltaics with constrained electron flow*. **Nature Communications, 10**, 4282. https://doi.org/10.1038/s41467-019-12190-w. [OpenAlex]
12. Reggente, M., Roullier, C., Mouhib, M., *et al.* (2024). *Polydopamine-coated photoautotrophic bacteria for improving extracellular electron transfer in living photovoltaics*. **Nano Research, 17**, 866–874. https://doi.org/10.1007/s12274-023-6396-1. [OpenAlex + AnySearch]
13. Chen, Z., McCuskey, S. R., Zhang, W., *et al.* (2025). *Three-dimensional conductive conjugated polyelectrolyte gels facilitate interfacial electron transfer for improved biophotovoltaic performance*. **Nature Communications, 16**, 5955. https://doi.org/10.1038/s41467-025-61086-5. [OpenAlex]
14. Goodchild-Michelman, I. M., Church, G. M., Schubert, M. G., & Tang, T.-C. (2023). *Light and carbon: Synthetic biology toward new cyanobacteria-based living biomaterials*. **Materials Today Bio, 19**, 100583. https://doi.org/10.1016/j.mtbio.2023.100583. [OpenAlex + AnySearch]
15. An, B., Wang, Y.-Y., Huang, Y.-Y., *et al.* (2023). *Engineered Living Materials For Sustainability*. **Chemical Reviews, 123**(5), 2349–2419. https://doi.org/10.1021/acs.chemrev.2c00512. [OpenAlex + AnySearch]
16. Islam, M., Selhuber-Unkel, C., Korvink, J. G., & Díaz Lantada, A. (2023). *Engineered living carbon materials*. **Matter, 6**(5), 1382–1403. https://doi.org/10.1016/j.matt.2023.03.018. [OpenAlex + AnySearch]

## Retrieval note

The bibliography was discovered through OpenAlex and AnySearch on 2026-08-30. “OpenAlex + AnySearch” means the record was matched across both sources by the hybrid search tool; “OpenAlex” means it was retained as a single-source, high-relevance discovery record. DOI resolution was checked where available; publisher sites may block automated requests, so Crossref/OpenAlex metadata and DOI landing URLs are retained as the reproducible bibliographic record. No claim in this survey relies only on the attached provenance annotations.
