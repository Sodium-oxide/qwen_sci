# ExperimentDesign Agent: UNIVERSAL-CIRCULAR-RECOVERY

## 1. Objective

Test whether coordinated product design, information, collection, sorting, processing, markets, and policy can make a broad portfolio of materials repeatedly useful. The experiment does not try to force every object into a recycling route. It measures when reuse, repair, refurbishment, mechanical recycling, chemical recovery, biological processing, substitution, or controlled treatment is the least-burden feasible action.

The design-only mode is explicit. No material has been tested in this package, and no measured yield, cost, environmental impact, or route ranking is reported as observed.

## 2. Testable hypotheses

- H1: Technical processability is substantially higher than product-grade recycling under realistic contamination, sorting error, and market acceptance.
- H2: Design-for-recovery improves quality-adjusted yield and recovered-material displacement in at least one product class without violating the frozen service requirement.
- H3: Quality-aware routing produces more future service units per unit of primary resource than routing that maximizes recovered mass or tonnage.
- H4: Reuse or refurbishment has a product- and region-specific break-even cycle count; below it recycling can be better, and above it reuse can be better.
- H5: Including social and environmental external costs changes at least one private-cost route ranking.
- H6: No single route dominates reduction, reuse, repair, refurbishment, recycling, chemical recovery, and controlled treatment across all tested classes and regions.

## 3. Product and material strata

Use six deliberately contrasting strata:

1. beverage containers: PET, aluminum, and glass with deposit or curbside variants;
2. protective food packaging: mono-material film, multilayer film, paperboard, and contaminated pizza-box-like fiber;
3. construction products: steel, concrete aggregate, gypsum, and composite panels;
4. textiles and furnishings: cotton, polyester, wool, and blended fabrics;
5. consumer electronics: separable plastics, metals, glass, batteries, and printed-circuit assemblies;
6. medical, hygiene, and hazardous products: contaminated or chemically complex articles that may require controlled treatment rather than open recovery.

The strata are not assumed to be representative of all global materials. They are chosen to expose differences between high-value durable streams, clean monomaterials, mixed products, contaminated products, and streams in which safety constrains recovery.

## 4. Functional units and system boundary

The primary functional unit is one delivered service, frozen before testing:

- one beverage-container service with specified volume and number of uses;
- one food-protection service for a specified mass and shelf life;
- one square meter-year of construction performance;
- one garment-year of required wear and cleaning;
- one electronic-device service over a specified operating life; and
- one sterile or safe medical/hygiene service where regulated disposal is part of the requirement.

Secondary units are one tonne of post-use material and one kilogram of recovered product. They are used for throughput and facility analysis but cannot replace equal-service comparison.

The life-cycle boundary includes product design, material extraction or production, additives, manufacturing, distribution, use, collection, transport, sorting, cleaning, disassembly, processing, purification, recovered-product manufacturing, rejects, residues, leakage, and avoided virgin production. Reuse adds return transport, washing, repair, inspection, damage, loss, and successful cycles. The social boundary separately records worker exposure, community exposure, noise, traffic, and burden distribution.

## 5. Experimental stages

### Stage 1: Material-flow and route audit

For each stratum and region, collect waste-composition audits, collection coverage, route probabilities, sorting capacity, facility throughput, contamination, rejects, recovered grades, and identified buyers. Use at least three contrasting regions: high collection and established markets, established recycling but limited reuse or composting, and low collection with substantial leakage or informal handling. Record the date, geography, sampling frame, and uncertainty for every flow.

### Stage 2: Design and identity intervention

Construct matched conventional and design-for-recovery products. Vary mono-material versus multilayer construction, reversible versus permanent joins, label and adhesive formulation, additive disclosure, fastener accessibility, and machine-readable identity. Keep required service, safety, mass, and lifetime constraints frozen. Measure production scrap, assembly time, material use, barrier or structural performance, user handling, and disassembly time.

### Stage 3: Contamination and sorting trials

Create controlled contamination strata: clean, moisture, food residue, biological residue, incompatible material, pigment or additive, label or adhesive, mixed assembly, and unknown prior history. Use blinded samples where possible. Measure optical, near-infrared, magnetic, density, robotic, and manual sorting performance as appropriate. Report false positive and false negative rates, route-specific contamination, worker exposure controls, and the fate of unsorted material.

### Stage 4: Reuse, repair, and recovery trials

For reusable products, run repeated service cycles with realistic washing, inspection, repair, return logistics, breakage, loss, and user damage. For mechanical routes, run repeated processing cycles and measure yield, purity, molecular or structural change, mechanical performance, odor, color, additive carryover, and the next product grade. For chemical routes, measure conversion, depolymerization or feedstock yield, solvent and catalyst recovery, energy, purification, residue, and whether the output displaces virgin material. For biological or thermal treatment, quantify products, emissions, residues, and safe containment.

### Stage 5: Techno-economic and life-cycle model

