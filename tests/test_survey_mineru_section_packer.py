import os
import sys

import pytest
from types import SimpleNamespace


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SURVEY_AGENT_ROOT = os.path.join(PROJECT_ROOT, "src", "agents", "survey_agent")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, SURVEY_AGENT_ROOT)

from utils.mineru_section_packer import (
    derive_effective_body_budget,
    pack_mineru_markdown_by_complete_sections,
    render_packet_outline,
)
from utils.utils import get_hash
from modules.work_analyzer import (
    FULLTEXT_READING_BYPASS_PAPER_IDS,
    WorkAnalyzer,
)
from modules.paper_graph_retriever import PaperGraphRetriever


def _count_characters(text: str) -> int:
    return len(text)


MINERU_FIXTURE = """# A MinerU Parsed Paper

Author One<sup>1</sup>

## ABSTRACT

The complete abstract.

## 1. Introduction

Introduction body with a display equation:
$$
E = mc^2
$$

## 1.1. Context

Context body.

```python
## Not a MinerU body section
```

## 2. Method

Method body.

## ACKNOWLEDGMENTS

Thanks to the reviewers.

## REFERENCES

[1] A complete bibliography entry.
"""


def test_mineru_sections_use_exact_level_two_boundaries_and_preserve_source():
    result = pack_mineru_markdown_by_complete_sections(
        MINERU_FIXTURE,
        max_body_tokens=10_000,
        count_tokens=_count_characters,
    )

    assert result.status == "single_packet"
    assert result.paper_title == "A MinerU Parsed Paper"
    assert [section.heading for section in result.sections] == [
        "ABSTRACT",
        "1. Introduction",
        "1.1. Context",
        "2. Method",
        "ACKNOWLEDGMENTS",
        "REFERENCES",
    ]
    assert result.sections[2].number == "1.1."
    assert result.sections[2].title == "Context"
    assert "## Not a MinerU body section" in result.sections[2].markdown
    assert "$$\nE = mc^2\n$$" in result.packets[0].markdown
    assert "## REFERENCES" not in result.packets[0].markdown
    assert result.excluded_headings == ("ACKNOWLEDGMENTS", "REFERENCES")


def test_packer_groups_only_complete_sections_in_source_order():
    markdown = """# Title

## 1. One
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
## 1.1. Two
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
## 2. Three
cccccccccccccccccccccccccccccc
"""
    result = pack_mineru_markdown_by_complete_sections(
        markdown,
        max_body_tokens=55,
        count_tokens=_count_characters,
    )

    assert result.status == "multi_packet"
    assert [packet.headings for packet in result.packets] == [
        ("1. One",),
        ("1.1. Two",),
        ("2. Three",),
    ]
    assert all(packet.body_token_count <= 55 for packet in result.packets)
    assert "## 1. One" in result.packets[0].markdown
    assert "## 1.1. Two" in result.packets[1].markdown
    assert "## 2. Three" in result.packets[2].markdown


def test_packer_never_token_slices_an_oversized_complete_section():
    markdown = """# Title

## 1. Oversized
abcdefghijklmnopqrstuvwxyz
"""
    result = pack_mineru_markdown_by_complete_sections(
        markdown,
        max_body_tokens=20,
        count_tokens=_count_characters,
    )

    assert result.status == "unsplittable_section"
    assert result.packets == ()
    assert result.unsplittable_section is not None
    assert result.unsplittable_section.heading == "1. Oversized"
    assert result.unsplittable_section.markdown.endswith("abcdefghijklmnopqrstuvwxyz\n")


def test_front_matter_is_metadata_when_including_it_would_break_a_section_budget():
    markdown = """# Title
xxxxxxxxxxxxxxxxxxxx
## 1. Complete
yyyyyyyyyyyyyyyyyyyyyyyyy
"""
    result = pack_mineru_markdown_by_complete_sections(
        markdown,
        max_body_tokens=45,
        count_tokens=_count_characters,
    )

    assert result.status == "single_packet"
    assert result.front_matter.startswith("# Title")
    assert result.packets[0].body_token_count <= 45
    assert result.packets[0].markdown.startswith("## 1. Complete")


