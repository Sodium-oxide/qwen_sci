from __future__ import annotations

from typing import Any

import pytest

from src.agents.quantitative_modeling.parameter_evidence.providers import AcademicMetadataProviders, ParameterEvidenceSettings
from src.webapp.parameter_search_service import _merge_records
from src.webapp.schemas import ParameterSearchRequest


def test_anysearch_provider_normalizes_common_response_envelope() -> None:
    def json_get(url: str, **_kwargs: Any) -> object:
        assert url.endswith("/search")
        return {"results": [{"id": "a-1", "title": "A parameter study", "publication_year": 2024, "doi": "https://doi.org/10.1234/example", "url": "https://example.test/paper"}]}

    provider = AcademicMetadataProviders(
        ParameterEvidenceSettings(anysearch_base_url="https://anysearch.test", anysearch_api_key="secret"),
        json_get=json_get,
    )
    records = provider.search_anysearch("parameter study")
    assert records[0]["provider"] == "anysearch"
    assert records[0]["doi"] == "10.1234/example"
    assert records[0]["oa_locations"][0]["landing_url"] == "https://example.test/paper"


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
