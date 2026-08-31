# Survey Agent Report: Are We Alone in the Universe?

## Scope and scientific reframing

The question "Are we alone in the universe?" cannot be answered by a single telescope exposure or a count of known exoplanets. It requires an operational definition of the target inference, environments where life might persist, measurements sensitive to those environments, and a rule for distinguishing a living or technological process from abiotic and instrumental alternatives. The tractable research question is:

**How can remote and in-situ observations be combined into a context-conditioned, falsifiable assessment of biological or technological activity without treating one spectral feature, one radio event, or one non-detection as a final answer about life in the universe?**

This survey separates four propositions:

1. a world has physical conditions compatible with a specified kind of life;
2. data contain a candidate biosignature or technosignature;
3. abiotic, instrumental, and human-made alternatives have been tested;
4. the observing program is sufficiently sensitive that a non-detection constrains a stated population or mechanism.

Only the latter three are detection-inference propositions. Habitability is a target-selection condition, not evidence that life is present. A non-detection is a statement about sensitivity and coverage unless an explicit population model and recovery efficiency are supplied.

## Evidence corpus and roles

The Survey Agent used dual-engine OpenAlex and AnySearch searches for biosignature assessment, false positives and false negatives, habitable-zone models, technosignature searches, and life detection on ocean worlds. The frozen source registry S1-S10 appears in "survey_manifest.json"; all selected primary sources were returned by both engines. The user-requested in-app browser was also attempted, but its local runtime exited under a Windows ACL failure. Thus, metadata were cross-validated by the two scholarly engines and DOI identifiers; direct publisher-page verification is retained as a human-review task.

The source corpus divides into four evidence branches.

* **Contextual remote biosignatures.** Schwieterman et al. survey gaseous, surface, temporal, and polarization-related biosignatures and explicitly discuss false positives, false negatives, host-star effects, chemical disequilibrium, and detection limits [S1]. Catling et al. formulate biosignature assessment as a Bayesian inference that combines system context, habitability, candidate signatures, and exclusion of false positives [S2]. Meadows et al. use oxygen as a detailed case study: oxygen can have abiotic sources, and both the presence and absence of oxygen need environmental context [S3].
* **Limits of habitability proxies and non-detections.** Kopparapu et al. supply a climate-model-based habitable-zone estimate for main-sequence stars while documenting model assumptions and omitted cloud effects [S4]. Reinhard et al. show why active ocean-bearing biospheres can be remote false negatives: ocean-atmosphere cycling can suppress canonical atmospheric signatures for long intervals [S5]. Therefore, position in a habitable zone neither establishes life nor makes absence of O2 or methane decisive.
* **Technosignature candidates and artifacts.** Wright et al. argue that technology-related signatures can complement biosignature searches and may have distinct detectability and ambiguity properties [S6]. Margot et al. illustrate the operational importance of signal-injection recovery, radio-frequency-interference rejection, duty cycle, and defined search volume when interpreting a radio non-detection [S7]. A candidate signal must be localized, repeated, and tested against terrestrial and instrumental alternatives before it can support an extraordinary interpretation.
* **In-situ life detection.** The Ladder of Life Detection organizes multiple measurements by how strongly they discriminate indigenous life from abiotic alternatives [S8]. Enceladus sample-return and flight-detection studies emphasize preserved provenance, organic and isotopic context, repeat analyses, and planetary protection [S9, S10]. In-situ access can enrich evidence but does not remove the need to reject contamination and abiotic synthesis.

## Evidence-backed findings

### F1: Life detection is a contextual inference, not a molecule lookup

An atmospheric feature such as O2, O3, CH4, or a surface reflectance change can be biologically interesting, but none is automatically an observation of life. The likelihood of a feature under abiotic mechanisms can depend on stellar ultraviolet environment, atmospheric escape, photochemistry, surface chemistry, climate, mass, and geologic cycling [S1-S3]. The correct question is not simply whether a molecule exists; it is whether the joint observation is substantially more probable under a plausible living model than under credible nonliving models.

### F2: Habitability selects targets but does not determine occupancy

Habitable-zone calculations represent climate constraints under stated atmospheric and radiative assumptions [S4]. They are valuable for survey design, but a potentially temperate orbit does not establish liquid water, chemistry, persistence, or biological origin. Conversely, a subsurface ocean world or other nontraditional environment can be biologically relevant despite falling outside an orbital habitable-zone proxy. The proposal must keep target ranking distinct from a posterior claim that a world is inhabited.

