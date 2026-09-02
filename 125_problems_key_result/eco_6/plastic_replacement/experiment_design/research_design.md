# ExperimentDesign Agent: FUNCTIONAL-CIRCULAR-POLYMER Evaluation

## 1. Objective and design mode

This study evaluates candidate plastic replacements at the level of delivered product service and waste-system performance. It asks when an alternative maintains required strength, barrier, safety, and lifetime while reducing life-cycle burdens. The design is `DESIGN_ONLY`: no candidate has been tested, ranked, or declared environmentally superior.

## 2. Hypotheses

- **H1, functional equivalence:** A resin-mass comparison and an equal-service comparison produce different rankings for at least one product class.
- **H2, end-of-life dependence:** Actual routing, facility access, contamination, and treatment conditions materially change comparative environmental outcomes.
- **H3, trade-off structure:** Candidate polymers form context-dependent Pareto frontiers rather than one universal optimum.
- **H4, formulation completeness:** Additives, coatings, inks, adhesives, multilayers, and processing yield explain a meaningful share of impact variance.
- **H5, co-design value:** Optimizing material, product geometry, and end-of-life pathway together yields feasible candidates that are missed by material-only screening.

## 3. Product and functional units

Select four pilot product classes: flexible food film, rigid food container, durable consumer component, and biocompatible medical or laboratory product. Define a service unit for each before candidate selection. Examples are one package that protects a specified food mass for a specified shelf life; one rigid container that survives a defined number of fill and transport cycles; one component that meets a mechanical and thermal duty cycle for a defined lifetime; and one sterile device that meets a specified barrier, mechanical, and biocompatibility profile.

For each unit, predeclare thickness, mass range, mechanical limits, oxygen and water-vapor barrier, heat-seal or processing window, safety requirements, failure tolerance, and service lifetime. A candidate that needs extra mass, an additional coating, or a shorter lifetime is scored on that complete product system. Resin-level kilograms are a secondary diagnostic, not the primary comparison.

## 4. Candidate matrix

Test conventional polyethylene, polypropylene, PET, or relevant product-specific controls against PLA, PHA or PHB, starch and cellulose derivatives, PBS or PBAT blends, bio-based polyesters or polyamides, waste-derived formulations, chemically recyclable polyesters, and reuse-oriented redesigns where technically suitable. Candidate selection is constrained by product class; a material does not enter the medical comparison merely because it is biodegradable in a compost test.

Record monomer and feedstock origin, agricultural inputs, waste-preprocessing energy, catalyst and solvent use, additives, coatings, conversion yield, scrap rate, and packaging mass. Measure tensile and impact behavior, stiffness, thermal transitions, oxygen and water-vapor barrier, sealability, chemical resistance, dimensional stability, and relevant safety or cytotoxicity endpoints. The study can use certified or published data for screening, but every value receives a source, uncertainty, and product-condition tag.

## 5. End-of-life routing experiment

Route each candidate through a declared regional waste system: reuse, mechanical recycling, chemical recycling, industrial composting, home composting, anaerobic digestion, landfill, incineration with energy recovery, and uncontrolled leakage where relevant. Actual routing probabilities are varied by collection coverage, sorting accuracy, contamination, facility availability, and consumer behavior. Intended treatment is never substituted for observed or plausible treatment without a sensitivity case.

Degradation tests report mass loss, molecular-weight change, carbon conversion, carbon dioxide or methane production, residual fragments, additive release, and ecotoxicity under specified temperature, humidity, oxygen, inoculum, thickness, and time. Industrial composting, home composting, freshwater, soil, and marine conditions are separate protocols. A sample that fragments into microplastics without mineralization fails a complete-biodegradation claim. Mechanical and chemical recycling tests measure yield, product quality, additive carryover, and contamination of the incumbent stream.

## 6. Life-cycle inventory and assessment

