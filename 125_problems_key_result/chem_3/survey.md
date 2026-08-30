# Survey: Measuring Microscopic and Nanoscale Interfacial Phenomena

**Status:** Manual literature survey  
**Research object:** Molecular interfaces at gas--liquid, liquid--solid, and solid--solid boundaries  
**Primary question:** How can microscopic interface phenomena be measured beyond film thickness alone?  
**Evidence boundary:** This survey synthesizes bibliographic records discovered through OpenAlex and AnySearch Academic. The attached project-context and graph-provenance files were used to determine scope; they are not independent evidence for scientific claims.

## Executive summary

Microscopic interface measurement is not a single-instrument problem. The supplied project context correctly identifies the limitation of optical interference: it can provide a thickness coordinate for a gas or liquid film, but thickness by itself does not resolve molecular orientation, chemical identity, local force, interfacial morphology, or non-equilibrium heat and mass transport. The literature supports a complementary measurement architecture:

1. Optical interferometry and ellipsometry establish film thickness, meniscus shape, and lateral morphology.
2. Surface-specific nonlinear vibrational spectroscopy, especially SFG and SHG, constrains molecular orientation, hydrogen-bonding environments, and selected chemical changes in the interfacial region.
3. Scanning probe and surface-force methods measure local topography, confined-separation forces, capillary structures, and mechanical interaction landscapes.
4. Near-ambient chemical spectroscopy and surface-enhanced Raman methods provide chemically specific signatures at reactive gas--solid or liquid--solid interfaces.
5. Liquid-phase electron microscopy can image selected nanoscale dynamics at liquid--solid interfaces, but its beam, cell geometry, and confinement effects must be treated as part of the measurement model.
6. Thermal metrology and transient techniques connect microscopic interfacial structure to heat-transfer observables, but do not independently identify molecular mechanism.

The central synthesis is therefore a measurement principle: a defensible microscopic-interface claim should couple at least one **geometric observable**, one **chemical or structural observable**, one **dynamic or transport observable**, and an explicit **perturbation and uncertainty audit**. No one modality establishes all four.

## 1. Scope and evidence basis

The survey concerns molecular and nanoscale phenomena at gas--liquid, liquid--solid, and solid--solid interfaces. The target processes include film drainage and evaporation, adsorption and reaction, capillary and disjoining forces, phase-change heat transfer, nanoscale bubble or droplet evolution, and transport at buried material interfaces. The immediate application lanes are materials synthesis, combustion and spray systems, spray drying, and evaporative-cooling devices.

The scope excludes macroscopic fluid dynamics as the primary object, bulk-only spectroscopy, and biological membrane assays. This exclusion is important: a bulk property may correlate with interfacial behavior, but it does not automatically identify what occurs within the interfacial region.

The review *Water at Interfaces* frames aqueous interfaces as important in ultrathin films, liquid--solid electrochemistry, and liquid--vapor gas exchange, while also emphasizing remaining knowledge gaps [1]. The method literature does not support reducing this broad problem to a more precise version of the same thickness measurement. Rather, it supports combining orthogonal observables with models that state what each observable cannot identify.

## 2. What does “measure the interface” mean?

An interface can be treated as a latent state comprising geometry, composition, molecular orientation, charge or chemical potential, local mechanical response, heat flux, and mass flux. A measurement is a filtered observation of part of that state, with finite spatial and temporal resolution, an instrument-specific contrast mechanism, and possible perturbation.

This measurement model has a direct implication: a film-thickness trace cannot uniquely determine chemistry, and a vibrational spectrum cannot uniquely determine a depth-resolved geometry. A trustworthy mechanistic account requires agreement among observables whose failure modes differ.

