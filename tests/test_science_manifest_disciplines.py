from pathlib import Path

import pytest

from src.pipeline import science_manifests as manifests


def test_manifest_writer_canonicalizes_discipline_labels(monkeypatch):
    monkeypatch.setattr(manifests, "_build_manifest", lambda **fields: fields)
    monkeypatch.setattr(manifests, "_write_manifest", lambda path, payload: payload)
    result = manifests.write_experiment_design_manifest(
        attempt_dir="attempt", topic="topic", idea_manifest_path="idea_manifest.json",
        idea_result_path="idea_result.json", identity={}, design_id="design",
        selected_direction_id="direction", discipline_ids=["Physics and Astronomy", "31"],
        artifact_paths={"experiment_design_json": "design.json", "author_json": "author.json",
                        "experiment_design_markdown": "design.md"},
    )
    assert result["metadata"]["discipline_ids"] == ["31"]


@pytest.mark.parametrize("manifest_ids,design_ids,error", [
    (["Physics and Astronomy"], ["31"], None),
    (["https://openalex.org/fields/31"], ["31"], None),
    (["31", "Physics and Astronomy"], ["31"], None),
    (["31"], ["25"], "discipline_ids differ"),
    (["31", "nonexistent field"], ["31"], "unknown discipline"),
    (["31"], ["31", "nonexistent field"], "unknown discipline"),
])
def test_manifest_verifier_compares_canonical_disciplines(monkeypatch, manifest_ids, design_ids, error):
    identity = {"survey_run_id": "run", "project_id": "project",
                "project_context_fingerprint": "context", "survey_manifest_path": "survey.json",
                "handoff_fingerprint": "handoff", "selected_direction_id": "direction"}
    idea_path = Path("idea_result.json").resolve()
    artifact_paths = {"experiment_design_json": Path("design.json"), "author_json": Path("author.json")}
    payload = {"identity": identity, "topic": "topic", "metadata": {
        "discipline_ids": manifest_ids, "selected_direction_id": "direction", "execution_mode": "DESIGN_ONLY",
    }}
    design = {"execution_policy": {"mode": "DESIGN_ONLY"}, "research_brief": {"discipline_ids": design_ids}}
    handoff = {"schema_version": "research_plan_author_input_v3", "provenance": {
        "survey_binding": identity, "selected_direction_id": "direction", "idea_result_path": str(idea_path),
    }}
    monkeypatch.setattr(manifests, "_verify_common_manifest", lambda *args: (Path("manifest.json"), payload, artifact_paths))
    monkeypatch.setattr(manifests, "_verify_input", lambda *args, **kwargs: idea_path)
    monkeypatch.setattr(manifests, "verify_idea_manifest", lambda *args, **kwargs: manifests.VerifiedStageManifest(
        stage="idea", manifest_path=Path("idea_manifest.json"), canonical_path=idea_path,
        identity=identity, metadata={}, artifacts={},
    ))
    monkeypatch.setattr(manifests, "_read_json", lambda path, **kwargs: design if path == artifact_paths["experiment_design_json"] else handoff)
    if error:
        with pytest.raises(manifests.ScienceManifestError, match=error):
            manifests.verify_experiment_design_manifest("manifest.json")
    else:
        assert manifests.verify_experiment_design_manifest("manifest.json").stage == "exp_design"
