import json
import hashlib
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pytest
import torch


SURVEY_ROOT = Path(__file__).resolve().parents[1] / "src" / "agents" / "survey_agent"
sys.path.insert(0, str(SURVEY_ROOT))

from modules.survey_delivery import get_survey_checkpoint, resume_survey_delivery, run_survey_delivery
from utils.api_call import ChatAgent


OUTLINE = {
    "title": "Saved survey",
    "sections": [{"title": "Evidence", "subsections": [
        {"title": "First", "papers_to_use": ["W1"]},
        {"title": "Second", "papers_to_use": ["W1"]},
    ]}],
}
DRAFT = {
    "title": OUTLINE["title"], "outline": OUTLINE,
    "section_drafts": ["### Evidence\n\nCompleted prose <Paper ID: W1>."],
    "full_draft": "Saved survey\n\n### Evidence\n\nCompleted prose <Paper ID: W1>.",
}
STEPS = ["draft", "review", "section_quality", "consistency", "claim_support", "finalize", "export", "evaluation"]


class Generator:
    def __init__(self, directory, *, failure=None, resume_dir=""):
        self.config = SimpleNamespace(BasicInfo=SimpleNamespace(
            base_dir=str(directory), topic="Saved survey", survey_resume_dir=str(resume_dir),
            research_context={"project_id": "project-A"},
        ))
        self.logger = logging.getLogger(__name__)
        self.steps = []
        self.failure = failure
        self.survey_integrity_artifact = {"issues": []}
        self.survey_evidence_plan = {"saved_plan": True}
        graph = nx.DiGraph()
        graph.add_node("W1", title="Evidence paper")
        self.work_analyzer = SimpleNamespace(
            reference_graph=graph,
            work_collector=SimpleNamespace(reference_graph=graph, graph_paper_ids=["W1"]),
            paper_keynote_cache={hashlib.md5(b"W1").hexdigest(): {"keynote": "Previously read evidence"}},
        )
        self.database = SimpleNamespace(
            valid_paper_ids={"W1"},
            emb_dict={"ids": ["W1"], "embs": torch.tensor([[0.1, 0.2]])},
            title_emb_dict={"ids": ["W1"], "embs": torch.tensor([[0.3, 0.4]])},
        )

    def step(self, name):
        self.steps.append(name)
        if name == self.failure:
            raise ValueError(f"injected {name} failure")

    def draft_survey(self, *_args):
        self.step("draft")
        return dict(DRAFT)

    def review_and_revise_survey_in_parts(self, draft, *_args):
        assert (Path(self.config.BasicInfo.base_dir) / "draft.json").is_file()
        assert (Path(self.config.BasicInfo.base_dir) / "draft.md").read_text() == DRAFT["full_draft"]
        self.step("review")
        return draft

    def _evidence_bounded_writing_enabled(self):
        return True

    def _improve_evidence_bounded_sections(self, draft):
        self.step("section_quality")
        return draft

    def _consolidate_evidence_bounded_draft(self, draft):
        self.step("consistency")
        return draft

    def _repair_final_claim_support(self, draft):
        self.step("claim_support")
        return draft

    def _finalize_evidence_bounded_draft(self, draft):
        self.step("finalize")
        return draft["full_draft"] + "\n\nReferences:\n1. Evidence paper", ["W1"]

    def save_survey(self, text, references):
        self.step("export")
        path = Path(self.config.BasicInfo.base_dir) / "survey.md"
        path.write_text(text, encoding="utf-8")
        return {"survey_markdown_path": str(path)}

    def evaluate(self, text, references):
        self.step("evaluation")
        assert "Completed prose" in text
        assert references == ["W1"]
        return {"score": 8}, {"score": "Grounded"}


def deliver(generator):
    return run_survey_delivery(generator, generator, ["saved analysis"], "saved synthesis", OUTLINE,
                               code_report="saved code", env_report="saved environment")