def test_packet_outline_describes_omitted_complete_sections_only():
    result = pack_mineru_markdown_by_complete_sections(
        """# Title

## 1. One
one
## 2. Two
two
## REFERENCES
ref
""",
        max_body_tokens=25,
        count_tokens=_count_characters,
    )

    included, omitted = render_packet_outline(result, result.packets[0])
    assert "1. One" in included
    assert "2. Two" in omitted
    assert "REFERENCES" not in omitted


def test_no_level_two_sections_refuses_to_send_an_arbitrary_prefix():
    result = pack_mineru_markdown_by_complete_sections(
        "# Only a title\n\nA very long body without MinerU body headings.\n",
        max_body_tokens=10,
        count_tokens=_count_characters,
    )

    assert result.status == "no_sections"
    assert result.packets == ()


def test_effective_budget_caps_body_and_reserves_prompt_and_output():
    assert derive_effective_body_budget(
        configured_max_body_tokens=512_000,
        context_window_tokens=880_000,
        max_output_tokens=16_000,
        prompt_reserve_tokens=24_000,
    ) == 512_000
    assert derive_effective_body_budget(
        configured_max_body_tokens=860_000,
        context_window_tokens=1_000_000,
        max_output_tokens=16_000,
        prompt_reserve_tokens=24_000,
    ) == 512_000
    assert derive_effective_body_budget(
        configured_max_body_tokens=512_000,
        context_window_tokens=128_000,
        max_output_tokens=16_000,
        prompt_reserve_tokens=24_000,
    ) == 88_000

    with pytest.raises(ValueError, match="leaves no room"):
        derive_effective_body_budget(
            configured_max_body_tokens=512_000,
            context_window_tokens=20_000,
            max_output_tokens=16_000,
            prompt_reserve_tokens=4_000,
        )


def test_work_analyzer_synthesizes_multiple_complete_section_packets_without_prefix_truncation():
    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    class _ChatAgent:
        def __init__(self):
            self.calls = []

        def estimate_tokens(self, text):
            return len(text)

        def batch_remote_chat(self, prompts, **kwargs):
            self.calls.append((prompts, kwargs))
            if len(self.calls) == 1:
                return [
                    (
                        '{"source_sections":["packet"],'
                        '"claims":[{"claim":"complete",'
                        '"evidence":"complete section",'
                        '"source_section":"packet"}],'
                        '"methods":[],"results":[],"limitations":[],"unknowns":[]}'
                    )
                    for _ in prompts
                ]
            return ['{"paper_keynote":"synthesized from all complete packets"}']

    markdown = """# Long MinerU Paper

## 1. First
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
## 2. Second
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
## 3. Third
cccccccccccccccccccccccccccccc
"""
    work_config = SimpleNamespace(
        abstract_only_mode=False,
        paper_reading_max_retry=1,
        use_local_paper_graph_keynotes=False,
        abstract_when_full_text_fail=True,
        fulltext_section_packing_enabled=True,
        fulltext_section_max_tokens=60,
        fulltext_section_prompt_reserve_tokens=20,
        fulltext_section_max_output_tokens=20,
        fulltext_section_batch_worker=1,
        oversized_unsplittable_section_policy="abstract",
        paper_reading_temperature=0.0,
    )
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        APIInfo=SimpleNamespace(llm_max_context_length=5_000),
        ModuleInfo=SimpleNamespace(WorkAnalyzer=work_config),
    )
    analyzer.logger = _Logger()
    analyzer.chat_agent = _ChatAgent()
    analyzer.paper_keynote_cache = {}
    analyzer.paper_abstract_cache = {}
    analyzer.work_collector = SimpleNamespace(
        get_paper_raw_markdown=lambda _paper_id: markdown,
        add_papers_abstracts_in_cache=lambda _paper_ids: ["unused"],
    )

    assert analyzer.read_papers_and_write_keynotes(["W1"]) == []
    assert len(analyzer.chat_agent.calls) == 2
    section_prompts, section_kwargs = analyzer.chat_agent.calls[0]
    assert len(section_prompts) == 3
    assert section_kwargs["strict_input_budget"] is True
    assert all("Complete section text:" in prompt for prompt in section_prompts)
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in section_prompts[0]
    assert "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in section_prompts[1]
    assert "cccccccccccccccccccccccccccccc" in section_prompts[2]
    assert analyzer.paper_keynote_cache
    assert next(iter(analyzer.paper_keynote_cache.values()))["keynote"] == {
        "paper_keynote": "synthesized from all complete packets"
    }


