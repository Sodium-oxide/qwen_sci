import pytest

from src.pipeline.survey_response_normalization import (
    FormatBatch, align_paper_assessments, normalize_model_response, record_list, score_field,
)


@pytest.mark.parametrize("raw,expected", [
    (0, 0), (5, 5), ("4", 4), (" 3.0 ", 3), (4.0, 4), ("4/5", 4),
    ("0 / 5", 0), ({"score": "4"}, 4), ({"value": 3.0}, 3),
])
def test_explicit_scores_are_recovered_as_integers(raw, expected):
    diagnostic = FormatBatch("assessment", 1)
    assert score_field({"project_score": raw}, "project_score", diagnostic) == expected
    assert not diagnostic.issues
    assert bool(diagnostic.recoveries) == (type(raw) is not int)


@pytest.mark.parametrize("raw", [
    None, True, False, 3.7, -1, 6, float("nan"), float("inf"),
    "3.7", "80%", "4/10", "high", "unknown", {}, [],
    {"confidence": 4}, {"score": 4, "value": 3}, {"score": 4, "scale": 100},
])
def test_unknown_or_ambiguous_scores_are_never_inferred(raw):
    diagnostic = FormatBatch("assessment", 1)
    assert score_field({"project_score": raw}, "project_score", diagnostic) is None
    assert not diagnostic.recoveries


@pytest.mark.parametrize("record,expected", [
    ({"project_relevance_score": "4"}, 4),
    ({"project_score": 4, "project_relevance_score": "4"}, 4),
    ({"project_score": 4, "project_relevance_score": 3}, None),
    ({"project_score": None, "project_relevance_score": 4}, None),
    ({"project_score": "unknown", "project_relevance_score": 4}, None),
    ({"confidence": 4}, None),
    ({}, None),
])
def test_alias_recovery_preserves_missing_and_conflicting_judgments(record, expected):
    diagnostic = FormatBatch("assessment", 1)
    assert score_field(record, "project_score", diagnostic) == expected


def test_assessment_record_array_is_recovered_to_object_once():
    diagnostic = FormatBatch("assessment", 1)
    response = normalize_model_response([{"paper_id": "W1", "project_score": 4}],
        collection_field="papers", diagnostics=diagnostic)
    assert response == {"papers": [{"paper_id": "W1", "project_score": 4}]}
    assert diagnostic.issues == []
    assert diagnostic.recoveries == {"response:paper_records_array_to_object": 1}
    logger = type("Logger", (), {"info": lambda self, message, *args: None,
        "warning": lambda self, message, *args: (_ for _ in ()).throw(AssertionError(message))})()
    audit = diagnostic.publish(logger)
    assert audit["visible_issues"] == []


def test_response_failure_keeps_derived_issues_in_audit_without_warning_fanout():
    diagnostic = FormatBatch("assessment", 1, paper_ids=["W1"])
    diagnostic.unresolved("response", "invalid_or_missing_JSON", paper_id="W1")
    diagnostic.suppress_derived = True
    for sh_id in ("SH1", "SH2", "SH3", "SH4", "SH5"):
        diagnostic.unresolved("sh_assessments", "incomplete_assessment", paper_id="W1", sub_hypothesis_id=sh_id)
    messages = []
    logger = type("Logger", (), {"info": lambda self, message, *args: messages.append(message % args),
        "warning": lambda self, message, *args: messages.append(message % args)})()
    audit = diagnostic.publish(logger)
    assert len(audit["visible_issues"]) == 1
    assert len(audit["suppressed_issues"]) == 5
    assert sum("Survey format warning" in message for message in messages) == 1
    assert any("suppressed_derived=5" in message for message in messages)


