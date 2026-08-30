# Survey Agent Report

## 1. Question, definitions, and answer in one paragraph

The question “are there more colour pigments to discover?” contains three different claims. A **pigment** is a material used to impart colour through selective interaction with light; a **reflectance spectrum** is a physical distribution of reflected light as a function of wavelength; and a **colour appearance** is a perceptual outcome under a specified observer, illuminant, viewing geometry, and adaptation state. New pigments and new useful reflectance spectra remain scientifically plausible because chemical composition, crystal structure, defects, particle morphology, coating matrix, and processing create an enormous design space. In contrast, no pigment creates a new human cone class or a new fundamental dimension of normal trichromatic vision. A pigment may nonetheless make an appearance that is distinguishable from available products, improve a region of the material colour gamut, or offer the same CIE coordinates with a more favourable near-infrared response, durability, toxicity profile, or manufacturing route. The defensible research question is therefore whether a candidate material expands a **defined application-specific performance frontier**, not whether it creates an ontologically new human colour.

## 2. Evidence map

### 2.1 Colour is a measurement-and-observer relation

CIE 015:2018 specifies the standard observers, illuminants, reflectance reference, viewing conditions, tristimulus calculation, chromaticity, colour spaces, and colour-difference practices needed to make a colour claim reproducible [S1]. It follows that a statement such as “this is a new blue” is incomplete unless it specifies at least the spectral measurement conditions and a colour-difference criterion. The standard does not say that all possible material colours have been discovered; it supplies the coordinate framework for comparing them.

The separation of spectrum and appearance also creates an important counterexample to naïve novelty claims. Two spectra can match under one illuminant or observer and diverge under another. Therefore, identical CIE coordinates under one condition do not prove material equivalence, while a changed spectrum does not automatically prove a perceptually new colour. The relevant performance object is a tuple: spectral reflectance, CIE coordinates under named conditions, colour difference to an established reference set, and non-colour engineering attributes.

### 2.2 Pigment history motivates, but does not settle, discovery

Prussian Blue is commonly described as the first modern synthetic pigment, discovered in the early eighteenth century. Its importance is historical rather than a license to make a stronger claim that all later pigment discovery follows the same pathway. It illustrates that a chemical process can create a stable, reproducible material with a colour previously unavailable to artists and technologists. Modern searches need a narrower success definition: an identified composition or material family must be distinct, sufficiently stable, characterisable, and useful relative to existing products.

### 2.3 YInMn Blue is a correctly scoped motivating example

Subramanian and Li describe YInMn Blue as a new class of intense inorganic pigments based on trigonal-bipyramidal chromophores [S2]. The historical account associated with the material begins with an unintended material outcome in 2009 and later development of the composition family. This is evidence that the practical pigment landscape is not closed. It is not evidence that the visible spectrum gained a new wavelength or that human colour space changed. The case supports two narrower propositions:

1. Crystal-chemical coordination environments can yield useful spectral selectivity that was not previously represented in commercial pigment libraries.
2. Discovery can be accelerated when chemical hypotheses, structural characterisation, and property measurements are coordinated rather than treated as independent steps.

### 2.4 Why new pigments can exist even when colour space is fixed

Normal human colour matching is conventionally represented through three tristimulus values. A material's reflectance is a high-dimensional curve, which is projected into a lower-dimensional colour representation for a fixed viewing condition. The projection is many-to-one. Consequently, material discovery can find spectra that map to a familiar hue but differ in chroma, lightness, metamerism, solar/near-infrared behaviour, compatibility with a binder, cost, stability, and environmental burden. The unsearched space is not “new primary colours”; it is the joint space of material structures and useful optical/property trade-offs.

Industrial pigments are therefore multiobjective materials. A candidate that is visually attractive but decomposes, leaches, requires an unacceptable precursor, or cannot be dispersed has not met the practical definition of discovery. The literature on industrial inorganic pigments emphasises chemistry, structure, particle properties, and application context alongside colour [S3]. Nassau's account of the physical and chemical causes of colour further cautions against treating colour as a single compositional label [S4].

## 3. Literature synthesis by sub-hypothesis

### H1 — The chemical/material design space contains undiscovered pigment candidates

**Status: supported in principle; not quantified for a particular application.** Inorganic materials can vary in composition, crystal structure, local coordination, defects, and morphology. High-throughput and data-driven materials methods establish a general basis for screening such combinatorial spaces [S5], [S6]. YInMn demonstrates that a coordination motif can produce a commercially relevant colour material after a long period without an analogous blue pigment family [S2]. The survey does not infer a probability of discovery or a count of remaining pigments.