def test_work_analyzer_does_not_retry_invalid_section_packet_and_uses_abstract_fallback():
    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    valid_packet_note = (
        '{"source_sections":["1. First"],'
        '"claims":[{"claim":"first claim","evidence":"first evidence",'
        '"source_section":"1. First"}],'
        '"methods":[],"results":[],"limitations":[],"unknowns":[]}'
    )

    class _ChatAgent:
        def __init__(self):
            self.calls = []

        def estimate_tokens(self, text):
            return len(text)

        def supports_response_format(self, response_format):
            return response_format == "json_object"

        def batch_remote_chat(self, prompts, **kwargs):
            self.calls.append((prompts, kwargs))
            assert len(self.calls) == 1
            assert len(prompts) == 2
            return [valid_packet_note, "I received the section and summarized it."]

    markdown = """# Long MinerU Paper

## 1. First
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
## 2. Second
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
"""
    work_config = SimpleNamespace(
        abstract_only_mode=False,
        paper_reading_max_retry=5,
        use_local_paper_graph_keynotes=False,
        abstract_when_full_text_fail=True,
        fulltext_section_packing_enabled=True,
        fulltext_section_max_tokens=80,
        fulltext_section_prompt_reserve_tokens=20,
        fulltext_section_max_output_tokens=20,
        fulltext_section_batch_worker=2,
        oversized_unsplittable_section_policy="abstract",
        paper_reading_temperature=0.0,
    )
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        APIInfo=SimpleNamespace(llm_max_context_length=5_000),
        ModuleInfo=SimpleNamespace(WorkAnalyzer=work_config),
    )
    analyzer.logger = _Logger()
    analyzer.chat_agent = _ChatAgent()
    analyzer.paper_keynote_cache = {}
    analyzer.paper_abstract_cache = {}
    abstract_calls = []

    def add_abstract(paper_ids):
        abstract_calls.append(list(paper_ids))
        analyzer.paper_abstract_cache[get_hash("W1")] = {
            "paper_id": "W1",
            "title": "Long MinerU Paper",
            "abstract": "A usable fallback abstract with sufficient detail.",
        }
        return []

    analyzer.work_collector = SimpleNamespace(
        get_paper_raw_markdown=lambda _paper_id: markdown,
        add_papers_abstracts_in_cache=add_abstract,
    )

    assert analyzer.read_papers_and_write_keynotes(["W1"]) == []
    assert len(analyzer.chat_agent.calls) == 1
    assert analyzer.chat_agent.calls[0][1]["response_format"] == "json_object"
    schema_prompt = analyzer.chat_agent.calls[0][0][0]
    assert '"source_sections"' in schema_prompt
    assert '"source_section"' in schema_prompt
    assert "Do not add fields." in schema_prompt
    assert abstract_calls == [["W1"]]
    failure = analyzer.paper_keynote_failure_records["W1"]
    assert failure["code"] == "section_response_not_json"
    assert failure["fallback_status"] == "abstract_used"
    assert failure["invalid_response_attempts"] == 1


