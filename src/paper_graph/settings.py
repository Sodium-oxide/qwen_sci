"""One path contract for Survey, Idea, graph tools and diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[2]


def select(config: Any, key: str, default: Any = None) -> Any:
    if OmegaConf.is_config(config):
        return OmegaConf.select(config, key, default=default)
    value = config
    for part in key.split("."):
        if hasattr(value, "get"):
            value = value.get(part, default)
        else:
            value = getattr(value, part, default)
    return value


def repo_path(value: Any) -> Path:
    path = Path(str(value).replace("${repo_root}", str(ROOT))).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


@dataclass(frozen=True)
class PaperGraphSettings:
    db_path: Path
    index_dir: Path
    model_path: Path
    ingest_on_survey: bool = True

    @classmethod
    def from_config(cls, config: Any = None) -> "PaperGraphSettings":
        if config is None:
            from src.config import get_config
            config = get_config()
        # Survey/Idea may receive only their section. The canonical block is
        # copied into both sections by the unified config/adapters.
        return cls(
            repo_path(select(config, "paper_graph.db_path", "data/processed/graph.db")),
            repo_path(select(config, "paper_graph.index_dir", "data/processed/core_component_summary_vector_store")),
            repo_path(select(config, "paper_graph.model_path", "models/bge-m3")),
            bool(select(config, "paper_graph.ingest_on_survey", True)),
        )
