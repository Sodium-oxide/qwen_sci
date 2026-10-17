"""Source-grounded, checkpointed PDF translation with page-level provenance."""

from __future__ import annotations

from src.llm.json_call import build_web_json_llm_call, call_required_json

from .feature_contracts import TranslationOutput
from .document_contracts import DocumentBlock, document_source_map
from .feature_service_base import FeatureJobError, FeatureJobService
from .feature_schemas import TranslationJobCreate
from .job_artifacts import publish_json_artifact, publish_bytes_artifact
from .jobs import JobContext, JobExecutionResult
from .page_blocks import protect_block, restore_block
from .pdf_ingestion import parse_pdf_pages
from .worker_support import checkpoint_value, revision_feedback, revision_request
from .prompts.fragments import apply_rules, compile_rules


class TranslationService(FeatureJobService):
    kind = "translation"

    def create(self, request: TranslationJobCreate):
        request_payload = request.model_dump(mode="json")
        request, preferences = self.prepare_request(request)
        if request.mode == "image_page_translation":
            raise FeatureJobError(
                "Image page translation requires a reference-image editing backend that is not implemented.",
                code="CAPABILITY_UNAVAILABLE",
            )
        prompt = self.resolve_prompt(request.prompt_profile, axes={"language": request.target_language, "mode": request.mode})
        model, provider = self.resolve_model(prompt, request.model_name)
        records = self.validate_files([request.input_file_id], project_id=request.project_id)
        if records[0]["detected_type"] != "pdf":
            raise FeatureJobError("Translation input must be a verified PDF.")
        input_data = {key: value for key, value in request.model_dump(mode="json").items() if key not in {"input_file_id", "idempotency_key", "model_name", "prompt_profile"}}
        input_data["files"] = records
        input_data["preferences_snapshot"] = preferences
        input_data["prompt_rules"] = compile_rules(self.kind, request.model_dump(mode="json"))
        return self.create_job(
            request_payload=request_payload, input_manifest=input_data,
            prompt=prompt, model_name=model, provider_name=provider, idempotency_key=request.idempotency_key,
            project_id=request.project_id, run_id=request.run_id,
        )

    def run_job(self, context: JobContext) -> JobExecutionResult:
        manifest = self.read_manifest(context)
        data = manifest["input"]
        file_id = str(data["files"][0]["file_id"])
        path = self.file_service.content_path(file_id)
        settings = self.config.get("translation", {})
        if path.stat().st_size > int(settings.get("max_pdf_bytes", 52_428_800)):
            raise FeatureJobError("Translation PDF exceeds the configured size limit.")
        parsed_source = checkpoint_value(context, "parsed_pages", lambda: {"pages": [
            page.as_dict() for page in parse_pdf_pages(
                path, work_dir=context.job_dir / "parse",
                max_pages=int(settings.get("max_pages", 300)),
                prefer_mineru=settings.get("parser_backend", "mineru") == "mineru",
                ocr_enabled=bool(settings.get("ocr_enabled", True)),
            )
        ]}, feedback={})
        pages = parsed_source["pages"]
        start = int(data.get("page_start") or 1)
        end = int(data.get("page_end") or len(pages))
        if not pages or start > len(pages) or end > len(pages):
            raise FeatureJobError("The requested page range is outside the PDF.")
        pages = [page for page in pages if start <= page["page_number"] <= end]
        if not pages:
            raise FeatureJobError("PDF parsing produced no pages in the requested range.")
        prompt = self.resolve_prompt(
            str(context.job.prompt_id), prompt_version=context.job.prompt_version, prompt_hash=context.job.prompt_hash,
        )
        terminology = dict(data.get("terminology_overrides", {}))
        revision = revision_request(context)
        retained = revision.get("previous_result", {}) if revision.get("scope") == "pages" else {}
        previous_pages = {str(page["page_number"]): page for page in retained.get("pages", [])}
        for entry in retained.get("terminology_ledger", []):
            terminology.setdefault(entry["source"], entry["target"])
        translated_pages = []
        for ordinal, page in enumerate(pages):
            context.checkpoint(progress=15 + int(70 * ordinal / len(pages)), current_step="translating_page")
            if previous_pages and str(page["page_number"]) not in revision.get("unit_ids", []):
                if str(page["page_number"]) not in previous_pages:
                    raise FeatureJobError("The retained revision does not match the source pages.")
                translated_pages.append(previous_pages[str(page["page_number"])])
                continue
            translated = []
            unresolved = list(page.get("unresolved_items", []))
            blocks = page["source_blocks"]
            for block in blocks:
                context.check_cancelled()
                block_id = str(block["block_id"])
                if block.get("kind") in {"equation", "image", "table"}:
                    translated.append(dict(block))
                    continue
                protected, locks = protect_block(block_id, str(block["text"]), verbatim=block.get("kind") in {"equation", "image", "table"})
                if not protected.strip():
                    continue
                if len(protected) > 20_000:
                    raise FeatureJobError(f"Source block {block_id} exceeds the translation block limit.")
                def produce(page=page, block_id=block_id, protected=protected):
                    messages = prompt.build_messages(
                        input_manifest={"file_id": file_id, "page_number": page["page_number"]},
                        task_context={
                            "input": {key: value for key, value in data.items() if key != "files"},
                            "pages": [{"page_number": page["page_number"], "source_blocks": [{"block_id": block_id, "text": protected}]}],
                            "terminology_ledger": terminology,
                            "review_feedback": revision_feedback(context),
                        },
                    )
                    if data.get("prompt_rules"):
                        messages = apply_rules(messages, data["prompt_rules"])
                    callback = build_web_json_llm_call(
                        config=self.config, model=context.job.model_name, timeout=context.remaining_seconds(120),
                        temperature=manifest["model"].get("generation", {}).get("temperature", 0.2),
                        max_output_tokens=manifest["model"].get("generation", {}).get("max_output_tokens", 16384),
                    )
                    return TranslationOutput.model_validate(call_required_json(callback, messages, stage="web_translation")).model_dump()

                def validate(candidate, page=page, block_id=block_id, locks=locks):
                    result = TranslationOutput.model_validate(candidate)
                    if len(result.pages) != 1 or result.pages[0].page_number != page["page_number"]:
                        raise FeatureJobError("Translation changed the source page mapping.")
                    outputs = result.pages[0].translated_blocks
                    if len(outputs) != 1 or outputs[0].block_id != block_id:
                        raise FeatureJobError("Translation omitted, duplicated, or added a source block.")
                    translated_text = restore_block(outputs[0].text, locks)
                    for source_term, target_term in terminology.items():
                        if source_term in block["text"] and target_term not in translated_text:
                            raise FeatureJobError(
                                f"Translation omitted a required terminology mapping in {block_id}."
                            )
                    for entry in result.terminology_ledger:
                        previous = terminology.get(entry.source)
                        if previous is not None and previous != entry.target:
                            raise FeatureJobError(
                                f"Translation terminology is inconsistent in {block_id}."
                            )

                result = TranslationOutput.model_validate(checkpoint_value(
                    context, {"block_id": block_id, "terminology": terminology}, produce, validate,
                ))
                outputs = result.pages[0].translated_blocks
                translated_text = restore_block(outputs[0].text, locks)
                for entry in result.terminology_ledger:
                    terminology[entry.source] = entry.target
                translated.append({"block_id": block_id, "text": translated_text})
                unresolved.extend(result.pages[0].unresolved_items)
                unresolved.extend(result.unresolved_items)
            if not blocks:
                unresolved.append(f"page_{page['page_number']}_ocr_required")
            translated_pages.append({
                **page, "translated_blocks": translated, "review_status": "pending",
                "unresolved_items": list(dict.fromkeys(unresolved)),
            })
        output = {
            "schema_version": "translation_document_v1", "pages": translated_pages,
            "terminology_ledger": [{"source": source, "target": target} for source, target in terminology.items()],
            "unresolved_items": [item for page in translated_pages for item in page["unresolved_items"]],
        }
        context.checkpoint(progress=90, current_step="publishing_translation")
        provenance = {
            "prompt_id": prompt.prompt_id, "prompt_version": prompt.prompt_version, "prompt_hash": prompt.prompt_hash,
            "model": context.job.model_name, "parser_backends": sorted({page["parser_backend"] for page in pages}),
            "ocr_used": any(page["ocr_used"] for page in pages),
        }
        status = "WARN" if output["unresolved_items"] else "PASS"
        artifacts = [publish_json_artifact(
            context, role="translation_pages", filename="translation_pages.json", payload=output,
            provenance=provenance, source_file_ids=[file_id], validator_status=status,
        )]
        artifacts.append(publish_json_artifact(
            context, role="document_source_map", filename="document_source_map.json",
            payload=document_source_map(
                [DocumentBlock(str(block["block_id"]), str(block["text"]), str(block.get("kind", "text")), ordinal,
                               page_number=int(page["page_number"]), parent_block_id=block.get("parent_block_id"))
                 for page in pages for ordinal, block in enumerate(page["source_blocks"], start=1)],
                source_hashes={file_id: str(data["files"][0]["sha256"])}, parser="pdf_ingestion", parser_version="2.0.0",
                limitations=["Text exports retain page/block mapping; source PDF layout is not reconstructed."],
            ), validator_status=status, source_file_ids=[file_id],
        ))
        if "markdown" in data.get("output_formats", []):
            artifacts.append(publish_bytes_artifact(
                context, role="translation_markdown", filename="translation.md",
                content=self._markdown_output(translated_pages).encode("utf-8"), media_type="text/markdown",
                provenance=provenance, source_file_ids=[file_id], validator_status=status,
            ))
        return JobExecutionResult(status="WAITING_FOR_REVIEW", output_artifact_ids=tuple(artifacts), current_step="awaiting_page_review")

    @staticmethod
    def _markdown_output(pages: list[dict[str, object]]) -> str:
        chunks = []
        for page in pages:
            chunks.append(f"## Page {page['page_number']}")
            chunks.extend(str(block["text"]) for block in page["translated_blocks"])
            if page["unresolved_items"]:
                chunks.append("[AUTHOR_INPUT_NEEDED: source parsing or terminology requires review]")
        return "\n\n".join(chunks).strip() + "\n"
