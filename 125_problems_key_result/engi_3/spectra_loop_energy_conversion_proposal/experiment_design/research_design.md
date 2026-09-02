# ExperimentDesign Agent - SPECTRA-Loop Research Protocol

## Design-only scope

This is an `engineering_energy` design. Its execution policy is `DESIGN_ONLY`; `observed_results` is empty. No device was built, no model was executed, no source was irradiated, and no material/system efficiency was measured in this workflow. A future implementation requires appropriate laboratory safety review for optical, thermal, electrical, and material hazards.

## Research brief

- **Research object:** a PV-TPV converter architecture coupled to source-spectrum, optical-partition, thermal-boundary, electrical-load, calibration, and stability/transfer cards.
- **Reference:** a single-converter configuration operating under the same declared source and input boundary.
- **Intervention:** spectral routing into direct-PV and thermal-emitter/TPV branches, with all optical/thermal/electrical losses included in the ledger.
- **Central claim:** only a matched-boundary comparison can support a net system-efficiency claim.
- **Alternative explanations:** a gain can originate from a changed source denominator, unreported concentrator/filter gain, load mismatch, temperature drift, instrument response, undeclared storage, or an auxiliary load outside the numerator.

## Variables and cards

| Class | Variables | Required control or record |
|---|---|---|
| Independent | source spectrum; irradiance or thermal-source condition; partition cutoff; optical element; PV/TPV branch architecture; thermal coupling; electrical load | Source, optical-partition, and thermal-boundary cards. |
| Dependent | DC output; net electrical output; optical/thermal energy shares; energy residual; uncertainty; drift/stability status | Synchronized spectral, electrical, thermal, and auxiliary-power records. |
| Controlled | reference geometry; declared denominator; calibration traceability; sampling cadence; data-reduction version; decision thresholds | Frozen before comparing configurations. |
| Unknown | real deployment weather/duty cycle, manufacturing yield, long-duration degradation, cost, and grid integration | Remain `needs_human_input`; never imputed as a favorable result. |

## Energy-accounting contract

Future work must predeclare an energy balance at a single named boundary:

`P_source = P_PV + P_TPV + Q_rejected + P_optical_loss + P_parasitic + dU/dt + r_E`.

The reportable numerator is `P_net = P_PV + P_TPV - P_auxiliary`. The candidate's net efficiency is `eta_net = P_net / P_source` only when the source boundary, measurement period, and stored-energy policy match the reference. A nonzero residual is not silently discarded; it becomes a reconciliation or invalid-measurement outcome.

## Planned protocol

1. Freeze a source-spectrum card: lamp/solar/thermal source type, spectral radiance/irradiance method, geometry, concentration condition, warm-up, and stability record.
2. Freeze an optical-partition card: routing band, reflectance/transmittance/absorptance method, aperture, angular condition, and loss pathway.
3. Freeze a thermal card: receiver/emitter geometry, temperature sensors, heat-rejection path, insulation, heat-capacity policy, and observation window.
4. Freeze an electrical card: load sweep, maximum-power-point method, current/voltage instrumentation, sampling synchronization, and auxiliary-power measurement.
5. Measure the same card set for reference and candidate configurations in randomized/interleaved blocks; replicate after calibration checks.
6. Calculate the closure residual and combined uncertainty before labeling a comparison.
7. Execute a predeclared stability observation at the selected operating envelope; do not turn a short peak observation into a lifetime claim.
8. Publish only the boundary named by the source card; system transfer requires a separate human-reviewed statement.

## Pre-registered outcome branches

| Status | Future interpretation | Action |
|---|---|---|
| `NET_GAIN_SUPPORTED` | Candidate exceeds the matched reference after energy closure, uncertainty, and stability gates. | Report only the stated source/boundary domain. |
| `COMPONENT_GAIN_ONLY` | A branch improves while net system comparison does not close or does not exceed reference. | Report component result; do not call it system improvement. |
| `MEASUREMENT_BOUNDARY_INVALID` | Denominators, source inputs, or auxiliary loads are mismatched or omitted. | Reconfigure/re-measure; no comparison claim. |
| `STABILITY_LIMITED` | Initial metric drifts outside predeclared stability rule. | Report operating limitation and investigate materials/interfaces. |
| `TRANSFER_NOT_JUSTIFIED` | Laboratory conditions do not support the proposed use environment. | Keep claim laboratory-bounded. |
| `INCONCLUSIVE` | Joint uncertainty overlaps the reference or closure remains unresolved. | Report no direction of advantage. |

## Safety and human-review boundary

High-flux optical sources, hot emitters, high currents, vacuum hardware, semiconductor processing, and nanostructured/selective emitters require qualified laboratory personnel, appropriate shielding/interlocks, and institutional safety review. This proposal neither gives operation parameters nor authorizes experimental execution. Source bibliographic metadata, material selection, hazard review, and final performance claims require human expert confirmation.
