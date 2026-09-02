# ExperimentDesign: Barrier-Aware, Trigger-Gated Therapeutic Nanocarrier Benchmark

## 1. Design objective and scope

This protocol tests a narrow, clinically interpretable version of an injectable disease-fighting nanobot: a nanoscale carrier that recognizes a disease-associated feature, undergoes a defined trigger-dependent state change, and releases a payload at the target site. It does not test a self-powered general-purpose robot that independently diagnoses, navigates, samples, decides, treats, and exits the body. That stronger claim requires a different engineering program.

The study is design-only. No efficacy, biodistribution, immune, toxicity, or clinical result is claimed. All thresholds and animal escalation decisions are to be finalized in a preregistration after assay validation and veterinary review. The primary disease model is a vascularized solid-tumor model because the 2018 DNA nanorobot study provides a relevant preclinical precedent, but the logic is generalizable to other diseases after the target, payload, and rescue plan are changed.

## 2. Candidate and function stack

The candidate is a DNA-origami or equivalent programmable nanosystem with five declared modules: a targeting ligand, a molecular gate, a payload compartment, a traceable label, and a degradation or clearance design. The candidate must be characterized before biological testing. It is not called a robot merely because it has a nanoscale shape. The report records whether it has autonomous motion, externally biased transport, molecular recognition, computation, active state change, and controllable recovery.

Each batch is represented by

\[
\mathbf{F}=(T,R,G,P,C,S),
\]

where $T$ is transport, $R$ is recognition, $G$ is trigger gating, $P$ is payload action, $C$ is clearance, and $S$ is safety. The weakest function can determine the outcome. A particle that binds but does not release payload is not a therapeutic robot; a particle that releases payload but accumulates in liver and spleen may have an unacceptable risk profile.

Critical quality attributes include size distribution, shape integrity, surface ligand density, gate integrity, payload loading, release kinetics, aggregation, endotoxin or bioburden, sequence or composition identity, label stability, storage stability, and degradation products. Batch identity is blinded during performance tests. At least independent production lots are required, with the exact lot count selected by a reproducibility simulation before the main study.

## 3. Experimental arms

The benchmark contains five core arms and a diagnostic assay control:

| Arm | Design | Purpose |
|---|---|---|
| TG-targeted | target ligand plus active molecular gate and payload | full candidate function |
| T-disabled | target ligand with gate disabled or locked | separates targeting from gated release |
| NT-gated | no target ligand with active gate and payload | tests trigger without active targeting |
| Carrier-only | target ligand and gate but no active payload | measures carrier and trigger effects |
| Free drug | payload without nanosystem | establishes standard exposure and efficacy comparator |
| Assay controls | labeled standards, blank carrier, and positive release control | validates localization, opening, and payload assays |

The candidate and controls are matched for payload amount, label, buffer, injection vehicle, and relevant physicochemical attributes where possible. The free-drug arm is dose-matched on active payload, while carrier-only is dose-matched on particle material. The T-disabled arm is especially important: if it performs similarly to TG-targeted, the gate is not contributing to efficacy. The NT-gated arm tests whether apparent benefit is caused by a general trigger response rather than target recognition.

## 4. Stage 0: quality and assay qualification

Stage 0 uses no animals. It verifies the batch and assay stack. Size and morphology are measured with orthogonal methods. Payload loading and release are measured by an independent chemical assay and by the optical or imaging label. The gate is challenged with target-positive and target-negative matrices. Aggregation is tested in buffer, plasma, and serum under storage and assay time scales.

Protein corona is profiled after incubation in human plasma or serum, because the biological identity of an injected nanosystem can differ from its manufacturing identity. Complement activation, cytokine release, platelet interaction, and uptake by human monocyte-derived macrophages are measured in vitro. A trigger is accepted only if the opening ratio in target-positive conditions exceeds the target-negative ratio by a preregistered margin and if spontaneous opening in plasma remains below the safety boundary.

Assay qualification includes matrix effects, recovery, limit of detection, dynamic range, inter-day precision, and analyst blinding. The experiment uses separate aliquots for localization, gate opening, payload concentration, and immune assays so that one destructive assay does not obscure another. All failed qualification runs are logged and retained.

