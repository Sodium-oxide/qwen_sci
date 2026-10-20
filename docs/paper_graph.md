# Paper graph: ingestion, indexing and recovery

The component retriever needs a structured SQLite graph and a compatible FAISS index. Local Markdown, keynote caches and `reference_graph.pkl` do not provide that index by themselves. The citation graph in `reference_graph.pkl` is separate from the Paper/Core/Component graph.

## Shared configuration

Copy the project's full configuration and edit its canonical block:

```yaml
paper_graph:
  db_path: ${repo_root}/data/processed/graph.db
  index_dir: ${repo_root}/data/processed/core_component_summary_vector_store
  model_path: ${repo_root}/models/bge-m3
  ingest_on_survey: true
```

Relative graph, index and model paths resolve against the repository root. Survey, Idea, the graph server, the index builder and `doctor` use these settings. The Survey/Idea aliases in `src/config/default.yaml` retain compatibility with existing consumers. Set `QWENSCI_CONFIG` to the same configuration when launching the graph server; CLI commands also accept `--config`.

Embedding models must already exist locally in SentenceTransformer format. Building and querying use `local_files_only=True`. Changing the model requires a new index, including when its output dimension remains unchanged.

## Import existing material and complete the queue

Run from the repository root with the project's Python environment:

```bash
python -m src.cli paper-graph ingest --config /path/to/config.yaml --cache-dir database
python -m src.cli paper-graph queue --config /path/to/config.yaml --output /tmp/paper-graph-queue.json
```

The importer reads `constructed_nodes/*.json`, trusted local `paper_keynotes` diskcache records and parsed Markdown under `parsed_papers/<paper_id>/...` or the legacy MD5 directories. It does not download papers or call an LLM. A malformed record is reported separately; complete records from the same import can still be saved.

Each complete import creates Paper, Core and Component nodes, `has_contribution` edges and `has_component` edges in one transaction. A canonical paper identifier and an explicit entity `id` determine stable node IDs. Without an explicit entity ID, the name determines its ID; supply IDs if an entity may be renamed. Summary edits keep IDs stable. Repeated imports and reordered entities are idempotent. Repeated section extractions merge their supporting quotes.

Papers missing a title, recognized discipline, source text, structured contributions or verifiable evidence enter `extraction_queue`. Complete supported substructures can be saved on first import. An incomplete update preserves previously verified structure when the source set is unchanged; a changed source requires fresh extraction. Complete extractions replace the paper's prior structure, including removed components. Use the explicit delete command to remove an entire paper.

The queue exports each record as `pending[*].input` with local sources and reasons. Execute supplementary extraction against the existing full text:

```bash
python -m src.cli paper-graph extract --config /path/to/config.yaml --dry-run
python -m src.cli paper-graph extract --config /path/to/config.yaml --limit 2
python -m src.cli paper-graph extract --config /path/to/config.yaml --workers 10 --retry-failed --build-index
python -m src.cli paper-graph queue --config /path/to/config.yaml
python -m src.cli paper-graph extract --config /path/to/config.yaml --build-index \
  --query "a concrete mechanism or method to retrieve"
```

`extract` explicitly calls the configured Survey LLM and spends tokens. It reuses `extract_paper_info_batch()` with baseline/dataset extraction disabled and preserves every declared component and parent link for validation. It reads each paper's complete retained text, extracts contributions/components/discipline, saves the model result, verifies evidence and relationships, then calls the existing importer. It neither downloads full text nor substitutes abstracts or reading notes for a missing source. `--dry-run` reads sources and reports planned work without initializing a model, writing checkpoints or building an index.

`--workers` sets the maximum number of papers processed concurrently (default 10; use 1 for sequential execution). The rolling scheduler starts the next runnable paper as soon as a slot is free, without waiting for the rest of a batch. Each paper owns its extraction/retry/repair state; the model client is initialized once and shared, while SQLite writes and imports are serialized. `--limit` caps the total runnable papers, independently of workers; skipped failed papers do not consume this limit. Results retain queue order even when requests finish out of order, and the top-level JSON reports `workers`. Changing only workers preserves existing extraction fingerprints and checkpoints.