def test_section_note_parser_does_not_misread_a_nested_list_from_truncated_json():
    # The generic extractor can recover the nested source_sections list after
    # the outer object is truncated.  Section packets require a top-level
    # object, so that response must go straight to fallback rather than be
    # reported misleadingly as a valid JSON list.
    truncated_response = '{"source_sections":["1. First"],"claims":['

    with pytest.raises(ValueError, match="complete JSON object"):
        WorkAnalyzer._extract_section_note_json_object(truncated_response)


@pytest.mark.parametrize("paper_id", sorted(FULLTEXT_READING_BYPASS_PAPER_IDS))
def test_explicit_fulltext_reading_bypass_uses_abstract_without_llm_or_markdown(paper_id):
    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    abstract = "A cached abstract used instead of an expensive full-text request."
    work_config = SimpleNamespace(
        abstract_only_mode=False,
        paper_reading_max_retry=1,
        use_local_paper_graph_keynotes=False,
        abstract_when_full_text_fail=True,
    )
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        APIInfo=SimpleNamespace(llm_max_context_length=5_000),
        ModuleInfo=SimpleNamespace(WorkAnalyzer=work_config),
    )
    analyzer.logger = _Logger()
    analyzer.chat_agent = SimpleNamespace(
        batch_remote_chat=lambda *_args, **_kwargs: pytest.fail(
            "the bypassed paper must not invoke the LLM"
        )
    )
    analyzer.paper_keynote_cache = {}
    analyzer.paper_abstract_cache = {}
    abstract_calls = []

    def add_abstract(paper_ids):
        abstract_calls.append(list(paper_ids))
        analyzer.paper_abstract_cache[get_hash(paper_id)] = {
            "paper_id": paper_id,
            "title": "Oversized Paper",
            "abstract": abstract,
        }
        return []

    analyzer.work_collector = SimpleNamespace(
        get_paper_raw_markdown=lambda *_args: pytest.fail(
            "the bypassed paper must not read full-text Markdown"
        ),
        add_papers_abstracts_in_cache=add_abstract,
        get_paper_title_abstract=lambda _paper_id: ("Oversized Paper", abstract),
    )

    assert FULLTEXT_READING_BYPASS_PAPER_IDS == frozenset(
        {"W2074305322", "W4225610241"}
    )
    assert analyzer.read_papers_and_write_keynotes([paper_id]) == []
    assert abstract_calls == [[paper_id]]
    assert analyzer.paper_keynote_failure_records[paper_id] == {
        "schema_version": "paper_keynote_failure_v1",
        "paper_id": paper_id,
        "status": "fallback_used",
        "code": "explicit_fulltext_reading_bypass",
        "reason": "explicit deep-reading bypass for oversized full text",
        "fallback_status": "abstract_used",
    }
    assert analyzer.get_paper_keynote(paper_id) == abstract


def test_missing_abstract_is_negative_cached_within_the_same_run():
    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    work_config = SimpleNamespace(
        abstract_only_mode=False,
        paper_reading_max_retry=5,
        use_local_paper_graph_keynotes=False,
        abstract_when_full_text_fail=True,
        fulltext_section_packing_enabled=True,
        fulltext_section_max_tokens=80,
        fulltext_section_prompt_reserve_tokens=20,
        fulltext_section_max_output_tokens=20,
        fulltext_section_batch_worker=1,
        oversized_unsplittable_section_policy="abstract",
        paper_reading_temperature=0.0,
    )
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(debug=False),
        APIInfo=SimpleNamespace(llm_max_context_length=5_000),
        ModuleInfo=SimpleNamespace(WorkAnalyzer=work_config),
    )
    analyzer.logger = _Logger()
    analyzer.chat_agent = SimpleNamespace(estimate_tokens=len)
    analyzer.paper_keynote_cache = {}
    analyzer.paper_abstract_cache = {}
    abstract_calls = []
    analyzer.work_collector = SimpleNamespace(
        get_paper_raw_markdown=lambda _paper_id: "# Title\n\nBody without MinerU sections.\n",
        add_papers_abstracts_in_cache=lambda paper_ids: abstract_calls.append(list(paper_ids)) or list(paper_ids),
    )

    paper_id = "W2074305323"
    assert analyzer.read_papers_and_write_keynotes([paper_id]) == [paper_id]
    assert analyzer.read_papers_and_write_keynotes([paper_id]) == [paper_id]
    assert abstract_calls == [[paper_id]]
    assert analyzer.paper_keynote_failure_records[paper_id]["status"] == "permanent_failure"
    assert analyzer.paper_keynote_failure_records[paper_id]["fallback_status"] == "abstract_unavailable"