| Question | Minimum measurement target | Why thickness alone is insufficient |
|---|---|---|
| Why does a thin film drain, arrest, or rupture? | Thickness/shape, local force or disjoining-pressure proxy, surface chemistry, time dependence | Similar thickness histories can arise from different wetting, ionic, capillary, or adsorption mechanisms. |
| What controls evaporation or phase-change heat transfer? | Film geometry, temperature or heat-flux proxy, interfacial composition or orientation, transient mass transport | The same film thickness can support different thermal resistances and accommodation behavior. |
| What occurs at a reacting liquid--solid interface? | Chemical state, molecular arrangement, morphology/separation, reaction dynamics | Optical height information does not identify adsorbates, dissolution, nucleation, or charge-transfer pathways. |
| What sets solid--solid interfacial thermal or mechanical response? | Interface structure, local mechanical or thermal observable, temporal response | Bulk conductivity or modulus cannot isolate interface resistance or local contact state. |

## 3. Measurement families and what they can establish

### 3.1 Optical interferometry and ellipsometry: geometric anchors

Interferometric approaches can continuously track film thickness or interface position without requiring a local contacting probe. In a recent wetting study, phase-shifting imaging ellipsometry resolved droplet shape together with a nanometer-scale liquid film and nanoparticle layer [11]. This is direct evidence that optical methods can extend from a one-dimensional thickness trace toward spatial morphology.

Their limitation is equally important. Optical contrast is converted to thickness using an assumed or calibrated refractive-index model. The conversion does not independently establish molecular composition, molecular orientation, local pressure, or interfacial reaction state. Optical methods should therefore be used as the **geometric reference channel** in a multimodal design, rather than as a stand-alone mechanism detector.

For gas--liquid and liquid--solid systems, the most useful optical outputs are time-resolved thickness, meniscus curvature, lateral heterogeneity, and the location of nucleation or drying fronts. These outputs can then be synchronized with chemistry-sensitive or force-sensitive measurements.

### 3.2 Vibrational SFG and SHG: molecular selectivity

Vibrational sum-frequency generation (SFG) is intrinsically interface-sensitive in media where bulk response is suppressed by symmetry. Reviews show that SFG/SHG can report molecular arrangement in the first few interfacial water layers at mineral--water interfaces [2], and SFG studies of water--air and ice--air interfaces connect spectral interpretation with molecular simulation [3]. Quantitative spectral and orientational analysis remains nontrivial: the relationship between intensity and orientation depends on polarization, local-field factors, and spectral-model assumptions [4].

This method family is particularly valuable for the question in the project context because it supplies what film-thickness measurements lack: a chemical- and orientation-sensitive interfacial observable. Hyperspectral SFG microscopy extends this idea by resolving selected self-assembled systems across spatial, temporal, and spectral dimensions [5]. SFG has also been used to study buried polymer interfaces, demonstrating that molecular interface information need not be restricted to an exposed free surface [6].

However, SFG does not provide a universal depth profile. The water--air/ice--air review explicitly notes that SFG alone cannot recover how molecular orientation varies with distance from the interface [3]. A high-quality interpretation should therefore pair SFG with geometry, composition, and model comparison rather than infer complete molecular structure from one spectrum.

### 3.3 Scanning probe microscopy and surface-force methods: local mechanics and confinement

Atomic-force microscopy (AFM) and surface-force apparatus (SFA) methods address a different aspect of the interface: local topography, force-distance response, confined separation, and nanoscale capillary structures. The review of surface nanobubbles and nanodroplets documents the role of AFM in early observation and later comparison with optical measurements [9]. Its broader lesson is that the same interfacial object can require multiple modalities to distinguish a real structure from a measurement artifact.

SFA can follow force and reactive evolution in a confined liquid--solid system. Dziadkowiec *et al.* used SFA to follow reactivity and nm-range forces between rough calcite surfaces, linking a long-range repulsive response to nucleation events in confinement [10]. This establishes the method class as a route from interface separation and force to a physically constrained reaction hypothesis. It does not make force curves chemically self-interpreting: roughness, ionic conditions, surface history, and model choice remain competing explanations.