Use measured distributions from Stages 1–4 rather than point estimates where possible. Separate private cash flows from environmental and social externalities. Model recovered-material prices, virgin-material prices, collection fees, producer responsibility payments, recycled-content demand, transport, facility utilization, policy incentives, and demand shocks. Include sensitivity to electricity mix, fuel, labor, throughput, contamination, and route failure.

### Stage 6: Portfolio and out-of-sample validation

Optimize jointly over design, identity, route, facility allocation, cycle count, and policy. Hold out one product variant and one region to test transfer. The held-out case must be evaluated without changing the primary thresholds after seeing the outcome. Report whether a policy improves actual quality-adjusted service retention or merely moves material between accounting categories.

## 6. Route yield and service retention

For route k in region r, define quality-adjusted recovery as

\begin{equation}
Y_{k,r}=q_{\mathrm{collect}}q_{\mathrm{sort}}q_{\mathrm{process}}q_{\mathrm{grade}}q_{\mathrm{market}},
\label{eq:yield}
\end{equation}

where each factor is the probability that material passes collection, correct sorting, processing, the receiving-product grade, and an identified market. A route that has high process yield but no buyer has low product-grade recovery. Residue and leakage are tracked separately and are not assigned zero impact.

For reuse or refurbishment, expected delivered service is

\begin{equation}
S(c)=\frac{n_{\mathrm{cycles}}(c)\,[1-\lambda_{\mathrm{service}}(c)]}{1+\rho_{\mathrm{loss}}(c)},
\label{eq:service}
\end{equation}

where n cycles is the number of successful cycles, lambda service is the failure probability per required service, and rho loss represents additional replacement or loss burden. The exact inventory includes washing, repair, return transport, and replacement; the equation makes the cycle threshold visible.

## 7. Multi-objective decision model

For candidate c and region r, report the vector

\begin{equation}
J(c,r)=\left(G,E,W,T,P,C_{\mathrm{private}},C_{\mathrm{social}},Q,S,R\right),
\label{eq:objective}
\end{equation}

where G is greenhouse-gas impact, E energy, W water, T toxicity and exposure, P persistence or leakage, C private and social costs, Q quality-adjusted circularity, S delivered service, and R resilience to route or market failure. A candidate is feasible only when service, safety, regulatory, and receiving-grade constraints pass. Among feasible candidates, Pareto dominance is used instead of hiding all impacts in one score.

Define quality-adjusted circularity for a service unit as

\begin{equation}
Q(c,r)=\sum_k q_k(r)Y_{k,r}D_{k,r}V_{k,r},
\label{eq:circularity}
\end{equation}

where q is route probability, Y is route yield, D is the fraction of recovered output that displaces a specified primary resource, and V is value or service retention relative to the functional unit. The parameters are measured or bounded; they are not interpreted as a universal circularity percentage.

## 8. Baselines and ablations

Compare:

- current conventional product and current regional route;
- equal-service material comparison;
- material-mass-only comparison;
- technically ideal route with zero contamination;
- realistic route with measured contamination and sorting error;
- design-for-recovery product;
- quality-aware dynamic routing;
- reuse, repair, and refurbishment alternatives;
- chemical recovery where chemistry permits; and
- policy scenarios with and without external-cost internalization.

Remove one mechanism at a time in ablations: identity information, disassembly design, market demand, contamination, quality grading, reuse cycle losses, external costs, leakage, policy support, and regional infrastructure. A proposed mechanism is useful only if removing it changes route quality, future service, or burden in a reproducible direction.

## 9. Statistical plan and uncertainty

Use independent batches and randomized processing order for laboratory and facility trials. Estimate confidence intervals by block bootstrap for batch data. Propagate route probabilities and inventory uncertainty through Monte Carlo scenario sampling. Decompose variance into material, design, contamination, sorting, process, market, region, service, and interaction components. Report median, interval, and tail outcomes for each functional unit, not only pooled averages.

The primary success criterion is not a global recycling percentage. A portfolio succeeds when it increases quality-adjusted future service and reduces or bounds total impact across a declared set of plausible scenarios, while meeting safety and market constraints. A route is rejected when it depends on ideal contamination, an unavailable facility, an unidentified buyer, unsafe exposure, or a quality claim that does not survive repeated processing.

## 10. Safety and interpretation

Medical, biological, battery, flame-retarded, radioactive, and chemically hazardous materials are handled only under applicable containment, occupational, and regulatory procedures. They are not sent into open experimental recycling streams. A controlled treatment or substitution route is a valid outcome, not a failed recycling experiment.

The study reports conditional system conclusions. If a design increases sorting quality but requires excessive energy, the result identifies the energy threshold. If reuse wins only after many cycles, the result identifies the return and durability requirement. If chemical recovery has high yield but fails to displace virgin feedstock, it is not counted as closed-loop recovery. No claim of universal recyclability is made before execution.

## Expected-result boundary

This file specifies methods, hypotheses, comparisons, and acceptance criteria. It contains no observed results and no fabricated experimental values.
