# Survey Agent - Energy-Conversion Efficiency Limits

## Scientific reframing

The question "How can we break the current limit on energy-conversion efficiencies?" contains a useful ambition but an imprecise premise. There is no single efficiency ceiling shared by photovoltaic (PV), thermophotovoltaic (TPV), thermoelectric, piezoelectric, and other converters. An efficiency statement is meaningful only after it declares the converter architecture, source spectrum or temperature, input boundary, operating point, parasitic loads, and time horizon. A result can exceed the well-known single-junction PV detailed-balance benchmark by changing the architecture or its assumptions; it cannot evade energy conservation or the thermodynamic accounting required by the selected boundary.

This Survey narrows the research problem to a tractable and falsifiable engineering question:

> Can a spectrally partitioned and thermally integrated PV-TPV architecture improve *net useful electrical conversion* under a declared source spectrum, thermal boundary, optical-loss model, and measurement protocol, relative to a reference single-converter configuration?

The question intentionally does not promise to "break physics." It tests whether a coupled architecture can reassign loss channels that are unavoidable or severe for a specified reference converter, while keeping all energy flows visible.

## Evidence acquisition and confidence

Two independent academic indexes, OpenAlex and AnySearch Academic, were searched in parallel on 2026-09-01 with the queries `Shockley Queisser detailed balance limit tandem photovoltaic spectral splitting thermophotovoltaic` and `thermoelectric thermophotovoltaic system efficiency measurement boundary review`. Four records in the first query and seven records in the second query matched across both engines by DOI/title metadata. These are discovery-stage bibliographic records, not a substitute for reading full papers or verifying publisher landing pages.

The user-requested in-app browser successfully opened the U.S. Department of Energy (DOE) PV technology-basics page. The visible page states that PV materials and devices convert sunlight into electrical energy, that a cell is a semiconductor device, and that modules, arrays, and DC-to-AC components are parts of a full PV system. A navigation attempt to NREL's efficiency page failed with `ERR_CONNECTION_CLOSED`; no NREL content is represented as verified. The classic Shockley--Queisser article and a selected tandem-PV primary paper are retained as established bibliographic anchors, but their landing-page metadata remain a human-review item in this simulated workflow.

| Evidence ID | Bounded finding | Permitted downstream use | Confidence and boundary |
|---|---|---|---|
| E-PV-001 | Shockley and Queisser formulate a detailed-balance efficiency limit for idealized p-n-junction solar cells. | Define the *single-junction conditional baseline*. | Bibliographic anchor; not a universal energy-conversion law. |
| E-PV-002 | DOE distinguishes PV cells, modules, arrays, and complete PV systems. | Require device/module/system boundary declarations. | Browser-visible DOE page verified; it supplies no benchmark percentage here. |
| E-PV-003 | Dual-index records review tandem, spectral, hot-carrier, and conversion approaches aimed at limits of conventional PV. | Motivate architecture-changing routes. | Review/discovery evidence; no performance number is transferred. |
| E-PV-004 | Dual-index records describe light management and commercialization/stability needs for emerging PV. | Add optical-loss and transfer gates. | Review-level evidence; no product claim. |
| E-TPV-005 | Dual-index TPV reviews describe selective emission, spectral control, and material interfaces. | Motivate a thermal-recovery and spectral-partition branch. | Architecture evidence, not proof of hybrid-system performance. |
| E-TPV-006 | Dual-index TPV analyses separate component and whole-system energy/exergy accounting. | Require a closed source-to-sink accounting boundary. | Source-specific assumptions cannot be generalized. |
| E-TPV-007 | A dual-index selective-emitter record reports high-temperature stability as an engineering constraint. | Add stability as a first-class decision gate. | Emitter result does not establish a complete converter. |
| E-TE-008 | Dual-index thermoelectric reviews identify material performance, scaling, cost, toxicity, and measurement issues. | Contrast a non-selected recovery route and avoid one-metric reasoning. | Does not establish PV-TPV superiority. |

## Subhypotheses and evidence coverage

**SH-1: conditional-limit clarity.** A single-junction PV detailed-balance benchmark must be attached to its illumination, bandgap, ideality, and operating assumptions. E-PV-001 supplies the physics anchor; E-PV-002 supplies the system-boundary correction. Coverage is sufficient to reject the phrase "the current efficiency limit" as a universal scalar, but insufficient to select a numerical target for any new architecture.

**SH-2: spectral-loss reassignment.** Multi-junction conversion, spectral splitting, photon recycling, or a selective thermal emitter can redistribute spectral mismatch, thermalization, and sub-bandgap losses. E-PV-003 through E-TPV-005 support investigation of these route families. They do not establish a net gain after filters, transport, cooling, controls, and degradation are included.

**SH-3: boundary closure.** Useful electrical output is not comparable across studies unless radiant/thermal input, reflected/transmitted energy, rejected heat, stored-energy change, and parasitic consumption share one boundary. E-PV-002 and E-TPV-006 support this requirement. The literature does not provide a common reporting contract for PV-TPV hybrids.

**SH-4: stability and transfer.** A spectral-control element or high-performing absorber is not deployable merely because it has an attractive instantaneous optical/electrical metric. E-PV-004, E-TPV-007, and E-TE-008 motivate stability, thermal cycling, calibration, and transfer gates. A common duration and drift declaration remains missing.

## Accepted gap ledger

| Gap ID | Accepted gap | Why it matters | Handoff restriction |
|---|---|---|---|
| GAP-LIMIT-001 | Single-junction detailed-balance language is often conflated with all PV or all energy-conversion limits. | It invites invalid claims of "breaking" a universal law. | Primary idea must state the reference limit and the changed assumption. |
| GAP-SPECTRAL-002 | Spectral losses, thermal reuse, and electrical conversion are often discussed in separate device literatures. | An attractive component route can fail after coupling losses are counted. | Candidate must include a spectral and thermal interface card. |
| GAP-BOUNDARY-003 | Device, module, receiver, and system efficiencies use incompatible input/output boundaries. | Values cannot be compared or summed without energy closure. | Every claim must name its denominator and parasitic-load policy. |
| GAP-METROLOGY-004 | Spectral flux, optical losses, temperature, electrical load, calibration, and uncertainty are not consistently co-reported. | A measured gain may be non-reproducible or boundary-dependent. | Design must include a calibration/uncertainty card. |
| GAP-STABILITY-005 | High-efficiency components lack a common operating-stability and degradation transfer boundary. | Peak performance can mask failure under relevant duration or temperature. | Design must predeclare stability observation and acceptance logic. |
| GAP-TRANSFER-006 | Laboratory source/temperature conditions are silently transferred to deployed-energy-system claims. | A laboratory architecture may not retain its advantage at the system level. | Any deployment claim requires a separate transfer statement. |

## Survey conclusion and handoff

The evidence supports a direct conclusion: conversion efficiency is improved scientifically by changing a declared converter architecture and by reducing specified loss channels, not by declaring that thermodynamic constraints have been defeated. The primary research opportunity is therefore an auditable hybrid PV-TPV architecture that makes spectral routing, heat recovery, electrical output, auxiliary consumption, uncertainty, and stability visible in a single accounting contract. The Idea Agent must bind its direction to GAP-LIMIT-001 through GAP-METROLOGY-004, retain GAP-STABILITY-005 and GAP-TRANSFER-006 as decision gates, and include a falsifier rather than a generic claim of higher efficiency.