### H2 — A new candidate can be called visually novel only against a declared reference library and viewing protocol

**Status: strongly supported.** CIE colorimetry gives the measurement language but does not define a universal “new colour” threshold [S1]. A proposal should select a named reference library, illuminate samples under specified sources, compute CIE coordinates and colour differences, and declare a practical threshold before any samples are screened. The threshold is an application policy, not a universal perceptual law.

### H3 — Spectral novelty and CIE novelty are not interchangeable

**Status: strongly supported by colour science.** The mapping from reflectance spectra to tristimulus coordinates depends on the observer and illuminant. The project must therefore record both the raw spectrum and CIE-derived metrics. A high spectrum-space distance with low CIE distance can be materially valuable for energy or metamerism applications but must not be advertised as a newly perceived hue. Conversely, a CIE-space separation should be checked under more than one relevant illuminant.

### H4 — Computer-guided, safety-constrained prioritisation can reduce the search burden

**Status: plausible and testable; not yet demonstrated for this target.** Materials informatics can rank candidates across multiple objectives, but predictions must be calibrated and experimentally checked [S5], [S6]. A defensible initial project uses computational ranking to decide which *safe, authorised* candidates merit expert review, rather than treating a model score as a discovery. No current source in this survey establishes a validated pigment-specific model for the selected chemical family; this is a central gap.

## 4. Claim traceability and admissible language

| Claim type | Allowed language | Prohibited leap |
|---|---|---|
| Human vision | “normal trichromatic colour matching is represented by CIE colorimetry under stated conditions” | “a new pigment creates a new human primary colour” |
| History | “Prussian Blue is commonly regarded as an early synthetic pigment; YInMn is a modern example of pigment discovery” | “one historical case proves a large number of future discoveries” |
| Candidate score | “the model predicts that a candidate is Pareto-promising” | “the candidate is a new pigment” |
| Measurements | “a candidate exceeds a preregistered separation threshold against a named reference set” | “the pigment makes a never-before-seen colour” |
| Safety | “a proposed route requires materials-safety review” | “the design is safe to execute without institution-specific approval” |

## 5. Research gaps passed to the Idea Agent

1. **GAP-01 — Operational novelty gap.** No application-specific, auditable definition links spectral separation, CIE separation, and reference-library coverage to a claim of “new pigment appearance.”
2. **GAP-02 — Joint objective gap.** Pigment searches often report a hue/property result without an explicit, reproducible Pareto trade-off among visual performance, spectral functionality, stability, composition constraints, and uncertainty.
3. **GAP-03 — Structure-to-spectrum gap.** There is no verified, open, pigment-specific benchmark in this run that connects crystal-chemical descriptors to full reflectance spectra and multi-illuminant colour metrics for the target class.
4. **GAP-04 — Honest reporting gap.** A report format is needed that cleanly distinguishes predicted candidates, measured candidates, and commercial/discovery claims.

## 6. Survey conclusion

The answer is **yes, more pigments can plausibly be discovered or engineered; no, this should not be described as creating new fundamental human colours.** The best next study is not an unconstrained search for “a new blue.” It is a preregistered, multiobjective evaluation that asks whether a safety-screened material family contains candidates that expand a specified reference library's usable spectral–perceptual–engineering frontier. The project must publish spectra, conditions, reference-set distances, negative results, uncertainty, and human-review gates.

## References

- **[S1]** CIE, *Colorimetry, 4th Edition*, CIE 015:2018, 2018, doi: 10.25039/TR.015.2018.
- **[S2]** M. A. Subramanian and C. C. Li, “YInMn blue—200 years in the making: New intense inorganic pigments based on chromophores in trigonal bipyramidal coordination,” *Materials Today Advances*, vol. 16, Art. no. 100323, 2022, doi: 10.1016/j.mtadv.2022.100323.
- **[S3]** G. Buxbaum and G. Pfaff, *Industrial Inorganic Pigments*, 3rd ed. Weinheim, Germany: Wiley-VCH, 2005.
- **[S4]** K. Nassau, *The Physics and Chemistry of Color: The Fifteen Causes of Color*, 2nd ed. New York, NY, USA: Wiley, 2001.
- **[S5]** K. T. Butler, D. W. Davies, H. Cartwright, O. Isayev, and A. Walsh, “Machine learning for molecular and materials science,” *Nature*, vol. 559, pp. 547–555, 2018, doi: 10.1038/s41586-018-0337-2.
- **[S6]** S. Curtarolo *et al.*, “The high-throughput highway to computational materials design,” *Nature Materials*, vol. 12, pp. 191–201, 2013, doi: 10.1038/nmat3568.
