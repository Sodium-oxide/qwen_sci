"""Offline regression cases for repeated headings and literal evidence windows."""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.paper_graph.evidence_repair import (
    EvidenceLocatorCache, apply_repair_response, evidence_issues, repair_request, source_excerpts,
)
from src.paper_graph.ingest import source_documents, verified_evidence
from src.paper_graph.source_locations import quote_location, section_at, section_span


BODY = ("# Paper\n## Methods\nAn initial procedure.\n## Results\nAn initial result.\n"
        "## Methods\nThe retained procedure uses controlled input.\n"
        "## Results\nThe retained result confirms the procedure.\n")
QUOTE = "The retained procedure uses controlled input."


def documents(body=BODY):
    return source_documents({"source_documents": [{"source_id": "retained", "text": body}]})


@pytest.mark.parametrize("explicit_offsets", [False, True])
def test_repeated_heading_verifies_the_actual_occurrence(explicit_offsets):
    start = BODY.index(QUOTE)
    record = {"quote": QUOTE, "source_section": "Methods"}
    if explicit_offsets:
        record["locator"] = {"start": start, "end": start + len(QUOTE)}
    verified, = verified_evidence({"evidence_records": [record]}, documents())
    assert verified["locator"]["start"] == start
    assert verified["locator"]["section"] == "Methods"
    assert section_span(BODY, "Methods") is None
    assert section_span(BODY, "Methods", offset=start) == (section_at(BODY, start).start, section_at(BODY, start).end)


def test_repeated_heading_auto_locator_and_context_share_actual_position():
    docs = documents()
    entity = {"name": "Procedure", "summary": "controlled input", "quote": QUOTE, "source_section": "Wrong heading"}
    payload = {"core_contributions": [entity]}
    issue, = evidence_issues(payload, docs)
    record, hit = EvidenceLocatorCache(docs).resolve(issue.entry, entity)
    assert record["locator"]["start"] == BODY.index(QUOTE) and not hit
    excerpts = source_excerpts(entity, [issue], docs, max_chars=1000)
    assert any(QUOTE in excerpt["text"] for excerpt in excerpts)
    assert all(0 <= excerpt["start"] < excerpt["end"] <= len(BODY) for excerpt in excerpts)
    assert all(BODY[excerpt["start"]:excerpt["end"]] == excerpt["text"] for excerpt in excerpts)


def test_context_selects_matching_later_section_before_large_earlier_sections():
    body = BODY.replace("An initial procedure.", "Unrelated first section. " * 1200)
    docs = documents(body)
    entity = {"name": "Procedure", "summary": "controlled input", "quote": QUOTE, "source_section": "Methods"}
    from src.paper_graph.evidence_repair import EvidenceIssue
    issue = EvidenceIssue(("core_contributions", 0), "Procedure", "quote", None,
                          {"quote": QUOTE, "source_section": "Methods"}, [])
    excerpts = source_excerpts(entity, [issue], docs, max_chars=1200)
    assert any(QUOTE in excerpt["text"] for excerpt in excerpts)
    assert sum(len(excerpt["text"]) for excerpt in excerpts) <= 1200


def test_repeated_quote_requires_offsets_and_checks_actual_section():
    body = BODY.replace("An initial procedure.", QUOTE)
    docs = documents(body)
    record = {"quote": QUOTE, "source_section": "Methods"}
    assert not verified_evidence({"evidence_records": [record]}, docs)
    assert EvidenceLocatorCache(docs).resolve(record, {}) == (None, False)
    start = body.rindex(QUOTE)
    record["locator"] = {"start": start, "end": start + len(QUOTE)}
    assert verified_evidence({"evidence_records": [record]}, docs)[0]["locator"]["start"] == start
    record["source_section"] = "Results"
    assert not verified_evidence({"evidence_records": [record]}, docs)


def test_nested_duplicate_heading_uses_the_span_containing_the_entire_quote():
    body = "# Paper\n## Methods\nParent context.\n### Methods\nNested quote.\n## Results\nResult.\n"
    start = body.index("Nested quote.")
    assert quote_location(body, "Nested quote.", section="Methods") == ("Methods", start, start + len("Nested quote."))
    assert quote_location(body, "Parent context.\n### Methods\nNested quote.", section="Methods") is not None
    assert quote_location(body, "Nested quote.\n## Results\nResult.", section="Methods") is None