@pytest.mark.parametrize("failed_step", STEPS[1:])
def test_failed_delivery_retains_draft_and_resumes_only_pending_steps(tmp_path, failed_step):
    first = Generator(tmp_path, failure=failed_step)
    result, _reason = deliver(first)
    assert result == {"survey_status": "requires_review"}
    draft = json.loads((tmp_path / "survey_draft.json").read_text())
    assert draft["full_draft"] == DRAFT["full_draft"]
    assert draft["survey_status"] == "requires_review"
    assert failed_step in draft["unresolved_issues"][0]
    markdown = (tmp_path / "survey_draft.md").read_text()
    assert "待复核" in markdown and "Completed prose" in markdown and "未解决的问题" in markdown
    if STEPS.index(failed_step) < STEPS.index("export"):
        assert not (tmp_path / "survey.md").exists()

    resumed = Generator(tmp_path)
    resumed.database.title_emb_dict = None
    resumed.work_analyzer.work_collector.graph_paper_ids = []
    result, _reason = resume_survey_delivery(resumed, resumed)
    assert result == {"score": 8}
    assert resumed.steps == STEPS[STEPS.index(failed_step):]
    assert resumed.database.title_emb_dict["ids"] == ["W1"]
    assert torch.equal(resumed.database.title_emb_dict["embs"], torch.tensor([[0.3, 0.4]]))
    assert resumed.work_analyzer.work_collector.graph_paper_ids == ["W1"]
    assert resumed.work_analyzer.reference_graph.nodes["W1"]["title"] == "Evidence paper"
    assert json.loads((tmp_path / "survey_status.json").read_text())["survey_status"] == "completed"
    assert json.loads((tmp_path / "survey_draft.json").read_text())["unresolved_issues"] == []


def test_resume_at_main_entry_skips_collection_and_analysis(tmp_path):
    from scripts.run_deep_survey import run_pipeline

    assert deliver(Generator(tmp_path, failure="export"))[0]["survey_status"] == "requires_review"
    resumed = Generator(tmp_path)
    result, _reason = run_pipeline(resumed.config, None, None, None, resumed, resumed, None, None, None)
    assert result == {"score": 8}
    assert resumed.steps == ["export", "evaluation"]


def test_cross_attempt_resume_republishes_final_text_without_rewriting(tmp_path):
    previous = tmp_path / "attempt-001"
    current = tmp_path / "attempt-002"
    assert deliver(Generator(previous, failure="evaluation"))[0]["survey_status"] == "requires_review"
    (previous / "survey_retrieval_manifest.json").write_text('{"papers":[{"paper_id":"W1"}]}')
    resumed = Generator(current, resume_dir=previous)
    assert resume_survey_delivery(resumed, resumed)[0] == {"score": 8}
    assert resumed.steps == ["export", "evaluation"]
    assert (current / "survey.md").read_bytes() == (previous / "survey.md").read_bytes()
    assert (current / "draft.md").read_text() == DRAFT["full_draft"]
    assert (current / "survey_retrieval_manifest.json").read_bytes() == (previous / "survey_retrieval_manifest.json").read_bytes()
    again = Generator(current, resume_dir=previous)
    assert resume_survey_delivery(again, again)[0] == {"score": 8}
    assert again.steps == []


def test_missing_export_is_recreated_without_rewriting_or_reevaluation(tmp_path):
    assert deliver(Generator(tmp_path))[0] == {"score": 8}
    (tmp_path / "survey.md").unlink()
    resumed = Generator(tmp_path)
    assert resume_survey_delivery(resumed, resumed)[0] == {"score": 8}
    assert resumed.steps == ["export"]


def test_resume_restores_reading_and_multimodal_metadata_without_external_requests(tmp_path):
    from modules.work_analyzer import WorkAnalyzer
    from modules.work_collector import WorkCollector

    first = Generator(tmp_path, failure="review")
    first.work_analyzer.work_collector.data_anchored_subhypothesis_artifact = {"subhypotheses": ["SH-local"]}
    deliver(first)
    second = Generator(tmp_path)
    second.work_analyzer.paper_keynote_cache = {}
    assert resume_survey_delivery(second, second)[0] == {"score": 8}
    assert WorkAnalyzer.get_paper_keynote(second.work_analyzer, "W1") == "Previously read evidence"
    collector = second.work_analyzer.work_collector
    assert WorkCollector.get_paper_title_abstract(collector, "W1") == ("Evidence paper", "")
    assert collector.data_anchored_subhypothesis_artifact == {"subhypotheses": ["SH-local"]}