Acoustic subsurface AFM expands the local-mechanical imaging repertoire toward non-destructive three-dimensional nanoscale contrast [12]. Its relevance here is complementary, not substitutive: it can help map hidden morphology or mechanics, but it does not replace chemistry-sensitive measurements at a liquid interface.

### 3.4 Chemical-state methods: APXPS and surface-enhanced Raman

Chemical state is often the missing variable in a thickness/force experiment. Ambient-pressure X-ray photoelectron spectroscopy (APXPS) was reviewed as a means to probe elemental composition and chemical specificity of vapor--solid interfaces under pressures approaching 130 mbar [7]. It is relevant to heterogeneous reaction, catalysis, and gas--solid reaction questions. Its information depth, gas-phase scattering constraints, and beam/sample effects define its boundary; it should not be represented as a generic in-operando measurement of every liquid interface.

Surface-enhanced Raman spectroscopy (SERS) provides another chemistry-sensitive route. Tian, Ren, and Wu reviewed its surface sensitivity and applications to adsorption, electrocatalysis, and corrosion, while also discussing substrate and enhancement limitations [8]. SERS can contribute molecular adsorption or reaction signatures where an appropriately characterized enhancement substrate is justified. It cannot be assumed to represent an unperturbed interface, because the nanostructured substrate and enhancement mechanism are part of the observed system.

### 3.5 Liquid-phase electron microscopy: observing selected dynamic events

Liquid-phase electron microscopy (LP-EM) can directly image nanoscale processes in solution. Reviews describe its potential for nanometer spatial and sub-second temporal resolution, while stressing that electron-beam radiation can alter sample structure and chemical processes [14,15]. In-situ liquid-cell TEM has been used to study oriented attachment of gold nanoparticles at atomic resolution [16], illustrating the value of direct dynamic imaging for a liquid--solid process.

The method therefore answers a narrower but high-value question: under the measurement-cell and beam conditions, what dynamic morphology or assembly event occurs? The answer must not automatically be generalized to an unconfined or unirradiated interface. LP-EM is most defensible as a targeted imaging channel that is cross-validated against lower-perturbation optical or spectroscopic observations and explicitly audited for measurement-induced changes.

### 3.6 Transport-sensitive measurements: connecting microscopic state to heat flow

For evaporative cooling and solid--solid interfaces, the desired outcome is often heat transport rather than an image. Cahill *et al.* review nanoscale thermal-transport methods, including time-domain thermoreflectance, scanning thermal microscopy, and coherent-phonon approaches, and note the increasing importance of interfaces in nanoscale thermal behavior [13]. These methods can quantify transport-relevant observables, but they cannot independently decide whether an observed change originates from geometry, chemistry, phonon mismatch, or a phase-boundary state.

The measurement logic is bidirectional. Molecular and geometric channels generate candidate explanations for a transport change; thermal channels test whether those explanations matter for device-scale performance. Neither channel should stand in for the other.

## 4. Method-combination matrix

| Measurement family | Principal observable | Strength for this topic | Dominant non-identifiability or perturbation | Best complement |
|---|---|---|---|---|
| Interferometry / ellipsometry | Film thickness, curvature, lateral morphology | Non-contact temporal geometry and front tracking | Refractive-index/model dependence; weak chemical specificity | SFG/SHG, APXPS/SERS, force measurement |
| SFG / SHG / SFG microscopy | Interfacial vibrational signatures and orientational constraints | Molecular selectivity at selected interfaces | Spectral inversion, phase/polarization assumptions, limited depth information | Optical geometry, simulation, chemical-state method |
| AFM / SFA | Topography, confined separation, force landscape | Local mechanics and capillary/disjoining-force hypotheses | Tip/contact perturbation, roughness, model dependence | Optical imaging, SFG/chemical analysis |
| APXPS / SERS | Chemical state or adsorbate signature | Reaction and adsorption mechanisms | Information-depth, scattering, enhancement-substrate, or beam effects | Geometry and force measurements |
| LP-EM | Dynamic nanoscale morphology in a liquid cell | Direct observation of selected assembly or reaction events | Electron-beam and confinement effects | Optical/spectroscopic validation |
| Thermal metrology | Conductance, transient response, heat-flow proxy | Tests interface relevance to heat-transfer performance | Mechanism is indirect and spatially averaged | Structure and chemistry channels |