@pytest.mark.parametrize("response", [
    {"paper_id": "W1", "project_score": 4},
    [{"paper_id": "W1", "project_score": 4}],
    {"papers": {"paper_id": "W1", "project_score": 4}},
    {"papers": {"W1": {"project_score": 4}}},
    {"results": [{"paper_id": "W1", "project_score": 4}]},
    {"data": {"paper_assessments": [{"paper_id": "W1", "project_score": 4}]}},
    {"id": "response-123", "data": {"papers": [{"paper_id": "W1", "project_score": 4}]}},
    {"result": {"assessments": {"W1": {"project_score": 4}}}},
    {"W1": {"project_score": 4}},
    {"papers": [{"paper_id": "W1", "assessment": {"project_score": 4}}]},
])
def test_explicit_paper_wrappers_recover_without_changing_scores(response):
    diagnostic = FormatBatch("assessment", 1)
    normalized = normalize_model_response(response, collection_field="papers", diagnostics=diagnostic)
    aligned, audit = align_paper_assessments(["W1"], normalized["papers"], diagnostic)
    assert aligned["W1"]["project_score"] == 4
    assert audit["expected_records"][0]["status"] == "matched"
    assert diagnostic.response_audit["parsed_response"] == response
    assert diagnostic.recoveries
    assert not diagnostic.issues


@pytest.mark.parametrize("identifier", [
    "W1", " w1 ", "https://openalex.org/W1", "https://api.openalex.org/W1",
    "https://api.openalex.org/works/w1", "https://openalex.org/works/W1",
])
def test_returned_id_forms_match_without_rewriting_expected_ids(identifier):
    diagnostic = FormatBatch("assessment", 1)
    aligned, audit = align_paper_assessments(["https://openalex.org/W1"],
        [{"paper_id": identifier, "project_score": 4}], diagnostic)
    assert aligned["W1"]["project_score"] == 4
    assert audit["expected_records"][0]["paper_id"] == "https://openalex.org/W1"
    assert audit["returned_records"][0]["identity_fields_raw"] == {"paper_id": identifier}
    assert not diagnostic.issues


def test_keyed_paper_records_accept_equivalent_ids_and_reject_true_conflicts():
    diagnostic = FormatBatch("assessment", 1)
    records = record_list({
        "W1": {"paper_id": "https://api.openalex.org/W1", "project_score": 4},
        "W2": {"paper_id": "W3", "project_score": 4},
    }, "papers", diagnostic)
    assert records == [{"paper_id": "https://api.openalex.org/W1", "project_score": 4}]
    assert diagnostic.issues[0]["reason"] == "conflicting_identity"
    assert diagnostic.issues[0]["paper_id"] == "W2"


def test_paper_identity_aliases_recover_but_conflicting_fields_do_not_match():
    diagnostic = FormatBatch("assessment", 1)
    aligned, audit = align_paper_assessments(["W1", "W2"], [
        {"paperId": "https://api.openalex.org/works/W1", "project_score": 4},
        {"paper_id": "W2", "openalex_id": "W3", "project_score": 4},
    ], diagnostic)
    assert set(aligned) == {"W1"}
    assert audit["returned_records"][1]["status"] == "conflicting_paper_id_fields"
    assert audit["conflicting_paper_ids"] == ["W2"]
    assert not audit["missing_paper_ids"]
    assert audit["expected_records"][1]["returned_record_indices"] == [1]
    assert len(diagnostic.issues) == 1


def test_identical_duplicates_collapse_and_conflicting_duplicates_stay_unavailable():
    diagnostic = FormatBatch("assessment", 1)
    aligned, audit = align_paper_assessments(["W1", "W2"], [
        {"paper_id": "W1", "project_score": 4},
        {"paper_id": "https://openalex.org/W1", "project_score": 4},
        {"paper_id": "W2", "project_score": 4},
        {"paper_id": "https://openalex.org/W2", "project_score": 1},
    ], diagnostic)
    assert set(aligned) == {"W1"}
    assert audit["conflicting_paper_ids"] == ["W2"]
    assert audit["returned_records"][1]["status"] == "duplicate_identical"
    assert audit["expected_records"][0]["returned_record_indices"] == [0, 1]
    assert diagnostic.recoveries["papers:identical_assessments_collapsed"] == 1
    assert len(diagnostic.issues) == 1


def test_mixed_invalid_and_unexpected_records_preserve_original_indices():
    diagnostic = FormatBatch("assessment", 1)
    aligned, audit = align_paper_assessments(["W1", "W2"], [
        None, {"paper_id": "W2", "project_score": 4},
        {"paper_id": "W99", "project_score": 5}, {"project_score": 4},
    ], diagnostic)
    assert set(aligned) == {"W2"}
    assert audit["expected_records"][1]["returned_record_indices"] == [1]
    assert [record["record_index"] for record in audit["returned_records"]] == [0, 1, 2, 3]
    assert audit["unexpected_paper_ids"] == [{"paper_id": "W99"}]
    assert audit["returned_records"][3]["status"] == "missing_paper_id"
    assert len(diagnostic.issues) == 1
    assert diagnostic.suppressed_issues


