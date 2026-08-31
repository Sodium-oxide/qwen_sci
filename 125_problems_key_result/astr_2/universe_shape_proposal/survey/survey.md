# Survey Agent — What Is the Shape of the Universe?

## Scope and operational question

The phrase *shape of the universe* contains three distinct questions that must not be conflated:

1. **Spatial curvature:** within an FLRW description, is the curvature parameter `Omega_K` consistent with zero, negative (closed), or positive (open)?
2. **Global topology:** are spatial sections simply connected, or are they compact with identifications (for example, a flat three-torus)?
3. **Observable domain:** which of these statements are identifiable from finite, model-dependent observations rather than assumed from the background model?

This Survey focuses on curvature inference and records topology as a distinct, unresolved branch. It does not claim that a curvature fit alone measures the universe's global topology, finiteness, or total extent.

## Evidence map

| Evidence ID | Evidence family | What it can establish | Bounded finding | Limits that must travel with the finding |
|---|---|---|---|---|
| E1 | Planck 2018 primary CMB spectra | Acoustic-scale geometry and parameter degeneracies in specified cosmologies | In non-flat extensions, CMB spectra can prefer a closed direction when smoothing/lensing-related freedom is treated in particular ways. | A CMB-only posterior is conditional on likelihood, foreground handling, recombination model, and parameterization. |
| E2 | Planck lensing reconstruction | Lensing potential reconstruction independent of peak-smoothing inference | Tests whether the peak-smoothing anomaly is coherently supported by reconstructed lensing. | Reconstruction shares sky and calibration dependencies; it is not independent in every nuisance direction. |
| E3 | BAO distance ladder | Transverse and radial distance-redshift relations relative to the sound horizon | BAO sharply breaks CMB curvature-distance degeneracies in standard late-time extensions. | Calibration and expansion-history assumptions are explicit; BAO does not by itself determine topology. |
| E4 | Supernovae and galaxy clustering | Relative distance and growth consistency at low redshift | Provides an external geometric consistency check. | Photometric calibration, selection, bias, and model choices must be propagated. |
| E5 | ACT DR6 / SPT-3G | Independent high-resolution CMB spectra and lensing | Tests whether a Planck-specific smoothing/curvature preference replicates. | Different masks, frequencies, likelihoods, and sky overlap create both complementarity and correlation. |

## Verified literature registry

The following metadata were discovered through the required OpenAlex + AnySearch dual-engine search and cross-matched by DOI. The direct claims used downstream are restricted to the scope shown above.

| Ref. key | Source | Cross-validated metadata | Permitted use in this workflow |
|---|---|---|---|
| planck18 | Planck Collaboration, *Planck 2018 results VI*, A&A 641 A6 (2020), DOI `10.1051/0004-6361/201833910` | Yes | Baseline CMB constraints, lensing-amplitude caveat, and the Planck+BAO curvature statement. |
| dival19 | Di Valentino, Melchiorri, and Silk, *Planck evidence for a closed Universe and a possible crisis for cosmology*, Nature Astronomy 4, 196–203 (2020), DOI `10.1038/s41550-019-0906-9` | Yes | Closed-universe interpretation as a conditional CMB-only result, not a consensus measurement. |
| dival20 | Di Valentino, Melchiorri, and Silk, JCAP 01, 013 (2020), DOI `10.1088/1475-7516/2020/01/013` | Yes | Persistence and model dependence of the `A_L` anomaly in extended Planck fits. |
| eboss21 | Alam *et al.*, Phys. Rev. D 103, 083533 (2021), DOI `10.1103/PhysRevD.103.083533` | Yes | BAO/RSD geometric complementarity and combined curvature constraints. |
| spt23 | Pan *et al.*, Phys. Rev. D 108, 122005 (2023), DOI `10.1103/PhysRevD.108.122005` | Yes | Independent CMB lensing measurement context. |
| desi25 | DESI Collaboration, JCAP 02, 021 (2025), DOI `10.1088/1475-7516/2025/02/021` | Yes | Blinded BAO data and contemporary distance constraints. |
| act25 | Louis *et al.*, *ACT DR6 power spectra, likelihoods and LCDM parameters*, JCAP 11, 062 (2025), DOI `10.1088/1475-7516/2025/11/062` | Yes | Independent CMB test reporting no excess lensing and no departure from spatial flatness in its stated analysis. |

## Sub-hypothesis coverage

| ID | Sub-hypothesis | Direct coverage | Decision |
|---|---|---|---|
| SH1 | The sign of `Omega_K` is inferred through distances and spectra, not observed as a literal three-dimensional embedding shape. | E1, E3 | Supported. |
| SH2 | Planck's closed-curvature preference can be entangled with anomalous CMB peak smoothing. | E1, E2, dival19, dival20 | Supported as a model-dependent interpretation. |
| SH3 | Cross-probe distance information can test the Planck-only curvature direction. | E3, E4, eboss21, desi25 | Supported. |
| SH4 | Independent CMB data can test replication of a Planck-specific anomaly. | E5, spt23, act25 | Supported. |
| SH5 | Curvature inference alone determines global topology or whether space is finite. | No direct source set in this Survey | Not supported; remains a separate question. |

## Gap ledger

| Gap ID | Accepted research gap | Why it matters | Evidence needed to close it |
|---|---|---|---|
| G1 | Curvature claims are often reported as if CMB peak smoothing, lensing reconstruction, BAO, and supernova distances were interchangeable measurements. | This hides different likelihoods, shared systematics, and model assumptions. | Channel-specific likelihood and nuisance ledger. |
| G2 | A Planck-only closed posterior and multi-probe near-flat constraints are commonly summarized as a contradiction rather than a testable model/likelihood discrepancy. | A discrepancy can originate in curvature, `A_L`, foreground/recombination treatment, expansion history, or correlation accounting. | Pre-registered alternative-model and posterior-predictive tests. |
| G3 | Published curvature constraints are difficult to compare when priors, curvature conventions, sound-horizon calibration, and model extensions are not made machine-readable. | Apparent evidence can be generated by parameterization or prior-volume differences. | Translation cards that record `Omega_K` convention, priors, and forward model. |
| G4 | Geometry and topology are conflated in public explanations. | A flat universe need not be infinite, and a closed-curvature fit is not a topology detection. | Explicit topology branch with separate observables such as matched-circle searches. |

## Survey handoff to Idea Agent

The downstream idea must target at least one accepted gap `G1`–`G4`; retain the distinction between local curvature and topology; and never call a Planck-only posterior a confirmed closed universe. The strongest actionable opportunity is an auditable cross-probe inference framework that asks **which assumptions and channels create, erase, or replicate the curvature preference**.