def test_inputs_and_corrupted_checkpoint_never_overwrite_saved_draft(tmp_path):
    deliver(Generator(tmp_path, failure="review"))
    saved = (tmp_path / "survey_draft.md").read_bytes()
    changed = Generator(tmp_path)
    changed.config.BasicInfo.research_context = {"project_id": "different project"}
    with pytest.raises(ValueError, match="inputs changed"):
        resume_survey_delivery(changed, changed)
    pointer = tmp_path / "checkpoints" / "survey_checkpoint.json"
    pointer.write_text("{truncated", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        resume_survey_delivery(Generator(tmp_path), Generator(tmp_path))
    assert (tmp_path / "survey_draft.md").read_bytes() == saved


def test_batch_checkpoint_keeps_response_before_another_request_interrupts(tmp_path):
    generator = Generator(tmp_path)
    checkpoint = get_survey_checkpoint(generator)
    checkpoint.begin([], "", OUTLINE)

    class InterruptedChat:
        def batch_remote_chat(self, prompts, on_result, **_kwargs):
            on_result(0, "First subsection already completed.")
            assert "First subsection already completed" in (tmp_path / "survey_draft.md").read_text()
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        checkpoint.batch(InterruptedChat(), "subsection", [0, 1], ["first", "second"])

    restored = get_survey_checkpoint(Generator(tmp_path))
    restored.restore()
    calls = []

    class RemainingChat:
        def batch_remote_chat(self, prompts, **_kwargs):
            calls.extend(prompts)
            return ["Second subsection completed after resume."]

    responses = restored.batch(RemainingChat(), "subsection", [0, 1], ["first", "second"])
    assert calls == ["second"]
    assert responses == ["First subsection already completed.", "Second subsection completed after resume."]


@pytest.mark.parametrize("token_budget", [None, 100])
def test_chat_batch_notifies_completion_while_other_request_waits(token_budget):
    callback = threading.Event()

    class Chat:
        batch_workers = 2
        config = SimpleNamespace(APIInfo=SimpleNamespace(batch_chat_timeout=2, low_flow_mode=False))
        logger = logging.getLogger(__name__)

        def _configure_token_admission(self, _budget):
            pass

        def estimate_tokens(self, _prompt):
            return 1

        def _token_admitted_remote_chat(self, index, **_kwargs):
            if index == 1:
                assert callback.wait(1), "The first result must be saved before the batch ends"
            return index, f"response-{index}"

    results = ChatAgent.batch_remote_chat(Chat(), ["first", "second"],
        max_in_flight_tokens=token_budget, on_result=lambda _index, _response: callback.set())
    assert results == ["response-0", "response-1"]


def test_nonthrowing_revision_failure_is_delivered_and_retried(tmp_path):
    first = Generator(tmp_path)

    def unresolved(draft):
        first.step("section_quality")
        first.survey_integrity_artifact["issues"].append({
            "kind": "quality", "reason": "citation whitelist mismatch", "resolution": "manual_review",
        })
        return draft

    first._improve_evidence_bounded_sections = unresolved
    assert deliver(first)[0] == {"survey_status": "requires_review"}
    assert first.steps == STEPS[:3]
    second = Generator(tmp_path)
    assert resume_survey_delivery(second, second)[0] == {"score": 8}
    assert second.steps == STEPS[2:]
    assert second.survey_integrity_artifact["issues"] == []


def test_failed_mutating_revision_keeps_last_saved_text(tmp_path):
    first = Generator(tmp_path)

    def destructive_revision(draft, *_args):
        draft["section_drafts"][0] = "broken replacement"
        draft["full_draft"] = "broken replacement"
        raise ValueError("repair failed")

    first.review_and_revise_survey_in_parts = destructive_revision
    assert deliver(first)[0] == {"survey_status": "requires_review"}
    saved = json.loads((tmp_path / "survey_draft.json").read_text())
    assert saved["full_draft"] == DRAFT["full_draft"]
    assert "broken replacement" not in (tmp_path / "survey_draft.md").read_text()


def _writing_generator(directory, chat):
    from test_survey_evidence_bounded_writing import _generator

    generator = _generator()
    generator.logger = logging.getLogger(__name__)
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(base_dir=str(directory), topic="Saved survey", debug=False, error_conservatism_mode=False),
        ModuleInfo=SimpleNamespace(SurveyGenerator=SimpleNamespace(
            include_other_relevant_papers_RAG=False, subsection_draft_max_retry=1,
            subsection_draft_temperature=0, section_draft_max_retry=1,
            section_draft_temperature=0, claim_trace_validation_enabled=False,
        )),
    )
    generator.chat_agent = chat
    generator.omit_error_preserve_retry_time = 0
    generator._survey_length_budget = lambda _outline=None: {
        "survey_target_words": 20, "survey_max_words": 300,
        "section_count": 1, "subsection_count": 2,
        "subsection_target_words": 1, "subsection_max_words": 100,
        "subsection_target_citations": 1, "subsection_max_citations": 2,
        "section_preamble_target_words": 1, "section_preamble_max_words": 100,
        "section_preamble_target_citations": 1, "section_preamble_max_citations": 2,
    }
    generator._bounded_writing_analysis = lambda *_args: "saved analysis"
    generator._bounded_writing_code_report = lambda *_args: ""
    generator.build_prompt_with_truncation = lambda **kwargs: (kwargs["params"]["title"], ["W1"])
    generator.validate_id_citation_draft = lambda text, *_args, **_kwargs: (bool(text), [], text)
    generator.review_and_revise_survey_in_parts = lambda draft, *_args: draft
    generator._improve_evidence_bounded_sections = lambda draft: draft
    generator._consolidate_evidence_bounded_draft = lambda draft: draft
    generator._repair_final_claim_support = lambda draft: draft
    generator._finalize_evidence_bounded_draft = lambda draft: (draft["full_draft"], ["W1"])
    generator.save_survey = lambda *_args: {}
    return generator


