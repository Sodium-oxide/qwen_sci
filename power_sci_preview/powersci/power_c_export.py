"""Export the C-to-B integration bundle and create a zip archive."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from . import (
    apply_lens,
    create_default_registry,
    generate_truth,
    high_quality_lens,
    noisy_low_rate_lens,
    pmu_lens,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def export_bundle(output_root: str | Path, archive_path: str | Path | None = None) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    registry = create_default_registry()
    lens_specs = [high_quality_lens(), pmu_lens(), noisy_low_rate_lens()]
    index = {"bundle_version": "c_to_b_v1", "schema_versions": ["case_manifest_v2", "lens_spec_v2"], "cases": []}
    for case in registry.list():
        case_dir = root / "cases" / case.case_id / case.version
        truth = generate_truth(case)
        _write_json(case_dir / "case_manifest.json", case.to_dict())
        _write_json(case_dir / "truth_data.json", truth.to_dict())
        _write_json(case_dir / "metadata.json", {"case_id": case.case_id, "version": case.version,
                                                   "variables": truth.variable_metadata,
                                                   "truth_hash": truth.content_hash})
        case_entry = {"case_id": case.case_id, "version": case.version,
                      "case_manifest": str((case_dir / "case_manifest.json").relative_to(root)),
                      "truth_data": str((case_dir / "truth_data.json").relative_to(root)),
                      "case_hash": case.content_hash, "truth_hash": truth.content_hash, "lenses": []}
        for spec in lens_specs:
            result = apply_lens(truth, case, spec)
            lens_dir = root / "lenses" / spec.lens_id
            _write_json(lens_dir / "lens_spec.json", spec.to_dict())
            data_path = lens_dir / f"{case.case_id}.json"
            _write_json(data_path, result.to_dict())
            case_entry["lenses"].append({"lens_id": spec.lens_id, "lens_spec": str((lens_dir / "lens_spec.json").relative_to(root)),
                                         "dataset": str(data_path.relative_to(root)), "dataset_hash": result.content_hash})
        index["cases"].append(case_entry)
    _write_json(root / "manifest_index.json", index)
    (root / "README_B_INTERFACE.md").write_text(
        "# Project C to B integration bundle\n\n"
        "This bundle contains versioned B0/B1/B2 CaseManifestV2 files, deterministic truth data, "
        "and LensSpecV2 datasets. Units, coordinates, reference_mode, sampling rate, noise and seed "
        "are retained in every dataset. Truth equations are not included in the hidden evaluator API.\n\n"
        "Load a manifest with `CaseManifest.from_dict(json.load(...))`; load a lens with "
        "`LensSpec.from_dict(json.load(...))`. The `manifest_index.json` file lists SHA-256 hashes.\n",
        encoding="utf-8")
    if archive_path is None:
        archive_path = root.with_suffix(".zip")
    archive = Path(archive_path)
    if archive.suffix.lower() == ".zip":
        base = archive.with_suffix("")
        shutil.make_archive(str(base), "zip", root_dir=root.parent, base_dir=root.name)
        return archive
    return Path(shutil.make_archive(str(archive), "zip", root_dir=root.parent, base_dir=root.name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="part_c_for_b_bundle")
    parser.add_argument("--archive", default=None)
    args = parser.parse_args()
    archive = export_bundle(args.output, args.archive)
    print(f"bundle: {Path(args.output).resolve()}")
    print(f"archive: {archive.resolve()}")


if __name__ == "__main__":
    main()