### F3: Absence of a canonical atmospheric signal is not absence of life

Earth history shows that an inhabited ocean-bearing planet need not advertise life through high O2, O3, or CH4 levels at all epochs. Reinhard et al. identify mechanisms for cryptic biospheres and remote false negatives [S5]. This directly rules out a simplistic policy in which a spectrum without one gas is placed in a "lifeless" category. It instead motivates a sensitivity-aware status such as NOT_SENSITIVE_TO_DECLARED_BIOSPHERE_CLASS.

### F4: Technosignatures require an independent artifact and interference protocol

Radio and optical technosignature searches operate near extensive human radio-frequency interference and complex pipeline selection functions. Margot et al. quantify recovery efficiency and reject detections of anthropogenic origin in one large narrowband search [S7]. This does not argue against searching; it defines the evidence standard. A technosignature candidate requires on-target localization, time or frequency behavior consistent with a source model, independent re-observation, and a documented search for human and instrumental explanations.

### F5: In-situ evidence gains strength through independent, provenance-aware layers

The Ladder of Life Detection makes abiotic explanations the hypothesis of last resort and calls for suites of measurements rather than endorsement of one preferred instrument [S8]. Enceladus planning shows the complementary value of accessible ocean material, sample integrity, repeatable laboratory analysis, and planetary-protection controls [S9, S10]. A molecular pattern, isotopic anomaly, chirality measurement, and geologic context may jointly be far more diagnostic than a single observation, provided terrestrial contamination and abiotic chemistry remain active comparator hypotheses.

## Subhypotheses and coverage

**SH1 - Contextual biosignature discrimination.** A candidate feature must be assessed together with stellar, planetary, atmospheric, geologic, and temporal context. Direct evidence: S1-S3. Coverage: strong for framework and examples; incomplete for sparse spectra of real temperate terrestrial planets.

**SH2 - Sensitivity-aware negative inference.** Non-detection can constrain only a declared signal, target population, observing band, and recovery model. Direct evidence: S5 and S7. Coverage: direct for the logic; requires instrument-specific evaluation in each survey.

**SH3 - Cross-modal corroboration.** Independent data modes can reduce ambiguity when they test different abiotic and artifact pathways. Direct evidence: S1-S3 and S8-S10. Coverage: conceptual and mission-design support; cross-modal calibration is a usable gap.

**SH4 - Technosignature candidate confirmation.** A credible candidate needs repeated, localized, interference-controlled validation, not a single detection statistic. Direct evidence: S6-S7. Coverage: strong for radio-search practice; extension to every technology class remains open.

## Accepted gap ledger

| Gap ID | Accepted gap | Evidence anchors | Testable consequence |
|---|---|---|---|
| G1 | Remote biosignature studies lack a common protocol that binds sparse spectra to stellar, planetary, retrieval, and abiotic-alternative evidence before a life-oriented status is emitted. | S1-S3, S5 | Compare contextual multi-layer assessments with single-feature rules at matched sensitivity. |
| G2 | Non-detections are too often narrated as absence claims without a declared recovery efficiency, completeness region, or detectable biosphere and technology class. | S5, S7 | Require a sensitivity-and-coverage card for every negative result. |
| G3 | Biosignature, technosignature, and in-situ evidence pipelines use different confirmation vocabularies and do not share a provenance-aware falsification ledger. | S1-S3, S6-S10 | Test whether a common evidence ledger reduces untracked artifact and abiotic alternatives. |
| G4 | Target selection through a habitable-zone metric is often conflated with a probability that a target hosts life. | S4, S5 | Separate target priority from occupancy inference and quantify the effect on ranking. |
| G5 | Candidate follow-up is not systematically chosen by the observation with maximal expected ability to discriminate biology, technology, abiotic chemistry, and artifacts. | S1-S3, S6-S8 | Pre-register follow-up value for each candidate and compare with fixed follow-up rules. |

## Survey handoff

The Idea Agent is constrained to retain the distinction between life-compatible environment, candidate signal, confirmed interpretation, and sensitivity-limited null result. It must not propose a study whose apparent answer is "we are alone" from a non-detection. A selected direction must include both a biological and technological branch, define artifact and abiotic counter-hypotheses, and identify a next observation that can change the conclusion.
