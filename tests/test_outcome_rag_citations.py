from __future__ import annotations

from types import SimpleNamespace

from src.agents.survey_agent.modules.outcome_RAG import OutcomeRAG


def test_failed_citation_title_does_not_discard_other_citations() -> None:
    calls = []
    warnings = []

    def get_paper_title(paper_id: str) -> str:
        calls.append(paper_id)
        if paper_id == "W4288051764":
            raise ValueError("No valid abstract")
        return "Available paper"

    rag = OutcomeRAG.__new__(OutcomeRAG)
    rag.json_data = {"references": ["W4288051764", "W123"]}
    rag.work_collector = SimpleNamespace(get_paper_title=get_paper_title)
    rag.logger = SimpleNamespace(warning=lambda *args: warnings.append(args))
    rag._citation_lookup_cache = {}

    citations = rag._collect_citations("First [1], then [2], again [1].")

    assert citations[0]["paper_id"] == ""
    assert citations[1]["paper_id"] == "W123"
    assert citations[1]["title"] == "Available paper"
    assert len(warnings) == 1

    rag._collect_citations("Repeated [1] and [2].")
    assert calls == ["W4288051764", "W123"]
