# ExperimentDesign Agent: LifeTrace Study Design

## Design status

**Execution policy: DESIGN_ONLY.** This artifact defines a future research protocol. It does not run telescope observations, radio searches, laboratory assays, spacecraft operations, retrievals, synthetic-signal generation, or statistical fitting. No extraterrestrial life, biosignature, technosignature, or null result is claimed as observed by this proposal.

## Research brief

**Selected idea:** LifeTrace: A Contextual Multi-Modal Evidence Ledger for Life Detection.  
**Research object:** candidate evidence for biological or technological activity beyond Earth across remote exoplanet spectroscopy, radio or optical technosignature surveys, and in-situ ocean-world samples.  
**Central claim:** evidence should be represented as a context-and-provenance record with explicit biological, technological, abiotic, artifact, interference, and contamination hypotheses before a candidate status or negative-result constraint is released.

LifeTrace separates five outputs:

1. CONTEXT_INSUFFICIENT;
2. ABIOTIC_OR_ARTIFACT_NOT_EXCLUDED;
3. BIOLOGICAL_CANDIDATE_REQUIRES_FOLLOW_UP;
4. TECHNOLOGICAL_CANDIDATE_REQUIRES_INDEPENDENT_CONFIRMATION;
5. NEGATIVE_RESULT_SENSITIVITY_LIMITED.

None is a discovery declaration. A confirmed interpretation remains conditional on an independent human-reviewed body of evidence that excludes the relevant alternatives to the declared standard.

## Scope, safety, and human review

The design is routed to the computational-digital and mathematics-theory templates. It may later use public archives, authorized observatory products, documented simulations, and approved mission data. It must not autonomously command telescopes, transmit radio messages, select physical samples, or operate laboratory instruments. Human review is mandatory for data rights, observatory or mission policy, planetary-protection and sample-contamination implications, interference adjudication, model selection, and external communication of a candidate.

## Evidence record and formal objects

For a candidate \(c\), LifeTrace registers

\[
R_c=\{D_c,P_c,E_c,H_c,A_c,S_c,F_c\},
\]

where \(D_c\) is the measurement data, \(P_c\) is provenance, \(E_c\) is environment and observing context, \(H_c\) is the registered hypothesis set, \(A_c\) is the alternative-explanation ledger, \(S_c\) is sensitivity and recovery information, and \(F_c\) is the set of allowed follow-ups. The fields are mandatory, not optional narrative annotations.

The hypothesis set has at least

\[
H_c=\{H_{\mathrm{bio}},H_{\mathrm{tech}},H_{\mathrm{abiotic}},
H_{\mathrm{artifact}},H_{\mathrm{interference}},H_{\mathrm{contamination}}\}.
\]

Some hypotheses can be inapplicable to a specific branch, but their exclusion must be justified. Remote spectra focus on stellar, atmospheric, climate, geochemical, and retrieval alternatives. Technosignature data focus on terrestrial interference, known satellites, instrument behavior, localization, and repeatability. In-situ evidence focuses on sampling chain, blanks, terrestrial carryover, geological setting, and abiotic synthesis pathways.

For an eventual probabilistic analysis, the planned evidence update is

\[
p(H_i\mid D_c,E_c,P_c)=
\frac{p(D_c\mid H_i,E_c,P_c)p(H_i\mid E_c,P_c)}
{\sum_j p(D_c\mid H_j,E_c,P_c)p(H_j\mid E_c,P_c)}.
\]

The equation describes a design object. It does not assert that reliable priors or likelihoods already exist for all life forms or technologies. Every posterior must be accompanied by prior sensitivity, likelihood-model scope, and the strongest unexcluded alternative.

The proposed next-observation utility for follow-up \(f\) is

\[
U(f\mid c)=
\sum_{i,j} w_{ij}\,
\mathbb{E}_{D_f}\left[
\log\frac{p(D_f\mid H_i,R_c,f)}
{p(D_f\mid H_j,R_c,f)}\right]-\lambda C(f),
\]

where \(w_{ij}\) weights scientifically relevant hypothesis pairs, \(C(f)\) is operational cost or opportunity cost, and \(\lambda\) is approved before candidate analysis. This utility is a pre-registered prioritization rule, not an instruction to perform an observation.

## Variables and data branches

| Type | Construct | Operationalization | Role |
|---|---|---|---|
| Independent | Evidence modality | Remote spectrum, radio or optical signal, in-situ chemical or physical measurement | Determines evidence and artifact model |
| Independent | Context completeness | Stellar, planetary, geologic, instrument, provenance, and sensitivity fields present | H1 intervention |
| Independent | Follow-up policy | Fixed, random, expert-only, or expected-discrimination ranking | H4 intervention |
| Dependent | Candidate status | One of the five bounded LifeTrace statuses | Primary output |
| Dependent | Calibration and error control | False-candidate confidence, classification accuracy, sensitivity coverage, alternative-omission rate | Evaluation outputs |
| Control | Data release and instrument model | Versioned archive, pipeline, covariance, injection-recovery, calibration and blank-control record | Reproducibility |
| Control | Hypothesis library | Pre-registered biological, abiotic, artifact, and contamination alternatives | Prevents post hoc narrowing |