def test_real_drafting_resumes_missing_subsection_after_process_interrupt(tmp_path):
    class InterruptedChat:
        def batch_remote_chat(self, prompts, on_result, **_kwargs):
            assert [prompt.split("The previous draft", 1)[0] for prompt in prompts] == ["First", "Second"]
            on_result(0, "First accepted evidence <Paper ID: W1>.")
            raise KeyboardInterrupt()

    first = _writing_generator(tmp_path, InterruptedChat())
    with pytest.raises(KeyboardInterrupt):
        run_survey_delivery(first, None, [], "", OUTLINE)
    assert "First accepted evidence" in (tmp_path / "survey_draft.md").read_text()
    calls = []

    class RemainingChat:
        def batch_remote_chat(self, prompts, **kwargs):
            titles = [prompt.split("The previous draft", 1)[0] for prompt in prompts]
            calls.extend(titles)
            return [f"{title} resumed evidence <Paper ID: W1>." for title in titles]

    second = _writing_generator(tmp_path, RemainingChat())
    judge = SimpleNamespace(evaluate=lambda *_args: ({"score": 8}, {}))
    assert resume_survey_delivery(second, judge)[0] == {"score": 8}
    assert calls == ["Second", "Evidence"]
    saved = json.loads((tmp_path / "draft.json").read_text())
    assert "First accepted evidence" in saved["full_draft"]
    assert "Second resumed evidence" in saved["full_draft"]
    assert saved["full_draft"] == (tmp_path / "draft.md").read_text()


