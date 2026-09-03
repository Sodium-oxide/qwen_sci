from __future__ import annotations

import copy

from src.pipeline.survey_idea_handoff import (
    ArtifactManifestEntry,
    AnchorRecord,
    EvidenceEligibility,
    EvidenceRoleRecord,
    GapLedger,
    GapRecord,
    ProfileResolution,
    ScopeRecord,
    SourcePointer,
    SurveyIdeaHandoff,
    SurveyManifest,
    SURVEY_GAP_LEDGER_SCHEMA,
    SURVEY_GAP_LEDGER_SCHEMA_VERSION,
    SURVEY_IDEA_HANDOFF_SCHEMA,
    SURVEY_IDEA_HANDOFF_SCHEMA_VERSION,
    SURVEY_MANIFEST_SCHEMA,
    SURVEY_MANIFEST_SCHEMA_VERSION,
    build_gap_ledger_payload,
    build_handoff_payload,
    build_anchor_id,
    build_manifest_payload,
    canonical_fingerprint,
    topic_fingerprint,
    validate_gap_ledger_payload,
    validate_handoff_payload,
    validate_manifest_payload,
)


def _gap() -> GapRecord:
    return GapRecord.create(
        subhypothesis_id="SH3",
        gap_kind="missing_assumption",
        target_slot="formal_claim",
        statement="The validity conditions remain unspecified.",
        target_object="formal validity domain",
        priority="high",
        support_level="authoritative",
        candidate_defect_tags=["missing_assumption", "proof_gap"],
        candidate_contribution_modes=["formal_assumption", "counterexample"],
        anchor_ids=[
            build_anchor_id(
                "subhypothesis_slot",
                subhypothesis_id="SH3",
                target_slot="formal_claim",
                source_id="survey_evidence_plan.json",
            )
        ],
        evidence_eligibility=EvidenceEligibility(
            required_roles=["FORMAL_PROOF", "BOUNDARY_EVIDENCE"],
            allowed_claim_modes=["QUALIFIED_SYNTHESIS"],
        ),
        source_pointer=SourcePointer(
            artifact="survey_evidence_plan.json",
            json_pointer="/subhypotheses/2/missing_slots/0",
        ),
    )


def test_contract_versions_and_json_schemas_are_exported() -> None:
    assert SURVEY_GAP_LEDGER_SCHEMA["properties"]["schema_version"]["const"] == SURVEY_GAP_LEDGER_SCHEMA_VERSION
    assert SURVEY_IDEA_HANDOFF_SCHEMA["properties"]["schema_version"]["const"] == SURVEY_IDEA_HANDOFF_SCHEMA_VERSION
    assert SURVEY_MANIFEST_SCHEMA["properties"]["schema_version"]["const"] == SURVEY_MANIFEST_SCHEMA_VERSION


def test_gap_anchor_and_evidence_ids_are_stable() -> None:
    gap = _gap()
    assert gap.gap_id == GapRecord.create(
        subhypothesis_id="SH3",
        gap_kind="missing_assumption",
        target_slot="formal_claim",
        statement="changed wording does not change semantic ID",
        target_object="formal validity domain",
    ).gap_id
    anchor_a = AnchorRecord.create(
        anchor_type="subhypothesis_slot",
        label="Validity domain",
        subhypothesis_id="SH3",
        target_slot="formal_claim",
        source_id="survey_evidence_plan.json",
    )
    anchor_b = AnchorRecord.create(
        anchor_type="subhypothesis_slot",
        label="Different label",
        subhypothesis_id="SH3",
        target_slot="formal_claim",
        source_id="survey_evidence_plan.json",
    )
    assert anchor_a.anchor_id == anchor_b.anchor_id
    role_a = EvidenceRoleRecord.create(
        subhypothesis_id="SH3",
        target_slot="formal_claim",
        expected_role="FORMAL_PROOF",
    )
    role_b = EvidenceRoleRecord.create(
        subhypothesis_id="SH3",
        target_slot="formal_claim",
        expected_role="FORMAL_PROOF",
        claim_limits=["different explanatory note"],
    )
    assert role_a.role_id == role_b.role_id


