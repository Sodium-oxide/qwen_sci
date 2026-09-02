# ExperimentDesign: Blinded Product-Linked Replication of Cold Fusion Claims

## 1. Design objective

This protocol tests a narrow and falsifiable proposition: a reproducibly prepared palladium-deuterium electrochemical system can produce excess energy that is not explained by chemical or thermal artifacts and is accompanied by nuclear products consistent with a stated reaction model. The protocol does not assume that a positive temperature excursion is nuclear. It treats a heat claim, a product claim, a materials-state claim, and a technology claim as separate endpoints.

The study is design-only. No numerical effect, reaction rate, cost, or probability is reported as observed. All numerical thresholds below are protocol variables to be finalized in a preregistration after metrology characterization, not results from completed experiments.

## 2. Experimental arms and units

The unit of analysis is a complete cell run, nested within a cathode lot, laboratory, and randomized block. The minimum core design has four arms:

| Arm | Cathode and isotope condition | Purpose |
|---|---|---|
| D-Pd | palladium cathode with high-purity heavy-water electrolyte | canonical treatment condition |
| H-Pd | matched palladium cathode with protium-water electrolyte | isotope control for electrochemistry and materials |
| D-Inert | inert cathode with heavy-water electrolyte | separates palladium effects from electrolyte effects |
| D-Pd-open | palladium cathode and heavy-water electrolyte with electrochemical driving disabled | estimates passive thermal, detector, and environmental background |

Cathodes are drawn from multiple sealed lots with blind lot identifiers. Geometry, mass, surface preparation, electrolyte concentration, vessel, electrical leads, and gas-handling components are matched. A subset of runs uses dummy electrical heaters and calibrated heat pulses to validate the calorimeter without electrochemistry. A subset uses a known radioactive or neutron calibration source only under the institution's radiation-safety authorization and is analyzed separately from experimental runs.

The primary experiment uses randomized blocks containing all four arms. Within each block, run order is randomized by an analyst who does not operate the cell. The operator sees only a treatment code. The calorimetry and nuclear-detector analysts receive independently coded files. The code is held by a data steward until the preregistered data-quality checks are complete.

## 3. Metrology and calibration

### 3.1 Heat and electrical input

Heat is inferred with a calibrated calorimetric model, not from a single thermocouple. The system records temperatures at multiple locations, coolant or environmental conditions, gas pressure, gas flow, humidity, electrical voltage, current, and auxiliary-device power. Electrical meters are traceable to standards and sampled synchronously with the thermal channels. The model is calibrated with blinded heat pulses spanning the expected measurement range and with blank cells that reproduce the vessel, electrolyte volume, leads, and gas handling.

For a run of duration \(T\), the integrated excess energy is estimated as

\[
E_{\rm exc}=\int_0^T\left[P_{\rm out}(t)-\widehat{P}_{\rm chem}(t;M)-\widehat{P}_{\rm loss}(t;\phi)\right]dt,
\]

where \(M\) is the measured materials and gas state, \(P_{\rm chem}\) includes electrochemical enthalpy and recombination, and \(P_{\rm loss}\) is the calibrated heat-loss term. The uncertainty must include calibration covariance, sensor drift, electrical metrology, gas-composition uncertainty, model discrepancy, and any predeclared correlation between channels.

### 3.2 Chemistry and gas accounting

Open-cell systems can recombine electrolytically generated gases and return chemical energy as heat. Closed-cell systems can accumulate pressure and alter heat transfer. Both configurations are tested, but the primary endpoint is declared separately for each. Gas composition, flow, pressure, humidity, and oxygen/hydrogen balance are logged. A gas inventory closes the chemical energy audit. Runs with leaks, unexplained gas loss, or unstable pressure are classified according to a preregistered exclusion rule rather than removed after looking at heat.

### 3.3 Materials state

Deuterium loading, lattice strain, defects, grain structure, impurities, surface morphology, and temperature are treated as mediators. The protocol records loading proxies continuously where possible and uses pre-run and post-run isotope, microscopy, spectroscopy, and composition measurements. The minimum material record includes cathode lot, dimensions, mass, surface treatment, roughness, impurity screen, hydrogen/deuterium loading estimate, electrochemical history, pressure, temperature, and post-run change. The result is not interpreted as a treatment effect if the treatment and control arms occupy disjoint or undocumented materials states.

## 4. Nuclear-product measurement

Nuclear products are measured independently of the heat channel. Neutron and gamma detectors are calibrated for efficiency, energy response, dead time, shielding, and environmental background. Tritium and helium isotope assays use standards, reagent blanks, vessel blanks, chain-of-custody records, and contamination controls. Surface and bulk samples are archived before and after runs. The detector clock is synchronized with electrochemical and thermal data so that a claimed event can be tested for temporal association.

Let \(C_k\) be the count in channel \(k\). The protocol uses

\[
C_k\sim\operatorname{Poisson}\left(\epsilon_k N_k+B_kT\right),
\]

where \(\epsilon_k\) is calibrated efficiency, \(N_k\) is the number of produced products, and \(B_k\) is the background rate. Background is estimated from open-circuit, inert-cathode, pre-run, post-run, and environmental control data. A detector excess is not called a product unless it survives the corresponding blank and calibration model.

