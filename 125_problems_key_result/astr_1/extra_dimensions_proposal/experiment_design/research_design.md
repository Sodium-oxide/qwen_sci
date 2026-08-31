# ExperimentDesign Agent Output: DimensionBridge Study Design

## Design status

**Execution policy: DESIGN_ONLY.** This is a computational evidence-synthesis, likelihood-translation, and sensitivity-forecast design. It does not operate laboratory apparatus, access detector control systems, reprocess restricted events, claim a new collider/gravitational-wave/cosmological measurement, or report observed results. `observed_results = []`.

## Research brief

**Primary direction:** D3 -- DimensionBridge: A Cross-Scale Falsifiability Atlas for Extra-Dimension Models.

**Question:** Can a model-to-observable registry with explicit parameter translations, alternative explanations, and cross-channel overlap tests classify extra-dimension models more defensibly than isolated bounds or narrative summaries?

**H1 -- Translation discipline:** A constraint should change a model's status only where a traceable model-to-observable map covers the relevant parameter domain. This will prevent false global exclusion from isolated null results.

**H2 -- Complementarity discipline:** Combining genuinely overlapping but methodologically independent channels will improve the ability to classify selected parameter regions as excluded, currently compatible, sensitivity-limited, or observationally unidentifiable, compared with any one channel alone.

**H3 -- Discovery discipline:** A candidate anomaly requires an alternative-explanation and replication matrix; without it, the correct classification is not ``extra dimensions detected'' but `REQUIRES_INDEPENDENT_TEST`.

## Model registry and candidate classes

The study begins from a model registry, not a generic ``higher dimensions'' bin.

| Class | Latent parameters to record | Principal channels | Required alternative explanations |
|---|---|---|---|
| M1: ADD-like flat compact dimensions | number of extra dimensions, compactification scale/radius, fundamental gravity scale, effective-theory validity domain | short-range gravity; missing momentum; astrophysics | scalar fifth force, detector backgrounds, effective-theory truncation |
| M2: RS-like warped dimension | warp scale, curvature ratio, brane localization, resonance/coupling parameters | resonances; missing momentum; precision constraints | ordinary resonances, detector response, non-extra-dimensional new physics |
| M3: phenomenological modified propagation | crossover scale, damping/dispersion parameter, dimensional-flow ansatz | gravitational waves; multi-messenger distance comparisons | calibration, source population, cosmology, modified gravity without extra dimensions |
| M4: formal string/M-theory compactification class | compactification geometry, moduli stabilization, low-energy spectrum | indirect only unless a concrete effective map exists | model incompleteness and no accessible observable |
| M0: four-dimensional baseline | Standard-Model/GR nuisance and systematic parameters | all channels | used as common comparator |

## Data and evidence cards

The design ingests only public, citable summaries: published likelihood contours, exclusion curves, tabulated bounds, analysis selections, and data-release material when the analysis license permits. A source card records: source ID; model class; observable; parameter definition and units; detector/experiment; likelihood type or limit construction; confidence statement; nuisance/systematic assumptions; EFT/truncation conditions; and citation provenance.

Each translation from an experimental quantity to a model parameter receives a **translation card**. It distinguishes:

1. an experimentally fitted or bounded observable;
2. a derived model prediction;
3. a prior, compactification, or UV assumption;
4. a known alternative explanation; and
5. an uncertainty or inaccessible parameter region.

This prevents a laboratory Yukawa bound, for example, from being stored as if it were a direct count of compact dimensions.

## Core analysis

For model class \(M\), parameter vector \(\theta\), and channel likelihoods \(\mathcal{L}_c\), the planned joint compatibility object is

\[
\mathcal{L}_{\mathrm{joint}}(M,\theta)=\prod_{c \in \mathcal{C}_{\mathrm{compatible}}}\mathcal{L}_c\!\left(O_c\mid f_c(M,\theta),\eta_c\right),
\]

where \(f_c\) is the declared model-to-observable map and \(\eta_c\) contains channel-specific nuisance parameters. The set \(\mathcal{C}_{\mathrm{compatible}}\) excludes a channel unless parameter conventions, likelihood construction, and dependence assumptions allow a defensible combination. This equation is a future analysis structure, not a computed likelihood.

Define the coverage indicator for a parameter point as

\[
C(M,\theta)=\sum_c w_c\,I_c(M,\theta),
\]

where \(I_c=1\) only when channel \(c\) has a valid observable map and published sensitivity at \((M,\theta)\); weights \(w_c\) document independence and robustness, not perceived importance. The atlas reports coverage, overlap, and conflicts before it reports a status.

## Decision taxonomy

| Status | Meaning | Rule |
|---|---|---|
| `EXCLUDED_WITHIN_ASSUMPTIONS` | A declared model region is inconsistent with one or more valid channel likelihoods. | Every translation assumption is recorded; no conclusion extends beyond them. |
| `CURRENTLY_COMPATIBLE` | Available constraints do not exclude the specified region. | This is not positive evidence for extra dimensions. |
| `SENSITIVITY_LIMITED` | A concrete observable map exists, but present data do not reach the relevant region. | Produce a forecast requirement, not a discovery claim. |
| `OBSERVATIONALLY_UNIDENTIFIABLE` | No validated low-energy observable map or distinguishable prediction is available. | Do not rank it as empirically favored or disfavored. |
| `REQUIRES_INDEPENDENT_TEST` | A candidate excess lacks cross-channel or replication support. | Preserve alternatives and specify discriminating follow-up. |

## Stress tests and falsification

1. **Translation ablation:** remove declared compactification/warping assumptions. If a constraint remains numerically identical when its translation card is removed, the analysis has hidden a model assumption.
2. **Channel ablation:** compare single-channel and compatible cross-channel classifications. An apparent improvement driven by duplicated information or incompatible priors is invalid.
3. **Baseline injection:** simulate four-dimensional baseline pseudo-observables from published uncertainty summaries. The atlas must not manufacture an extra-dimension preference through parameter-volume effects.
4. **Alternative-model injection:** introduce a non-extra-dimensional modified-gravity, calibration, or resonance alternative. A unique attribution should disappear unless the discriminating observable is actually present.
5. **Holdout registry test:** withhold a published analysis card and test whether the framework predicts its relevant parameter/observable relation without using its final limit.

## Human review and reproducibility

Mandatory review includes phenomenologists specializing in extra dimensions and effective field theory, experimental analysts from the relevant channel, gravitational-wave/cosmology analysts for propagation mappings, and statisticians familiar with likelihood combination. The release package should contain the model registry, source cards, translation cards, machine-readable unit conventions, combination eligibility decisions, sensitivity maps, reason codes, and a record of sources excluded from joint likelihood construction.

## Safety and integrity constraints

The project has no biological, clinical, chemical, or physical-intervention execution component. Its main integrity risk is epistemic: incompatible parameterizations can be combined into a false quantitative conclusion. Therefore, the hard gates are traceability, model validity, channel-combination compatibility, and alternative-explanation coverage. Every proposed numerical forecast must be labeled future/unestimated until public likelihood data have been processed and reviewed.