def test_gap_ledger_builder_adds_fingerprint_and_validates() -> None:
    payload = build_gap_ledger_payload(
        GapLedger(
            project_id="project-1",
            survey_run_id="20260826-002857-396164",
            project_context_fingerprint="context-fingerprint",
            gaps=[_gap()],
            profile_resolution=ProfileResolution(status="unresolved", requires_human_confirmation=True),
            created_at="2026-08-26T01:00:00Z",
        )
    )
    assert payload["ledger_fingerprint"] == canonical_fingerprint(
        payload,
        exclude_fields={"ledger_fingerprint"},
    )
    assert validate_gap_ledger_payload(payload, verify_fingerprint=True) == []

    tampered = copy.deepcopy(payload)
    tampered["gaps"][0]["statement"] = "tampered"
    assert any("ledger_fingerprint" in error for error in validate_gap_ledger_payload(tampered, verify_fingerprint=True))


def test_handoff_builder_preserves_unresolved_profile_without_cs_fallback() -> None:
    handoff = build_handoff_payload(
        SurveyIdeaHandoff(
            project_id="project-1",
            survey_run_id="20260826-002857-396164",
            topic="Why do black holes exist?",
            project_context_fingerprint="context-fingerprint",
            gaps=[_gap()],
            anchors=[
                AnchorRecord.create(
                    anchor_type="subhypothesis_slot",
                    label="Validity domain",
                    subhypothesis_id="SH3",
                    target_slot="formal_claim",
                    source_id="survey_evidence_plan.json",
                    supports_gap_ids=[_gap().gap_id],
                )
            ],
            evidence_roles=[
                EvidenceRoleRecord.create(
                    subhypothesis_id="SH3",
                    target_slot="formal_claim",
                    expected_role="FORMAL_PROOF",
                )
            ],
            profile_resolution=ProfileResolution(status="unresolved", requires_human_confirmation=True),
            scope=ScopeRecord(research_object=["black holes"]),
            constraints={"may_generate_new_gap": False},
            created_at="2026-08-26T01:00:00Z",
        )
    )
    assert handoff["profile_resolution"]["status"] == "unresolved"
    assert handoff["profile_resolution"].get("profile_id_hint", "") == ""
    assert validate_handoff_payload(handoff, verify_fingerprint=True) == []


def test_manifest_builder_validates_artifact_hashes_and_completion() -> None:
    manifest = build_manifest_payload(
        SurveyManifest(
            survey_run_id="20260826-002857-396164",
            project_id="project-1",
            topic="Why do black holes exist?",
            project_context_fingerprint="context-fingerprint",
            base_dir=".",
            status="completed",
            created_at="2026-08-26T01:00:00Z",
            completed_at="2026-08-26T01:05:00Z",
            artifacts={
                "survey_json": ArtifactManifestEntry(
                    path="survey.json",
                    sha256="a" * 64,
                ),
                "idea_handoff": ArtifactManifestEntry(
                    path="survey_idea_handoff.json",
                    sha256="b" * 64,
                ),
                "survey_markdown": ArtifactManifestEntry(path="survey.md", sha256="c" * 64),
                "project_context": ArtifactManifestEntry(path="project_context.json", sha256="d" * 64),
                "evidence_plan": ArtifactManifestEntry(path="survey_evidence_plan.json", sha256="e" * 64),
                "claim_traceability": ArtifactManifestEntry(path="survey_claim_traceability.json", sha256="f" * 64),
                "gap_ledger": ArtifactManifestEntry(path="survey_gap_ledger.json", sha256="0" * 64),
            },
        )
    )
    assert manifest["topic_fingerprint"] == topic_fingerprint("Why do black holes exist?")
    assert validate_manifest_payload(manifest, verify_fingerprint=True) == []

    incomplete = copy.deepcopy(manifest)
    incomplete["completed_at"] = ""
    assert any("completed_at" in error for error in validate_manifest_payload(incomplete))