def test_work_analyzer_repackages_full_sections_after_exact_prompt_preflight():
    class _Logger:
        def warning(self, *_args, **_kwargs):
            pass

    class _ChatAgent:
        def estimate_tokens(self, text):
            # Raw sections are measured by their length.  The first final
            # section-reading envelope is deliberately one token too large,
            # so the helper must move a whole section into the next packet.
            if "You are reading one packet of complete sections" in text:
                return 101 if "## 1. First" in text and "## 2. Second" in text else 90
            return len(text)

    markdown = """# Long MinerU Paper

## 1. First
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
## 2. Second
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
## 3. Third
cccccccccccccccccccccccccccccc
"""
    analyzer = object.__new__(WorkAnalyzer)
    analyzer.chat_agent = _ChatAgent()
    analyzer.logger = _Logger()

    packing, tasks, unsafe_section = analyzer._build_safe_fulltext_tasks(
        pid="W1",
        hash_id="hash",
        paper_markdown_text=markdown,
        body_budget=100,
        max_input_tokens=100,
    )

    assert unsafe_section is None
    assert packing.status == "multi_packet"
    assert len(tasks) == 2
    assert all(analyzer.chat_agent.estimate_tokens(task["prompt"]) <= 100 for task in tasks)
    assert "## 1. First" in tasks[0]["prompt"]
    assert "## 2. Second" not in tasks[0]["prompt"]
    assert "## 2. Second" in tasks[1]["prompt"]
    assert "## 3. Third" in tasks[1]["prompt"]


def test_work_analyzer_hierarchically_compacts_notes_before_final_synthesis():
    class _ChatAgent:
        def __init__(self):
            self.calls = []

        def estimate_tokens(self, text):
            return len(text)

        def batch_remote_chat(self, prompts, **kwargs):
            self.calls.append((prompts, kwargs))
            return ['{"summary":"compact complete-section evidence"}' for _ in prompts]

    analyzer = object.__new__(WorkAnalyzer)
    analyzer.config = SimpleNamespace(APIInfo=SimpleNamespace(llm_max_context_length=2_000))
    analyzer.chat_agent = _ChatAgent()

    keynote = analyzer._synthesize_complete_section_notes(
        paper_title="Long MinerU Paper",
        section_notes=[{"claim": "a" * 800}, {"claim": "b" * 800}, {"claim": "c" * 800}],
        temperature=0.0,
        max_output_tokens=20,
        workers=1,
    )

    assert keynote == {"summary": "compact complete-section evidence"}
    assert len(analyzer.chat_agent.calls) == 2
    first_level_prompts, first_level_kwargs = analyzer.chat_agent.calls[0]
    assert len(first_level_prompts) == 3
    assert first_level_kwargs["strict_input_budget"] is True
    assert all(len(prompt) <= 1_980 for prompt in first_level_prompts)
    assert all("only one subset of the paper" in prompt for prompt in first_level_prompts)
    assert all("not the full paper" in prompt for prompt in first_level_prompts)
    final_prompts, _ = analyzer.chat_agent.calls[1]
    assert len(final_prompts) == 1
    assert len(final_prompts[0]) <= 1_980
    assert "Produce one deep, structured paper keynote" in final_prompts[0]


