# Survey Agent Report: Can AI Replace a Doctor?

## Scientific reframing

The phrase “replace a doctor” combines many distinct activities: data acquisition, diagnostic interpretation, uncertainty management, prognosis, treatment selection, physical examination, procedural care, consent, communication, coordination, escalation, longitudinal follow-up, and accountability. A model can outperform a clinician on a narrowly defined benchmark while remaining unable to assume the entire clinical service.

**Operational question.** For a named clinical task, population, site distribution, decision authority, and outcome horizon, can an AI-enabled pathway satisfy safety, external validity, equity, calibration/abstention, patient communication, accountability, and continuous-monitoring requirements at least as well as a human-led pathway?

This reframing yields a direct conclusion. Current evidence supports AI as a powerful component of clinical work and, in selected tasks, as a potentially autonomous *subtask* performer. It does not establish that an AI system can replace physicians as general, independently accountable clinicians across the full care episode.

## Evidence map

### What is established

1. **Task-specific performance can be high.** AI systems can match or surpass clinician comparison groups in defined image-analysis tasks. McKinney et al. evaluated an AI system for breast-cancer screening across UK and US datasets and compared it with radiologists [S1]. Systematic reviews also find comparable performance in many diagnostic-image studies [S2, S3].
2. **Benchmark performance is not clinical replacement evidence.** The systematic review by Nagendran et al. found that relatively few comparative deep-learning studies were prospective or tested in a real-world setting; many had high risk of bias and limited reporting or code/data access [S2].
3. **Translation requires clinical integration.** Real clinical value depends on local data, workflow, end-user understanding, prospective evaluation, regulation, and post-deployment monitoring; technical accuracy alone is not a sufficient outcome [S5, S12].
4. **Bias and distribution shift are clinical safety issues.** Biased labels, unrepresentative data, local practice patterns, and subgroup performance gaps can create or worsen inequities [S6--S8]. Local external validation and ongoing recalibration are essential.
5. **Governance keeps humans responsible.** Ethics, regulation, and lifecycle guidance place responsibility on people and institutions, not on the AI system. Trustworthy systems need fairness, universality, traceability, usability, robustness, explainability, monitoring, and accountable governance [S9, S13--S16].
6. **Human-AI interaction is an empirical object.** Explanations and interface choices may change trust, attention, workload, and final decisions. They cannot be assumed to improve patient outcomes merely because the model is accurate [S17, S18].

### What the evidence does not justify

- A result in breast screening, dermatology, or another bounded imaging task does not prove competence in general medicine.
- A model's area under the ROC curve does not prove safer treatment, better patient understanding, or valid informed consent.
- “Human in the loop” is not a safety guarantee unless the human's authority, information, workload, escalation rule, and accountability are defined and evaluated.
- A locally validated model does not retain its performance automatically after case mix, scanner, guideline, referral, or treatment practice changes.
- AI should not be described as having legal or ethical responsibility; institutions and clinicians remain duty bearers.

## Subhypotheses and coverage

| ID | Subhypothesis | Evidence status | Evidence anchors |
|---|---|---|---|
| SH-1 | An AI can equal or exceed an expert comparison group in a tightly defined diagnostic task. | Supported for selected tasks | S1--S4 |
| SH-2 | Technical performance transfers unchanged to diverse clinical sites and populations. | Not supported as a general claim | S2, S5--S8 |
| SH-3 | A clinician-AI pathway can be safer or more efficient than either alone. | Plausible, task-dependent, requires prospective testing | S1, S5, S12, S18 |
| SH-4 | An AI can independently replace a doctor across a full care episode. | Not supported | S2, S5, S9, S13--S16 |
| SH-5 | Continuous monitoring and an explicit escalation path can make task delegation auditable. | Strong design rationale; needs prospective validation | S10--S16 |

## Accepted research gaps

### GAP-BOUNDARY-001: performance claims lack a delegation boundary

Studies often compare model and clinician metrics without specifying which decision right, patient subgroup, uncertainty level, or downstream consequence could be delegated. A task score is not a scope-of-practice definition.

### GAP-OUTCOME-002: technical accuracy is detached from care-episode outcomes

Clinical safety depends on missed harmful events, false alarms, downstream work, timeliness, patient understanding, and continuity. These outcomes must be assessed alongside discrimination metrics.

### GAP-EQUITY-003: subgroup failure modes are under-specified

Dataset composition, labels, access, and deployment context can produce differential errors. Aggregate performance can conceal clinically meaningful harm to specific subgroups.

### GAP-HUMAN-004: human oversight is underspecified

