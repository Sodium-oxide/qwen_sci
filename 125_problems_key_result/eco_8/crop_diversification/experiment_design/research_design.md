# ExperimentDesign Agent: DIVERSIFIED-RESILIENT-AGRIFOOD

## 1. Objective and design mode

Test when diversification reduces food-system and ecological risk without unacceptable losses in food delivery, farmer income, nutrition, land, water, labor, or safety. The design compares temporal, spatial, genetic, landscape, and food-system diversity and then tests whether they remain useful under compound shocks.

This is a DESIGN_ONLY package. It contains protocols, hypotheses, model equations, controls, and decision rules. It contains no completed field measurements, no observed yields, no verified pest forecasts, and no fabricated economic or nutrition outcomes.

## 2. Experimental strata

Use four dominant-crop systems and six diversification interventions:

- wheat, maize, rice, and soy monoculture baselines;
- temporal rotation with legumes, oilseeds, roots, forage, or cover crops;
- spatial intercropping with complementary crops;
- cultivar mixtures or diversified seed sources;
- field-margin, hedgerow, wetland, and non-crop habitat;
- locally adapted neglected or underutilized crop corridors; and
- combined portfolios that stack compatible interventions.

Each intervention is matched to a conventional system with comparable soil class, climate, farm size, irrigation, planting window, and market access. The design retains systems in which a dominant crop remains present; the target is lower hazardous concentration rather than zero specialization.

## 3. Functional units and outcomes

Primary units are one hectare-year and one delivered nutrition basket. The basket reports energy, protein, and specified micronutrients after storage, processing, and food loss. Secondary units include one tonne of crop, one unit of farm income, and one kilogram of fertilizer or pesticide avoided.

Primary outcomes:

- mean yield, yield variance, lower-tail loss, and recovery time;
- calories, protein, micronutrients, food safety, and affordability;
- soil organic carbon, erosion, nutrient balance, water use, and pesticide use;
- pest and disease incidence, treatment frequency, and resistance indicators;
- pollinator and natural-enemy abundance, habitat quality, and flowering continuity;
- greenhouse gases, land-use change, displaced production, and food loss;
- farmer income, labor, machinery, storage, price volatility, and adoption persistence.

## 4. Study stages

### Stage 1: Baseline and historical risk

Assemble field, farm, remote-sensing, weather, pest, pathogen, price, trade, seed, and storage records. Define crop area, genotype, management, and shock exposure at a common spatial and temporal scale. Estimate correlations among yield, climate, pest, disease, and market outcomes. Do not infer resilience from mean yield alone.

### Stage 2: Controlled field experiments

Use randomized blocks or matched long-term sites with monoculture, rotations, intercrops, cultivar mixtures, habitat support, forgotten-crop treatments, and combined designs. Replicate across soil and climate strata. Record planting and harvest timing, inputs, machinery passes, labor, crop competition, soil cover, soil carbon, erosion proxies, water, pests, pathogens, pollinators, natural enemies, yield, quality, and food safety.

At least one multi-year phase is required because rotation disease breaks, soil changes, habitat establishment, and adoption costs are not first-season effects. Failed establishment and weather-damaged plots remain in the analysis.

### Stage 3: Farm and value-chain trials

Move promising treatments to commercial farms with farmer-led implementation. Track seed access, machinery compatibility, timing conflicts, storage, processing, buyers, price, contract risk, labor, and household food use. For neglected crops, test the complete corridor: seed multiplication, agronomy, harvest, drying, processing, storage, food safety, nutrition, consumer acceptance, procurement, and market demand.

### Stage 4: Shock experiments and simulation

Expose crop portfolios to historical and synthetic drought, heat, flood, frost, pest, pathogen, input-price, transport, and trade shocks. Use crop growth and pest models calibrated to Stage 1 and evaluated on held-out years. Couple crop output to storage, processing capacity, reserves, imports, substitution among foods, and household affordability.

### Stage 5: Adoption and policy

Compare extension, seed support, shared machinery, crop insurance, ecosystem-service payments, procurement, storage investment, price guarantees, and risk-sharing contracts. Measure adoption after one, three, and five years. Distinguish stated interest from repeated management and include who bears transition labor and financial risk.

### Stage 6: Out-of-sample validation

Hold out one region, one farm-size class, one crop, or one shock family. Freeze thresholds and model parameters before the holdout. Report transfer error, ranking stability, and whether the intervention reduces tail risk outside the calibration environment.

## 5. Risk and resilience model