On interruption the executor stops scheduling new papers and waits for active extraction calls to finish and save their output, then stops before further repair requests or graph import once the interruption is observed. An import already in progress finishes atomically. The queue lock remains held until workers exit, preventing a replacement process from claiming their papers prematurely. Unscheduled papers remain pending, and saved outputs resume on the next run. `--build-index` starts only after all scheduled workers finish. API request/token limits still determine actual throughput; reduce `--workers` if the provider throttles concurrent work.

Every declared Core and Component must have valid evidence and a recognized discipline; a valid quote cannot conceal a fabricated extra quote on the same entity. Incorrect source identities, checksums, pages, supplied paths and unknown component parents fail the paper before graph mutation. Sections and offsets must pass exact verification after any locator correction described below. One failed paper does not stop later papers. The complete prompt must fit `survey.APIInfo.llm_max_context_length` minus `--max-output-tokens` (default 16000). An oversized input records `input_budget_exceeded` and makes no model request; it is never silently truncated. Configure an adequate supported context window before retrying such a paper.

Processing state lives in the same database's additive `extraction_attempts` table. Each attempt retains its paper/input fingerprint, status, stage, timestamps, extracted output, concrete error and import result. Stages are `source_validation`, `extraction`, `extraction_json_repair`, `evidence_verification`, `evidence_repair`, `component_repair`, `ingestion` and `complete`. `queue` includes the latest attempt as `pending[*].execution`; resolved papers disappear from the pending list, while their attempt history remains in SQLite. Queue checkpoints do not change the graph revision or invalidate an otherwise current index.

Rerun the same command to continue after interruption. A saved extraction from an interrupted or failed ingestion is verified again and reused. Failed papers are skipped on ordinary runs. With `--retry-failed`, saved evidence failures and missing-component failures resume their targeted repair. Outputs that now pass validation after a locator fix resume import directly. A saved failed main JSON response resumes field repair, preserving decoded fields; a received or validated response saved before interruption is replayed locally before making another request. Historical main failures without a saved response, and structural failures outside the supported repairs, require fresh extraction. Changed queued input, actual source content, model configuration or extraction options produce a fresh fingerprint. A stale source checksum still requires reimporting the updated source. Use repeated `--paper-id` arguments to select pending papers; `--limit` counts runnable papers, excluding previously failed records that are skipped.

New and resumed outputs first receive deterministic locator correction. An unchanged quote must match exactly once in one eligible retained source, respecting any declared source ID, checksum and path. The executor derives the actual Markdown heading (or a verified page-specific source) and character offsets, then passes the replacement through the existing exact verifier. A plain-text subheading can therefore resolve to its actual enclosing Markdown heading without another model request. Ambiguous matches, noncontiguous or absent quotes, conflicting source identities/checksums/paths and unretained page numbers are not automatically corrected. Claims, relationships, source files and unrelated evidence remain unchanged; the complete paper is validated again before import.

A per-paper cache uses `(source_id, source_sha256, quote)` as its key and starts from already verified evidence. Multiple entities sharing the same unique quote reuse its verified location. The cache belongs to one source snapshot; a later run rebuilds it from the saved output and current sources. Model repair responses can also receive the same narrowly scoped locator correction before acceptance. This does not reuse a model's replacement claim or selected passage across unrelated entities.

Verification, automatic location and repair-context selection share the character-based section resolver in `source_locations.py`. Repeated headings retain distinct ranges. A quote or explicit offsets select the occurrence containing the entire passage; the first identically named heading is never assumed to be the correct section. Multiple occurrences of the same quote within eligible ranges require explicit valid offsets. Matching source windows are prioritized over unrelated sections with the same heading, and every excerpt remains an exact slice with valid start/end bounds. Parent-section evidence can include nested subsections, but a quote cannot cross the selected section's ending boundary.

After deterministic correction, each remaining failed entity gets at most `--max-evidence-repairs` repair requests (default 2) per invocation. `--max-retry` controls the main extractor's request retries. Set `--max-evidence-repairs 0` to disable evidence model repairs while retaining deterministic locator correction; component repair has its own limit below. Repair limits and locator correction do not change the extraction fingerprint, so existing saved outputs remain usable. Keep the same extraction options and model configuration when resuming an earlier attempt. Dry runs report `repair_evidence` for reusable failures, including the exact failing targets and reasons, without correcting output, writing audit records or calling a model.