## 5. A defensible microscopic-interface measurement framework

The literature supports a four-layer evidence design rather than a single modality:

1. **Locate and time the event.** Use an optical or imaging channel to define where and when the film, meniscus, droplet, contact, or reaction front changes.
2. **Resolve interfacial state.** Use a surface-sensitive chemical or vibrational channel to test a declared molecular or chemical explanation.
3. **Constrain local mechanics or transport.** Use force, mechanical, or thermal data to test whether the proposed interfacial state changes the relevant transfer process.
4. **Audit non-identifiability.** Report calibration assumptions, spatial/temporal resolution, surface history, beam/tip/light perturbation, and whether each conclusion survives an orthogonal method.

The core inference should be conditional. For example, synchronized film thinning and an SFG-signature change can support, but do not prove, a dehydration or molecular-reorientation mechanism. Support becomes stronger only if a force or transport signal changes in the predicted direction and plausible optical or instrument-induced alternatives are not favored.

This framework prevents a common misinterpretation in evaporative and reactive interfaces: treating a measured film thickness as the mechanism rather than as one state variable. The open problem is to infer how geometry, chemistry, and flux interact, not to add ever finer thickness precision without additional observables.

## 6. Implications for the application lanes

### Materials synthesis

Nucleation, oriented attachment, dissolution, and interfacial assembly are natural targets for combined liquid-cell imaging, spectroscopy, and force/geometry measurements. The calcite-confinement study [10] and liquid-cell TEM study [16] demonstrate complementary pieces of such a problem: confined forces/reaction evolution and direct nanoscale assembly dynamics. They do not supply a universal protocol for all syntheses; the system chemistry determines which contrast mechanisms remain valid.

### Combustion and spray drying

The strongest general lesson is that an optical film or droplet trajectory needs to be linked to chemical and thermal observables before attributing a drying or reaction pathway to a microscopic interfacial mechanism. This retrieval did not yield a sufficiently direct, cross-validated set of papers on the exact combined regime of reactive spray drying and microexplosion. This is an evidence gap, not evidence that the mechanism is unimportant. A future focused search should separate droplet-size imaging, volatile-composition measurement, interfacial reaction spectroscopy, and transient heat/mass-transfer models.

### Evaporative-cooling nanodevices

Thin-film geometry and nanoscale thermal transport must be jointly measured. Optical channels can locate liquid distribution, while thermal channels test heat-transfer consequences; the decisive missing bridge is a chemically or structurally specific measurement that can discriminate wettability, adsorption, and confined-liquid-state explanations. This is a promising area for correlative measurement, but the present survey does not identify one technique that supplies all required variables without a trade-off.

## 7. Open questions and research gaps

### 7.1 Operando correlation without self-created artifacts

Many powerful modalities change the interface they seek to measure. AFM tips apply local forces, LP-EM introduces beam chemistry and confinement, nonlinear optical methods require model-dependent spectral inversion, and APXPS/SERS operate with technique-specific contrast conditions. The field needs explicit perturbation budgets and cross-method replication before treating a microscopic signal as native behavior.

### 7.2 Spatiotemporal registration across modalities

Relevant events can be localized in nanometers but evolve on much larger time and length scales. The key challenge is not only higher nominal resolution; it is aligning time bases, coordinate systems, and sampled interface regions across methods. A measurement that averages over a different region or duration cannot straightforwardly validate a local event.

### 7.3 Quantitative inversion and uncertainty