For crop c, region r, year t, and shock s, let F be delivered food output after losses and processing. A risk-adjusted portfolio utility is

\begin{equation}
U(P)=\mathbb{E}[F(P)]-\alpha \operatorname{CVaR}_{\beta}(F(P))-\gamma A(P),
\label{eq:utility}
\end{equation}

where P is the crop-management portfolio, CVaR is lower-tail food loss at confidence level beta, A is the total adoption and management burden, and alpha and gamma are declared decision weights. Mean output, tail loss, and burden are also reported separately; the utility is not treated as a universal food-security score.

For a portfolio with crop shares w_i and shock-specific yields y_i,s, food delivery is

\begin{equation}
F(P,s)=\sum_i w_i y_{i,s}(1-\ell_{i,s})\kappa_i,
\label{eq:food}
\end{equation}

where ell is post-harvest and processing loss and kappa converts output into the chosen nutrition unit. The model includes correlations among y, loss, prices, and infrastructure. Independent crop components are not assumed.

## 6. Ecological mechanism tests

Mechanism tests connect outcomes to causal pathways:

- rotation versus continuous crop tests disease break and nutrient balance;
- intercrop density gradients test complementarity against competition;
- cultivar mixtures test pathogen spread and synchronized susceptibility;
- habitat treatments test pollinator and natural-enemy mediation;
- cover-crop treatments test soil cover, erosion, carbon, and water pathways;
- reduced pesticide treatments test whether biological control replaces chemical input;
- forgotten-crop treatments test nutrition and climate tolerance with value-chain constraints.

Mediation is reported only when the mechanism is measured. A higher yield without a soil, pest, pollination, or nutrient mechanism is not used to claim ecological causation.

## 7. Economic, nutrition, and life-cycle model

For service unit u, report

\begin{equation}
J(P,r)=\left(F_{\mathrm{energy}},F_{\mathrm{protein}},N_{\mathrm{micro}},Y_{\mathrm{tail}},S_{\mathrm{soil}},B_{\mathrm{bio}},G,W,L,C,I\right),
\label{eq:objectives}
\end{equation}

where the terms represent food energy, protein, micronutrients, tail loss, soil service, biodiversity service, greenhouse gases, water, land displacement, cost, and income distribution. Labor, machinery, storage, processing, food loss, and affordability are explicit.

The land-use account includes displaced production and leakage. If a diversified region produces less of a dominant crop and another region expands to compensate, the net land and climate burden is assigned to the complete system. If a forgotten crop improves nutrition but requires more water or processing energy, both benefits and burdens remain visible.

## 8. Baselines and ablations

Compare:

- current monoculture with current inputs and markets;
- monoculture with improved cultivar or input management;
- rotation only;
- intercropping only;
- cultivar mixture only;
- landscape habitat only;
- forgotten-crop corridor only;
- combined diversification portfolio;
- portfolio with storage and processing support; and
- portfolio with policy and risk-sharing support.

Ablations remove one layer at a time: genetic diversity, rotation, habitat, forgotten crops, storage, processing, market access, shock insurance, land-displacement accounting, food-loss accounting, and multi-year adoption. These comparisons identify whether a result comes from field biology, value-chain support, or policy.

## 9. Statistical plan and decision rules

Use hierarchical models with site, farm, year, crop, and treatment effects. Block bootstrap provides uncertainty for repeated field observations. Shock simulations sample climate, pest, disease, price, and infrastructure uncertainty. Report effect sizes, confidence or credible intervals, lower-tail food loss, and heterogeneous effects by farm and region.

A portfolio advances only if it:

1. meets food, safety, and nutritional requirements;
2. reduces tail loss or improves measured ecosystem services without unacceptable mean-yield or income loss;
3. does not shift land, water, pollution, or labor burdens outside the study boundary;
4. has seed, machinery, storage, processing, and buyer access; and
5. remains beneficial under plausible climate, pest, price, and policy scenarios.

The conclusion is conditional by design. A portfolio can be recommended for one crop-region system and rejected for another.

## 10. Safety and interpretation

Pest and pathogen trials use contained or regulated protocols. Seed movement and neglected-crop introduction follow phytosanitary and food-safety requirements. No treatment encourages uncontrolled release of organisms or replacement of local varieties without risk assessment. Household or farmer trials require informed participation and protection against financial loss where applicable.

The “end of monoculture” is therefore operationalized as a reduction in hazardous concentration and synchronized failure, not the elimination of all large-scale crop specialization. No observed result is asserted until the staged experiments and model validation are performed.