After evidence repair, each verified Core with no declared components gets at most `--max-component-repairs` requests (default 2 per Core per invocation; 0 disables this step). This repair only appends concrete, source-supported components under the selected Core. Its request contains the protected Core, source identities, bounded original excerpts and previous errors. New components require nonempty names/summaries and independently verified evidence; unknown targets, edits to existing fields, duplicate identities and invalid sources are rejected. Valid additions are checkpointed atomically with their audit outcome. Missing or unsupported components remain pending with specific reasons while independent verified contributions and components can be imported. Existing components with failed evidence keep their own repair targets rather than being replaced by newly invented components. Dry runs identify supported work as `repair_components`.

The queue's main extractor parses the outer JSON object strictly; malformed outer JSON is never replaced by a nested metadata object. Within the existing `--max-retry` attempt limit, schema failures receive the exact validation error and a list of fields to repair. Complete decoded fields are protected and merged in code. For truncated JSON, only complete top-level values preceding the malformed field are retained; missing/truncated fields are requested from the original paper. The full source is retained in repair prompts, while the previous response excerpt is bounded and explicitly labeled when partial. If source plus repair instructions cannot fit the context budget, the request fails explicitly without calling the model. Main JSON repairs cannot alter protected contributions, components or evidence. Dry runs identify saved JSON work as `repair_main_json`.

The additive `extraction_requests` table retains main extraction/JSON repair and component repair requests, raw responses (including invalid JSON), outcomes and resumable JSON state. A response is saved before validation; successful component additions and their output checkpoint commit together. These audit writes preserve the graph revision. Per-paper results include `component_repairs`, and remaining structural errors include `component_repair_errors`. Main and component events identify the paper, attempt and round. Historical failed responses that were never recorded cannot be reconstructed by this change.

The repair model receives only the failed entity's protected claims, failing evidence targets, specific errors, source identities and bounded, unmodified original excerpts. The excerpts include literal matching fragments on both sides of interruptions and the claimed section when it fits. Similarity selects context only; it never verifies evidence. A repair can replace a failed evidence slot with one or more independently verified records. The executor rejects unknown targets, changes to non-evidence fields, empty replacements and fabricated quotes/locations. Other verified evidence and every entity/relationship remain in the saved extraction. A model can explicitly leave unsupported claims unresolved.

For each failed quote, code enumerates retained-source matches in `location_candidates`, using exact matches first and restricted formatting matches only when no exact location exists. Each candidate has a stable ID bound to its target, source identity/checksum/path and character range, plus the original quote, actual Markdown heading, offsets and surrounding context. Source identity/checksum/path/page constraints still apply. Repeated quotes and headings remain separate choices, including headings with PDF bullet characters. For a target with candidates, the model returns only `target_id` and nonempty `candidate_ids`; code restores those candidates' original evidence and runs full verification again. Unknown IDs, another target's IDs, duplicate IDs, rewritten candidate fields and stale-source locations are rejected. Candidates and raw selections are retained in the existing repair audit. All candidate context contributes to the complete prompt budget; an oversized prompt fails explicitly before a model call. Targets without a matching candidate retain the contiguous-fragment repair path, and unsupported or undecidable targets stay unresolved.

For a sentence interrupted by a figure or caption, retain separate `evidence_records`, one per continuous fragment. Each record gets its own exact source ID, SHA256, section/page and character offsets; no synthetic joined sentence is treated as a verbatim quote. Both legacy `evidence` and `quote`/`source_quote` evidence remain available when repaired records are added.

Evidence first uses literal matching. If that fails, a restricted whitespace matcher allows ordinary spaces, tabs, nonbreaking spaces (U+00A0/U+202F), figure/thin spaces and a single line wrap to correspond. It never changes words, numbers, case, punctuation or HTML, skips a caption, or collapses a blank paragraph boundary. A normalized match must resolve uniquely within the eligible sources and section. The stored quote is then copied from the original source slice with its real offsets and unchanged source checksum; graph/index/runtime provenance checks still compare that stored slice exactly. Wrong source identities, checksums and page claims remain rejected. Automatic locator recovery uses the same matcher when correcting a section. Repeated headings are checked against the occurrence containing the actual offsets, including during index and runtime validation.