For a standard D-D model, the reaction count \(N_{\rm DD}\) implies branch-specific product counts and nuclear energy. The two dominant branches are

\[
D+D\rightarrow T+p+4.03\;\mathrm{MeV},
\qquad
D+D\rightarrow {}^3\mathrm{He}+n+3.27\;\mathrm{MeV}.
\]

The radiative branch is written as

\[
D+D\rightarrow {}^4\mathrm{He}+\gamma+23.85\;\mathrm{MeV},
\]

but its branch fraction is not freely selected to rescue a heat-only claim. If a model predicts a heat output \(Q N_{\rm DD}\), the expected products and their detector upper limits are propagated into the same likelihood. A product-suppressed model is a separate hypothesis requiring a mechanism and an independent prior, not a hidden assumption.

## 5. Blinding, randomization, and preregistration

Before experimental runs begin, the team preregisters the primary endpoint, minimum detectable excess power, product detection limits, data windows, calibration model, artifact models, exclusion rules, missing-data rules, Bayesian priors, replication threshold, and stopping rule. The primary endpoint is a joint evidence score, not a temperature maximum. Secondary endpoints include integrated excess energy, loading dependence, detector-specific counts, isotope differences, and post-run material changes.

Run identifiers, treatment codes, and laboratory identities are separated. An independent steward creates the allocation sequence. Analysts first fit calibration, blank, and control data. The treatment code is opened only after the data-quality checklist is signed. If a sensor fails, the failure is logged and the data are retained; the run is not silently replaced. Any protocol amendment is versioned, time-stamped, and made before unblinding.

## 6. Statistical analysis

The primary model compares four hypotheses:

\[
H_0: H_{\rm nuc}=0,
\quad H_1: H_{\rm exc}=H_{\rm chem}+H_{\rm loss},
\quad H_2: \text{screened D-D},
\quad H_3: \text{anomalous product-suppressed process}.
\]

The data vector includes heat time series, electrical input, gas inventory, loading state, neutron and gamma counts, isotope assays, and material measurements. For hypothesis \(H_j\),

\[
p(D\mid H_j)=\int p(D\mid\vartheta_j,H_j)p(\vartheta_j\mid H_j)d\vartheta_j.
\]

The primary contrast is

\[
BF_{\rm nuc,art}=\frac{p(D\mid H_2\;\text{or}\;H_3)}{p(D\mid H_0\;\text{or}\;H_1)}.
\]

The exact prior widths are set from calibration and published before treatment unblinding. Sensitivity analysis reports how the result changes under reasonable prior alternatives. A frequentist companion analysis reports confidence or credible upper limits on excess power and product rates. The study uses hierarchical effects for laboratory, cathode lot, and run block, preserving between-lab heterogeneity rather than averaging it away.

The experiment is powered by simulation before data collection. Synthetic data are generated under the strongest artifact model, a screened D-D model, and stress-test alternatives. The chosen run count must provide adequate probability of rejecting an artifact model when a prespecified minimum useful effect exists while controlling false discovery under the null. No optional stopping is allowed. The primary result is reported with all runs included according to the preregistered rule.

## 7. Replication and decision gates

The program has four gates:

1. **Metrology gate:** heat pulses and blank cells meet calibration residual, drift, and detector-background criteria.
2. **Local blinded gate:** the operating laboratory completes randomized treatment and control blocks without code access.
3. **Independent replication gate:** at least two external laboratories repeat the protocol using shared material lots and independently managed analysis.
4. **Technology gate:** a positive scientific signal is converted to net useful energy only if auxiliary electricity, gas management, heat removal, shielding, materials lifetime, maintenance, and safety systems are included.

A canonical cold-fusion claim is supported only if the joint evidence exceeds the preregistered threshold, survives the product-energy consistency test, and replicates independently. A heat-only signal is classified as unresolved or artifact-consistent, not as fusion. A product-only signal is subjected to contamination and detector-specificity analysis. A null result produces upper bounds at the stated sensitivity and is not described as proof that every possible low-energy nuclear mechanism is impossible.

## 8. Safety and governance

All work requires institutional approval for pressurized vessels, hydrogen/deuterium handling, electrical systems, chemical exposure, and any radiation source or activated material. The design uses engineering controls for ventilation, leak detection, pressure relief, electrical isolation, remote monitoring, and emergency shutdown. A radiation-safety officer approves detector calibration and sample handling. No unreviewed recipe, unlicensed source, or uncontained gas operation is part of this proposal. Data and sample custody are documented so that later product assays remain credible.

## 9. Expected information gain

The study can be informative under every major outcome. A calibrated null constrains the canonical effect at a quantitative sensitivity. A deuterium-specific thermal signal that tracks recombination supports H1. A materials-state effect without nuclear products motivates hydride science but does not establish fusion. A product-linked replicated signal would motivate mechanism-specific nuclear work. Only a positive result that also passes the technology gate can support the stronger statement that cold fusion may become an energy technology.

## 10. Design-only boundary

No observed results, reaction rates, Bayes factors, net power, or engineering performance are claimed. The outputs of this stage are the protocol, analysis plan, preregistration schema, and author handoff. Laboratory execution and human review are required before any scientific conclusion is upgraded.
