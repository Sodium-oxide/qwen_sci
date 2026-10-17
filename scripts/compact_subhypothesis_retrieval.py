"""Migrate retrieval JSON to verified reference storage, retaining indentation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.subhypothesis_retrieval_storage import (
    expand_subhypothesis_retrieval,
    serialize_subhypothesis_retrieval,
)


def compact_file(path: Path) -> dict:
    """Replace only after the written JSON reconstructs all original data."""

    path = path.resolve(strict=True)
    original_stat = path.stat()
    with path.open(encoding="utf-8") as handle:
        original = json.load(handle)
    stored = serialize_subhypothesis_retrieval(original)
    if stored == original:
        return {"file": str(path), "before_bytes": original_stat.st_size,
                "after_bytes": original_stat.st_size, "changed": False}
    expected = expand_subhypothesis_retrieval(original)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(stored, handle, ensure_ascii=False, indent=2)
        with temporary.open(encoding="utf-8") as handle:
            restored = expand_subhypothesis_retrieval(json.load(handle))
        if restored != expected:
            raise ValueError(f"Retrieval migration did not preserve all original data: {path}")
        os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
        after_bytes = temporary.stat().st_size
        # Avoid replacing an artifact that a running collector updated meanwhile.
        current_stat = path.stat()
        if (current_stat.st_mtime_ns, current_stat.st_size) != (
            original_stat.st_mtime_ns, original_stat.st_size,
        ):
            raise ValueError(f"Retrieval artifact changed during migration: {path}")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"file": str(path), "before_bytes": original_stat.st_size,
            "after_bytes": after_bytes, "changed": True, "roundtrip_verified": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Existing subhypothesis_retrieval.json files")
    args = parser.parse_args()
    for path in args.paths:
        print(json.dumps(compact_file(path), ensure_ascii=False))


if __name__ == "__main__":
    main()
