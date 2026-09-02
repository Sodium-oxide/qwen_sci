# Idea: A Blinded, Product-Linked Evidence Chain for Cold Fusion

## 1. Proposed contribution

The proposed study is not a search for an interesting temperature trace. It is a preregistered evidence-chain experiment that tests whether a defined palladium-deuterium electrochemical state produces a nuclear signal that is simultaneously calorimetric, product-linked, reproducible, and compatible with reaction physics. The working name is **BLINDED-PRODUCT-LINKED-REPLICATION**.

The key design choice is to make heat and nuclear products jointly necessary for a strong claim. The experiment continuously measures excess power, deuterium loading, electrical input, gas composition, neutron and gamma counts, tritium, helium isotopes, and post-run material changes. A central analysis server receives blinded run labels and fixed metadata before unblinding. Independent laboratories receive identical material lots, construction specifications, calibration artifacts, and control schedules. No laboratory may select a stopping time after viewing the outcome.

This idea addresses the field's central failure mode: a small heat anomaly can arise from chemistry, recombination, thermal drift, gas handling, or calibration error, while a low-count detector can create an apparent nuclear excess through background fluctuation or contamination. A true nuclear process must create a constrained pattern across observables. The study therefore asks whether the entire vector of observations is more probable under a nuclear-process model than under a calibrated null model.

## 2. Hypotheses

The hypotheses are deliberately layered rather than binary.

- **H0, measurement null:** after calibration and control adjustment, no excess heat or nuclear-product signal exists beyond instrument noise and known background.
- **H1, chemical/thermal artifact:** apparent excess power is explained by recombination, electrochemical enthalpy, evaporation/condensation, electrical lead heating, thermal drift, or an unmodeled heat-loss coefficient.
- **H2, conventional low-energy nuclear process:** a reaction occurs and produces heat plus products whose rates and branch ratios can be represented by a screened D-D reaction model.
- **H3, anomalous product-suppressed process:** a reproducible excess-energy signal occurs with nuclear products that do not follow standard D-D branch expectations, requiring an explicit new mechanism rather than an omitted product term.

H2 and H3 are not accepted because they fit heat alone. They require a posterior likelihood gain across heat, product counts, isotopes, loading state, and cross-lab replication. If a heat signal appears only in deuterium cells but cannot be distinguished from a materials-state artifact, the result supports a materials or chemistry explanation rather than cold fusion.

## 3. Causal structure

The experiment treats palladium state as a measured mediator, not a hidden label. Electrolyte isotope, cathode lot, grain structure, defect density, deuterium loading, temperature, current density, pressure, and gas recombination affect both ordinary chemistry and any proposed nuclear rate. The causal structure is:

\[
\text{material state, isotope, electrochemistry}
\rightarrow \{\text{chemical heat, nuclear rate, detector background}\}
\rightarrow \{\text{heat, products, material change}\}.
\]

The design randomizes treatment assignment and run order within blocks, but it does not pretend that randomization removes all materials physics. It measures the mediators, stratifies by loading and defect state, and tests whether a putative signal persists after those states are included.

## 4. Joint evidence model

Let \(H(t)\) be measured heat rate, \(P(t)\) electrical input, \(C_k(t)\) counts for product channel \(k\), and \(M(t)\) the measured material state. The calibrated signal model is

\[
H(t)=H_{\rm chem}(t;M)+H_{\rm nuc}(t;\theta)+H_{\rm loss}(t;\phi)+\varepsilon_H(t),
\]

where \(H_{\rm chem}\) includes recombination and electrochemical enthalpy, \(H_{\rm loss}\) is the heat-loss model, and \(\theta\) contains a possible nuclear rate and branch parameters. Product counts are modeled as

\[
C_k \sim \operatorname{Poisson}\left(\int [\eta_k R_k(\theta)+B_k]dt\right),
\]

with detector efficiency \(\eta_k\), background \(B_k\), and product rate \(R_k\). The observation likelihood is the product of the calibrated heat likelihood, detector likelihoods, isotope likelihoods, and material-state likelihood, with correlation terms retained when instruments share a common environment.

For each hypothesis \(H_j\), the analysis computes a marginal likelihood

\[
p(D\mid H_j)=\int p(D\mid\vartheta,H_j)p(\vartheta\mid H_j)d\vartheta,
\]

and compares the nuclear model with the strongest artifact model using a Bayes factor

\[
BF_{\rm nuc,art}=\frac{p(D\mid H_2\;\text{or}\;H_3)}{p(D\mid H_0\;\text{or}\;H_1)}.
\]

The design predefines a strong-evidence threshold, a replication threshold, and a minimum product-energy consistency requirement. The exact prior distributions and thresholds are fixed before unblinding and sensitivity-tested in the protocol. They are not chosen after observing a favorable run.

## 5. Why this is scientifically useful

The design can produce informative outcomes even if cold fusion is not detected. A null result with calibrated upper limits narrows the allowed rate region. A deuterium-specific heat signal without products tests the missing-product problem. A product signal without heat tests contamination and detector specificity. A signal that tracks loading or defects but not isotope controls can motivate materials science without being labeled fusion. A successful, product-linked signal would identify a quantitative parameter regime for a new nuclear-material interaction and justify a separate mechanism study.

The idea also creates a bridge from nuclear physics to energy technology. The final decision is not "is there any anomaly?" It is whether the inferred reaction rate, specific power, duty cycle, shielding, heat removal, material lifetime, and auxiliary energy permit net useful power. An effect that releases only microscopic heat or requires more electrochemical energy than it returns is scientifically interesting but not a practical energy source.

## 6. Falsification criteria

The study is considered negative for a canonical cold-fusion energy claim if any of the following holds under the preregistered protocol:

1. excess heat is not detected above the calibrated control distribution;
2. the apparent heat excess is fully explained by a control-calibrated chemical or thermal model;
3. the heat signal fails to replicate in an independent laboratory using the shared material protocol;
4. product counts remain at background while the claimed heat would require detectable products under standard D-D channels;
5. the inferred energy output is below the declared net-power threshold after auxiliary inputs and uncertainty are included.

The criteria are asymmetric. Failure to prove H2 is not a proof that every conceivable low-energy nuclear mechanism is impossible. It is evidence against the tested mechanism and claim at the tested sensitivity.

## 7. Handoff to ExperimentDesign

The experimental phase must specify cell construction, isotope controls, cathode lots, randomization, blinding, calibration, synchronized detectors, minimum detectable power, product detection limits, data retention, stopping rules, cross-lab roles, statistical priors, safety controls, and the net-energy decision threshold. The output remains design-only until the experiment is actually run.
