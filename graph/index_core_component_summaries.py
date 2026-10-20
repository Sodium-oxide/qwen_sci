"""Compatibility entrypoint for the shared versioned component index builder."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.paper_graph.cli import add_build_options, run_command
from src.paper_graph.indexing import GraphCoreComponentIndexer, build_component_summary_vector_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a versioned index from all active Core component summaries")
    add_build_options(parser)
    args = parser.parse_args(argv)
    args.graph_action = "build"
    return run_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
