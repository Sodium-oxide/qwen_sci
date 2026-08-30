# ExperimentDesign Agent — Design-Only Research Protocol

## 1. Research brief

**Selected direction:** D2, *Beyond the Current Pigment Library: A Calibrated Multiobjective Search for New Usable Reflectance Signatures.*

**Research question:** For a declared reference pigment library, can an uncertainty-aware, safety-constrained multiobjective selection policy identify future authorised test candidates that pass a preregistered practical-novelty gate more efficiently than random and color-distance-only selection?

**Central hypothesis:** A Pareto acquisition policy that jointly uses spectrum-derived colour metrics, spectral functionality, stability/feasibility proxies, composition constraints, and uncertainty will produce a higher novelty-gate pass rate than prespecified baselines.

**Execution policy:** `DESIGN_ONLY`. This protocol does **not** synthesise materials, operate instruments, collect specimens, execute simulations, or report observed results.

## 2. Scope and safety gate

This is a computational-and-characterisation planning template for non-clinical materials research. It must be activated only after a qualified materials chemist, institutional safety process, and site-specific waste/environmental review approve the candidate family and any physical work. The pipeline must automatically exclude or route for expert review any candidate involving regulated, highly toxic, unstable, or otherwise inappropriate constituent classes under the governing institution's rules.

The proposed study does not prescribe reagent quantities, temperatures, synthesis steps, or handling instructions. A future authorised team may add those details only in a separate, institution-approved experimental protocol.

## 3. Operational definition of practical pigment novelty

Let the reference library be \(\mathcal{R}\), containing measured reflectance spectra \(R_j(\lambda)\) and metadata for pigments relevant to a named application. Let a candidate have spectrum \(R_c(\lambda)\). Under illuminant \(I\) and observer \(O\), calculate CIE coordinates \(\mathbf{z}_{c,I,O}\) and \(\mathbf{z}_{j,I,O}\). A candidate is **not** called a discovery solely because it is compositionally new.

A future measured candidate passes the practical-novelty gate only if all conditions are met:

1. **Spectral separation:** it exceeds a preregistered spectrum-distance threshold from the nearest appropriate member of \(\mathcal{R}\), with an explicit normalization and wavelength interval.
2. **Perceptual separation:** its minimum CIEDE2000 distance to eligible references exceeds an application-defined threshold under a primary illuminant and remains above a lower robustness threshold under a secondary illuminant.
3. **Utility/constraint gate:** it meets application-specific engineering proxy targets and is not excluded by composition, safety, or environmental review.
4. **Uncertainty gate:** prediction uncertainty is below a preregistered review threshold before scarce characterisation capacity is assigned.
5. **Replicate/traceability gate:** future measurements are repeated under documented preparation and viewing conditions; failure of this gate yields an inconclusive, not a positive, result.

This definition deliberately separates **predicted frontier extension**, **measured gate pass**, **expert-reviewed candidate**, and **commercial pigment**.

## 4. Data model and variables

| Variable family | Symbol / type | Definition | Planned source | Status |
|---|---|---|---|---|
| Candidate identity | `candidate_id` | Immutable ID and provenance | Curated structure/composition record | Required |
| Structural descriptors | \(\mathbf{x}\) | Composition, local coordination, symmetry, structure features | Curated computation/database | Required |
| Spectrum | \(R(\lambda)\) | Reflectance on declared wavelength grid | Reference measurement or approved future measurement | Required |
| Colour coordinates | \(L^*,a^*,b^*\) | Derived under named illuminant/observer | Deterministic calculation from spectrum | Required |
| Perceptual novelty | \(d_{\mathrm{CIE}}\) | Minimum CIEDE2000 distance to eligible library member | Derived | Required |
| Spectral novelty | \(d_{\mathrm{spec}}\) | Nearest-library normalized spectral distance | Derived | Required |
| Function proxy | \(f_{\mathrm{NIR}}\) | Declared near-infrared or thermal-use proxy if relevant | Derived / measured later | Conditional |
| Feasibility proxy | \(s\) | Stability/processing proxy with uncertainty | Model or vetted records | Conditional |
| Constraint status | `constraint_flag` | pass / review / exclude with reason | Rules + human review | Required |
| Predictive uncertainty | \(u\) | Calibrated interval or ensemble spread | Model | Required |
| Outcome state | `evidence_state` | predicted / measured / reviewed / rejected | Stage ledger | Required |

Confounders include particle size distribution, concentration, binder/matrix, surface texture, measurement geometry, calibration standard, illumination, observer model, batch history, and incomplete reference coverage. The future study must either control, stratify, or explicitly model these variables.

## 5. Proposed workflow

### WP1 — Reference atlas and data-quality audit

Assemble a representative reference library before candidates are ranked. Each record must keep the raw spectrum, wavelength grid, instrument/viewing metadata, material identity, preparation/matrix information, intended application, provenance, and any missing fields. Harmonise wavelength grids only through documented interpolation; never silently merge spectra measured under incompatible geometry. Create a hold-out split that prevents trivial near-duplicate leakage across composition/structure families.

**Exit condition:** The study has a versioned reference set, a data dictionary, missingness report, and a declared eligible comparator subset. If these do not exist, no novelty score may be reported.