Spectra, force curves, and optical phase maps are indirect observables. Their conversion to orientation, interaction potential, film thickness, or transport coefficient relies on models. Future studies should publish the forward model, calibration basis, uncertainty propagation, and alternative models that fit the data comparably well.

### 7.4 Chemistry--geometry--transport causality

The consequential unresolved question is causal rather than instrumental: which molecular interfacial changes actually control phase change, reaction, or heat transfer? A useful future dataset should track geometry, interface-specific chemistry, a local mechanical/force representation, and flux in the same declared boundary. Simulations can help interpret this joint dataset, but simulations must be anchored to observables rather than substitute for measurement.

## 8. Conclusion

Microscopic interface phenomena can be measured by combining, not substituting among, method families. Optical interference remains essential for film geometry; SFG/SHG and chemical-state methods add molecular specificity; AFM/SFA constrain confined mechanics; LP-EM offers selected direct dynamic imaging; and thermal measurements establish transport relevance. The research frontier is a calibrated correlative workflow that makes each method's contrast mechanism, perturbation, resolution, and non-identifiability explicit.

For the supplied project context, the best-supported near-term research direction is to develop an **evidence architecture for correlative interface metrology**, rather than to seek one universally superior microscope. The first design decision should be the causal question--film stability, reaction, molecular reorientation, or heat/mass transfer--followed by an observable set that can rule out the main alternatives.

## References