## 5. Stage 1: human vascular microfluidic barrier model

The first functional test uses human endothelial cells and tumor-microenvironment components in a flow-controlled microfluidic model. The model includes a target-positive vascular compartment, a target-negative vascular compartment, plasma or serum, and an extracellular matrix or tissue compartment appropriate to the selected tumor model. Flow rates cover the declared physiological range rather than a single convenient static condition.

The low-Reynolds-number transport is modeled explicitly. For radius $a$, fluid viscosity $\mu$, and speed $U$, the drag is

\[
F_d=6\pi\mu aU,
\]

and the diffusion coefficient is

\[
D=\frac{k_BT}{6\pi\mu a}.
\]

The study measures arrival probability, residence time, target binding, nonspecific adhesion, internalization, gate opening, payload release, and cell response. The Péclet number

\[
Pe=\frac{UL}{D}
\]

is reported to indicate whether directed flow or diffusion dominates in each chamber. A nanosystem is not expected to follow a macroscopic trajectory; its relevant transport output is the probability of reaching and remaining in a disease compartment.

Localization is measured separately from function. Fluorescence or another traceable label determines particle position, while a chemically distinct payload assay determines release. A disease-relevant endothelial or tumor-cell response is measured after free payload, carrier-only, and gate-disabled controls. The primary microfluidic endpoint is a preregistered combination of target-to-off-target payload exposure and trigger specificity.

## 6. Stage 2: ex vivo blood compatibility

Before animal dosing, the candidate is exposed to blood or plasma from multiple donors under controlled temperature and flow conditions. The panel measures protein-corona composition, complement activation, cytokine release, platelet activation, hemolysis, coagulation time where the payload could affect coagulation, and uptake by monocytes or macrophages. Donor-to-donor variation is retained as a random effect.

The test is especially strict for vaso-occlusive payloads such as thrombin. The 2018 tumor study used thrombin to induce tumor-vessel thrombosis; that mechanism cannot be treated as a generic safe payload. Platelet activation, fibrin formation, microvascular injury markers, and off-target coagulation are measured before any escalation. A systemic coagulation signal above the veterinary and safety boundary stops the program or requires a redesigned payload.

## 7. Stage 3: staged animal study

Only a candidate that passes assay, flow, and blood gates proceeds to a randomized, blinded animal study. The study uses a prespecified tumor-bearing mouse model with target-positive tumors and appropriate healthy-tissue controls. Animals are randomized by block, sex where relevant, baseline tumor burden, and treatment day. Allocation and imaging analysts are separate from dosing personnel. The primary animal study uses all five core arms, with the sample count determined by a preregistered power simulation based on the target pharmacodynamic effect and safety variance.

The first animal cohort is a biodistribution and safety cohort, not an efficacy cohort. It measures plasma exposure, target tumor exposure, liver and spleen accumulation, kidney and lung distribution, clearance, degradation, cytokines, complement, hematology, organ injury, histology, and trigger opening in target and off-target tissues. The label is checked for dissociation from the carrier. Payload concentration is measured independently of label intensity.

The second cohort tests pharmacodynamic action and efficacy only if the first cohort meets the safety gate. Endpoints include target-site payload action, tumor perfusion or vascular response, tumor growth trajectory, survival or humane endpoint as appropriate, and systemic toxicity. The endpoint is compared with free drug and with the gate-disabled carrier. If the target-site effect is not payload-dependent, the result is not credited to the nanocarrier.

Repeat-dose evaluation is a separate gate. It measures anti-carrier antibodies, complement reactivation, altered clearance, hypersensitivity, organ retention, delayed injury, and loss of efficacy. A single tolerated dose is insufficient for a platform likely to require repeated treatment.

## 8. Stage 4: conditional large-animal translation

Large-animal testing is not automatic. It begins only if the candidate has reproducible batch performance, target-to-off-target exposure, disease pharmacodynamics, and acceptable repeat-dose safety in the earlier stages. The large-animal study is designed around anatomy, blood volume, vascular flow, immune response, and clinical monitoring that are relevant to the intended human indication. It is not used to manufacture a positive result after an unsuccessful mouse experiment.

