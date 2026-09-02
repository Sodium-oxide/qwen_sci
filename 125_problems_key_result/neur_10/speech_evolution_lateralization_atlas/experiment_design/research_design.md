# ExperimentDesign: PDSCEA

## Design status

This is a preregistration-ready research design. It is **DESIGN_ONLY**: no data have been collected, no model has been fitted, and `observed_results` is intentionally empty. The design is intended to test a mechanistic synthesis about speech evolution, not to claim that the historical sequence of evolution has already been observed.

## Research question and predictions

The operational question is whether conserved primate communication-signal representations, human auditory-motor connectivity, developmental network lateralization, and speech-specific temporal coupling jointly explain learned vocal control better than isolated-region or isolated-gene accounts.

The primary prediction is a graded one: (P1) humans and nonhuman primates will share a limited representational geometry for communication signals; (P2) human speech learning and speech motor control will be associated with the strength and topology of auditory-to-articulatory connections; (P3) leftward language specialization will increase for many participants across development while retaining bilateral and atypical subgroups; and (P4) speech will produce more specific auditory-motor temporal coupling than matched non-speech and generic motor tasks.

The evolutionary interpretation is supported only if these predictions form a coherent model across datasets. A significant result in one modality alone is not sufficient.

## Cohorts and data layers

### Human cross-sectional and developmental layer

The human layer will combine an adult neuroimaging cohort with a developmental cohort. The adult target is 240 participants balanced as far as feasible for sex, handedness, and language background. The developmental target is 180 participants, ages 5–17, with three age bands and a one-year repeat scan for a subset of 90 participants. Existing openly available datasets may replace or supplement recruitment if their task, imaging, and consent metadata satisfy the preregistered criteria.

The design does not assume that a single spoken language represents all speech. Language background is recorded, and lexical-semantic effects are separated from acoustic-phonetic and motor effects through nonword and syllable conditions.

### Comparative primate layer

The comparative layer uses existing nonhuman-primate functional imaging or electrophysiology where available, supplemented only by approved studies with the smallest feasible sample and no human-like speech training claim. The minimum inclusion criteria are: species identity, individual vocalization labels, acoustic stimulus metadata, anatomical localization, and a non-vocal auditory control. The primary comparison is representational geometry, not absolute BOLD magnitude, because cross-species hemodynamic and scanner differences are substantial.

### Measurement layers

1. Structural MRI and diffusion MRI estimate cortical anatomy and auditory-frontotemporal tract organization.
2. Resting-state and task fMRI estimate network organization and language lateralization.
3. EEG or MEG estimates the timing of speech-envelope tracking, phase-locking, and auditory-motor coordination.
4. Acoustic and kinematic recordings quantify phoneme timing, voice onset, pitch control, lip/jaw motion, and respiratory timing.
5. Genotype or family structure is used only as a covariate or variance component when consent permits; FOXP2 is not treated as a deterministic predictor.

## Task battery

Human tasks include: (T1) natural speech comprehension; (T2) nonword and syllable discrimination; (T3) overt and covert articulation; (T4) delayed vocal imitation; (T5) non-vocal environmental sounds; (T6) pure-tone and spectrally rotated speech controls; (T7) generic oro-facial movement controls; and (T8) a mild, reversible auditory-feedback perturbation such as delayed or frequency-shifted feedback within approved safety limits.

Primate tasks include conspecific vocalizations, individual-identity vocalizations, heterospecific vocalizations, non-vocal natural sounds, and matched acoustic controls. No task is interpreted as language comprehension. The purpose is to test conserved communication-signal representations and their relation to auditory pathways.

## Regions and network representation

The preregistered atlas includes primary and belt auditory cortex, superior temporal plane and sulcus, anterior temporal voice-sensitive cortex, inferior frontal and premotor regions, ventral and dorsal sensorimotor representations of lips, tongue and larynx, insula, supplementary motor area, basal ganglia, cerebellum, and frontotemporal white-matter pathways including the arcuate and superior longitudinal systems. Region labels are linked to probabilistic homologues rather than one-to-one anatomical assertions.

## Mathematical model

For participant or animal (i), task (t), region or network feature (d), define the response model

\begin{equation}
Y_{i d t}=\beta_0+\beta_1\mathrm{Species}_i+\beta_2\mathrm{Age}_i+\beta_3\mathrm{Hemisphere}_d+\beta_4\mathrm{Task}_t+\beta_5\mathrm{Connectivity}_{i d}+\beta_6\mathrm{Species}_i\mathrm{Age}_i+\beta_7\mathrm{Task}_t\mathrm{Connectivity}_{i d}+u_{\mathrm{site}}+u_i+\epsilon_{i d t}.
\label{eq:hierarchical}
\end{equation}