Import eligibility is evaluated per entity. Every declared evidence slot of an imported Core or Component must verify, its required fields must be complete, and a Component must have an eligible parent Core. A failed entity does not discard unrelated eligible entities. A verified Core with no eligible components can be retained, but has no component vector until a component is repaired and does not count toward indexed discipline coverage. Missing title, full text or recognized discipline still prevents new grounded nodes from being imported.

Papers with imported grounded nodes and remaining work receive `status=partial` in both queue and execution history. Extraction summaries report `partial` separately from `succeeded` and `failed`; `ok=false` and exit status 1 continue to indicate unfinished work. The pending export includes both `pending` and `partial` entries. Partial imports, their precise reasons and execution checkpoints commit in one transaction. Re-running `extract` resumes their saved output without a fresh main extraction; `--retry-failed` is still needed for an ordinary failed attempt. The queue retains its original input so a partial import does not change the resume fingerprint. Partial updates merge previously verified nodes only when the source identities/checksums are unchanged; complete authoritative extractions can replace the graph normally.

The full extraction remains in `extraction_attempts.output_json`. Import payloads retain a `candidate_verification` report containing original candidate content, evidence issues and `verification_status` (`verified`, `unverified`, or `blocked`). Results expose unresolved entities under `candidates`; a component with verified text but an unverified parent is `blocked`. Unverified and blocked candidates stay outside graph nodes, FTS and the component vector index. MCTS evidence operations therefore receive only grounded graph entities. Graph provenance also rejects any explicitly unverified candidate inserted into the graph by another writer.

Every targeted request and raw response (including malformed JSON) is retained in the additive `extraction_evidence_repairs` table, linked to its extraction attempt. Deterministic corrections use `round=0` and `method=deterministic_locator`, preserving the original failed evidence, proposed replacement and outcome; model requests use rounds starting at 1. Each repair outcome records applied targets, errors and remaining issues. Applied patches and the extraction checkpoint commit together before the next entity request. An interruption therefore resumes from the latest saved partial output. The original failed attempt remains in history; the new attempt contains the repaired output. `pending[*].execution.error.evidence_issues` identifies remaining fields, quotes and precise failure reasons; `repair_errors` records the last model/patch errors for each entity.

Per-paper results report model repair requests as `evidence_repairs`, separately from `evidence_locator_corrections` and `evidence_locator_cache_hits`. The executor emits one-line JSON events to stderr with paper/attempt IDs; model repair start and finish events include the entity, round, repair ID, cumulative request count and outcome. Batch completion logs identify their paper/stage. Progress bars automatically disable on non-TTY streams, so redirected logs contain ordinary log lines and JSON events rather than repeated cursor redraws. Existing running processes use the code already loaded in memory; these changes apply when starting a subsequent executor.

```bash
python -m src.cli paper-graph extract --config /path/to/config.yaml \
  --paper-id W4412488967 --paper-id W7214989968 --retry-failed
```

Only one queue executor can run for a given database. A concurrent ordinary reimport remains permitted: the executor checks the current queue payload inside the import transaction and rejects stale output if that payload changed. Graph writes, queue resolution and the successful attempt checkpoint commit together, so a process exit immediately after import cannot leave a committed paper marked as running.

`extract --build-index` first checks for active component summaries. With none, it reports `no_indexable_components` without initializing an encoder or publishing an index. Otherwise it builds the full active graph, checks provenance/index consistency and discipline coverage, and runs the production vector query path. Extraction limits never restrict index membership. Repeated `--query` arguments return actual scores, Core/paper/domain identities, matched components and evidence. Without `--query`, one component summary is used as a clearly labeled `component_summary_smoke` query: this checks the retrieval path, not scientific transfer quality. Build/query failures are reported alongside the retained per-paper extraction outcomes.

Alternatively, fill the missing structured fields using the exported sources, then reimport the queue file or a separate list of completed paper objects:

```bash
python -m src.cli paper-graph ingest --config /path/to/config.yaml --input /tmp/paper-graph-queue.json
python -m src.cli paper-graph queue --config /path/to/config.yaml
```

