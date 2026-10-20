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
python -m src.cli paper-graph queue --config /path/to/config.yaml
python -m src.cli paper-graph extract --config /path/to/config.yaml --build-index \
  --query "a concrete mechanism or method to retrieve"
```

`extract` explicitly calls the configured Survey LLM and spends tokens. It reuses `extract_paper_info_batch()` with baseline/dataset extraction disabled and preserves every declared component and parent link for validation. It reads each paper's complete retained text, extracts contributions/components/discipline, saves the model result, verifies evidence and relationships, then calls the existing importer. It neither downloads full text nor substitutes abstracts or reading notes for a missing source. `--dry-run` reads sources and reports planned work without initializing a model, writing checkpoints or building an index.

Every declared Core and Component must have valid evidence and a recognized discipline; a valid quote cannot conceal a fabricated extra quote on the same entity. Incorrect source identities, checksums, sections, pages, supplied paths/offsets and unknown component parents fail the paper before graph mutation. One failed paper does not stop later papers. The complete prompt must fit `survey.APIInfo.llm_max_context_length` minus `--max-output-tokens` (default 16000). An oversized input records `input_budget_exceeded` and makes no model request; it is never silently truncated. Configure an adequate supported context window before retrying such a paper.

Processing state lives in the same database's additive `extraction_attempts` table. Each attempt retains its paper/input fingerprint, status, stage, timestamps, extracted output, concrete error and import result. Stages are `source_validation`, `extraction`, `evidence_verification`, `ingestion` and `complete`. `queue` includes the latest attempt as `pending[*].execution`; resolved papers disappear from the pending list, while their attempt history remains in SQLite. Queue checkpoints do not change the graph revision or invalidate an otherwise current index.

Rerun the same command to continue after interruption. A saved extraction from an interrupted or failed ingestion is verified again and reused without another LLM call. Failed extraction/evidence checks are skipped on ordinary runs; use `--retry-failed` to call the model again. Changed queued input, actual source content, model configuration or extraction options produce a fresh fingerprint. A stale source checksum still requires reimporting the updated source. Use repeated `--paper-id` arguments to select pending papers; `--limit` counts runnable papers, excluding previously failed records that are skipped.

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
