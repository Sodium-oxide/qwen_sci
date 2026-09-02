# Survey Agent: Can Robots or AIs Have Human Creativity?

## 1. Scientific reframing

The popular question asks whether a robot or AI can have human creativity. The phrase
"have" mixes several claims that must be separated. This study therefore reframes the
question as:

> Under what conditions can an AI or robot produce artifacts that are novel, valuable,
> surprising, diverse, and constraint-satisfying, while also showing adaptive search,
> transfer to held-out tasks, and useful human-AI co-creation?

The reframing is intentionally operational. It evaluates observable products and
processes, not consciousness, subjective experience, moral status, or an untestable
claim that a machine is human.

## 2. Evidence map

### 2.1 Narrow creative performance

Silver et al. introduced AlphaGo as a combination of policy networks, value networks,
supervised learning from human expert games, reinforcement learning from self-play,
and Monte Carlo tree search [1]. The Nature abstract reports a 99.8% win rate against
other Go programs and a 5-0 victory over the European Go champion. Unusual or admired
moves are evidence that a search system can generate surprising game actions. They are
not, by themselves, evidence of human-like intention, domain-general creativity, or
subjective appreciation of beauty.

### 2.2 Computational creativity

Wiggins proposed a framework for describing, analyzing, and comparing creative systems
[2]. It is useful because it treats creativity as a system-level phenomenon involving
spaces, rules, exploration, and evaluation. Boden's account distinguishes combinations,
explorations, and transformations of conceptual spaces [3]. Together they motivate a
measurement protocol that reports both the artifact and the generative search trace.

### 2.3 Human-like generalization

Lake et al. argue that systems that perform well on selected benchmarks can still differ
from people in compositionality, causal learning, intuitive physics, and learning from
small data [4]. A creative AI claim should therefore include held-out concepts,
perturbed constraints, and cross-domain transfer rather than only in-distribution
quality.

### 2.4 Human-AI co-creativity

Amershi et al. describe interactive machine learning as a setting in which people guide
and correct learning systems [5]. Dellermann et al. characterize hybrid intelligence as
complementary human and machine capabilities that can jointly outperform either side in
some tasks [6]. These sources motivate a separate co-creation condition and explicit
tracking of human edits, vetoes, and attribution.

## 3. Definitions for the benchmark

* **Product creativity:** novelty plus value/usefulness under a stated domain and
  constraints.
* **Process creativity:** adaptive exploration, self-critique, search-space coverage,
  and transfer, measured from logs and held-out tasks.
* **Co-creativity:** a human-AI workflow in which contributions interact and the joint
  result is evaluated separately from either agent's solo result.
* **Novelty:** distance from a reference corpus, with nearest-neighbor and memorization
  controls.
* **Value:** objective task performance when available, and blinded multi-rater scores
  only as a supplementary measure.
* **Surprise:** evaluator disagreement or calibrated unexpectedness, not a synonym for
  quality.
* **Agency/authorship:** a provenance and control property. Output style cannot
  establish consciousness or intention.

## 4. Current consensus and unresolved issues

The evidence supports the following bounded conclusion: current systems can generate
novel-looking and useful artifacts in bounded domains, especially when they combine
large-scale learning with explicit search or feedback. It does not establish that they
possess human creativity as a unified cognitive trait. The central unresolved issue is
whether apparent creativity remains robust when memorization is controlled, evaluation
criteria change, constraints are novel, and the system must transfer its strategy.

Five recurrent confounds are important:

1. **Selection confound:** humans choose and polish the best outputs.
2. **Training leakage:** a supposedly novel output may be a close retrieval or learned
   template.
3. **Evaluator bias:** unusualness is often mistaken for creativity.
4. **Objective mismatch:** a high benchmark score may reward optimization, not insight.
5. **Attribution ambiguity:** a joint human-AI artifact has multiple causal contributors.

## 5. Gap ledger

| Gap | Scientific consequence | Proposed control |
|---|---|---|
| Novelty is corpus-dependent | Scores cannot be compared across datasets | Publish reference corpus, embedding model, and distance thresholds |
| Value is domain-dependent | Aesthetic preference can dominate | Pair blinded ratings with executable or engineering criteria |
| Search traces are rarely retained | Process claims cannot be audited | Store prompts, candidates, edits, seeds, and rejection reasons |
| Transfer is under-tested | Narrow memorization looks general | Use held-out concepts, domains, and constraint perturbations |
| Humans are labeled by condition | Expectancy changes ratings | Blind raters to source and randomize presentation |
| Human contribution is hidden | Co-creativity is over-claimed | Log time, edits, vetoes, and origin of each final component |

## 6. Survey research questions

* RQ1: Can product-level novelty and usefulness be achieved without evidence of
  human-like agency?
* RQ2: Do self-critique and explicit search improve creativity metrics, and do they
  reduce diversity through evaluator optimization?
* RQ3: Under what task conditions does a human-AI team outperform human-only and AI-only
  baselines?
* RQ4: Do held-out concepts and cross-domain transfer distinguish recombination from
  memorization?
* RQ5: How much do source labels change human judgments of creativity?

## 7. Scope and evidence status

This is a design-only research program. No human ratings, model scores, or causal
results are asserted. The proposed benchmark is named
**CREATIVE-AI-AGENCY-BENCHMARK**. AlphaGo is treated as a motivating case of bounded
search competence, not as a proof of human creativity. Claims about consciousness,
sentience, personhood, or general intelligence are outside the study's evidentiary
scope.

## References used by Survey

[1] D. Silver et al., "Mastering the game of Go with deep neural networks and tree
search," *Nature*, vol. 529, pp. 484-489, 2016.

[2] G. A. Wiggins, "A preliminary framework for description, analysis and comparison
of creative systems," *Knowledge-Based Systems*, vol. 19, no. 7-8, pp. 449-458, 2006.

[3] M. A. Boden, *The Creative Mind: Myths and Mechanisms*, 2nd ed. London, U.K.:
Routledge, 2004.

[4] B. M. Lake, T. D. Ullman, J. B. Tenenbaum, and S. J. Gershman, "Building machines
that learn and think like people," *Behavioral and Brain Sciences*, vol. 40, 2017.

[5] S. Amershi et al., "Power to the people: The role of humans in interactive machine
learning," *AI Magazine*, vol. 35, no. 4, pp. 105-120, 2014.

[6] D. Dellermann, P. Ebel, M. Sollner, and J. M. Leimeister, "Hybrid intelligence,"
*Business & Information Systems Engineering*, vol. 61, pp. 637-643, 2019.