A resolved record remains in queue history with status `resolved` and disappears from the pending export. `ingest`, `queue`, `build`, ordinary `check` and `doctor` do not call the LLM. Survey's structured extractor requests the shared discipline IDs, contiguous source quotes, section headings, structure, assumptions and boundary conditions. Ordinary keynote strings remain queued until extraction supplies the required structure.

The following object illustrates the input contract. Replace the path and passages with actual source material:

```json
{
  "paper_id": "https://openalex.org/W123",
  "metadata": {"title": "Example paper", "domain": "physics_astronomy"},
  "source_documents": [{"source_id": "paper-text", "path": "/absolute/path/paper.md"}],
  "ideation_resource": {
    "core_contributions": [{
      "id": "main-relation",
      "name": "Conservation relation",
      "summary": "A conserved quantity under the stated conditions.",
      "structure": "A conserves B.",
      "assumptions": ["Stationary noise"],
      "boundary_conditions": ["Equilibrium"],
      "evidence_records": [
        {"quote": "A conserves B under constant input.", "source_id": "paper-text", "source_section": "Method"},
        {"quote": "This relation assumes stationary noise.", "source_id": "paper-text", "source_section": "Method"},
        {"quote": "It holds only at equilibrium.", "source_id": "paper-text", "source_section": "Method"}
      ],
      "components": [{
        "id": "measurement",
        "name": "Measurement",
        "summary": "Measures the conserved quantity.",
        "quote": "A component measures the conserved quantity.",
        "source_section": "Results"
      }]
    }]
  }
}
```

The existing Survey shape with root-level `components[*].related_to_core` is also accepted. That link must match a declared Core name or explicit ID. Unknown links remain pending. `metadata.domain` uses the allowlist in `src/pipeline/discipline_taxonomy.py`; `Others`, `Hybrid` and unrecognized labels never establish cross-domain eligibility.

Every indexed component and its parent contribution require an exact quote. The importer stores the source SHA256, evidence ID, path and character offsets, plus section or page. Legacy `quote`/`source_quote` fields are accepted; a missing section can be recovered only from a unique literal quote match under an actual Markdown heading. Page numbers require page-specific source text. A quoted page number beside an unpaginated Markdown file does not verify the page. Added ellipses, paraphrases, wrong sections, missing files and mismatched checksums do not pass validation.

For path-backed sources, the file is authoritative. Inline text cannot replace a missing file while claiming that file as provenance. Inline full text can also be explicitly supplied in `source_documents[*].text`; it is retained in the graph for verification. Verified abstracts from discovery metadata are excluded from automatic full-text ingestion. A verified quote establishes a source location; whether it supports a claim still requires semantic review.

## Build and publish the component index

```bash
python -m src.cli paper-graph build --config /path/to/config.yaml
python -m src.cli paper-graph check --config /path/to/config.yaml
python -m src.cli doctor --config /path/to/config.yaml
```

`ingest` and `delete` also accept `--build-index`. The old builder entrypoint delegates to the same implementation:

```bash
python graph/index_core_component_summaries.py \
  --db-path /absolute/path/graph.db \
  --store-path /absolute/path/core_component_summary_vector_store \
  --model-path /absolute/path/local-model
```

The builder validates node relationships and original source files, snapshots the current graph, reuses unchanged component embeddings, embeds changed/new components and removes deleted components. It validates embeddings and refuses a partial `--limit` publication. If the graph changes during the build, it asks for a retry. An initially empty component corpus cannot produce a usable index. Deleting the last component can publish an empty generation with the existing model dimension; health then reports the corpus as unready.

Each build produces an immutable generation:

```text
index_dir/
  CURRENT.json
  generations/<generation>/
    faiss.index
    meta.json
    manifest.json
    build_stats.json
```

The manifest records graph schema/revision/fingerprint, model file hashes, model revision, dimension, metric, normalization, component count and artifact checksums. Readers resolve `CURRENT.json` once and read all files from that generation. Publication switches the pointer atomically after writing the new generation. Failed publication leaves the preceding pointer intact. Older generations are retained.

Legacy indexes without a manifest require `build --rebuild`. An incompatible legacy SQL schema requires a new database path and reimport. The read-only retriever and `doctor` never create a missing graph database. Existing summary-only nodes without source evidence cannot become grounded results by rebuilding their vectors.