The role of the clinician is frequently left as a vague “human in the loop.” Without an authority map, abstention rule, workload model, and override record, it cannot be evaluated.

### GAP-LIFECYCLE-005: model performance is treated as static

Clinical environments shift. A deployable system needs monitoring, drift thresholds, retraining governance, incident response, and a safe withdrawal path.

## Survey handoff

The Idea Agent should not search for a generic “AI doctor.” It should construct a **Clinical Delegation Boundary Contract (CDBC)** for a single low-intervention clinical subtask, starting with screening-mammography triage in a shadow-mode evaluation. The contract must declare what the model may do, when it must abstain, who makes the final decision, which populations and sites are in scope, how equity is audited, and what evidence permits or revokes a delegation tier.

## Source register

- **S1** S. M. McKinney et al., “International evaluation of an AI system for breast cancer screening,” *Nature*, 2020, doi:10.1038/s41586-019-1799-6. Publisher page verified in the in-app browser: title, authors, publication date, journal, volume, pages, DOI, and abstract.
- **S2** M. Nagendran et al., “Artificial intelligence versus clinicians: systematic review of design, reporting standards, and claims of deep learning studies,” *BMJ*, 2020, doi:10.1136/bmj.m689.
- **S3** J. Shen et al., “Artificial Intelligence Versus Clinicians in Disease Diagnosis: Systematic Review,” *JMIR Medical Informatics*, 2019, doi:10.2196/10010.
- **S4** E. J. Topol, “High-performance medicine: the convergence of human and artificial intelligence,” *Nature Medicine*, 2019, doi:10.1038/s41591-018-0300-7.
- **S5** C. J. Kelly et al., “Key challenges for delivering clinical impact with artificial intelligence,” *BMC Medicine*, 2019, doi:10.1186/s12916-019-1426-2.
- **S6** Z. Obermeyer et al., “Dissecting racial bias in an algorithm used to manage the health of populations,” *Science*, 2019, doi:10.1126/science.aax2342.
- **S7** L. A. Celi et al., “Sources of bias in artificial intelligence that perpetuate healthcare disparities---A global review,” *PLOS Digital Health*, 2022, doi:10.1371/journal.pdig.0000022.
- **S8** R. Challen et al., “Artificial intelligence, bias and clinical safety,” *BMJ Quality & Safety*, 2019, doi:10.1136/bmjqs-2018-008370.
- **S9** World Health Organization, *Ethics and Governance of Artificial Intelligence for Health*, 2021.
- **S10** X. Liu et al., “Reporting guidelines for clinical trial reports for interventions involving artificial intelligence: the CONSORT-AI extension,” *Nature Medicine*, 2020, doi:10.1038/s41591-020-1034-x.
- **S11** B. Vasey et al., “Reporting guideline for the early-stage clinical evaluation of decision support systems driven by artificial intelligence: DECIDE-AI,” *Nature Medicine*, 2022, doi:10.1038/s41591-022-01772-9.
- **S12** J. Feng et al., “Clinical artificial intelligence quality improvement: towards continual monitoring and updating of AI algorithms in healthcare,” *npj Digital Medicine*, 2022, doi:10.1038/s41746-022-00611-y.
- **S13** National Institute of Standards and Technology, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, 2023, doi:10.6028/NIST.AI.100-1.
- **S14** U.S. FDA, Health Canada, and MHRA, *Good Machine Learning Practice for Medical Device Development: Guiding Principles*, 2021.
- **S15** K. Lekadir et al., “FUTURE-AI: international consensus guideline for trustworthy and deployable artificial intelligence in healthcare,” *BMJ*, 2025, doi:10.1136/bmj-2024-081554.
- **S16** B. Meskó and E. J. Topol, “The imperative for regulatory oversight of large language models (or generative AI) in healthcare,” *npj Digital Medicine*, 2023, doi:10.1038/s41746-023-00873-0.
- **S17** J. Amann et al., “Explainability for artificial intelligence in healthcare: a multidisciplinary perspective,” *BMC Medical Informatics and Decision Making*, 2020, doi:10.1186/s12911-020-01332-6.
- **S18** C. Panigutti et al., “Co-design of Human-centered, Explainable AI for Clinical Decision Support,” *ACM Transactions on Interactive Intelligent Systems*, 2023, doi:10.1145/3587271.

**Review condition.** Before a real clinical study, domain experts must review the full text, intended-use labeling, regulatory status, local standard of care, evidence applicability, ethics, privacy, and data-governance requirements. This survey does not authorize clinical deployment or provide medical advice.
