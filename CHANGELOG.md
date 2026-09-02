# Changelog

All notable user-facing changes are documented in this file.

## [0.3.0] - 2026-09-03

### Added

- An optional, supervised quantitative-modeling sidecar that may create up to
  two independent candidates, `Q1` and `Q2`, for bounded mathematical modeling
  and numerical simulation.
- Evidence-bound parameter workflows: the system can prepare a model blueprint,
  discover citable parameter sources, extract quote-anchored candidates, and
  create a reviewable parameter proposal.
- Explicit human approval for a complete parameter set and an identity-bound
  `quantitative simulate --execute --plan-identity ...` operation for every
  numerical execution.
- Human qualification of completed simulation results as
  `SUPPORTED_WITHIN_MODEL`, `CONSTRAINED`, `REFUTED_WITHIN_MODEL`, or
  `INCONCLUSIVE`, with the result ledger retaining qualified non-positive and
  inconclusive outcomes.
- Controlled quantitative refinement from `v0` through at most `v2`; every
  accepted revision requires a newly materialized plan and a new explicit
  execution authorization.
- A standalone mathematical-model PDF and a controlled quantitative Author
  handoff containing the qualified final outcome and necessary revision lineage.
- Resumable quantitative status and continuation paths that can generate safe
  non-executing artifacts while returning at every human decision point.

### Changed

- The primary scientific workflow remains `Survey -> Idea -> ExperimentDesign
  -> Author`. Quantitative modeling is an isolated Q1/Q2 sidecar, not a fifth
  stage of that state machine.
- The quantitative sidecar does not modify `idea_result_v5` or the input passed
  to ExperimentDesign. It may start only after the same science run has a
  completed design-only ExperimentDesign artifact.
- `--quantitative-mode required` intentionally pauses the primary workflow
  after ExperimentDesign until a completed quantitative Author handoff exists;
  `off` and `optional` preserve the ordinary Author closure behavior.
- The main research report PDF and the mathematical-model PDF are intentionally
  separate deliverables. Author receives a bounded handoff rather than parsing
  the mathematical-model chapter as part of the main article.

### Safety and Execution Boundary

- Quantitative modeling is not an autonomous closed loop. Parameter selection,
  parameter approval, network evidence retrieval, numerical execution, result
  interpretation, and revision acceptance remain explicit human decisions.
- LLMs may propose validated MathIR/PDEIR model contracts, but cannot supply or
  execute arbitrary Python, Julia, MATLAB, or shell code. Numerical execution
  is limited to registered, trusted solver adapters.
- Simulated outputs remain model-internal, non-empirical evidence and are not
  presented as laboratory or observational results.

### Upgrade Notes

- Existing users can continue to run the normal four-stage workflow without
  requesting or executing quantitative modeling.
- Local science runs, research results, caches, uploads, and generated PDFs are
  excluded from version control by default. Preserve or distribute them through
  an explicit, reviewed artifact-export path rather than a source release.
