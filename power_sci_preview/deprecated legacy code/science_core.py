"""Science Core — Re-export facade.

This module re-exports all public symbols from the split submodules.
External code importing from science_core should see no change.
"""
from __future__ import annotations

try:
    from ._utils import *  # noqa: F401,F403
    from ._discipline_taxonomy import *  # noqa: F401,F403
    from ._models import *  # noqa: F401,F403
    from ._project import *  # noqa: F401,F403
    from ._evidence_standards import *  # noqa: F401,F403
    from ._subhypothesis_annotation import *  # noqa: F401,F403
    from ._literature_retrieval_foundation import *  # noqa: F401,F403
    from ._retrieval_strategy import *  # noqa: F401,F403
    from ._llm import *  # noqa: F401,F403
    from ._literature_search import *  # noqa: F401,F403
    from ._literature_scoring import *  # noqa: F401,F403
    from ._literature_graph import *  # noqa: F401,F403
    from ._literature_import import *  # noqa: F401,F403
    from ._research_graph import *  # noqa: F401,F403
    from ._gap_evidence_graph import *  # noqa: F401,F403
    from ._gap_detectors import *  # noqa: F401,F403
    from ._gap_detection import *  # noqa: F401,F403
    from ._socrates_type_review import *  # noqa: F401,F403
    from ._proposal_contracts import *  # noqa: F401,F403
    from ._proposal_brief import *  # noqa: F401,F403
    from ._proposal_writer import *  # noqa: F401,F403
    from ._proposal_audit import *  # noqa: F401,F403
    from ._proposal_export import *  # noqa: F401,F403
    from ._proposal_report import *  # noqa: F401,F403
    from ._gap_source_role import *  # noqa: F401,F403
    from ._hypothesis import *  # noqa: F401,F403
    from ._research_report import *  # noqa: F401,F403
    from ._socrates import *  # noqa: F401,F403
    from ._verification import *  # noqa: F401,F403
    from ._debate import *  # noqa: F401,F403
    from ._supplement import *  # noqa: F401,F403
    from ._pipeline import *  # noqa: F401,F403
except ImportError:
    from _utils import *  # noqa: F401,F403
    from _discipline_taxonomy import *  # noqa: F401,F403
    from _models import *  # noqa: F401,F403
    from _project import *  # noqa: F401,F403
    from _evidence_standards import *  # noqa: F401,F403
    from _subhypothesis_annotation import *  # noqa: F401,F403
    from _literature_retrieval_foundation import *  # noqa: F401,F403
    from _retrieval_strategy import *  # noqa: F401,F403
    from _llm import *  # noqa: F401,F403
    from _literature_search import *  # noqa: F401,F403
    from _literature_scoring import *  # noqa: F401,F403
    from _literature_graph import *  # noqa: F401,F403
    from _literature_import import *  # noqa: F401,F403
    from _research_graph import *  # noqa: F401,F403
    from _gap_evidence_graph import *  # noqa: F401,F403
    from _gap_detectors import *  # noqa: F401,F403
    from _gap_detection import *  # noqa: F401,F403
    from _socrates_type_review import *  # noqa: F401,F403
    from _proposal_contracts import *  # noqa: F401,F403
    from _proposal_brief import *  # noqa: F401,F403
    from _proposal_writer import *  # noqa: F401,F403
    from _proposal_audit import *  # noqa: F401,F403
    from _proposal_export import *  # noqa: F401,F403
    from _proposal_report import *  # noqa: F401,F403
    from _gap_source_role import *  # noqa: F401,F403
    from _hypothesis import *  # noqa: F401,F403
    from _research_report import *  # noqa: F401,F403
    from _socrates import *  # noqa: F401,F403
    from _verification import *  # noqa: F401,F403
    from _debate import *  # noqa: F401,F403
    from _supplement import *  # noqa: F401,F403
    from _pipeline import *  # noqa: F401,F403

# Make submodule references available for internal use
try:
    from . import _utils
    from . import _discipline_taxonomy
    from . import _pdf_extraction
    from . import _models
    from . import _project
    from . import _evidence_standards
    from . import _subhypothesis_annotation
    from . import _literature_retrieval_foundation
    from . import _retrieval_strategy
    from . import _llm
    from . import _literature_search
    from . import _literature_scoring
    from . import _literature_graph
    from . import _literature_import
    from . import _research_graph
    from . import _gap_evidence_graph
    from . import _gap_detectors
    from . import _gap_detection
    from . import _socrates_type_review
    from . import _proposal_contracts
    from . import _proposal_brief
    from . import _proposal_writer
    from . import _proposal_audit
    from . import _proposal_export
    from . import _proposal_report
    from . import _gap_source_role
    from . import _hypothesis
    from . import _research_report
    from . import _socrates
    from . import _verification
    from . import _debate
    from . import _supplement
    from . import _pipeline
except ImportError:
    import _utils
    import _discipline_taxonomy
    import _pdf_extraction
    import _models
    import _project
    import _evidence_standards
    import _subhypothesis_annotation
    import _literature_retrieval_foundation
    import _retrieval_strategy
    import _llm
    import _literature_search
    import _literature_scoring
    import _literature_graph
    import _literature_import
    import _research_graph
    import _gap_evidence_graph
    import _gap_detectors
    import _gap_detection
    import _socrates_type_review
    import _proposal_contracts
    import _proposal_brief
    import _proposal_writer
    import _proposal_audit
    import _proposal_export
    import _proposal_report
    import _gap_source_role
    import _hypothesis
    import _research_report
    import _socrates
    import _verification
    import _debate
    import _supplement
    import _pipeline
