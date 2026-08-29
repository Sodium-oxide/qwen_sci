"""Search Paper Abstract Tool - OpenHands Format"""

import os
import sys
from typing import List, Dict, Any, Sequence
import logging
from pydantic import Field

from openhands.sdk import (
    Action,
    ImageContent,
    Observation,
    TextContent,
)
from openhands.sdk.tool import (
    ToolExecutor,
    register_tool,
    ToolDefinition,
)


logger = logging.getLogger(__name__)

# Add src to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
src_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if src_root not in sys.path:
    sys.path.insert(0, src_root)

# Import the search function
from blog_agent.utils.semantic_scholar import search_paper_and_get_abstract


# --- Action / Observation ---


class SearchPaperAbstractAction(Action):
    """Search for a paper on Semantic Scholar and retrieve its full abstract."""

    query: str = Field(
        description="Search query - can be paper title, keywords, or any text to find the paper"
    )
    max_results: int = Field(
        default=1,
        ge=1,
        le=20,
        description="Number of ranked paper candidates to return; use multiple results for topic discovery",
    )


class SearchPaperAbstractObservation(Observation):
    """Result of searching paper abstract from Semantic Scholar."""

    status: str = Field(
        description="Status: 'success' or 'fail'"
    )
    detail: str = Field(
        description="Detail: failure reason or paper info"
    )
    paper: Dict[str, Any] = Field(
        default_factory=dict,
        description="Paper details including title, abstract, year, authors, venue, paper_id, url (only on success)"
    )
    papers: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Ranked candidate papers, including the best paper, for broader topic searches",
    )

    @property
    def to_llm_content(self) -> Sequence[TextContent | ImageContent]:
        if self.status == "fail":
            return [TextContent(text=f"Search failed: {self.detail}")]

        candidates = self.papers or ([self.paper] if self.paper else [])
        lines = [self.detail]
        for index, paper in enumerate(candidates, start=1):
            abstract = paper.get("abstract") or "N/A"
            if len(abstract) > 350:
                abstract = abstract[:350] + "..."
            lines.extend([
                "",
                f"Candidate {index}: {paper.get('title', 'N/A')}",
                f"Year: {paper.get('year', 'N/A')}",
                f"Venue: {paper.get('venue', 'N/A')}",
                f"Authors: {', '.join(paper.get('authors') or [])}",
                f"Paper ID: {paper.get('paper_id', 'N/A')}",
                f"URL: {paper.get('url', 'N/A')}",
                "Abstract:",
                abstract,
            ])

        return [TextContent(text="\n".join(lines))]


# --- Executor ---


class SearchPaperAbstractExecutor(ToolExecutor[SearchPaperAbstractAction, SearchPaperAbstractObservation]):
    """Executor that searches Semantic Scholar for paper abstracts."""

    def __call__(
        self,
        action: SearchPaperAbstractAction,
        conversation=None
    ) -> SearchPaperAbstractObservation:
        """Execute the search_paper_abstract action."""
        result = search_paper_and_get_abstract(
            query=action.query,
            max_results=action.max_results,
        )

        return SearchPaperAbstractObservation(
            status=result.get("status", "fail"),
            detail=result.get("detail", "Unknown error"),
            paper=result.get("paper") or {},
            papers=result.get("papers") or [],
        )


# --- Tool Description ---
_SEARCH_PAPER_ABSTRACT_DESCRIPTION = """Search Semantic Scholar for academic papers and retrieve full abstracts.
* Takes a search query (paper title, keywords, or any text)
* Set max_results above 1 to discover a ranked, bounded set of candidates for a topic
* Returns paper details including: title, abstract, year, authors, venue, paper ID, URL
* Useful for finding detailed paper information when local graph retrieval is unavailable
* Supports fuzzy search - not limited to exact title matches
"""


# --- Tool Definition ---


class SearchPaperAbstractTool(ToolDefinition[SearchPaperAbstractAction, SearchPaperAbstractObservation]):
    """A custom tool for searching paper abstracts from Semantic Scholar."""

    @classmethod
    def create(cls, conv_state) -> Sequence[ToolDefinition]:
        """Create SearchPaperAbstractTool instance.

        Args:
            conv_state: Conversation state (not used but required by interface).

        Returns:
            A sequence containing a single SearchPaperAbstractTool instance.
        """
        executor = SearchPaperAbstractExecutor()

        return [
            cls(
                description=_SEARCH_PAPER_ABSTRACT_DESCRIPTION,
                action_type=SearchPaperAbstractAction,
                observation_type=SearchPaperAbstractObservation,
                executor=executor,
            )
        ]


# --- Registration ---
def _make_search_paper_abstract_tool(conv_state) -> list[ToolDefinition]:
    """Create the search paper abstract tool."""
    return list(SearchPaperAbstractTool.create(conv_state))


register_tool("SearchPaperAbstractTool", _make_search_paper_abstract_tool)