### WP2 — Deterministic colourimetric and spectrum metrics

For every spectrum, compute tristimulus values with a named CIE observer and illuminant, then calculate chromaticity/CIELAB coordinates and CIEDE2000 distances. Store the raw spectrum alongside all derived values. At least two illuminants are required: a primary application condition and a secondary robustness condition. Use a predeclared normalized spectrum-distance measure, such as a weighted root-mean-square distance over the documented grid, plus a sensitivity analysis over reasonable weighting choices.

**Exit condition:** Deterministic calculations reproduce from the stored spectra and metadata. A failing record is quarantined, not imputed as a positive candidate.

### WP3 — Constraint filtering and human-review queue

Apply a transparent rule list to create `pass`, `review`, and `exclude` labels. The automated stage can recognize missing metadata or policy matches but cannot determine chemical safety on its own. All borderline candidates enter an expert-review queue. The published study must retain the number and reason of exclusions so that the apparent frontier cannot be inflated by silently hiding unsuitable materials.

**Exit condition:** Every remaining candidate has a recorded constraint state and reviewer accountability path.

### WP4 — Calibrated prediction and Pareto acquisition

Train a baseline colour-distance model and a multioutput model that predicts \(d_{\mathrm{CIE}}\), \(d_{\mathrm{spec}}\), selected function/stability proxies, and uncertainty. Use group-aware validation to estimate calibration and out-of-distribution degradation. Rank candidates by constrained Pareto dominance and a batch-diversity term; do not collapse objectives into an unexplained single score.

The acquisition utility is specified conceptually as

\[
U(c)=\mathbb{I}_{\mathrm{eligible}}(c)\;A\big(d_{\mathrm{CIE}},d_{\mathrm{spec}},f_{\mathrm{NIR}},s,u,\mathrm{diversity}\big),
\]

where \(\mathbb{I}_{\mathrm{eligible}}\) is zero for excluded candidates and \(A\) is disclosed before selection. The actual model family and hyperparameters must be frozen before the future hold-out evaluation.

**Exit condition:** The model meets preregistered calibration and baseline-comparison criteria. Otherwise the study reports the model failure and returns only the reference atlas.

### WP5 — Future authorised characterisation and decision audit

Only a separately approved laboratory protocol may characterise a ranked batch. The experiment plan calls for blinded reference comparisons where practicable, documented repeat measurements, raw-spectrum retention, calibration records, and both positive and negative candidate ledgers. The design does not predict how many candidates will pass.

**Exit condition:** A future candidate can be promoted from `predicted` to `measured` only when its raw data, conditions, and quality controls are archived. It can be promoted to `reviewed` only after expert assessment. “Commercial pigment” is an external status requiring manufacturing, regulatory, and application validation beyond this research plan.

## 6. Baselines, outcomes, and decision rules

### Baselines

1. **B0 Random eligible selection:** sample from the constraint-passing pool with the same batch size.
2. **B1 Colour-only selection:** rank solely by predicted distance from the closest reference coordinate under the primary condition.
3. **B2 Spectrum-only selection:** rank solely by normalized spectrum distance.
4. **B3 Atlas-only audit:** no predictive ranking; quantify coverage and uncertainty.

### Primary endpoint

The future primary endpoint is the proportion of selected, authoritatively measured candidates that pass every preregistered practical-novelty gate. The comparison is D2 versus B0 and B1 at equal selection budgets. No endpoint is observed in this artifact.

### Secondary endpoints

- Calibration error and coverage of uncertainty intervals on a group-held-out set.
- Hypervolume or coverage improvement of the measured Pareto frontier relative to the reference library.
- Cross-illuminant retention of perceptual separation.
- Diversity of selected composition/structure families.
- Fraction of selected candidates later routed to human review or excluded.
- Negative-result completeness: fraction of characterisation records with raw spectra and decision state.

### Failure criteria

The study must report a null or negative result if the primary comparison is not favourable, if uncertainty is miscalibrated, if review excludes the apparent winners, or if the reference library changes enough to remove apparent novelty. These are valuable outcomes because they state where the current pigment frontier has not been extended.

## 7. Reproducibility and reporting contract

Every future run must publish or archive, as permitted: a dataset card, data license/provenance, preprocessing code, split identifiers, metric formulas, model configuration, uncertainty method, frozen reference-library version, candidate state ledger, and raw/processed spectra for measured candidates. Every results table must label values `predicted`, `measured`, `reviewed`, or `not_available`. The final manuscript must include the sentence: **“This study evaluates material candidates relative to a stated reference library; it does not claim a new fundamental human colour.”**

## 8. Required human reviews

| Review | Trigger | Decision authority |
|---|---|---|
| Chemical safety and waste | Any physical measurement or synthesis proposal | Qualified institutional safety process |
| Environmental/composition constraints | Candidate uses restricted or uncertain constituent class | Domain expert with institutional policy |
| Colour measurement validity | Geometry, calibration, or metadata are incomplete | Colorimetry expert |
| Materials interpretation | Model predicts a frontier extension | Materials scientist |
| Claim wording | Any request to call a candidate “new” | Joint scientific/editorial review |
