"""Academic language-polishing Job service with invariant validation."""

from __future__ import annotations

import hashlib

from src.llm.json_call import build_web_json_llm_call, call_required_json

from .document_segments import segment_text, validate_revision_segments
from .document_contracts import DocumentBlock, document_source_map
from .feature_contracts import PolishOutput
from .feature_job_service import FeatureJobError, FeatureJobService
from .feature_schemas import PolishJobCreate
from .job_artifacts import publish_json_artifact, read_job_manifest
from .jobs.models import JobExecutionResult
from .jobs.runner import JobContext
from .worker_support import checkpoint_value, revision_feedback, revision_request, source_text
from .prompts.fragments import apply_rules, compile_rules


class PolishService(FeatureJobService):
    kind = "polish"

    def create(self, request: PolishJobCreate):
        request_payload = request.model_dump(mode="json")
        request, preferences = self.prepare_request(request)
        prompt = self.resolve_prompt(
            request.prompt_profile,
            axes={
                "paper_type": request.paper_type,
                "language": request.target_language,
                "journal": request.target_journal,
            },
        )
        model_name, provider_name = self.resolve_model(prompt, request.model_name)
        input_manifest: dict[str, object] = {
            "source_language": request.source_language,
            "target_language": request.target_language,
            "paper_type": request.paper_type,
            "section": list(request.section),
            "target_journal": request.target_journal,
            "style_profile": request.style_profile,
            "preserve_terms": list(request.preserve_terms),
            "citation_style": request.citation_style,
            "output_formats": request.output_formats,
            "preferences_snapshot": preferences,
            "prompt_rules": compile_rules(self.kind, request.model_dump(mode="json")),
        }
        if request.text is not None:
            input_manifest["text"] = request.text
        else:
            records = self.validate_files([str(request.input_file_id)], project_id=request.project_id)
            input_manifest["files"] = records
        return self.create_job(
            request_payload=request_payload,
            input_manifest=input_manifest,
            prompt=prompt,
            model_name=model_name,
            provider_name=provider_name,
            idempotency_key=request.idempotency_key,
            project_id=request.project_id, run_id=request.run_id,
        )

    def run_job(self, context: JobContext) -> JobExecutionResult:
        manifest = self.read_manifest(context)
        input_data = manifest.get("input")
        if not isinstance(input_data, dict):
            raise FeatureJobError("Polish input manifest has no input object.")
        text = source_text(self.file_service, input_data)
        if not text.strip():
            raise FeatureJobError("Polish input text is empty.")
        if len(text) > int(self.config.get("polish", {}).get("max_input_chars", 200_000)):
            raise FeatureJobError("Polish input exceeds the configured character limit.")

        segments = segment_text(text)
        if len(segments) > int(self.config.get("polish", {}).get("max_segments", 2000)):
            raise FeatureJobError("Polish input exceeds the configured segment limit.")
        context.checkpoint(progress=15, current_step="segmenting_document")
        prompt = self.resolve_prompt(
            str(context.job.prompt_id or "polish-generic"),
            prompt_version=context.job.prompt_version, prompt_hash=context.job.prompt_hash,
        )
        revisions = []
        global_notes = []
        revision = revision_request(context)
        retained = revision.get("previous_result", {}) if revision.get("scope") == "segments" else {}
        previous_segments = {item["segment_id"]: item for item in retained.get("segments", [])}
        global_notes.extend(retained.get("global_notes", []))
        for ordinal, segment in enumerate(segments):
            context.checkpoint(progress=15 + int(60 * ordinal / len(segments)), current_step="polishing_segment")
            if previous_segments and segment.segment_id not in revision.get("unit_ids", []):
                if segment.segment_id not in previous_segments:
                    raise FeatureJobError("The retained revision does not match the document segments.")
                revisions.append(previous_segments[segment.segment_id])
                continue
            if segment.kind in {"code", "table"}:
                revisions.append({
                    "segment_id": segment.segment_id, "original": segment.text, "revised": segment.text,
                    "rationale": "Structured content preserved verbatim.", "risk": "low",
                    "preserved_entities": [], "unresolved_items": [],
                })
                continue
            if len(segment.text) > 20_000:
                raise FeatureJobError("Split paragraphs longer than 20000 characters before polishing.")
            def produce(segment=segment):
                messages = prompt.build_messages(
                    input_manifest={"segment_count": 1},
                    task_context={
                        "segments": [{"segment_id": segment.segment_id, "kind": segment.kind, "text": segment.text}],
                        "request": {key: value for key, value in input_data.items() if key not in {"text", "files"}},
                        "review_feedback": revision_feedback(context),
                    },
                )
                if input_data.get("prompt_rules"):
                    messages = apply_rules(messages, input_data["prompt_rules"])
                callback = build_web_json_llm_call(
                    config=self.config, model=context.job.model_name,
                    timeout=context.remaining_seconds(120),
                    temperature=manifest["model"].get("generation", {}).get("temperature", 0.2),
                    max_output_tokens=manifest["model"].get("generation", {}).get("max_output_tokens", 16384),
                )
                response = call_required_json(callback, messages, stage="web_polish")
                return PolishOutput.model_validate(response).model_dump()

            def validate(candidate, segment=segment):
                result = PolishOutput.model_validate(candidate)
                errors = validate_revision_segments([segment], [item.model_dump() for item in result.segments])
                for revision in result.segments:
                    for term in input_data.get("preserve_terms", []):
                        if segment.text.count(term) != revision.revised.count(term):
                            errors.append(f"{segment.segment_id}:preserved_term_changed")
                if errors:
                    raise FeatureJobError("Polish invariant validation failed: " + ", ".join(errors[:12]))

            candidate = checkpoint_value(context, {"segment": segment.segment_id}, produce, validate)
            candidate = PolishOutput.model_validate(candidate).model_dump()
            revisions.extend(candidate["segments"])
            global_notes.extend(candidate["global_notes"])
        errors = validate_revision_segments(segments, revisions)
        for segment, revision in zip(segments, revisions):
            for term in input_data.get("preserve_terms", []):
                if segment.text.count(term) != revision["revised"].count(term):
                    errors.append(f"{segment.segment_id}:preserved_term_changed")
        if errors:
            raise FeatureJobError(f"Polish invariant validation failed: {', '.join(errors[:12])}")
        parsed = {"schema_version": "polish_revision_v1", "segments": revisions, "global_notes": list(dict.fromkeys(global_notes))}
        context.checkpoint(progress=80, current_step="publishing_revision_set")
        artifact_id = publish_json_artifact(
            context,
            role="polish_revision_set",
            filename="polish_revisions.json",
            payload=parsed,
            provenance={
                "prompt_id": prompt.prompt_id,
                "prompt_version": prompt.prompt_version,
                "prompt_hash": prompt.prompt_hash,
                "model": context.job.model_name,
                "source_character_count": len(text),
            },
            source_file_ids=[str(item.get("file_id")) for item in input_data.get("files", []) if isinstance(item, dict) and item.get("file_id")],
            validator_status="WARN" if any(item["unresolved_items"] for item in revisions) else "PASS",
        )
        source_map_id = publish_json_artifact(
            context, role="document_source_map", filename="document_source_map.json",
            payload=document_source_map(
                [DocumentBlock(segment.segment_id, segment.text, segment.kind, segment.ordinal, start=segment.start, end=segment.end) for segment in segments],
                source_hashes={"text": hashlib.sha256(text.encode("utf-8")).hexdigest(), **{str(item["file_id"]): str(item["sha256"]) for item in input_data.get("files", [])}},
                parser="document_segments", parser_version="1.0.0",
                limitations=["DOCX export preserves text and headings; native equation objects and source formatting are unsupported."]
                if input_data.get("files", [{}])[0].get("original_name", "").endswith(".docx") else [],
            ), validator_status="PASS",
        )
        return JobExecutionResult(
            status="WAITING_FOR_REVIEW",
            output_artifact_ids=(artifact_id, source_map_id),
            progress=100,
            current_step="awaiting_segment_review",
        )
