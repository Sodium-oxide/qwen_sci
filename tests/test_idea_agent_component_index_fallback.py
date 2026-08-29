from types import SimpleNamespace

from src.agents.idea_agent.agent.mcts import MemoryGuidedMCTS


class UnavailableComponentStore:
    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, **_kwargs: object) -> list[dict[str, object]]:
        self.search_calls += 1
        raise RuntimeError("Component index files are missing")


class CapturingLogger:
    def __init__(self) -> None:
        self.warnings: list[tuple[object, ...]] = []

    def warning(self, message: object, *args: object) -> None:
        self.warnings.append((message, *args))


def test_mechanism_commit_retrieval_falls_back_when_component_index_is_missing() -> None:
    component_store = UnavailableComponentStore()
    logger = CapturingLogger()
    mcts = object.__new__(MemoryGuidedMCTS)
    mcts.config = SimpleNamespace(
        mechanism_commit_retrieval_top_k=3,
        mechanism_commit_similarity_threshold=0.6,
    )
    mcts.paper_graph_vector_store = component_store
    mcts.logger = logger
    mcts.log_sink = None
    mcts._mechanism_commit_retrieval_unavailable = False

    query_payload = {"query": "training-free temporal memory"}

    assert mcts._retrieve_mechanism_commit_references(query_payload) == []
    assert mcts._retrieve_mechanism_commit_references(query_payload) == []
    assert component_store.search_calls == 1
    assert len(logger.warnings) == 1
    assert "continuing without paper-graph grounding" in str(logger.warnings[0][0])