def test_failed_trace_repair_reuses_all_prose_and_only_repairs_pending_metadata(tmp_path):
    def claims(text):
        return [{
            "claim_text": text, "sub_hypothesis_ids": ["SH1"],
            "claim_mode": "EVIDENCE_BACKED_SYNTHESIS", "limitation_slots": [],
            "evidence_paths": [{"sub_hypothesis_id": "SH1", "slot_name": "direct_observation",
                                "paper_id": "W1", "support_kind": "DIRECT_LEDGER_EVIDENCE",
                                "evidence_role": "DIRECT_OBSERVATION"}],
        }]

    class Chat:
        def __init__(self):
            self.prompts = []

        def batch_remote_chat(self, prompts, **_kwargs):
            self.prompts.extend(prompts)
            return [prompt.split("The previous draft", 1)[0] + " observation <Paper ID: W1>." for prompt in prompts]

    first = _writing_generator(tmp_path, Chat())
    first.config.ModuleInfo.SurveyGenerator.claim_trace_validation_enabled = True

    def failing_repair(records, **_kwargs):
        return {0: claims(records[0]["visible_draft"])}, {1: ["injected metadata failure"]}

    first._repair_claim_traces = failing_repair
    assert run_survey_delivery(first, None, [], "", OUTLINE)[0] == {"survey_status": "requires_review"}
    assert "First observation" in (tmp_path / "survey_draft.md").read_text()
    assert "Second observation" in (tmp_path / "survey_draft.md").read_text()
    second = _writing_generator(tmp_path, Chat())
    second.config.ModuleInfo.SurveyGenerator.claim_trace_validation_enabled = True
    repairs = []

    def repair(records, *, stage):
        repairs.append((stage, [record["draft_index"] for record in records]))
        return {record["draft_index"]: claims(record["visible_draft"]) for record in records}, {}

    second._repair_claim_traces = repair
    judge = SimpleNamespace(evaluate=lambda *_args: ({"score": 8}, {}))
    assert resume_survey_delivery(second, judge)[0] == {"score": 8}
    assert len(second.chat_agent.prompts) == 1
    assert second.chat_agent.prompts[0].startswith("Evidence")
    assert repairs == [("subsection", [1]), ("section", [0])]


def test_batch_topics_keep_separate_drafts_and_failed_steps(tmp_path):
    from modules.survey_delivery import survey_checkpoint_pending

    first = Generator(tmp_path)
    assert resume_survey_delivery(first, first, isolate_topic=True) is None
    checkpoint = first._survey_checkpoint
    checkpoint.begin([], "", OUTLINE)
    checkpoint.save_draft(DRAFT, initial=True)
    checkpoint.failed(ValueError("injected"))
    assert survey_checkpoint_pending(first.config, first.config.BasicInfo.topic)
    second = Generator(tmp_path)
    second.config.BasicInfo.topic = "Other research topic"
    assert resume_survey_delivery(second, second, isolate_topic=True) is None
    assert first._survey_checkpoint.base_dir != second._survey_checkpoint.base_dir
    assert not survey_checkpoint_pending(second.config, second.config.BasicInfo.topic)
    assert (first._survey_checkpoint.base_dir / "draft.md").is_file()


def test_quality_resume_only_reviews_the_failed_section(tmp_path):
    from test_survey_evidence_bounded_writing import _quality_draft, _quality_generator

    text = "### Evidence\n\nThe measurement supports a cautious conclusion <Paper ID: W1>."
    draft = _quality_draft(text)
    draft["outline"]["sections"].append({"title": "Second", "papers_to_use": ["W1"], "subsections": []})
    draft["section_drafts"].append(text.replace("### Evidence", "### Second"))
    draft["full_draft"] = draft["title"] + "\n\n" + "\n\n".join(draft["section_drafts"])
    reviews = []

    def quality_generator(fail_second):
        generator = _quality_generator([])
        generator.config.BasicInfo.base_dir = str(tmp_path)
        generator.draft_survey = lambda *_args: draft
        generator._consolidate_evidence_bounded_draft = lambda value: value
        generator._repair_final_claim_support = lambda value: value
        generator._finalize_evidence_bounded_draft = lambda value: (value["full_draft"], ["W1"])
        generator.save_survey = lambda *_args: {}

        def review(**kwargs):
            title = kwargs["section_outline"]["title"]
            reviews.append(title)
            if fail_second and title == "Second":
                return None
            return {"scores": {"clarity": 9}, "suggestions": [], "target_excerpts": []}

        generator._review_evidence_bounded_section_quality = review
        return generator

    judge = SimpleNamespace(evaluate=lambda *_args: ({"score": 8}, {}))
    first = quality_generator(True)
    assert run_survey_delivery(first, judge, [], "", draft["outline"])[0] == {"survey_status": "requires_review"}
    assert reviews == ["Evidence", "Second"]
    reviews.clear()
    second = quality_generator(False)
    assert resume_survey_delivery(second, judge)[0] == {"score": 8}
    assert reviews == ["Second"]