@pytest.mark.parametrize("retained", ["Fig.\u00a07", "Fig.\u202f7", "Fig.   7", "Fig.\n7"])
def test_format_matching_restores_original_characters_and_offsets(retained):
    body = "## Results\nThe result is shown in " + retained + ".\n"
    docs = documents(body)
    quote = "The result is shown in Fig. 7."
    record, = verified_evidence({"evidence_records": [{"quote": quote, "source_section": "Results"}]}, docs)
    assert record["quote"] == "The result is shown in " + retained + "."
    assert body[record["locator"]["start"]:record["locator"]["end"]] == record["quote"]
    assert record["source_sha256"] == docs[0]["sha256"]


@pytest.mark.parametrize("retained", ["Fig.\n\n7", "Fig.\n![caption](figure.png)\n7", "Fig. 8",
                                       "FIG. 7", "Fig.7", "Fig. <sup>7</sup>"])
def test_format_matching_does_not_skip_content_or_paragraph_boundaries(retained):
    docs = documents("## Results\nThe result is shown in " + retained + ".\n")
    assert not verified_evidence({"quote": "The result is shown in Fig. 7.", "source_section": "Results"}, docs)


def test_exact_quote_precedes_format_candidates_and_normalized_matches_must_be_unique():
    body = "## Results\nSee Fig.\u00a07.\nSee Fig. 7.\n"
    record, = verified_evidence({"quote": "See Fig. 7.", "source_section": "Results"}, documents(body))
    assert record["locator"]["start"] == body.index("See Fig. 7.")
    body = body.replace("See Fig. 7.", "See Fig.\u202f7.")
    assert not verified_evidence({"quote": "See Fig. 7.", "source_section": "Results"}, documents(body))
    issue, = evidence_issues({"core_contributions": [{"quote": "See Fig. 7.", "source_section": "Results"}]}, documents(body))
    assert "ambiguous_quote_location" in issue.reasons and "quote_not_contiguous_in_retained_fulltext" not in issue.reasons
    docs = source_documents({"source_documents": [
        {"source_id": "first", "text": "## Results\nSee Fig.\u00a07."},
        {"source_id": "second", "text": "## Results\nSee Fig.\u202f7."}]})
    assert not verified_evidence({"quote": "See Fig. 7.", "source_section": "Results"}, docs)
    record, = verified_evidence({"evidence_records": [{"quote": "See Fig. 7.", "source_id": "first",
                                                       "source_section": "Results"}]}, docs)
    assert record["source_id"] == "first" and record["quote"] == "See Fig.\u00a07."
    docs[0]["text"] += "\nSee Fig.\u202f7."
    assert not verified_evidence({"quote": "See Fig. 7.", "source_section": "Results"}, docs)
    assert EvidenceLocatorCache(docs).resolve({"quote": "See Fig. 7."}, {}) == (None, False)


def test_format_locator_corrects_section_and_refuses_wrong_source_identity():
    docs = documents("## Results\nSee Fig.\u00a07.\n")
    cache = EvidenceLocatorCache(docs)
    record, _ = cache.resolve({"quote": "See Fig. 7.", "source_section": "Wrong"}, {})
    assert record["quote"] == "See Fig.\u00a07." and record["locator"]["section"] == "Results"
    assert cache.resolve({"quote": "See Fig. 7.", "source_sha256": "wrong"}, {}) == (None, False)


def candidate_case(field="evidence_records"):
    quote = "The sampling procedure uses controlled input."
    body = ("# Paper\n## \uf0b7 Sampling\nInitial sampling context.\n" + quote +
            "\n## o Sampling\nFollow-up sampling context.\n" + quote + "\n")
    evidence = {"quote": quote, "source_section": "Sampling"}
    entity = {"name": "Procedure", "summary": "A controlled procedure", "assumptions": ["constant input"]}
    if field == "evidence_records":
        entity[field] = [evidence]
    else:
        entity.update(evidence)
    output = {"ideation_resource": {"core_contributions": [entity]}}
    docs = documents(body)
    issues = evidence_issues(output, docs)
    return output, docs, issues, repair_request(output, issues, docs, [])