`paper-graph check` returns exit status 0 for readiness, 1 for failed checks and 2 for command errors. It checks schema, Core/component counts, relationships, provenance against original files, discipline coverage, component membership, FAISS IDs/counts/checksums, vector normalization and model/graph compatibility. Ordinary `check` does not initialize an embedding model; add `--query "..."` to also initialize the configured local encoder and verify an actual query against the current index. `extract` uses the same exit statuses for successful work, per-paper/validation failures and command errors. Both commands keep JSON results on stdout and model/embedding logs on stderr. Discipline coverage is reported separately: a healthy single-domain corpus supports component retrieval but cannot guarantee cross-domain results for any given target.

Survey ingestion writes graph data and pending work. Run the explicit build stage after importing complete extractions and before starting Idea retrieval. Automatic ingestion does not rebuild the full index after each paper.

## Cross-domain retrieval and semantic applicability

MCTS increases the Core candidate window within `idea.mcts.retrieval_candidate_budget` and `retrieval_call_budget`. The provider also widens its component-vector window so a Core with many highly ranked components cannot conceal the remainder of the corpus. The search stops when enough eligible Cores are found, the corpus is exhausted or a budget is reached.

Diagnostics separately report `raw_hits`, `low_score`, `same_domain`, `missing_domain`, `unrecognized_domain`, `eligible`, inspected `windows` and `stop_reason`. Counts describe the last inspected window; they do not double-count repeated candidates across windows. An unresolved target discipline cannot establish cross-domain eligibility. A candidate limit or call limit produces `budget_exhausted` when no eligible result was obtained, rather than claiming the corpus had no candidate. Partial eligible results retain their truncation diagnostics.

Eligible cross-domain results then receive a semantic transfer review. The review supplies a structure mapping, source assumptions, source boundaries, exact supporting evidence IDs and quotes, target-condition checks and concrete validation obligations. A malformed review, forged quote, unknown condition or violated condition cannot qualify. `compatible` candidates remain proposed transfers requiring validation. Exact-quote checks validate citation identity and location; the semantic judgment still depends on the review model.

The existing statuses remain `success`, `no_hits`, `unavailable`, `error` and `budget_exhausted`. Required evidence operators skip child creation when their preconditions fail. Exploratory mechanism proposals retain the explicit absence of grounding.

## Recover an existing agent

After completing ingestion and rebuilding, the host that owns an existing agent can invoke:

```python
agent.reload_paper_graph(warm_model=False)  # LigAgent: all shared MCTS routes
# or, for a standalone engine:
engine.reload_paper_graph(warm_model=False)
```

Reload validates the replacement before swapping it into the shared provider. Failure preserves the preceding provider state and unavailable status. Success clears the provider's disabled error, each consumer's unavailable capability, cached novelty model/axes, graph-derived evidence catalog entries and evaluation cache. `warm_model=True` additionally initializes the local encoder. Querying after graph/source files change refuses stale results and requires reimport/build/reload as appropriate. This is a Python API for the owning process; an external CLI cannot mutate another running process's in-memory agent.

## Validation of the current local assets

On 2026-10-20 a temporary import of the local cache read 69 paper records and their Markdown without import errors. It produced zero Core nodes and zero Component nodes: all 69 records lacked structured contributions and a recognized discipline, so all 69 entered the supplementary extraction queue. Completing extraction is necessary before the current cache can support a production component index. Cross-domain coverage must then be measured from the completed corpus.

The queue executor's read-only `extract --dry-run` also planned all 69 pending papers successfully against their existing full text, with no source errors. This run made no LLM calls, wrote no extraction checkpoints and published no index. Offline executor tests use the real extractor/retry code, SQLite transactions and FAISS retrieval with fake model transport and deterministic embeddings; they cover rejected evidence, interrupted execution, concurrent reimport, atomic completion and truthful discipline coverage.

An independent offline smoke test used the installed `models/all-MiniLM-L6-v2` on two explicitly synthetic fixture papers, producing two 384-dimensional vectors, two retrieved Cores, verified source locations and a passing health check. It validates real encoding/index/query plumbing; it does not establish scientific transfer quality. Both validations used temporary databases and indexes and left the production graph and running research processes untouched.
