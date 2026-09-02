# Idea: UNCERTAINTY-CALIBRATED-HUMAN-AI-COLLABORATION-BENCHMARK

## One-sentence proposal

Create a preregistered, factorial benchmark that measures the boundary between AI automation, human augmentation, and human-AI complementarity across routine, distribution-shifted, and equivocal tasks, with calibrated delegation interfaces and repeated exposure tests for human learning and over-reliance.

## Why this idea

“Replace humans” is not one outcome. A system can replace a narrow task while creating new tasks, improve a worker's productivity while making their judgment less practiced, or perform better alone on average while harming a team through correlated errors and automation bias. The proposed benchmark measures these mechanisms directly.

The key insight is to treat uncertainty communication as an experimental treatment, not a user-interface detail. In a well-calibrated system, confidence can guide a person to inspect difficult cases. In an overconfident or miscalibrated system, the same interface can increase acceptance of wrong answers. In an equivocal task, a probability over labels is insufficient because the problem may have multiple plausible interpretations or incomplete objectives. A robust collaborator should identify missing assumptions, request information, abstain, or escalate.

## Experimental factors

* **Agent condition:** human alone, AI alone, human plus AI, and human plus an oracle-calibrated reference.
* **Task regime:** routine/stationary, distribution shift, and equivocal/underspecified.
* **Interface:** answer only, calibrated confidence, confidence plus rationale, and selective abstention/delegation.
* **Expertise:** novice, intermediate, and expert strata.
* **Exposure:** single session versus repeated sessions followed by no-AI transfer.
* **Cost structure:** symmetric versus asymmetric false-positive and false-negative consequences.

The oracle-calibrated reference is not assumed to be available in deployment. It separates the value of truthful uncertainty from the value of merely displaying a confidence number. The AI-only condition establishes automation performance; the human-only condition establishes baseline judgment; the hybrid conditions test complementarity.

## Hypotheses

**H0 - performance-only automation:** AI will dominate humans on routine, stationary tasks, but hybrid performance will not reliably exceed the best member once communication cost and error correlation are included.

**H1 - distribution-shift boundary:** Under distribution shift, calibrated abstention and human review will reduce expected loss relative to answer-only AI, especially when the model's confidence is aligned with error probability.

**H2 - equivocality complementarity:** On tasks with multiple plausible interpretations or under-specified objectives, a hybrid with explicit assumption elicitation will outperform AI-only and human-only conditions on utility and calibration.

**H3 - complementary errors:** Team value will increase as conditional human and AI errors become less correlated, but a poorly designed interface can erase complementarity through automation bias.

**H4 - expertise heterogeneity:** Novices will obtain larger immediate productivity gains from AI assistance, while experts will contribute more under shift and equivocality; repeated exposure can either improve human learning or cause deskilling depending on delegation policy.

**H5 - uncertainty-aware delegation:** A policy that allows the AI to abstain and asks the human for targeted information will achieve a better risk-coverage curve than fixed always-answer or always-review policies at equal time budget.

**H6 - replacement is task-conditional:** The strongest evidence for replacement will occur only for narrow stationary task slices. At the workflow level, new human tasks in verification, exception handling, goal specification, and accountability will remain measurable.

## Main contribution

The benchmark returns a boundary map rather than a binary prediction:

\[
\text{task regime} \times \text{interface} \times \text{expertise}
\longrightarrow \text{automation, augmentation, or complementarity}.
\]

The primary outcome is expected utility per unit time subject to a risk constraint. Secondary outcomes capture calibration, selective delegation, error dependence, learning, workload, trust updates, and subgroup disparity. A future empirical result could therefore answer not only whether AI is faster, but when speed is outweighed by uncertainty, coordination cost, or loss of human capability.

## Scientific and practical value

If AI alone is strong on routine tasks but fails under shift, the study identifies an evaluation boundary rather than declaring a general limit. If a calibrated hybrid dominates both agents on equivocal tasks, it supports human-AI complementarity and provides an interface design target. If repeated assistance improves novices but weakens unaided transfer, the result identifies a learning trade-off that ordinary productivity metrics miss. If human and AI errors remain highly correlated, deploying both may create a false sense of redundancy.

## Safety and governance value

The design is suitable for low-stakes simulated decisions first. No participant should make medical, legal, employment, or safety-critical decisions as part of an unreviewed pilot. If human participants are later enrolled, the protocol requires informed consent, privacy protection, preregistration, institutional review, deception minimization, and debriefing. The AI is never the sole authority in a high-stakes setting. Audit logs record model version, confidence, abstention, human override, and final decision.