def test_quality_checkpoint_never_replaces_saved_text_with_over_budget_revision(tmp_path):
    from test_survey_evidence_bounded_writing import _quality_draft, _quality_generator

    generator = _quality_generator([])
    generator.config.BasicInfo.base_dir = str(tmp_path)
    settings = generator.config.ModuleInfo.SurveyGenerator
    settings.survey_target_words = 40
    settings.survey_max_words = 50
    original = "### Evidence\n\nThe observation supports a conclusion <Paper ID: W1>."
    draft = _quality_draft(original)
    draft["outline"]["sections"].append({"title": "Second", "papers_to_use": ["W1"]})
    draft["section_drafts"].append(original.replace("Evidence", "Second"))
    draft["full_draft"] = draft["title"] + "\n\n" + "\n\n".join(draft["section_drafts"])
    generator.draft_survey = lambda *_args: draft
    generator._review_evidence_bounded_section_quality = lambda **kwargs: {
        "scores": {"clarity": 9 if len(kwargs["section_text"].split()) >= 25 else 7},
        "suggestions": ["clarify"], "target_excerpts": ["The observation"],
    }
    generator._revise_evidence_bounded_section_quality = lambda **kwargs: (
        "### " + kwargs["section_outline"]["title"] + "\n\n" + "detail " * 20 + "<Paper ID: W1>."
    )
    checkpoint = get_survey_checkpoint(generator)
    save = checkpoint.save_draft

    def save_with_budget_check(value, **kwargs):
        assert len(value["full_draft"].split()) <= 50
        save(value, **kwargs)

    checkpoint.save_draft = save_with_budget_check
    result, _reason = run_survey_delivery(generator, None, [], "", draft["outline"])
    assert result == {"survey_status": "requires_review"}
    assert "word budget" in (tmp_path / "survey_draft.md").read_text()
    assert "1" not in checkpoint.state["quality_sections"]


def test_running_survey_draft_is_available_in_web_artifacts(tmp_path):
    from src.pipeline.science_run import initialize_science_run
    from src.webapp.artifact_service import artifact_index

    config = tmp_path / "config.yaml"
    config.write_text("{}")
    paths, _metadata, state = initialize_science_run(
        output_root=tmp_path / "runs", topic="Saved survey", config_path=config,
        immutable_options={}, run_id="draft-recovery",
    )
    attempt = paths.run_dir / "survey" / "attempt-001"
    attempt.mkdir(parents=True)
    (attempt / "survey_draft.md").write_text("Already saved section")
    (attempt / "private-runtime.json").write_text("hidden runtime")
    outputs = artifact_index(paths, state)
    assert outputs["survey:draft:attempt-001/survey_draft.md"] == (attempt / "survey_draft.md").resolve()
    assert (attempt / "private-runtime.json").resolve() not in outputs.values()


def test_preset_rerun_selects_matching_pending_run_and_explicit_run_starts_fresh(tmp_path, monkeypatch):
    from omegaconf import OmegaConf
    from utils import config_utils

    output_root = tmp_path / "outputs"
    defaults = tmp_path / "defaults.yaml"
    OmegaConf.save(OmegaConf.create({"survey": {"BasicInfo": {
        "topic": "Saved survey", "base_dir": str(output_root),
        "save_path": "", "save_json_path": "", "survey_run_id": "",
    }}}), defaults)
    monkeypatch.setattr(config_utils, "resolve_runtime_config_path", lambda: defaults)
    first_config = config_utils.merge_with_default_survey_config(OmegaConf.create({}))
    generator = Generator(Path(first_config.BasicInfo.base_dir), failure="export")
    generator.config = first_config
    assert deliver(generator)[0] == {"survey_status": "requires_review"}
    second_config = config_utils.merge_with_default_survey_config(OmegaConf.create({}))
    assert second_config.BasicInfo.base_dir == first_config.BasicInfo.base_dir
    new_config = config_utils.merge_with_default_survey_config(OmegaConf.create({
        "BasicInfo": {"survey_run_id": "new-run"},
    }))
    assert Path(new_config.BasicInfo.base_dir) == output_root / "new-run"
    resumed = Generator(Path(second_config.BasicInfo.base_dir))
    resumed.config = second_config
    assert resume_survey_delivery(resumed, resumed)[0] == {"score": 8}
    third_config = config_utils.merge_with_default_survey_config(OmegaConf.create({}))
    assert third_config.BasicInfo.base_dir != first_config.BasicInfo.base_dir