def test_graph_repackages_complete_sections_after_exact_prompt_preflight():
    class _Logger:
        def warning(self, *_args, **_kwargs):
            pass

    class _ChatAgent:
        def estimate_tokens(self, text):
            if "You are a Senior Research Analyst" in text:
                return 141 if "## 1. First" in text and "## 2. Second" in text else 90
            return len(text)

    markdown = """# Long MinerU Paper

## 1. First
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
## 2. Second
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
## 3. Third
cccccccccccccccccccccccccccccc
"""
    work_config = SimpleNamespace(
        fulltext_section_packing_enabled=True,
        fulltext_section_max_tokens=120,
        fulltext_section_prompt_reserve_tokens=20,
        fulltext_section_max_output_tokens=20,
    )
    retriever = object.__new__(PaperGraphRetriever)
    retriever.config = SimpleNamespace(
        APIInfo=SimpleNamespace(llm_max_context_length=160),
        ModuleInfo=SimpleNamespace(WorkAnalyzer=work_config),
    )
    retriever.chat_agent = _ChatAgent()
    retriever.logger = _Logger()

    prompts, metadata = retriever._build_main_prompts(["W1"], [markdown])

    assert len(prompts) == 2
    assert len(metadata) == 2
    assert "## 1. First" in prompts[0]
    assert "## 2. Second" not in prompts[0]
    assert "## 2. Second" in prompts[1]
    assert "COMPLETE SECTIONS FROM THE PAPER" in prompts[0]
    assert all(retriever.chat_agent.estimate_tokens(prompt) <= 140 for prompt in prompts)


def test_graph_path_uses_the_same_complete_section_packets_and_merges_them():
    class _Logger:
        def warning(self, *_args, **_kwargs):
            pass

    markdown = """# Long MinerU Paper

## 1. First
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
## 2. Second
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
## 3. Third
cccccccccccccccccccccccccccccc
"""
    work_config = SimpleNamespace(
        fulltext_section_packing_enabled=True,
        fulltext_section_max_tokens=60,
        fulltext_section_prompt_reserve_tokens=20,
        fulltext_section_max_output_tokens=20,
    )
    retriever = object.__new__(PaperGraphRetriever)
    retriever.config = SimpleNamespace(
        APIInfo=SimpleNamespace(llm_max_context_length=50_000),
        ModuleInfo=SimpleNamespace(WorkAnalyzer=work_config),
    )
    retriever.chat_agent = SimpleNamespace(estimate_tokens=lambda text: len(text))
    retriever.logger = _Logger()

    prompts, metadata = retriever._build_main_prompts(["W1"], [markdown])

    assert len(prompts) == 3
    assert [item["packet_index"] for item in metadata] == [0, 1, 2]
    assert all("COMPLETE SECTIONS FROM THE PAPER" in prompt for prompt in prompts)
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in prompts[0]
    assert "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in prompts[1]
    assert "cccccccccccccccccccccccccccccc" in prompts[2]

    merged = retriever._merge_section_main_results(
        [
            {
                "node_id": "W1",
                "original_title": "Long MinerU Paper",
                "result": {
                    "metadata": {"title": "Long MinerU Paper"},
                    "core_contributions": [{"name": "Method A"}],
                    "limitations": [{"summary": "First limitation"}],
                },
            },
            {
                "node_id": "W1",
                "result": {
                    "metadata": {"structured_summary": {"result": "Result B"}},
                    "core_contributions": [{"name": "Method A"}],
                    "limitations": [{"summary": "Second limitation"}],
                },
            },
        ],
        ["W1"],
    )

    assert merged[0]["core_names"] == ["Method A"]
    assert merged[0]["result"]["metadata"]["structured_summary"] == {"result": "Result B"}
    assert [item["summary"] for item in merged[0]["result"]["limitations"]] == [
        "First limitation",
        "Second limitation",
    ]
