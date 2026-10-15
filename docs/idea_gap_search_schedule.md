# Gap-focused Idea search scheduling

The default Idea scheduler selects routes from the primary scientific gap, rather
than running every route for every mature idea. The five existing route policies
remain available; selection uses gap kind, target slot, and defect tags. It does
not use topic names, species, or discipline-specific exceptions.

## Coverage and budget

Screening assigns one compatible route and one representative seed to each
eligible gap referenced by the mature ideas. Verified/core gaps take priority,
followed by provisional and exploratory gaps. Supporting constraints,
verification-only items, excluded items, and unknown IDs in a Survey handoff do
not become primary novelty targets. With no Survey handoff, explicit seed gap
IDs are accepted. Gapless seeds already admitted by the seed collector receive
one fallback route after eligible gaps, including unanchored reframing seeds with
a Survey handoff. They do not count toward Survey gap coverage.

`idea.mcts.screening_max_iterations` defaults to 3. Both screening and refinement
are capped by `idea.mcts.max_iterations`, and logs record the effective budget.
`idea.portfolio.screening_search_budget` defaults to 0, meaning one screening
search for each eligible referenced gap. A positive value limits screening
searches, and any gaps not searched remain visible in the schedule.

`idea.portfolio.refinement_search_budget` defaults to 3. Refinement allocates these
searches first to gaps not yet searched, then to gaps whose screening failed to
return a candidate, and finally to successful gaps ranked by priority and
candidate score. Previously attempted gaps receive a different route when one
is available. Refinement uses `idea.mcts.refinement_max_iterations` (default 8).
It retains successful screening candidates, even if refinement fails or returns
a weaker candidate. These are separate searches, not continuation of the same
MCTS tree.

The configured screening route IDs are the allowed route pool, not a requirement
to run every route. The legacy `screening_route_expansions_per_seed` limits the
size of that pool, rather than creating that many searches per seed. The former
`refinement_top_seeds` and `refinement_route_expansions_per_seed` no longer govern
the gap-focused refinement phase.

## Search contract and traceability

Each task records its original seed ID, primary gap, route selection reason,
effective iteration budget, and prior coverage status. Root and child states,
generation and evaluation prompts, rollout traces, and persisted candidates
carry this focus. Programmatic binding prevents generated gap IDs from replacing
the assigned primary gap. Other seed gaps remain contextual obligations rather
than simultaneous novelty targets. The focus retains their authoritative gap
content and evidence eligibility as `context_constraints`, while the evidence
handoff and `target_gap_ids` remain scoped to the primary gap. Unknown IDs do not
enter this constraint projection.

The stage artifact `gap_route_schedule` records screening and refinement tasks,
candidate coverage, and gaps left unsearched. Candidate coverage means that an
evaluated candidate was returned. It does not mean an experiment succeeded or a
scientific gap was resolved. Search identity and result filenames include the
primary gap, so two searches for different gaps do not overwrite each other.

The supplied-data coverage passes remain separate and retain their existing
coverage branches and budget cap. Disabling `run.route_matrix_enabled` retains
the single-direction compatibility path.