The large-animal protocol requires independent veterinary review, a rescue plan, stopping rules, pharmacokinetic sampling, immune monitoring, organ imaging, and pathology. If the candidate depends on external magnetic, acoustic, or optical actuation, the human-scale field or exposure geometry must be modeled and measured before dosing. A system that cannot deliver the required field without tissue heating, interference, or poor spatial precision does not pass the translation gate.

## 9. Endpoints and statistical model

Let $A_T$ denote target-compartment payload exposure and $A_O$ off-target exposure. The exposure targeting index is

\[
TI_{\mathrm{exp}}=\frac{A_T}{A_O+\epsilon},
\]

where $\epsilon$ is fixed before analysis. Let $\Delta Y_T$ and $\Delta Y_O$ be target and off-target pharmacodynamic responses. The pharmacodynamic index is

\[
TI_{\mathrm{PD}}=\frac{\Delta Y_T}{\Delta Y_O+\epsilon}.
\]

The primary analysis uses a hierarchical mixed-effects model with fixed treatment arm and time, and random effects for batch, donor or animal block, and laboratory. It jointly models localization, opening, payload, pharmacodynamics, and toxicity. The candidate is superior only if it improves target action relative to free drug or matched carrier controls without exceeding the safety boundary.

For a hypothesis $H_j$, the evidence is

\[
p(D\mid H_j)=\int p(D\mid\vartheta_j,H_j)p(\vartheta_j\mid H_j)d\vartheta_j.
\]

The main contrast is between the full trigger-gated mechanism and the strongest non-gated or non-targeted explanation:

\[
BF_{\mathrm{TG,control}}=\frac{p(D\mid H_{\mathrm{trigger}})}{p(D\mid H_{\mathrm{control}})}.
\]

Priors, minimum effect sizes, missing-data rules, and decision thresholds are preregistered. A frequentist companion analysis reports confidence intervals and upper limits. Multiple endpoints are ordered hierarchically; exploratory endpoints do not override the primary decision.

## 10. Decision gates and falsification

The program has five gates:

1. **Quality gate:** particle identity, size, morphology, payload, gate integrity, sterility or bioburden, and batch stability pass release criteria.
2. **Barrier gate:** target-to-off-target transport and trigger specificity persist in human plasma flow models.
3. **Blood gate:** complement, cytokine, platelet, hemolysis, and coagulation effects remain within the declared boundary.
4. **Animal gate:** target-site payload action and disease response replicate under blinded randomization without unacceptable organ or immune toxicity.
5. **Translation gate:** repeat-dose safety, manufacturing comparability, clearance, monitoring, rescue, and human-scale deployment constraints are addressed.

The nanobot-like claim is falsified for the tested candidate if the full carrier is not superior to the strongest matched control, if gate opening is not target-specific, if target response is independent of payload, if benefit disappears across lots, if systemic exposure or immune activation exceeds the safety boundary, or if the effect cannot be reproduced in an independent laboratory. A negative result identifies a failed function stack; it does not prove that every nanosystem is impossible.

## 11. Ethics, safety, and data governance

All animal work requires institutional animal-care approval, humane endpoints, analgesia where applicable, and independent veterinary oversight. The study uses the minimum number of animals justified by power simulation and stops for predefined toxicity. Plasma and human-cell work requires appropriate biosafety and donor-consent governance. Manufacturing includes endotoxin, sterility or bioburden, and residual-reagent controls.

Raw images, particle characterization, flow conditions, protein-corona data, assay calibration, biodistribution files, sample custody, exclusions, and analysis code are archived. The treatment code is opened only after the data lock. Any deviation from the protocol is time-stamped and reported. A clinical translation claim is not made from an animal result alone; it requires a product-specific regulatory and manufacturing package.

## 12. Design-only boundary

The expected outputs are a validated assay protocol, transport and trigger measurements, preclinical biodistribution, efficacy and safety estimates, and a reproducibility assessment. Since no experiments have been run in this workflow, all expected and observed result fields remain empty. Human efficacy, human safety, autonomous navigation, and commercial feasibility are not inferred.
