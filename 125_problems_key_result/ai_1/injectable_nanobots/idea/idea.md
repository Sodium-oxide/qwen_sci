# Idea: A Barrier-Aware Benchmark for Trigger-Gated Therapeutic Nanocarriers

## 1. Proposed contribution

The proposed study tests the most clinically plausible interpretation of an injectable disease-fighting nanobot: a nanoscale carrier that recognizes a disease-associated molecular feature, changes state when triggered, and releases a payload locally. The device is not described as a self-powered general-purpose robot. Instead, its capabilities are decomposed into transport, recognition, state change, payload action, and clearance. This vocabulary makes progress measurable and prevents a successful nanoparticle from being credited with autonomy that it does not possess.

The working name is **BARRIER-AWARE-TRIGGER-GATED-NANOCARRIER-BENCHMARK**. The benchmark compares a tumor-targeted DNA-origami nanocarrier with four controls in human vascular microfluidic models and then in a staged tumor-bearing animal study. It asks whether a molecular trigger improves target-site payload action while reducing systemic exposure after accounting for protein corona, flow, immune activation, biodistribution, batch variation, and clearance.

## 2. Functional hypothesis

The central hypothesis is:

> A nanosystem that combines disease-receptor recognition with a disease-specific opening trigger will produce a higher target-to-off-target payload exposure ratio and a larger therapeutic effect per unit systemic toxicity than the same carrier with a disabled trigger, no targeting ligand, carrier alone, or free drug.

This is deliberately narrower than the claim that a 50-100 nm robot can diagnose, navigate, sample, decide, treat, and self-destruct. If the benchmark succeeds, it supports a realistic nanobot-like therapeutic function. It does not prove general autonomy. If it fails, the failure can be assigned to transport, recognition, triggering, payload release, immune clearance, manufacturing, or disease biology rather than being hidden by the word nanobot.

## 3. Experimental hypotheses

- **H0, carrier equivalence:** the targeted trigger-gated carrier does not improve target-site payload action relative to a non-gated or non-targeted carrier after exposure is normalized.
- **H1, trigger specificity:** the targeted carrier opens and releases payload preferentially in the disease compartment, increasing target-to-off-target exposure.
- **H2, barrier penalty:** protein corona, vascular shear, extracellular matrix, or immune clearance attenuates the intended targeting and trigger response.
- **H3, translational robustness:** the effect persists across independent batches, human microvascular models, and a prespecified animal model without unacceptable immunotoxicity or organ retention.

H1 is accepted only if three measurements agree: target localization, trigger-dependent opening or payload release, and target-site pharmacodynamic action. A fluorescently localized particle without active payload is not therapeutic success. A tumor response without evidence of target localization is not proof of nanobot control. A favorable acute toxicity panel does not establish repeat-dose safety.

## 4. Function-stack representation

Each particle batch is represented by a function vector

\[
\mathbf{F}=(T,R,G,P,C,S),
\]

where $T$ is transport under flow, $R$ is receptor recognition, $G$ is trigger-gated state change, $P$ is payload delivery and pharmacodynamics, $C$ is clearance, and $S$ is safety. A proposed nanobot is not a single binary object; it is a stack whose weakest function can determine clinical performance.

The benchmark reports target and off-target exposure separately. Let $A_T$ be target-compartment payload exposure and $A_O$ be exposure in a prespecified off-target compartment. A useful targeting index is

\[
TI_{\mathrm{exposure}}=\frac{A_T}{A_O+\epsilon},
\]

where $\epsilon$ is a preregistered small stabilizer. A pharmacodynamic targeting index is

\[
TI_{\mathrm{PD}}=\frac{\Delta Y_T}{\Delta Y_O+\epsilon},
\]

where $\Delta Y$ is the disease-relevant response. Safety is incorporated separately through cytokines, complement, hematology, organ injury, histology, and repeat-dose recovery. A large exposure ratio with no disease response is not sufficient; a disease response with systemic toxicity is not a therapeutic improvement.

## 5. Why human-relevant flow comes first

Static cell binding overestimates targeting because it omits shear, protein corona, variable receptor density, and competing cells. The first stage uses human endothelial and tumor microenvironment microfluidic models with controlled flow, plasma or serum, disease-receptor gradients, and an off-target vascular compartment. The device is tracked by fluorescence, microscopy, and chemical payload assays. Trigger activation is measured independently from particle localization.

The low-Reynolds-number transport problem is explicit. For a nanosystem of radius $a$ in fluid viscosity $\mu$, the drag is

\[
F_d=6\pi\mu aU,
\]

and the diffusion coefficient is

\[
D=\frac{k_BT}{6\pi\mu a}.
\]

The assay estimates arrival probability, residence time, binding under flow, opening probability, payload release, and loss to nonspecific surfaces. These are more clinically useful than a claim that the particle follows a programmed trajectory.

## 6. Safety-centered novelty

The benchmark treats safety as a mechanism-level endpoint. The trigger is designed to open in a disease context, but off-target opening is measured in normal endothelium, liver-like cells, immune cells, and plasma. Protein corona composition is characterized because it can mask ligands and change clearance. Innate immune activation includes complement, cytokines, monocyte and macrophage uptake, and platelet interactions. Repeat-dose studies test antibodies, accelerated clearance, hypersensitivity, organ retention, and delayed tissue injury.

For a thrombin-like or vaso-occlusive payload, the key safety endpoint is not merely body weight. It includes coagulation markers, platelet activation, microvascular injury, liver and kidney function, and histological evidence of off-target thrombosis. A rescue plan is defined before dosing. The payload mechanism is chosen to match the disease model, and the experiment stops if predefined systemic injury thresholds are crossed.

## 7. Expected information gain

The benchmark can distinguish several scientifically valuable outcomes. If targeting and triggering work in buffer but fail under plasma flow, the barrier model is the limiting function. If localization is preserved but payload effect is absent, the trigger or pharmacodynamics is limiting. If target-site action improves but immune activation increases, the platform has a benefit-risk tradeoff rather than a simple success. If batch variation dominates, manufacturing is the barrier. If efficacy and safety replicate across species, the platform earns a translational milestone, not a claim of a universal injectable robot.

## 8. Falsification criteria

The nanobot-like therapeutic claim is considered unsupported if the trigger-gated carrier does not outperform the strongest matched control on the preregistered joint endpoint, if opening occurs in off-target tissues at comparable frequency, if the target response is not payload-dependent, if the effect disappears across independent lots, or if repeat-dose immune and organ toxicity exceed the safety boundary. A negative result at one target does not prove that all nanocarriers are impossible; it identifies the failed function stack for the tested design.

## 9. Handoff to ExperimentDesign

The experimental design must specify carrier composition and critical quality attributes, control arms, human microfluidic models, biodistribution methods, trigger and payload assays, immune and toxicity panels, staged animal escalation, randomization and blinding, batch replication, statistical endpoints, rescue and stopping rules, and the regulatory boundary between a research construct and a drug candidate. No human efficacy or clinical safety result may be claimed.