1. Björneholm, O., Hansen, M. H., Hodgson, A., *et al.* (2016). *Water at Interfaces*. **Chemical Reviews, 116**(13), 7698--7726. DOI: 10.1021/acs.chemrev.6b00045. **OpenAlex + AnySearch**.
2. Backus, E. H. G., Schaefer, J., & Bonn, M. (2020). *Probing the Mineral--Water Interface with Nonlinear Optical Spectroscopy*. **Angewandte Chemie International Edition, 60**(19), 10482--10501. DOI: 10.1002/anie.202003085. **OpenAlex + AnySearch**.
3. Tang, F., Ohto, T., Sun, S., *et al.* (2020). *Molecular Structure and Modeling of Water--Air and Ice--Air Interfaces Monitored by Sum-Frequency Generation*. **Chemical Reviews, 120**(8), 3633--3667. DOI: 10.1021/acs.chemrev.9b00512. **OpenAlex + AnySearch**.
4. Wang, H., Gan, W., Lu, R., Rao, Y., & Wu, B. (2005). *Quantitative spectral and orientational analysis in surface sum frequency generation vibrational spectroscopy (SFG-VS)*. **International Reviews in Physical Chemistry, 24**(2), 191--256. DOI: 10.1080/01442350500225894. **OpenAlex + AnySearch**.
5. Wang, H., & Xiong, W. (2021). *Vibrational Sum-Frequency Generation Hyperspectral Microscopy for Molecular Self-Assembled Systems*. **Annual Review of Physical Chemistry, 72**(1), 279--306. DOI: 10.1146/annurev-physchem-090519-050510. **OpenAlex only; discovery evidence**.
6. Chen, Z. (2010). *Investigating buried polymer interfaces using sum frequency generation vibrational spectroscopy*. **Progress in Polymer Science, 35**(11), 1376--1402. DOI: 10.1016/j.progpolymsci.2010.07.003. **OpenAlex + AnySearch**.
7. Starr, D. E., Liu, Z., Hävecker, M., Knop-Gericke, A., & Bluhm, H. (2013). *Investigation of solid/vapor interfaces using ambient pressure X-ray photoelectron spectroscopy*. **Chemical Society Reviews, 42**(13), 5833. DOI: 10.1039/c3cs60057b. **OpenAlex only; discovery evidence**.
8. Tian, Z.-Q., Ren, B., & Wu, D.-Y. (2002). *Surface-Enhanced Raman Scattering: From Noble to Transition Metals and from Rough Surfaces to Ordered Nanostructures*. **The Journal of Physical Chemistry B, 106**(37), 9463--9483. DOI: 10.1021/jp0257449. **OpenAlex + AnySearch**.
9. Lohse, D., & Zhang, X. (2015). *Surface nanobubbles and nanodroplets*. **Reviews of Modern Physics, 87**(3), 981--1035. DOI: 10.1103/revmodphys.87.981. **OpenAlex + AnySearch**.
10. Dziadkowiec, J., Zareeipolgardani, B., Dysthe, D. K., & Røyne, A. (2019). *Nucleation in confinement generates long-range repulsion between rough calcite surfaces*. **Scientific Reports, 9**, 8948. DOI: 10.1038/s41598-019-45163-6. **OpenAlex + AnySearch**.
11. Shoji, E., Hoshino, A., Biwa, T., *et al.* (2024). *Superspreading Wetting of Nanofluid Droplet Laden with Highly Dispersed Nanoparticles*. **Langmuir, 40**(50), 26509--26516. DOI: 10.1021/acs.langmuir.4c03347. **OpenAlex + AnySearch**.
12. Jiryaei Sharahi, H., Janmaleki, M., Tétard, L., *et al.* (2021). *Acoustic subsurface-atomic force microscopy: Three-dimensional imaging at the nanoscale*. **Journal of Applied Physics, 129**(3). DOI: 10.1063/5.0035151. **OpenAlex + AnySearch**.
13. Cahill, D. G., Ford, W. K., Goodson, K. E., *et al.* (2003). *Nanoscale thermal transport*. **Journal of Applied Physics, 93**(2), 793--818. DOI: 10.1063/1.1524305. **OpenAlex + AnySearch**.
14. Mirsaidov, U., Patterson, J. P., & Zheng, H. (2020). *Liquid phase transmission electron microscopy for imaging of nanoscale processes in solution*. **MRS Bulletin, 45**(9), 704--712. DOI: 10.1557/mrs.2020.222. **OpenAlex only; discovery evidence**.
15. Wu, H., Friedrich, H., Patterson, J. P., Sommerdijk, N. A. J. M., & de Jonge, N. (2020). *Liquid-Phase Electron Microscopy for Soft Matter Science and Biology*. **Advanced Materials, 32**(25), e2001582. DOI: 10.1002/adma.202001582. **OpenAlex only; discovery evidence**.
16. Zhu, C., Liang, S., Song, E., *et al.* (2018). *In-situ liquid cell transmission electron microscopy investigation on oriented attachment of gold nanoparticles*. **Nature Communications, 9**, 421. DOI: 10.1038/s41467-018-02925-6. **OpenAlex + AnySearch**.

## Retrieval note

- **Date:** 2026-08-30.
- **Engines:** OpenAlex and AnySearch Academic, queried in parallel by the hybrid-search tool.
- **Queries:**  
  1. nanoscale interfacial phenomena measurement optical interference atomic force microscopy sum frequency spectroscopy  
  2. nanoscale liquid film thickness interferometry evaporation disjoining pressure surface forces apparatus  
  3. molecular structure liquid solid interface vibrational sum frequency generation spectroscopy review  
  4. liquid phase transmission electron microscopy nanoscale liquid solid interface dynamics review
- **Inclusion rule:** Retain method papers and reviews that address geometry, molecular structure/chemistry, local force/mechanics, direct liquid-interface imaging, or thermal transport at a microscopic/nanoscale interface. A record had to be relevant to at least two terms in a focused query.
- **Source policy:** DOI-matched records from both engines are marked **OpenAlex + AnySearch**. OpenAlex-only records are retained only when method relevance is clear and are marked as discovery evidence, not cross-validated evidence.
- **DOI check:** DOI landing-page requests were attempted. Some DOI providers returned HTTP 403 to automated requests; DOI strings, titles, authors, venues, years, and source status were therefore retained from structured OpenAlex/AnySearch metadata, with source status preserved.
