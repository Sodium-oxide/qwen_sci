# ExperimentDesign Agent: PERSIST-CO2 research design

## Study question and mode

The experiment tests whether a permanence-aware portfolio can retain more verified atmospheric benefit, with fewer lifecycle and distributional burdens, than single-pathway or nominal-cost storage strategies. It is a prospective scenario and optimization study in `DESIGN_ONLY` mode. It reports no measured storage performance or deployed removal.

## Pathway representation

The scenario library contains geological storage in saline formations and depleted reservoirs; mineralization; terrestrial biological pools; coastal biological pools; DACCS; BECCS; enhanced weathering; and exploratory ocean-based methods. Each pathway has a declared boundary for captured or removed mass, energy source, transport, water, land or mineral demand, monitoring cost, retention curve, leakage modes, reversal events, and co-impacts. Pathway parameters are ranges rather than universal constants.

The portfolio contains pathway shares, siting decisions, transport and injection capacity, monitoring intensity, stewardship reserves, and staged deployment. Gross emissions reduction is an upstream control and is never replaced by a removal credit.

## Common carbon accounting

Let $M_{i,t}$ be gross CO2 captured or removed by pathway $i$ at time $t$, $e_i$ its lifecycle CO2-equivalent burden per unit gross removal, $p_i(t)$ retained fraction, and $l_i(t)$ measured or modeled leakage and reversal fraction. Net atmospheric benefit is defined as:

\begin{equation}
R_t^{\mathrm{net}}=\sum_i M_{i,t}\left[p_i(t)-l_i(t)-e_i\right],
\label{eq:netremoval}
\end{equation}

where all terms are converted to the same CO2-equivalent boundary and $e_i$ is capped or reported separately when lifecycle accounting is uncertain. The model reports gross capture, lifecycle burden, retained stock, leakage, reversal, and net benefit separately so that a large gross number cannot conceal a small durable benefit.

For a storage pool $S_i(t)$, the stock dynamics are:

\begin{equation}
\frac{dS_i(t)}{dt}=I_i(t)-\lambda_i(t)S_i(t)-V_i(t),
\label{eq:stock}
\end{equation}

where $I_i$ is injected or accumulated carbon, $\lambda_i$ is a leakage rate, and $V_i$ is a disturbance or reversal flux. Geological, biological, and ocean pathways use different priors and event distributions for these terms.

## Resource and infrastructure constraints

For each region $r$ and time $t$, energy consumed by removal and compression is bounded by available low-carbon energy:

\begin{equation}
\sum_i a_{i,r,t}M_{i,r,t}+E^{\mathrm{MRV}}_{r,t}
\leq E^{\mathrm{clean}}_{r,t}-E^{\mathrm{priority}}_{r,t},
\label{eq:energy}
\end{equation}

where $a_i$ is pathway energy intensity, $E^{\mathrm{MRV}}$ is monitoring energy, and $E^{\mathrm{priority}}$ protects existing essential demand. Land, water, mineral, pipeline, well, and monitoring capacity are represented with analogous inequalities. Biological pathways cannot exceed available eligible land after food, biodiversity, and tenure constraints. Geological pathways cannot exceed site-specific injectivity, pressure, plume, and monitoring limits.

Additionality is enforced by comparing the intervention with a declared baseline land or industrial trajectory. A project receives no removal credit for carbon that would have been stored without the intervention. Transport leakage, parasitic energy, and emissions displaced to other regions remain inside the accounting boundary.

## Robust portfolio optimization

Let $z$ be a staged portfolio and $J_w(z)$ a vector of cost, negative net atmospheric benefit, energy burden, land and water burden, ecological impact, leakage risk, monitoring shortfall, and distributional burden in scenario $w$. The policy minimizes worst-case regret subject to a minimum durable benefit and safety limits:

\begin{equation}
\begin{aligned}
z^*=\mathop{\mathrm{arg\,min}}\limits_{z\in\mathcal{Z}}\;&\max_{w\in\mathcal{W}}\nonumber\\
&\left\|J_w(z)-\min_{z'\in\mathcal{Z}}J_w(z')\right\|_\infty\\
\text{subject to }&R_t^{\mathrm{net}}\geq \underline{R}_t,\nonumber\\
&\operatorname{MRVShortfall}(z,w)\leq \overline{m},\nonumber\\
&\operatorname{Burden}_{r}(z,w)\leq \overline{b}_r.
\end{aligned}
\label{eq:robust}
\end{equation}

Here $\mathcal{Z}$ is the feasible portfolio set, $\mathcal{W}$ is the scenario set, $\underline{R}_t$ is the declared minimum net benefit, and $\overline{m}$ and $\overline{b}_r$ are monitoring and regional burden limits. Pareto fronts and weight sensitivity are reported instead of one undisclosed score.

## Scenario ensemble and controls

Scenarios vary emissions baselines, energy carbon intensity and availability, pathway costs, retention and leakage, fire and drought frequency, storage-site integrity, mineral supply, land and water scarcity, transport build rates, monitoring errors, governance capacity, and social acceptance. Development, stress-test, and held-out sets are separated before optimization.

Controls include avoidance-only, geology-first, biology-first, engineered-removal-first, and a nominal-cost optimizer that ignores durability. A perfect-MRV control estimates an information upper bound. Ablations remove durability accounting, monitoring capacity, resource constraints, equity constraints, or stewardship triggers one at a time.

## Monitoring, liability, and staged triggers

Each project registers a baseline, mass flow, retention horizon, measurement uncertainty, leakage pathway, responsible operator, financial reserve, and closure plan. A trigger is activated when observed plume migration, pressure, ecosystem loss, fire, drought, or monitoring uncertainty crosses a predeclared envelope. The response can pause injection, retire credits, fund remediation, or move future volume to another pathway. Hysteresis avoids repeated switching around noisy measurements. The model never treats a trigger as a substitute for legal authority.

## Analysis and falsification

The sequence is: freeze boundaries and parameter ranges; construct scenarios; calibrate pathway models; optimize every control and treatment; evaluate held-out scenarios and extreme events; run ablations; test sensitivity to retention horizon and lifecycle accounting; and report net benefit, regret, resource use, MRV shortfall, reversal, and distributional burden.

PERSIST-CO2 is supported only if it improves held-out durability-adjusted regret while meeting declared resource, MRV, and burden constraints. It is falsified if a single-pathway or nominal-cost control performs as well under equal accounting, if its advantage disappears under held-out reversal or energy scenarios, or if it requires perfect monitoring, unbounded land, or unpriced stewardship. A negative result identifies which pathway or accounting assumption failed.