Here (Y) is a preregistered neural or behavioral outcome, (u_{\mathrm{site}}) is a site-level random effect, (u_i) is a participant or animal random effect, and (\epsilon) is residual error. The interaction terms test whether connectivity and development alter the species and task effects. The primary model is compared with nested single-region, no-development, and no-connectivity models using out-of-sample predictive performance and a complexity penalty.

For each bilateral feature, lateralization is summarized by

\begin{equation}
LI_{i d t}=\frac{L_{i d t}-R_{i d t}}{|L_{i d t}|+|R_{i d t}|+\varepsilon},
\label{eq:lateralization}
\end{equation}

where (L) and (R) are left- and right-hemisphere estimates, and (\varepsilon) prevents instability near zero. Positive values indicate leftward relative response and negative values indicate rightward relative response; the sign is not treated as a value judgment.

For EEG/MEG, phase-locking value at frequency (f) is defined as

\begin{equation}
PLV_{r}(f)=\left|\frac{1}{N}\sum_{k=1}^{N}\exp\left(j[\phi_{r,k}(f)-\phi_{s,k}(f)]\right)\right|,
\label{eq:plv}
\end{equation}

where (\phi_{r,k}) and (\phi_{s,k}) are the phases of two preregistered signals in trial (k), (N) is the number of trials, and (j) is the imaginary unit. Speech-specific coupling is estimated as the contrast between speech and matched non-speech or generic movement conditions, with surrogate phase controls for volume conduction and stimulus regularity.

To test whether connectivity mediates developmental and species effects on speech learning, the design estimates

\begin{align}
M_i&=a_0+a_1\mathrm{Age}_i+a_2\mathrm{Species}_i+a_3\mathrm{Family}_i+u_i+e_i,\nonumber\\
Y_i&=c'_0+c'_1\mathrm{Age}_i+c'_2\mathrm{Species}_i+c'_3M_i+c'_4\mathrm{Handedness}_i+v_i+\eta_i,
\label{eq:mediation}
\end{align}

where (M) is auditory-motor connectivity, (Y) is speech-learning or speech-control performance, (a_3) captures the association between the mediator and the outcome, and (c'_3) is not interpreted as causal without the preregistered perturbation analysis. Family structure enters as a variance component or covariate rather than as a claim of simple genetic determinism.

## Cross-species representational alignment

For each species, condition-by-condition neural patterns are converted to a representational dissimilarity matrix (RDM). Human and primate RDMs are compared after anatomical and acoustic controls. The primary cross-species result is an alignment statistic above the distribution obtained from non-vocal control RDMs and label-preserving permutations. A positive alignment does not imply identical subjective experience, language, or cognitive meaning; it indicates shared structure in measured neural responses.

## Analysis sequence and controls

The analysis sequence is fixed before outcome inspection: quality control, preprocessing, atlas registration, task contrasts, lateralization indices, connectivity estimation, temporal coupling, cross-species RDM analysis, hierarchical model fitting, and held-out prediction. Site, age, sex, handedness, hearing status, motion, language background, and task difficulty are modeled or balanced. Speech acoustics are matched to non-speech controls for intensity, duration, and envelope where possible.

The study reports both positive and null results. Multiple comparisons are controlled within each preregistered family of tests. Missingness and exclusion thresholds are reported before model fitting. A robustness set repeats the main analysis with alternative parcellations, excluding high-motion participants, and using bilateral rather than unilateral features.

## Falsification and decision rules

PDSCEA is weakened or rejected if any of the following occurs after preregistered quality control: (1) cross-species communication-signal alignment does not exceed matched non-vocal controls; (2) auditory-motor connectivity does not predict speech learning or control beyond single-region activity; (3) the developmental lateralization trajectory is absent or is fully explained by handedness; (4) speech-specific dynamic coupling disappears under acoustic and movement controls; or (5) a single-region or FOXP2-only baseline predicts held-out outcomes as well as or better than the integrated model under the prespecified penalty.

Conversely, the integrated hypothesis is strengthened when conserved representations, developmental lateralization, connectivity, and temporal coupling replicate across sites and each contributes incremental held-out predictive value. This would support the proposed mechanism without proving a unique historical pathway.

## Safety, ethics, and reproducibility

Human work requires informed consent or guardian consent plus child assent, institutional review, privacy-preserving data handling, hearing safety, and a reversible feedback perturbation. Primate data should preferentially be reused from existing approved datasets; any new work requires species-specific welfare review and must not frame animals as failed human speakers. No invasive procedure is required for the core human design.

The preregistration stores stimulus hashes, atlas versions, preprocessing parameters, exclusion rules, model formulas, contrast definitions, and analysis code. Raw identifiable data remain under the originating consent and governance rules. Released derivative data must remove facial and voice identifiers when required.

## Expected outputs

The design will produce a cross-species speech-circuit atlas, a developmental lateralization trajectory, estimates of auditory-motor connectivity and temporal coupling, model-comparison tables, and a falsification report. These are planned outputs; no observed values are supplied in this handoff.
