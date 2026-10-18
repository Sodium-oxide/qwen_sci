"""Durable survey drafts and resumable delivery stages."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from omegaconf import OmegaConf

from src.pipeline.science_run import atomic_write_json, atomic_write_text


_GENERATOR_STATE = (
    "survey_evidence_plan", "survey_claim_traceability_artifact",
    "survey_outline_artifact", "survey_integrity_artifact",
    "survey_multimodal_evidence", "_claim_audit_source_cache",
)
_BASIC_RUNTIME = (
    "research_context", "research_design_inventory", "subhypothesis_decomposition",
    "subhypothesis_retrieval", "fulltext_acquisition_by_paper",
)
_COLLECTOR_STATE = (
    "subhypothesis_retrieval_artifact", "subhypothesis_decomposition_artifact",
    "sh_graph_provenance_artifact", "data_anchored_subhypothesis_artifact",
    "fulltext_budget_plan", "graph_seed_expansion_modes", "_openalex_id_aliases",
)


def _plain(value):
    if OmegaConf.is_config(value):
        return _plain(OmegaConf.to_container(value, resolve=True))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, SimpleNamespace):
        return _plain(vars(value))
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _fingerprint(config):
    basic = config.BasicInfo
    inputs = {
        key: _plain(getattr(basic, key, None))
        for key in (
            "topic", "research_title", "research_objective", "research_brief",
            "research_context_path", "subhypothesis_decomposition_path",
            "research_context", "subhypothesis_decomposition",
            "declared_domain", "subhypotheses",
        )
    }
    for key in ("research_context_path", "subhypothesis_decomposition_path"):
        path = Path(str(inputs.get(key) or ""))
        if path.is_file():
            inputs[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    multimodal = _plain(getattr(config, "multimodal_evidence", {}))
    if isinstance(multimodal, dict):
        inputs["multimodal_input"] = multimodal.get("input_spec", {})
    inputs["ablation"] = _plain(getattr(config, "AblationInfo", {}))
    settings = getattr(getattr(config, "ModuleInfo", None), "SurveyGenerator", None)
    inputs["writing_contract"] = {
        key: _plain(getattr(settings, key, None)) for key in (
            "survey_target_words", "survey_max_words", "use_title_in_draft",
            "claim_trace_validation_enabled", "include_code_report",
        )
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class SurveyNeedsReview(RuntimeError):
    pass


class SurveyCheckpoint:
    def __init__(self, generator, *, directory=None):
        self.generator = generator
        basic = generator.config.BasicInfo
        base = str(getattr(basic, "base_dir", "") or "")
        self.base_dir = Path(directory or base).resolve() if directory or base else None
        self.directory = self.base_dir / "checkpoints" if self.base_dir else None
        self.identity = _fingerprint(generator.config)
        self.state = {
            "schema_version": "survey_checkpoint_v1", "input_fingerprint": self.identity,
            "topic": str(getattr(basic, "topic", "")), "units": {}, "completed": [],
            "failures": [], "review_issues": {},
        }
        resume = str(getattr(basic, "survey_resume_dir", "") or "")
        source = Path(resume).resolve() if resume else self.base_dir
        if self.directory is not None and (self.directory / "survey_checkpoint.json").is_file():
            source = self.base_dir
        if source is not None:
            pointer = source / "checkpoints" / "survey_checkpoint.json"
            if pointer.is_file():
                saved = json.loads(pointer.read_text(encoding="utf-8"))
                if saved.get("schema_version") != "survey_checkpoint_v1":
                    raise ValueError(f"Unsupported survey checkpoint: {pointer}")
                if saved.get("input_fingerprint") != self.identity:
                    raise ValueError("Survey checkpoint inputs changed; use a new output directory for a new survey")
                self.state = saved
                if source != self.base_dir:
                    self._import_runtime(source)
                    self.state.pop("export", None)
                    self.state["completed"] = [name for name in self.state["completed"] if name != "export"]
        self.current_step = "draft"

    def _import_runtime(self, source):
        self.directory.mkdir(parents=True, exist_ok=True)
        for name in ("runtime.json", "database.pt"):
            original = source / "checkpoints" / name
            if original.is_file():
                self._write_binary(self.directory / name, original.read_bytes())
        for name in (
            "survey_retrieval_manifest.json", "subhypothesis_retrieval.json",
            "subhypothesis_decomposition.json", "project_context.json",
            "survey_evidence_plan.json", "survey_outline.json", "sh_graph_provenance.json",
        ):
            original = source / name
            if original.is_file():
                self._write_binary(self.base_dir / name, original.read_bytes())
        for original in (source / "analysis").glob("*"):
            if original.is_file() and original.suffix in {".json", ".tex", ".md"}:
                self._write_binary(self.base_dir / "analysis" / original.name, original.read_bytes())

    @staticmethod
    def _write_binary(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def persist(self):
        if self.directory is not None:
            atomic_write_json(self.directory / "survey_checkpoint.json", _plain(self.state))

    def capture_generator(self):
        self.state["generator"] = {
            key: _plain(getattr(self.generator, key))
            for key in _GENERATOR_STATE if hasattr(self.generator, key)
        }

    def begin(self, intra_analysis_results, inter_analysis_results, outline, code_report=None, env_report=None):
        if "context" in self.state:
            return
        self.state["context"] = _plain({
            "intra_analysis_results": intra_analysis_results,
            "inter_analysis_results": inter_analysis_results, "outline": outline,
            "code_report": code_report, "env_report": env_report,
        })
        self.capture_generator()
        if self.directory is not None:
            analyzer = getattr(self.generator, "work_analyzer", None)
            database = getattr(self.generator, "database", None)
            collector = getattr(analyzer, "work_collector", None)
            graph = getattr(collector, "reference_graph", None)
            if graph is None:
                graph = getattr(analyzer, "reference_graph", None)
            graph_data = None
            if graph is not None:
                import networkx as nx
                graph_data = nx.node_link_data(graph, edges="edges")
            runtime = {
                "basic": {key: _plain(getattr(self.generator.config.BasicInfo, key))
                          for key in _BASIC_RUNTIME if hasattr(self.generator.config.BasicInfo, key)},
                "graph": _plain(graph_data),
                "graph_paper_ids": list(getattr(collector, "graph_paper_ids", [])),
                "valid_paper_ids": list(getattr(database, "valid_paper_ids", [])),
                "collector": {key: _plain(getattr(collector, key)) for key in _COLLECTOR_STATE if hasattr(collector, key)},
            }
            runtime["keynotes"] = {}
            runtime["abstracts"] = {}
            keynote_cache = getattr(analyzer, "paper_keynote_cache", {})
            abstract_cache = getattr(collector, "paper_abstract_cache", {})
            for paper_id in set(runtime["graph_paper_ids"]) | set(runtime["valid_paper_ids"]):
                cache_key = hashlib.md5(str(paper_id).encode("utf-8")).hexdigest()
                keynote = keynote_cache.get(cache_key, {})
                if isinstance(keynote, Mapping) and keynote.get("keynote"):
                    runtime["keynotes"][paper_id] = _plain(keynote["keynote"])
                metadata = abstract_cache.get(cache_key, {})
                if not isinstance(metadata, Mapping) or not metadata.get("title"):
                    metadata = dict(graph.nodes.get(paper_id, {})) if graph is not None else {}
                if metadata.get("title"):
                    runtime["abstracts"][paper_id] = [metadata["title"], metadata.get("abstract", "")]
            atomic_write_json(self.directory / "runtime.json", runtime)
            if database is not None:
                import io
                import torch
                buffer = io.BytesIO()
                torch.save({key: getattr(database, key, None) for key in ("emb_dict", "title_emb_dict")}, buffer)
                self._write_binary(self.directory / "database.pt", buffer.getvalue())
        self.persist()

    def restore(self):
        if self.directory is not None:
            runtime = json.loads((self.directory / "runtime.json").read_text(encoding="utf-8"))
            for key, value in runtime["basic"].items():
                basic = self.generator.config.BasicInfo
                if OmegaConf.is_config(basic):
                    OmegaConf.update(basic, key, value, merge=False, force_add=True)
                else:
                    setattr(basic, key, value)
            analyzer = getattr(self.generator, "work_analyzer", None)
            collector = getattr(analyzer, "work_collector", None)
            if runtime.get("graph") is not None:
                import networkx as nx
                graph = nx.node_link_graph(runtime["graph"], edges="edges")
                if collector is not None:
                    collector.reference_graph = graph
                if analyzer is not None:
                    analyzer.reference_graph = graph
            if collector is not None:
                collector.graph_paper_ids = runtime["graph_paper_ids"]
                collector._survey_resume_abstracts = runtime.get("abstracts", {})
                for key, value in runtime.get("collector", {}).items():
                    setattr(collector, key, value)
            if analyzer is not None:
                analyzer._survey_resume_keynotes = runtime.get("keynotes", {})
            database = getattr(self.generator, "database", None)
            if database is not None:
                import torch
                indexes = torch.load(self.directory / "database.pt", map_location="cpu", weights_only=True)
                for key, value in indexes.items():
                    setattr(database, key, value)
                database.valid_paper_ids = set(runtime["valid_paper_ids"])
        for key, value in self.state.get("generator", {}).items():
            setattr(self.generator, key, copy.deepcopy(value))
        if "export" in self.state["completed"]:
            for record in self.state.get("export_files", []):
                path = Path(record["path"])
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                    self.state["completed"].remove("export")
                    break
        self.persist()
        self.write_drafts()

    def record_response(self, kind, index, response):
        if not isinstance(response, str) or not response.strip():
            return
        key = f"{kind}:{index}"
        unit = self.state["units"].setdefault(key, {})
        if not unit.get("accepted"):
            unit["response"] = response
            unit.pop("invalid", None)
        self.persist()
        self.write_drafts()

    def record_unit(self, kind, index, text, claims, *, accepted):
        unit = self.state["units"].setdefault(f"{kind}:{index}", {})
        unit.update(text=text, claims=_plain(claims), accepted=accepted)
        if not accepted:
            unit["trace_pending"] = True
        else:
            unit.pop("trace_pending", None)
        self.persist()
        self.write_drafts()

    def reject_response(self, kind, index):
        self.state["units"].setdefault(f"{kind}:{index}", {}).update(invalid=True, accepted=False)
        self.persist()

    def batch(self, chat_agent, kind, indices, prompts, **kwargs):
        responses = [None] * len(indices)
        missing = []
        for position, index in enumerate(indices):
            unit = self.state["units"].get(f"{kind}:{index}", {})
            if not unit.get("invalid"):
                responses[position] = unit.get("response")
            if responses[position] is None:
                missing.append(position)
        if missing:
            def on_result(position, response):
                self.record_response(kind, indices[missing[position]], response)
            generated = chat_agent.batch_remote_chat(
                [prompts[position] for position in missing], on_result=on_result, **kwargs
            )
            for missing_index, (position, response) in enumerate(zip(missing, generated)):
                responses[position] = response
                on_result(missing_index, response)
        return responses

    def partial_draft(self):
        context = self.state.get("context", {})
        outline = context.get("outline", {})
        sections = []
        subsection_index = 0
        for section_index, section in enumerate(outline.get("sections", [])):
            preamble = self.unit_text("section", section_index)
            parts = [preamble or f"### {section.get('title', '')}"]
            for subsection in section.get("subsections", []):
                text = self.unit_text("subsection", subsection_index)
                parts.append(f"#### {subsection.get('title', '')}\n\n{text}")
                subsection_index += 1
            sections.append("\n\n".join(parts))
        title = outline.get("title", self.state["topic"])
        return {"title": title, "outline": outline, "section_drafts": sections,
                "full_draft": str(title) + "\n\n" + "\n\n".join(sections)}

    def unit_text(self, kind, index):
        unit = self.state["units"].get(f"{kind}:{index}", {})
        if unit.get("text"):
            return unit["text"]
        response = unit.get("response", "")
        extractor = getattr(self.generator, "_extract_claim_trace", None)
        return extractor(response)[0] if response and extractor else response

    def write_drafts(self):
        if self.base_dir is None or "context" not in self.state:
            return
        draft = self.state.get("draft") or self.partial_draft()
        status = "requires_review" if self.state.get("failed_step") else (
            "completed" if "evaluation" in self.state["completed"] else "in_progress"
        )
        payload = {**draft, "survey_status": status, "unresolved_issues": self.state.get("unresolved_issues", [])}
        if self.state.get("final"):
            payload["paper"] = self.state["final"]["survey"]
            payload["references"] = self.state["final"]["references"]
        atomic_write_json(self.base_dir / "survey_draft.json", _plain(payload))
        text = payload.get("paper") or payload.get("full_draft", "")
        banner = "> 待复核草稿\n\n" if status == "requires_review" else "> 已自动保存的草稿\n\n"
        issues = payload["unresolved_issues"]
        appendix = "\n\n## 未解决的问题\n\n" + "\n".join(f"- {issue}" for issue in issues) if issues else ""
        atomic_write_text(self.base_dir / "survey_draft.md", banner + text + appendix)
        if "initial_draft" in self.state:
            atomic_write_json(self.base_dir / "draft.json", self.state["initial_draft"])
            atomic_write_text(self.base_dir / "draft.md", self.state["initial_draft"]["full_draft"])

    def save_draft(self, draft, *, initial=False):
        self.state["draft"] = _plain(copy.deepcopy(draft))
        if initial and "initial_draft" not in self.state:
            self.state["initial_draft"] = copy.deepcopy(self.state["draft"])
        self.capture_generator()
        self.persist()
        self.write_drafts()

    def draft_step(self, name, operation):
        self.current_step = name
        if name in self.state["completed"]:
            return self.state["draft"]
        integrity = getattr(self.generator, "survey_integrity_artifact", {})
        prior_issues = self.state["review_issues"].get(name, [])
        if prior_issues:
            integrity["issues"] = [issue for issue in integrity.get("issues", []) if issue not in prior_issues]
        before = copy.deepcopy(integrity.get("issues", []))
        draft = operation(copy.deepcopy(self.state["draft"]))
        self.save_draft(draft)
        integrity = getattr(self.generator, "survey_integrity_artifact", {})
        unresolved = [issue for issue in integrity.get("issues", [])
                      if issue.get("resolution") == "manual_review" and issue not in before]
        self.state["review_issues"][name] = unresolved
        if unresolved:
            raise SurveyNeedsReview(" | ".join(str(issue.get("reason") or issue) for issue in unresolved))
        self.state["completed"].append(name)
        self.persist()
        return draft

    def status(self, status, issues=()):
        if self.base_dir is None:
            return
        atomic_write_json(self.base_dir / "survey_status.json", {
            "schema_version": "survey_status_v1", "survey_status": status,
            "topic": self.state["topic"], "failed_step": self.state.get("failed_step"),
            "completed_steps": self.state["completed"], "unresolved_issues": list(issues),
            "reason": " | ".join(issues), "draft_json": "survey_draft.json",
            "draft_markdown": "survey_draft.md", "checkpoint": "checkpoints/survey_checkpoint.json",
        })

    def failed(self, error):
        reason = f"{self.current_step}: {type(error).__name__}: {error}"
        self.state.update(failed_step=self.current_step, unresolved_issues=[reason])
        self.state["failures"].append({"step": self.current_step, "error": reason})
        integrity = getattr(self.generator, "survey_integrity_artifact", {})
        self.state["review_issues"][self.current_step] = [
            issue for issue in integrity.get("issues", [])
            if issue.get("resolution") == "manual_review"
        ]
        self.capture_generator()
        self.persist()
        self.write_drafts()
        self.status("requires_review", [reason])
        self.generator.logger.error("Survey draft retained for review and resume: %s", reason)
        return {"survey_status": "requires_review"}, {"survey_status": reason}


def _batch_directory(config, topic=None):
    base = str(getattr(config.BasicInfo, "base_dir", "") or "")
    if not base:
        return None
    identity = {
        "topic": str(topic or config.BasicInfo.topic),
        "model": str(getattr(getattr(config, "APIInfo", None), "llm_model_name", "")),
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    return Path(base).resolve() / "survey_drafts" / key


def find_pending_survey_checkpoint(config, output_root):
    identity = _fingerprint(config)
    candidates = []
    for path in Path(output_root).glob("*/checkpoints/survey_checkpoint.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if (state.get("schema_version") == "survey_checkpoint_v1"
                    and state.get("input_fingerprint") == identity and state.get("context")
                    and ("evaluation" not in state.get("completed", []) or state.get("failed_step"))):
                candidates.append((path.stat().st_mtime_ns, path.parent.parent))
        except (OSError, ValueError, AttributeError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def survey_checkpoint_pending(config, topic):
    directory = _batch_directory(config, topic)
    path = directory / "checkpoints" / "survey_checkpoint.json" if directory is not None else None
    if path is None or not path.is_file():
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return "evaluation" not in state.get("completed", []) or bool(state.get("failed_step"))
    except (OSError, ValueError):
        return True


def get_survey_checkpoint(generator, *, isolate_topic=False):
    checkpoint = getattr(generator, "_survey_checkpoint", None)
    if checkpoint is None:
        directory = _batch_directory(generator.config) if isolate_topic else None
        checkpoint = SurveyCheckpoint(generator, directory=directory)
        generator._survey_checkpoint = checkpoint
    return checkpoint


def resume_survey_delivery(generator, judge, *, isolate_topic=False):
    checkpoint = get_survey_checkpoint(generator, isolate_topic=isolate_topic)
    if "context" not in checkpoint.state:
        return None
    generator.logger.info("Resuming saved survey; completed steps: %s", checkpoint.state["completed"])
    checkpoint.restore()
    return run_survey_delivery(generator, judge, **checkpoint.state["context"])


def run_survey_delivery(generator, judge, intra_analysis_results, inter_analysis_results,
                        outline, code_report=None, env_report=None, draft=None):
    checkpoint = get_survey_checkpoint(generator)
    checkpoint.begin(intra_analysis_results, inter_analysis_results, outline, code_report, env_report)
    try:
        checkpoint.current_step = "draft"
        if "draft" not in checkpoint.state["completed"]:
            draft = draft if draft is not None else generator.draft_survey(
                intra_analysis_results, inter_analysis_results, outline, code_report
            )
            checkpoint.save_draft(draft, initial=True)
            checkpoint.state["completed"].append("draft")
            checkpoint.persist()
        checkpoint.draft_step("review", lambda value: generator.review_and_revise_survey_in_parts(
            value, outline, code_report, env_report
        ))
        if generator._evidence_bounded_writing_enabled():
            for name, operation in (
                ("section_quality", generator._improve_evidence_bounded_sections),
                ("consistency", generator._consolidate_evidence_bounded_draft),
                ("claim_support", generator._repair_final_claim_support),
            ):
                checkpoint.draft_step(name, operation)
        checkpoint.current_step = "finalize"
        if "finalize" not in checkpoint.state["completed"]:
            last_draft = copy.deepcopy(checkpoint.state["draft"])
            if generator._evidence_bounded_writing_enabled():
                survey, references = generator._finalize_evidence_bounded_draft(last_draft)
            else:
                survey, references = generator.refine_draft(last_draft, code_report, env_report)
            checkpoint.state["final"] = {"survey": survey, "references": references}
            checkpoint.capture_generator()
            checkpoint.state["completed"].append("finalize")
            checkpoint.persist()
            checkpoint.write_drafts()
        final = checkpoint.state["final"]
        checkpoint.current_step = "export"
        if "export" not in checkpoint.state["completed"]:
            artifacts = generator.save_survey(final["survey"], final["references"])
            checkpoint.state["export"] = _plain(artifacts or {})
            checkpoint.state["export_files"] = []
            for value in (artifacts or {}).values():
                if not isinstance(value, (str, Path)):
                    continue
                path = Path(value)
                if path.is_file():
                    checkpoint.state["export_files"].append({
                        "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    })
            checkpoint.capture_generator()
            checkpoint.state["completed"].append("export")
            checkpoint.persist()
        checkpoint.current_step = "evaluation"
        if "evaluation" not in checkpoint.state["completed"]:
            checkpoint.state["evaluation"] = _plain(judge.evaluate(final["survey"], final["references"]))
            checkpoint.state["completed"].append("evaluation")
            checkpoint.persist()
        checkpoint.state.pop("failed_step", None)
        checkpoint.state["unresolved_issues"] = []
        checkpoint.persist()
        checkpoint.write_drafts()
        checkpoint.status("completed")
        return tuple(checkpoint.state["evaluation"])
    except Exception as error:
        return checkpoint.failed(error)
    except BaseException as error:
        checkpoint.failed(error)
        raise