The remote branch may contain stellar spectral energy distribution and activity, orbit, radius and mass constraints, transmission, emission, or reflected-light spectra, retrieval posteriors, co-occurring gases, surface or temporal indicators, and known abiotic pathways. The technosignature branch may contain pointing, time-frequency data, drift behavior, beam pattern, on-off source checks, injection-recovery curve, interference catalog, repeat observations, and independent-observatory status. The in-situ branch may contain sample location and depth, chain of custody, blank controls, organic distributions, isotopes, chirality, mineral context, replicate measurement, and contamination controls.

## Planned evidence bundle

The design freezes the Survey source roles: broad remote biosignature and context reviews (S1-S3); habitable-zone target selection and false-negative limits (S4-S5); technosignature complementarity and recovery-controlled radio search (S6-S7); and in-situ evidence ladder, sample-return, and ocean-world detection studies (S8-S10). A future execution must add exact archive, mission, or simulation version, license, calibration files, and procedural chain. Paper abstracts and target labels are not sufficient numerical inputs.

## Procedure

### Phase 0: Pre-registration and eligibility

Register the hypothesis library, evidence-record schema, target-selection rationale, decision thresholds, recovery requirements, follow-up cost model, and release rules. Declare which candidate classes are within sensitivity. A habitable-zone field is stored as target context only; it cannot raise a candidate to a life-evidence status by itself.

### Phase 1: Branch-specific provenance and quality control

For each record, verify instrument calibration and pipeline versions. Remote data require stellar and retrieval context. Radio and optical candidates require interference and artifact screening, on-target checks, and a recovery model. In-situ measurements require provenance, blanks, replicates, geological setting, and contamination-risk fields. Records that lack mandatory controls remain CONTEXT_INSUFFICIENT.

### Phase 2: Alternative-hypothesis assessment

Build a declared likelihood or qualitative evidence matrix for every applicable hypothesis. For atmospheric data, test photochemical, escape, geochemical, cloud, haze, stellar-contamination, and retrieval-degeneracy explanations. For technosignature data, test terrestrial radio-frequency interference, satellite and aircraft pathways, instrument artifacts, sidelobes, and coincidence. For in-situ data, test abiotic organics, mineral catalysis, transport, preservation, and terrestrial contamination. A candidate remains ABIOTIC_OR_ARTIFACT_NOT_EXCLUDED whenever a registered alternative has not been discriminated.

### Phase 3: Follow-up selection

Enumerate feasible follow-ups and estimate the utility in the declared model. Examples include a new spectral band that distinguishes photolysis from biology, time-resolved spectra, independent telescope measurement, radio on-off cadence, multi-site confirmation, a different radio band, orthogonal mass-spectrometric assay, chirality measurement, isotope ratio, or context-imaging measurement. Choose the highest-utility approved follow-up only after human review of operational feasibility and safety.

### Phase 4: Negative-result interpretation

Every negative result must state signal class, target population, observing band or sample volume, sensitivity curve, injection-recovery performance, duty cycle when relevant, and coverage domain. The allowed output is NEGATIVE_RESULT_SENSITIVITY_LIMITED. The design forbids statements that no life or technology exists in an unobserved class or outside the tested completeness region.

## Comparators, ablations, and metrics

The proposed comparators are: C1, a single-feature biosignature rule; C2, a target-habitability-only ranker; C3, a radio candidate list without injection-recovery and interference ledger; C4, an in-situ signature list without provenance controls; and C5, full LifeTrace. Ablations remove environmental context, recovery cards, the common provenance ledger, the negative-result status, or utility-guided follow-up.

Evaluation uses registered synthetic cases and public benchmark records only in a future execution. The planned metrics are calibration of candidate confidence; false-positive and false-negative rate at matched sensitivity; alternative-explanation omission rate under blinded audit; recovery-curve coverage; follow-up information gain per unit approved cost; status stability under plausible priors and retrieval models; and provenance completeness. No metric is reported as measured in this design document.

## Conditional conclusions and limits

| Condition | Permitted output |
|---|---|
| Mandatory context, provenance, or recovery data absent | CONTEXT_INSUFFICIENT |
| A declared abiotic, artifact, interference, or contamination explanation remains viable | ABIOTIC_OR_ARTIFACT_NOT_EXCLUDED |
| Biological models are favored but need a registered independent discriminator | BIOLOGICAL_CANDIDATE_REQUIRES_FOLLOW_UP |
| Technological interpretation survives initial controls but lacks independent confirmation | TECHNOLOGICAL_CANDIDATE_REQUIRES_INDEPENDENT_CONFIRMATION |
| No candidate is recovered within the declared sensitivity and coverage region | NEGATIVE_RESULT_SENSITIVITY_LIMITED |

Known limits include unknown life chemistries, model-complete abiotic alternatives that may not yet be cataloged, sparse exoplanet spectra, stellar heterogeneity, selection bias, terrestrial interference, unmodeled instrumental effects, limited sample mass, contamination, and the impossibility of treating a finite search as a census of the universe. These limits belong in the model and decision record, not as reasons to make the proposal vague.

## Reproducibility deliverables

An eventual execution should release source and data manifests, evidence-record schema, hypothesis library, instrument and recovery cards, synthetic benchmark generator, alternative-explanation matrices, follow-up utility code, blinded review rubric, sensitivity maps, and a final human-reviewed status ledger. The present artifact is the research design only; observed results remain empty.