@pytest.mark.parametrize("field", ["quote", "evidence_records"])
def test_candidate_selection_restores_real_pdf_heading_prefix_and_exact_offsets(field):
    output, docs, issues, request = candidate_case(field)
    candidates = request["location_candidates"]
    assert len(candidates) == 2
    assert [candidate["evidence_record"]["locator"]["section"] for candidate in candidates] == [
        "\uf0b7 Sampling", "o Sampling"]
    assert candidates == repair_request(output, issues, docs, ["previous failure"])["location_candidates"]
    for candidate in candidates:
        record = candidate["evidence_record"]
        context = candidate["context"]
        locator = record["locator"]
        assert candidate["target_id"] == issues[0].target_id and candidate["match_type"] == "exact"
        assert record["source_id"] == docs[0]["source_id"] and record["source_sha256"] == docs[0]["sha256"]
        assert docs[0]["text"][locator["start"]:locator["end"]] == record["quote"]
        assert docs[0]["text"][context["start"]:context["end"]] == context["text"]
        assert context["start"] <= locator["start"] < locator["end"] <= context["end"]
    selected = candidates[1]
    response = {"repairs": [{"target_id": issues[0].target_id,
                              "candidate_ids": [selected["candidate_id"]]}], "unresolved": []}
    repaired, applied, errors = apply_repair_response(output, issues, response, docs, candidates=candidates)
    assert applied == [issues[0].target_id] and not errors and not evidence_issues(repaired, docs)
    entity = repaired["ideation_resource"]["core_contributions"][0]
    record, = entity["evidence_records"]
    assert record["locator"] == selected["evidence_record"]["locator"]
    assert record["locator"]["start"] == docs[0]["text"].rindex(record["quote"])
    assert {key: value for key, value in entity.items() if key not in {"quote", "evidence_records"}} == {
        key: value for key, value in output["ideation_resource"]["core_contributions"][0].items()
        if key not in {"quote", "evidence_records"}}


def test_format_candidates_enumerate_all_matches_and_restore_actual_source_characters():
    body = "# Paper\n## Results\nSee Fig.\u00a07.\nSee Fig.\u202f7.\nSee Fig.\u20097.\n"
    docs = documents(body)
    output = {"core_contributions": [{"name": "Result", "quote": "See Fig. 7.", "source_section": "Results"}]}
    issues = evidence_issues(output, docs)
    request = repair_request(output, issues, docs, [])
    candidates = request["location_candidates"]
    assert len(candidates) == 3 and {candidate["match_type"] for candidate in candidates} == {"format"}
    selected = candidates[-1]
    response = {"repairs": [{"target_id": issues[0].target_id, "candidate_ids": [selected["candidate_id"]]}]}
    repaired, applied, errors = apply_repair_response(output, issues, response, docs, candidates=candidates)
    assert applied and not errors and not evidence_issues(repaired, docs)
    record, = repaired["core_contributions"][0]["evidence_records"]
    assert record["quote"] == "See Fig.\u20097." and record["locator"]["start"] == body.rindex("See Fig.")


def test_candidate_generation_prefers_exact_matches_across_eligible_sources():
    docs = source_documents({"source_documents": [
        {"source_id": "first", "text": "## Results\nSee Fig.\u00a07."},
        {"source_id": "second", "text": "## Results\nSee Fig. 7."}]})
    output = {"core_contributions": [{"quote": "See Fig. 7.", "source_section": "Unknown"}]}
    issues = evidence_issues(output, docs)
    candidate, = repair_request(output, issues, docs, [])["location_candidates"]
    assert candidate["match_type"] == "exact" and candidate["evidence_record"]["source_id"] == "second"


def test_candidate_ids_keep_case_sensitive_source_identities_distinct():
    docs = source_documents({"source_documents": [
        {"source_id": "Source", "text": "## Results\nRepeated evidence."},
        {"source_id": "source", "text": "## Results\nRepeated evidence."}]})
    output = {"core_contributions": [{"quote": "Repeated evidence.", "source_section": "Unknown"}]}
    issues = evidence_issues(output, docs)
    candidates = repair_request(output, issues, docs, [])["location_candidates"]
    assert len(candidates) == 2 and len({candidate["candidate_id"] for candidate in candidates}) == 2
    assert {candidate["evidence_record"]["source_id"] for candidate in candidates} == {"Source", "source"}


@pytest.mark.parametrize("constraint", [
    {"source_id": "unknown"}, {"source_sha256": "wrong"},
    {"locator": {"path": "/different/source.md"}}, {"page": 9},
])
def test_candidates_preserve_source_identity_checksum_path_and_page_constraints(constraint):
    output, docs, _, _ = candidate_case()
    output["ideation_resource"]["core_contributions"][0]["evidence_records"][0].update(constraint)
    issues = evidence_issues(output, docs)
    assert not repair_request(output, issues, docs, [])["location_candidates"]


