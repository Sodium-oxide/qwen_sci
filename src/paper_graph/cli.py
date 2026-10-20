"""Import, explicitly extract, index and verify grounded paper contributions."""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from src.paper_graph.settings import PaperGraphSettings, repo_path


def settings_for(args: argparse.Namespace, *, config: Any = None) -> PaperGraphSettings:
    from src.config import load_config
    settings = PaperGraphSettings.from_config(config if config is not None else load_config(getattr(args, "config", None)))
    return PaperGraphSettings(
        repo_path(getattr(args, "db_path", None) or settings.db_path),
        repo_path(getattr(args, "store_path", None) or settings.index_dir),
        repo_path(getattr(args, "model_path", None) or settings.model_path),
        settings.ingest_on_survey,
    )


def add_build_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--store-path", default=None)
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--fetch-size", type=int, default=16)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--no-progress", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--limit", type=int, default=None, help=argparse.SUPPRESS)


def build_command(args: argparse.Namespace) -> int:
    with redirect_stdout(sys.stderr):
        from src.paper_graph.indexing import GraphCoreComponentIndexer
        settings = settings_for(args)
        result = GraphCoreComponentIndexer(settings.db_path, settings.index_dir, settings.model_path,
                                          fetch_size=args.fetch_size).build(args.batch_size, args.limit, args.rebuild)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def configure_parser(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="paper_graph_command", required=True)
    build = commands.add_parser("build", help="Reconcile active components and atomically publish an index")
    add_build_options(build)
    build.set_defaults(func=run_command, graph_action="build")
    ingest = commands.add_parser("ingest", help="Import structured JSON and/or existing Survey caches")
    ingest.add_argument("--config", default=None)
    ingest.add_argument("--cache-dir", type=Path)
    ingest.add_argument("--input", type=Path, action="append", default=[])
    ingest.add_argument("--build-index", action="store_true")
    ingest.set_defaults(func=run_command, graph_action="ingest")
    queue = commands.add_parser("queue", help="Export incomplete papers for supplementary extraction")
    queue.add_argument("--config", default=None)
    queue.add_argument("--output", type=Path)
    queue.set_defaults(func=run_command, graph_action="queue")
    extract = commands.add_parser("extract", help="Execute queued full-text extractions with evidence checks and checkpoints")
    extract.add_argument("--config", default=None)
    extract.add_argument("--paper-id", action="append", default=[], help="Select a pending paper; repeat for multiple papers")
    extract.add_argument("--limit", type=int, default=None, help="Maximum runnable papers in this invocation")
    extract.add_argument("--dry-run", action="store_true", help="Inspect work without model calls or checkpoint writes")
    extract.add_argument("--retry-failed", action="store_true", help="Retry failed extractions or evidence checks")
    extract.add_argument("--temperature", type=float, default=0.05)
    extract.add_argument("--max-retry", type=int, default=3)
    extract.add_argument("--max-output-tokens", type=int, default=16000)
    extract.add_argument("--build-index", action="store_true", help="Build the complete active index and verify retrieval afterwards")
    extract.add_argument("--query", action="append", default=None, help="Verify retrieval with this query; requires --build-index")
    extract.add_argument("--top-k", type=int, default=5)
    extract.add_argument("--batch-size", type=int, default=8, help="Embedding batch size when building the index")
    extract.add_argument("--fetch-size", type=int, default=16)
    extract.add_argument("--rebuild", action="store_true")
    extract.set_defaults(func=run_command, graph_action="extract")
    delete = commands.add_parser("delete", help="Remove a paper and its contributions; rebuild to publish")
    delete.add_argument("--config", default=None)
    delete.add_argument("--paper-id", required=True)
    delete.add_argument("--build-index", action="store_true")
    delete.set_defaults(func=run_command, graph_action="delete")
    check = commands.add_parser("check", help="Check readiness; only --query initializes embeddings")
    check.add_argument("--config", default=None)
    check.add_argument("--query", action="append", default=None, help="Also run a real vector query; repeat for multiple queries")
    check.add_argument("--top-k", type=int, default=5)
    check.set_defaults(func=run_command, graph_action="check")