The system boundary includes feedstock extraction or cultivation, land and water use, fertilizer and agricultural emissions, waste preprocessing, polymer synthesis, solvent and catalyst recovery, compounding, conversion, scrap, transport, use, collection, sorting, treatment, leakage, and avoided virgin production. For reusable products, include washing, repair, loss, replacement, and number of cycles. For food packaging, include product loss caused by reduced shelf life. For medical products, include sterilization, controlled disposal, and safety-related design constraints.

Primary impact dimensions are greenhouse-gas emissions, fossil-resource use, land occupation or land-use change, water consumption, eutrophication, acidification, toxicity, particulate matter, persistence or environmental residence, waste-system disruption, and cost. Biogenic carbon timing, methane, energy mix, avoided products, and allocation rules are sensitivity parameters. LCA outputs are reported per functional service unit and per kilogram only as a supplementary diagnostic.

## 7. Multi-objective selection

Let (v(c)) be the measured service vector and (b) the minimum requirement. Candidate (c) is feasible when

\[
 g_j(c)=v_j(c)-b_j\geq 0 \quad \text{for every required performance constraint } j.
\]

For feasible candidates, report the objective vector

\[
 J(c)=(G,F,L,W,T,P,C,Q,E),
\]

where the terms represent greenhouse gases, fossil resources, land, water, toxicity, persistence, cost, circularity, and equity or social burden. A candidate is Pareto-dominated when another feasible candidate is no worse in every declared objective and strictly better in at least one. Do not collapse the vector into one score until weights are predeclared; publish the frontier and the chosen policy-weighted ranking separately.

## 8. Baselines and ablations

Baselines are conventional fossil polymer with current regional routing, mass-based LCA ranking, bio-based drop-in substitution, biodegradable replacement with ideal industrial composting, and reuse-oriented redesign. Ablations remove equal-service constraints, additives and multilayers, actual routing, leakage, agricultural burden, biogenic-carbon timing, product-loss penalty, recycling contamination, and regional electricity mix. These ablations reveal whether a claimed advantage comes from material chemistry or an optimistic system assumption.

## 9. Statistical design

Use a hierarchical uncertainty model over material properties, process yield, feedstock emissions, electricity, facility access, routing, degradation rate, recycling yield, and exposure. Report median, interval, and tail outcomes for each functional unit. Bootstrap independent batches or product lots for laboratory measures and use scenario sampling for system uncertainty. Treat product class and region as random or stratified factors, not as interchangeable observations. Predeclare primary outcomes and use multi-objective sensitivity analysis for secondary outcomes.

## 10. Stress tests and falsification

Stress cases include a low-carbon grid, a fossil-heavy grid, crop-feedstock expansion, waste-feedstock contamination, low collection coverage, absent composting facilities, high mis-sorting, cold marine release, short product shelf life, high reuse loss, and additive migration. A candidate's claim is falsified if it fails the service constraint, if mineralization is replaced by fragmentation, if its advantage disappears under plausible routing, or if it shifts an excluded burden beyond a predeclared threshold.

The framework rejects a universal winner if the Pareto frontier changes with product class, region, or waste pathway. It advances a candidate to pilot manufacture only if functional tests pass, the dominant life-cycle impacts are measured, and the intended end-of-life route is available or explicitly labeled as a required infrastructure investment. A material that is environmentally better only under a facility that does not exist is a conditional design, not a current replacement.

## 11. Reproducibility and safety

Freeze functional units, controls, formulation recipes, testing conditions, LCA boundaries, allocation rules, waste-routing probabilities, impact weights, and regional datasets before final comparison. Store raw material tests, failed specimens, calibration certificates, and product versions. Medical or food-contact candidates require independent safety and regulatory review. No environmental label or public claim is issued from this design package alone.

## 12. Planned deliverables

Execution would produce a service-equivalence table, material property dataset, degradation and recycling results, regional routing matrix, life-cycle inventory, Pareto frontiers, uncertainty decomposition, and candidate model cards. These are planned outputs only. `expected_results` and `observed_results` remain empty in this handoff.
