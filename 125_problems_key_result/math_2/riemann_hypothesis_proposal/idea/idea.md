# Idea Agent Portfolio: An Audit-First Program for RH

| ID | Direction | Evaluation | Decision |
|---|---|---|---|
| I1 | New finite zero-height record | Valuable but cannot resolve G1 alone | Competitive component |
| I2 | Finite initial segment of Li coefficients | Useful certificate exercise but cannot resolve G2 | Competitive component |
| I3 | Accept a recent external-model claim | No verified map or tail closure | Rejected |
| I4 | **ProofBridge: auditable Li positivity and tail exclusion** | Directly targets G1--G4 | **Selected** |
| I5 | Survey reformulations only | No discriminating theorem program | Rejected |

## Selected idea: ProofBridge

ProofBridge treats a proof attempt as a directed graph of formal obligations, not as a sequence of persuasive analogies. Its base node is the completed xi function and its target is the universal statement \(\forall\rho\in Z(\xi),\ \Re\rho=1/2\). The selected bridge is Li's criterion: define the Li coefficients exactly, establish the equivalence between RH and \(\lambda_n\ge0\) for every positive integer \(n\), and then separate the finite-computation layer from the all-index analytic layer.

The research question is: **Can a non-circular structural theorem supply a uniform tail-exclusion bound strong enough to upgrade certified finite Li positivity into all-index positivity?** ProofBridge does not assume that such a theorem exists. Its first output may be an obstruction ledger showing where a candidate bridge lacks a defined map, a verified theorem hypothesis, or an unbounded quantifier.

## Typed outputs and falsification

Every edge receives one of `PROVED`, `CERTIFIED_FINITE`, `CONDITIONAL`, `GAP`, or `UNVERIFIED_CLAIM`. A proof is released only if every edge is `PROVED`. A finite Li certificate remains `CERTIFIED_FINITE`. The route is falsified as a proof if any bridge lacks a defined map, a cited theorem's hypotheses fail, a tail estimate is non-uniform, or an implication imports RH or an equivalent statement. This preserves useful subtheorems while stopping a finite or conditional result from being misreported as RH.

## MCTS evolution

The search began from a high-risk goal of deriving RH from a recent external-model claim. It split the narrative into map, theorem, tail, and circularity obligations; this revealed multiple hidden universal statements. It then combined the strongest formal anchor (Li positivity) with a typed proof-obligation graph. The final direction is bolder than a passive survey because it demands a path to a theorem, but it refuses to manufacture that path.