@pytest.mark.parametrize("selection,reason", [
    ("unknown", "unknown_candidate_id"), ("other_target", "candidate_target_mismatch"),
    ("duplicate", "duplicate_candidate_id"), ("empty", "candidate_ids_must_be_nonempty_strings"),
    ("nonstring", "candidate_ids_must_be_nonempty_strings"),
    ("override", "unexpected_patch_fields"), ("freehand", "candidate_selection_required"),
])
def test_invalid_candidate_choices_preserve_original_evidence(selection, reason):
    output, docs, _, _ = candidate_case()
    entity = output["ideation_resource"]["core_contributions"][0]
    entity["evidence_records"].append(deepcopy(entity["evidence_records"][0]))
    issues = evidence_issues(output, docs)
    candidates = repair_request(output, issues, docs, [])["location_candidates"]
    selected = next(candidate for candidate in candidates if candidate["target_id"] == issues[0].target_id)
    other = next(candidate for candidate in candidates if candidate["target_id"] == issues[1].target_id)
    patch = {"target_id": issues[0].target_id, "candidate_ids": [selected["candidate_id"]]}
    if selection == "unknown":
        patch["candidate_ids"] = ["candidate:invented"]
    elif selection == "other_target":
        patch["candidate_ids"] = [other["candidate_id"]]
    elif selection == "duplicate":
        patch["candidate_ids"] *= 2
    elif selection == "empty":
        patch["candidate_ids"] = []
    elif selection == "nonstring":
        patch["candidate_ids"] = [None]
    elif selection == "override":
        patch["source_section"] = "Invented heading"
    elif selection == "freehand":
        patch.pop("candidate_ids")
        patch["evidence_records"] = [selected["evidence_record"]]
    repaired, applied, errors = apply_repair_response(output, issues, {"repairs": [patch]}, docs,
                                                      candidates=candidates)
    assert repaired == output and not applied and any(reason in error for error in errors)


def test_candidate_ids_are_limited_to_sent_choices_and_unchanged_source_snapshot():
    output, docs, issues, request = candidate_case()
    candidates = request["location_candidates"]
    selected = candidates[-1]
    response = {"repairs": [{"target_id": issues[0].target_id, "candidate_ids": [selected["candidate_id"]]}]}
    repaired, applied, errors = apply_repair_response(output, issues, response, docs, candidates=candidates[:1])
    assert repaired == output and not applied and any("unknown_candidate_id" in error for error in errors)
    changed_docs = documents(docs[0]["text"] + "\nChanged source content.")
    changed_candidates = repair_request(output, issues, changed_docs, [])["location_candidates"]
    assert {candidate["candidate_id"] for candidate in candidates}.isdisjoint(
        candidate["candidate_id"] for candidate in changed_candidates)
    repaired, applied, errors = apply_repair_response(output, issues, response, changed_docs, candidates=candidates,
                                                      locator_cache=EvidenceLocatorCache(changed_docs))
    assert repaired == output and not applied and any("source_checksum_mismatch" in error for error in errors)


def test_valid_candidate_patch_commits_independently_and_undecidable_target_stays_unresolved():
    output, docs, _, _ = candidate_case()
    entity = output["ideation_resource"]["core_contributions"][0]
    entity["evidence_records"].append(deepcopy(entity["evidence_records"][0]))
    issues = evidence_issues(output, docs)
    candidates = repair_request(output, issues, docs, [])["location_candidates"]
    selected = candidates[0]
    response = {"repairs": [{"target_id": issues[0].target_id, "candidate_ids": [selected["candidate_id"]]}],
                "unresolved": [{"target_id": issues[1].target_id, "reason": "The two contexts do not identify the intended sample."}]}
    repaired, applied, errors = apply_repair_response(output, issues, response, docs, candidates=candidates)
    assert applied == [issues[0].target_id] and len(errors) == 1 and "intended sample" in errors[0]
    remaining, = evidence_issues(repaired, docs)
    assert remaining.target_id == issues[1].target_id
    assert repaired["ideation_resource"]["core_contributions"][0]["evidence_records"][1] == entity["evidence_records"][1]