def run_command(args: argparse.Namespace) -> int:
    try:
        if args.graph_action == "build":
            return build_command(args)
        from src.config import load_config
        config = load_config(getattr(args, "config", None))
        settings = settings_for(args, config=config)
        from src.paper_graph.repository import PaperGraphRepository
        from src.paper_graph.ingest import import_survey_cache, ingest_paper
        result: Any
        exit_code = 0
        if args.graph_action == "check":
            from src.paper_graph.health import check_paper_graph
            result = check_paper_graph(settings)
            if args.query:
                with redirect_stdout(sys.stderr):
                    from src.paper_graph.validation import check_retrieval
                    result["retrieval"] = (check_retrieval(settings, args.query, top_k=args.top_k) if result["ok"] else
                        {"ok": False, "status": "skipped", "reason": "graph_or_index_not_ready"})
                result["ok"] = result["ok"] and result["retrieval"]["ok"]
            exit_code = 0 if result["ok"] else 1
        elif args.graph_action == "extract":
            if args.query and not args.build_index:
                raise ValueError("extract --query requires --build-index; use check --query for an existing index")
            if args.top_k < 1 or args.batch_size < 1 or args.fetch_size < 1:
                raise ValueError("top-k, batch-size and fetch-size must be positive")
            # Model/provider logs and embedding progress belong on stderr so
            # stdout remains a single machine-readable JSON result.
            with redirect_stdout(sys.stderr):
                from src.paper_graph.extraction import PaperGraphExtractionExecutor
                result = PaperGraphExtractionExecutor(settings.db_path, config=config).run(
                    paper_ids=args.paper_id, limit=args.limit, retry_failed=args.retry_failed, dry_run=args.dry_run,
                    temperature=args.temperature, max_retry=args.max_retry, max_output_tokens=args.max_output_tokens)
            if args.build_index:
                if args.dry_run:
                    result["validation"] = {"status": "planned", "build": "full_active_snapshot", "queries": args.query}
                else:
                    with redirect_stdout(sys.stderr):
                        from src.paper_graph.validation import build_and_check
                        result["validation"] = build_and_check(settings, queries=args.query, top_k=args.top_k,
                            batch_size=args.batch_size, fetch_size=args.fetch_size, rebuild=args.rebuild)
                    result["ok"] = result["ok"] and result["validation"]["ok"]
            exit_code = 0 if result["ok"] else 1
        elif args.graph_action == "queue":
            result = {"pending": PaperGraphRepository(settings.db_path).pending(),
                      "instructions": "Run paper-graph extract --dry-run to inspect queued full text, then paper-graph extract "
                                      "to extract and verify contributions, components and disciplines. Use --retry-failed for "
                                      "failed papers. Execution checkpoints and concrete errors are in pending[*].execution. "
                                      "Alternatively supply structured fields and reimport using paper-graph ingest --input."}
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        elif args.graph_action == "delete":
            PaperGraphRepository(settings.db_path).delete_paper(args.paper_id)
            result = {"deleted": args.paper_id}
        else:
            if not args.cache_dir and not args.input:
                raise ValueError("ingest requires --cache-dir and/or --input")
            result = {"cache": import_survey_cache(settings.db_path, args.cache_dir) if args.cache_dir else None,
                      "imports": []}
            for path in args.input:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and "pending" in payload:
                    payload = [entry.get("input") for entry in payload["pending"]]
                for paper in payload if isinstance(payload, list) else [payload]:
                    if not isinstance(paper, dict):
                        raise ValueError(f"Expected a paper object in {path}")
                    result["imports"].append(ingest_paper(settings.db_path, paper))
            if result["cache"] and result["cache"]["errors"]:
                exit_code = 2
        if getattr(args, "build_index", False) and args.graph_action != "extract":
            with redirect_stdout(sys.stderr):
                from src.paper_graph.indexing import GraphCoreComponentIndexer
                result["index"] = GraphCoreComponentIndexer(settings.db_path, settings.index_dir, settings.model_path).build()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False))
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage grounded paper contributions and component indexes")
    configure_parser(parser)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
