from __future__ import annotations

from typing import Any

import pytest

from src.agents.quantitative_modeling.parameter_evidence.providers import AcademicMetadataProviders, ParameterEvidenceProviderError, ParameterEvidenceSettings
from src.webapp.parameter_search_service import _merge_records
from src.webapp.schemas import ParameterSearchRequest


def test_anysearch_provider_normalizes_common_response_envelope() -> None:
    def json_post(url: str, **kwargs: Any) -> object:
        assert url == "https://anysearch.test/v1/search"
        assert kwargs["json"] == {"query": "parameter study", "max_results": 10, "tag": "academic.search", "format": "json"}
        assert kwargs["headers"] == {"Authorization": "Bearer secret"}
        return {"code": 0, "data": {"results": [{"id": "a-1", "title": "A parameter study", "publication_year": 2024, "doi": "https://doi.org/10.1234/example", "url": "https://example.test/paper"}]}}

    provider = AcademicMetadataProviders(
        ParameterEvidenceSettings(anysearch_base_url="https://anysearch.test", anysearch_api_key="secret"),
        json_post=json_post,
    )
    records = provider.search_anysearch("parameter study")
    assert records[0]["provider"] == "anysearch"
    assert records[0]["doi"] == "10.1234/example"
    assert records[0]["oa_locations"][0]["landing_url"] == "https://example.test/paper"


def test_anysearch_parameter_provider_keeps_cleaned_content_out_of_abstract() -> None:
    def json_post(_url: str, **kwargs: Any) -> object:
        assert kwargs["headers"] == {}
        return {"code": 0, "data": {"results": [{"title": "A parameter study", "url": "https://doi.org/10.1234/example",
                                                    "snippet": "Search text", "content": "Cleaned search content"}]}}

    records = AcademicMetadataProviders(ParameterEvidenceSettings(), json_post=json_post).search_anysearch("parameter study")
    assert records[0]["doi"] == "10.1234/example"
    assert records[0]["abstract"] == ""
    assert records[0]["discovery_content"] == "Cleaned search content"


def test_anysearch_parameter_provider_reports_business_failure() -> None:
    provider = AcademicMetadataProviders(ParameterEvidenceSettings(), json_post=lambda *_args, **_kwargs: {"code": -1, "data": {"results": []}})
    with pytest.raises(ParameterEvidenceProviderError):
        provider.search_anysearch("parameter study")


def test_search_merge_cross_validates_doi_and_title_year_matches() -> None:
    merged = _merge_records(
        [
            {"provider": "openalex", "provider_paper_id": "W1", "title": "Kilonova Parameter Study", "doi": "10.1/x", "year": 2024},
            {"provider": "anysearch", "provider_paper_id": "A1", "title": "Kilonova Parameter Study", "doi": "https://doi.org/10.1/x", "year": 2024},
            {"provider": "openalex", "provider_paper_id": "W2", "title": "Neutron capture model", "year": 2023},
            {"provider": "anysearch", "provider_paper_id": "A2", "title": "Neutron-capture model", "year": 2023},
        ]
    )
    assert len(merged) == 2
    assert merged[0]["cross_validated"] is True
    assert set(merged[0]["sources"]) == {"openalex", "anysearch"}
    assert merged[1]["match_method"] == "title_year"


def test_parameter_search_requires_explicit_network_authorization() -> None:
    with pytest.raises(ValueError):
        ParameterSearchRequest(
            idea_id="Q1",
            version=0,
            parameter_id="velocity",
            query="kilonova velocity",
            network_authorized=False,
        )
