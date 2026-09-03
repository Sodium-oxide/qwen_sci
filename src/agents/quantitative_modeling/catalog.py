"""Read the approved advisory model catalogs without treating them as whitelists."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
_APPROVED_CATALOG_LOCATIONS = (
    REPO_ROOT / "five_domain_top_journal_model_catalog_en.md",
    REPO_ROOT / "five_domain_top_journal_model_catalog.md",
    REPO_ROOT / "output" / "markdown" / "five_domain_top_journal_model_catalog.md",
)
MODEL_CATALOG_SCHEMA_VERSION = "model_catalog_v1"
_DOMAIN_HEADINGS = {
    "Mathematics, Physics, and Astronomy": "MATH_PHYS_ASTRONOMY",
    "Energy, Engineering, and Systems": "ENGINEERING_ENERGY",
    "Earth, Environment, and Agricultural Ecology": "EARTH_ENVIRONMENT",
    "Materials, Chemistry, and Chemical Engineering": "MATERIALS_CHEMISTRY",
}
_TABLE_DIVIDER = re.compile(r"^\|?\s*:?-{3,}")


def _catalog_identifier(domain: str, name: str, seen: set[str]) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:72] or "model"
    base = f"{domain.casefold()}-{stem}"
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}-{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def parse_model_catalog_markdown(text: str, *, source_path: Path) -> dict[str, Any]:
    """Convert the approved Markdown catalog into a deterministic JSON index.

    The index deliberately preserves only catalog guidance.  It is not a
    solver whitelist and callers must still audit every proposed MathIR model.
    """

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    active_domain = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            active_domain = ""
            for heading, domain in _DOMAIN_HEADINGS.items():
                if heading in line:
                    active_domain = domain
                    break
            continue
        if not active_domain or not line.startswith("|") or _TABLE_DIVIDER.match(line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 4 or cells[0].casefold() == "model family":
            continue
        name, governing_form, variables, outputs = cells
        if not name or not governing_form:
            continue
        rows.append(
            {
                "catalog_model_id": _catalog_identifier(active_domain, name, seen_ids),
                "canonical_name": name,
                "domain": active_domain,
                "scientific_use_case": outputs,
                "required_variables": variables,
                "required_parameters": "Review the source model and task-specific parameterization.",
                "governing_form": governing_form,
                "supported_solver_families": [],
                "assumptions": [],
                "known_failure_modes": [],
                "source_references": [str(source_path)],
            }
        )
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "schema_version": MODEL_CATALOG_SCHEMA_VERSION,
        "source": {"path": str(source_path), "sha256": source_hash},
        "entries": rows,
        "advisory_only": True,
    }


def write_model_catalog_json(*, output_path: str | Path) -> Path:
    """Materialize the approved Markdown catalog as a JSON review artifact."""

    source = resolve_model_catalog_path()
    if source is None:
        raise FileNotFoundError("No approved model catalog Markdown file is available")
    payload = parse_model_catalog_markdown(source.read_text(encoding="utf-8"), source_path=source)
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def resolve_model_catalog_path() -> Path | None:
    """Resolve only the approved, repository-local model catalog artifacts."""

    for candidate in _APPROVED_CATALOG_LOCATIONS:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(REPO_ROOT)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def load_model_catalog_context(*, max_characters: int = 24_000) -> tuple[dict[str, Any], str]:
    """Return bounded prompt context and provenance for the approved catalog."""

    resolved = resolve_model_catalog_path()
    if resolved is None:
        return {"status": "NOT_FOUND"}, ""
    text = resolved.read_text(encoding="utf-8")
    payload = parse_model_catalog_markdown(text, source_path=resolved)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = payload["source"]["sha256"]
    context = serialized[: max(1, int(max_characters))]
    metadata = {
        "status": "AVAILABLE",
        "path": str(resolved),
        "sha256": digest,
        "truncated": str(len(context) < len(serialized)).lower(),
        "schema_version": MODEL_CATALOG_SCHEMA_VERSION,
        "entry_count": str(len(payload["entries"])),
    }
    return metadata, context


__all__ = [
    "MODEL_CATALOG_SCHEMA_VERSION",
    "load_model_catalog_context",
    "parse_model_catalog_markdown",
    "resolve_model_catalog_path",
    "write_model_catalog_json",
]