def test_non_openalex_ids_are_not_matched_by_position_or_case():
    diagnostic = FormatBatch("assessment", 1)
    aligned, audit = align_paper_assessments(["provider-ABC"],
        [{"paper_id": "provider-abc", "project_score": 4}], diagnostic)
    assert not aligned
    assert audit["missing_paper_ids"] == ["provider-ABC"]
    assert audit["unexpected_paper_ids"] == [{"paper_id": "provider-abc"}]


def test_missing_record_suppression_is_scoped_to_its_paper():
    diagnostic = FormatBatch("assessment", 1)
    align_paper_assessments(["W1", "W2"], [{"paper_id": "W2", "project_score": 4}], diagnostic)
    for sh_id in ("SH1", "SH2", "SH3", "SH4", "SH5"):
        diagnostic.unresolved("sh_assessments", "incomplete_assessment", paper_id="W1", sub_hypothesis_id=sh_id)
    diagnostic.unresolved("project_score", "invalid_score", paper_id="W2")
    assert [issue["reason"] for issue in diagnostic.issues] == ["assessment_alignment_incomplete", "invalid_score"]
    assert len(diagnostic.suppressed_issues) == 6
    assert all(issue["derived_from"]["reason"] == "assessment_alignment_incomplete" for issue in diagnostic.suppressed_issues)


def test_unrecognized_assessment_envelope_has_one_response_root_cause():
    diagnostic = FormatBatch("assessment", 1)
    normalized = normalize_model_response({"candidates": [{"candidate_id": "C1"}]},
        collection_field="papers", diagnostics=diagnostic)
    assert normalized["_survey_response_unavailable"]
    assert diagnostic.response_audit["collection_paths"] == []
    assert len(diagnostic.issues) == 1
    assert diagnostic.issues[0]["field"] == "response"


def test_keyed_identity_conflict_retains_both_possible_links_without_assigning_either():
    diagnostic = FormatBatch("assessment", 1)
    aligned, audit = align_paper_assessments(["W1", "W2", "W3"], {
        "W1": {"paper_id": "W2", "project_score": 5}, "W3": {"project_score": 4},
    }, diagnostic)
    assert set(aligned) == {"W3"}
    assert audit["conflicting_paper_ids"] == ["W1", "W2"]
    assert [record["returned_record_indices"] for record in audit["expected_records"]] == [[0], [0], [1]]
    assert audit["returned_records"][0]["keyed_paper_id"] == "W1"
    assert audit["returned_records"][0]["identity_fields_raw"] == {"paper_id": "W2"}
    assert len(diagnostic.issues) == 1


def test_nested_identity_conflict_does_not_lose_inner_or_outer_id():
    diagnostic = FormatBatch("assessment", 1)
    aligned, audit = align_paper_assessments(["W1", "W2"], [
        {"paper_id": "W1", "assessment": {"paper_id": "W2", "project_score": 5}},
    ], diagnostic)
    assert not aligned
    assert audit["conflicting_paper_ids"] == ["W1", "W2"]
    assert audit["returned_records"][0]["canonical_identity_options"] == ["W1", "W2"]


def test_multiple_paper_collections_preserve_records_and_conflicts():
    diagnostic = FormatBatch("assessment", 1)
    response = {"papers": [{"paper_id": "W1", "project_score": 4}],
        "results": [{"paper_id": "W2", "project_score": 4}, {"paper_id": "W1", "project_score": 1}]}
    normalized = normalize_model_response(response, collection_field="papers", diagnostics=diagnostic)
    aligned, audit = align_paper_assessments(["W1", "W2"], normalized["papers"], diagnostic)
    assert set(aligned) == {"W2"}
    assert audit["conflicting_paper_ids"] == ["W1"]
    assert diagnostic.response_audit["collection_paths"] == ["$.papers", "$.results"]

