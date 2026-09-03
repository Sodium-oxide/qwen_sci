"""Batch-A preparation entrypoint for the Research Plan Author."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from copy import deepcopy
from collections.abc import Callable, Mapping
from typing import Any

from .authoring_blueprint import AuthoringBlueprintError, AuthoringBlueprintPlanner
from .bibtex_renderer import BibtexRenderError, bibliography_preflight_errors
from .contract_repair import AuthorContractRepairError
from .document_quality import optimize_research_plan_document
from .contracts import (
    AUTHORING_LANGUAGE,
    AUTHOR_PREPARATION_SCHEMA_VERSION,
    build_research_plan_document_skeleton,
)
from .idea_evolution import (
    IdeaEvolutionError,
    disabled_idea_evolution,
    project_idea_evolution,
    unavailable_idea_evolution,
)
from .input_loader import AuthorInputLoadError, load_author_input_with_identity
from .quantitative_disclosure_validator import validate_quantitative_disclosure
from .quantitative_evidence_adapter import (
    QuantitativeEvidenceLoadError,
    append_quantitative_evidence_section,
    load_quantitative_evidence_capsule,
)
from .run_logging import AuthorRunLogger
from .section_cache import SectionCompositionCache, section_cache_identity
from .section_composer import SectionComposer, SectionCompositionError, validate_section_output
from .section_router import route_author_sections
from .semantic_validator import validate_composed_research_plan
from .source_bundle import build_author_source_bundle
from .source_registry import (
    build_authoring_knowledge_base,
    build_frozen_source_registry,
    source_registry_for_blueprint_section,
)
from .survey_source_loader import SurveyAuthorSourceError, load_verified_survey_sources
from .theory_spine import TheorySpineError, build_theory_spine


class AuthorRunError(RuntimeError):
    """Typed Author preparation failure with a stage for CLI reporting."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


class AuthorCompositionError(AuthorRunError):
    """Composition failure that preserves a private contract-repair audit."""

    def __init__(self, message: str, *, audit: Mapping[str, Any] | None = None) -> None:
        super().__init__("composition", message)
        self.audit = deepcopy(dict(audit)) if isinstance(audit, Mapping) else None


_WSL_MOUNTED_PATH = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_WINDOWS_DRIVE_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")
_SURVEY_BINDING_FIELDS = (
    "survey_run_id",
    "project_id",
    "project_context_fingerprint",
)


def _resolve_optional_path(value: str | Path | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    raw_value = os.fspath(value)
    normalized = raw_value.replace("\\", "/")
    if os.name == "nt":
        wsl_match = _WSL_MOUNTED_PATH.fullmatch(normalized)
        path = Path(f"{wsl_match.group(1).upper()}:/{wsl_match.group(2) or ''}") if wsl_match else Path(raw_value)
    else:
        windows_match = _WINDOWS_DRIVE_PATH.fullmatch(normalized)
        path = Path(f"/mnt/{windows_match.group(1).lower()}/{windows_match.group(2)}") if windows_match else Path(raw_value)
    return path.expanduser().resolve()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _verify_survey_binding(
    author_input: dict[str, Any],
    survey_sources: dict[str, Any],
    *,
    strict: bool,
) -> dict[str, Any]:
    """Bind Survey identity to the design or expose the missing binding clearly."""

    provenance = _mapping(author_input.get("provenance"))
    expected = {field: _text(_mapping(provenance.get("survey_binding")).get(field)) for field in _SURVEY_BINDING_FIELDS}
    resolved = {field: _text(survey_sources.get(field)) for field in _SURVEY_BINDING_FIELDS}
    has_binding = any(expected.values())
    if not has_binding:
        if strict:
            raise AuthorRunError(
                "survey",
                "Author handoff has no provenance.survey_binding; strict Survey binding requires all identity fields",
            )
        return {
            "status": "UNBOUND_REQUIRES_HUMAN_CONFIRMATION",
            "expected": expected,
            "resolved": resolved,
            "human_confirmation_required": True,
        }
    missing = [field for field, value in expected.items() if not value]
    if missing:
        raise AuthorRunError(
            "survey",
            "Author handoff provenance.survey_binding is incomplete; missing " + ", ".join(missing),
        )
    mismatched = [field for field in _SURVEY_BINDING_FIELDS if expected[field] != resolved[field]]
    if mismatched:
        raise AuthorRunError(
            "survey",
            "Survey manifest does not match Author handoff provenance.survey_binding for " + ", ".join(mismatched),
        )
    return {
        "status": "BOUND_VERIFIED",
        "expected": expected,
        "resolved": resolved,
        "human_confirmation_required": False,
    }


def run_author_preparation(
    author_input_path: str | Path,
    *,
    survey_manifest_path: str | Path,
    idea_result_path: str | Path | None = None,
    include_idea_evolution: str = "auto",
    max_idea_iterations: int = 3,
    strict_survey_binding: bool = False,
    quantitative_handoff_manifest_path: str | Path | None = None,
    logger: AuthorRunLogger | None = None,
) -> dict[str, Any]:
    """Verify all Batch-A sources and produce no prose, TeX, or PDF yet."""

    mode = str(include_idea_evolution or "auto").strip().casefold()
    if mode not in {"auto", "on", "off"}:
        raise AuthorRunError("input", "include_idea_evolution must be one of auto, on, or off")
    if max_idea_iterations not in {2, 3}:
        raise AuthorRunError("input", "max_idea_iterations must be either 2 or 3")
    active_logger = logger
    try:
        if active_logger is None:
            resolved_author_input, author_input, author_input_identity = load_author_input_with_identity(author_input_path)
        else:
            with active_logger.stage("input", input_path=str(author_input_path)):
                resolved_author_input, author_input, author_input_identity = load_author_input_with_identity(author_input_path)
    except AuthorInputLoadError as error:
        raise AuthorRunError("input", str(error)) from error
    source_registry = _mapping(author_input.get("source_registry"))
    try:
        if active_logger is None:
            bibliography_errors = bibliography_preflight_errors(source_registry.get("citation_registry"))
        else:
            with active_logger.stage(
                "bibliography_preflight",
                citation_count=len(source_registry.get("citation_registry") or []),
            ):
                bibliography_errors = bibliography_preflight_errors(source_registry.get("citation_registry"))
                if bibliography_errors:
                    raise AuthorRunError(
                        "input",
                        "citation registry contains records that cannot render before composition: "
                        + "; ".join(bibliography_errors),
                    )
    except BibtexRenderError as error:
        raise AuthorRunError("input", f"invalid citation registry before composition: {error}") from error
    if bibliography_errors:
        raise AuthorRunError(
            "input",
            "citation registry contains records that cannot render before composition: "
            + "; ".join(bibliography_errors),
        )
    try:
        if active_logger is None:
            survey_sources = load_verified_survey_sources(survey_manifest_path)
        else:
            with active_logger.stage("survey", manifest_path=str(survey_manifest_path)):
                survey_sources = load_verified_survey_sources(survey_manifest_path)
    except SurveyAuthorSourceError as error:
        raise AuthorRunError("survey", str(error)) from error
    try:
        survey_binding = _verify_survey_binding(
            author_input,
            survey_sources,
            strict=bool(strict_survey_binding),
        )
    except AuthorRunError:
        raise
    if active_logger is not None:
        active_logger.emit(
            "survey",
            "binding_verified" if survey_binding["status"] == "BOUND_VERIFIED" else "binding_unbound",
            level="INFO" if survey_binding["status"] == "BOUND_VERIFIED" else "WARNING",
            status=survey_binding["status"],
            human_confirmation_required=survey_binding["human_confirmation_required"],
        )
    provenance = author_input.get("provenance") or {}
    selected_direction_id = str(provenance.get("selected_direction_id") or "").strip()
    quantitative_evidence: dict[str, Any] = {}
    if quantitative_handoff_manifest_path is not None:
        try:
            quantitative_evidence = load_quantitative_evidence_capsule(
                quantitative_handoff_manifest_path,
                expected_identity={
                    **survey_binding["resolved"],
                    "selected_direction_id": selected_direction_id,
                },
            )
        except QuantitativeEvidenceLoadError as error:
            raise AuthorRunError("input", f"quantitative Author handoff validation failed: {error}") from error
    requested_idea_path = _resolve_optional_path(idea_result_path)
    inherited_idea_path = _resolve_optional_path(provenance.get("idea_result_path"))
    resolved_idea_path = requested_idea_path or inherited_idea_path
    if mode == "off":
        idea_evolution = disabled_idea_evolution()
    elif resolved_idea_path is None:
        if mode == "on":
            raise AuthorRunError("idea_evolution", "--idea-result is required when --include-idea-evolution=on")
        idea_evolution = unavailable_idea_evolution("No explicit or provenance idea_result.json path is available")
    else:
        try:
            if active_logger is None:
                idea_evolution = project_idea_evolution(
                    resolved_idea_path,
                    selected_direction_id=selected_direction_id,
                    max_iterations=max_idea_iterations,
                )
            else:
                with active_logger.stage(
                    "idea_evolution",
                    idea_result_path=str(resolved_idea_path),
                    selected_direction_id=selected_direction_id,
                ):
                    idea_evolution = project_idea_evolution(
                        resolved_idea_path,
                        selected_direction_id=selected_direction_id,
                        max_iterations=max_idea_iterations,
                    )
        except IdeaEvolutionError as error:
            if "selected direction mismatch" in str(error):
                raise AuthorRunError("idea_evolution", str(error)) from error
            if mode == "auto" and requested_idea_path is None:
                idea_evolution = unavailable_idea_evolution(str(error))
                if active_logger is not None:
                    active_logger.emit(
                        "idea_evolution",
                        "unavailable",
                        level="WARNING",
                        status="UNAVAILABLE",
                        reason=str(error),
                    )
            else:
                raise AuthorRunError("idea_evolution", str(error)) from error
    source_bundle = build_author_source_bundle(
        author_input,
        author_input_path=str(resolved_author_input),
        author_input_identity=author_input_identity,
        survey_sources=survey_sources,
        survey_binding=survey_binding,
        idea_evolution=idea_evolution,
        quantitative_evidence=quantitative_evidence,
    )
    document = build_research_plan_document_skeleton(author_input, source_bundle)
    theory_preparation = {
        "source_design_id": author_input["source_design_id"],
        "source_bundle": source_bundle,
        "document": document,
    }
    routing = route_author_sections(author_input)
    try:
        if active_logger is None:
            theory_spine = build_theory_spine(
                theory_preparation,
                routing=routing,
                source_registry=build_frozen_source_registry(theory_preparation),
            )
        else:
            with active_logger.stage("theory_spine", template_family=routing["template_family"]):
                theory_spine = build_theory_spine(
                    theory_preparation,
                    routing=routing,
                    source_registry=build_frozen_source_registry(theory_preparation),
                )
    except TheorySpineError as error:
        raise AuthorRunError("theory_spine", str(error)) from error
    result = {
        "schema_version": AUTHOR_PREPARATION_SCHEMA_VERSION,
        "status": "PREPARED_FOR_COMPOSITION",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "language": AUTHORING_LANGUAGE,
        "source_design_id": author_input["source_design_id"],
        "selected_direction_id": selected_direction_id,
        "source_bundle": source_bundle,
        "document": document,
        "theory_spine": theory_spine,
    }
    if active_logger is not None:
        active_logger.emit(
            "preparation",
            "completed",
            status="COMPLETED",
            source_design_id=result["source_design_id"],
            selected_direction_id=selected_direction_id,
            idea_evolution_status=idea_evolution["status"],
            survey_binding_status=survey_binding["status"],
            theory_spine_enabled=theory_spine["enabled"],
            language=AUTHORING_LANGUAGE,
        )
    return result


def _mapping_value(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _append_unique(items: list[Any], additions: object) -> None:
    if not isinstance(additions, list):
        return
    for candidate in additions:
        if candidate not in items:
            items.append(deepcopy(candidate))


def _namespace_section_claim_ids(section: Mapping[str, Any]) -> dict[str, Any]:
    """Make locally valid claim identifiers unique in the assembled document."""

    normalized = deepcopy(dict(section))
    section_id = str(normalized.get("section_id") or "").strip()
    claims = [dict(claim) for claim in normalized.get("claim_provenance") or [] if isinstance(claim, Mapping)]
    normalized["claim_provenance"] = claims
    claim_id_map = {
        str(claim.get("claim_id") or "").strip(): f"{section_id}:{str(claim.get('claim_id') or '').strip()}"
        for claim in claims
    }
    for claim in claims:
        claim_id = str(claim.get("claim_id") or "").strip()
        claim["claim_id"] = claim_id_map[claim_id]
    blocks: list[Any] = []
    for block in normalized.get("blocks") or []:
        if not isinstance(block, Mapping):
            blocks.append(deepcopy(block))
            continue
        normalized_block = dict(block)
        block_claim_ids = [str(claim_id).strip() for claim_id in normalized_block.get("claim_ids") or []]
        normalized_block["claim_ids"] = [claim_id_map.get(claim_id, claim_id) for claim_id in block_claim_ids]
        blocks.append(normalized_block)
    normalized["blocks"] = blocks
    return normalized


def _render_composed_document(
    preparation: Mapping[str, Any],
    *,
    blueprint: Mapping[str, Any],
    routing: Mapping[str, Any],
    source_registry: Mapping[str, Any],
    composed_sections: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
    repair_audits: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge validated routed sections without allowing them to replace provenance."""

    document = deepcopy(_mapping_value(preparation.get("document")))
    document["document_status"] = "PROPOSAL_NO_OBSERVED_RESULTS"
    metadata = _mapping_value(document.get("document_metadata"))
    metadata["title"] = str(blueprint.get("document_title") or "").strip()
    metadata["title_status"] = "english_llm_composed"
    document["document_metadata"] = metadata
    document["keywords"] = list(blueprint.get("keywords") or [])
    document["authoring_blueprint"] = deepcopy(dict(blueprint))
    document["theory_spine"] = deepcopy(_mapping_value(preparation.get("theory_spine")))
    document["citation_registry"] = deepcopy(list(source_registry.get("citation_registry") or []))
    document["claim_provenance"] = []
    document["sections"] = []
    document["appendices"] = []
    document["contract_repair_audit"] = [deepcopy(dict(audit)) for audit in repair_audits]
    all_open_items: list[Any] = []
    all_review_items: list[Any] = []
    for route, raw_section in composed_sections:
        section = _namespace_section_claim_ids(raw_section)
        section_id = str(section.get("section_id") or "")
        _append_unique(all_open_items, section.get("open_items"))
        _append_unique(all_review_items, section.get("review_items"))
        document["claim_provenance"].extend(deepcopy(list(section.get("claim_provenance") or [])))
        if route.get("target") == "abstract":
            document["abstract"] = {
                "text": "\n\n".join(
                    str(block.get("text") or "").strip()
                    for block in section.get("blocks") or []
                    if isinstance(block, Mapping) and str(block.get("text") or "").strip()
                ),
                "claim_ids": list(
                    dict.fromkeys(
                        str(claim_id).strip()
                        for block in section.get("blocks") or []
                        if isinstance(block, Mapping)
                        for claim_id in block.get("claim_ids") or []
                        if str(claim_id).strip()
                    )
                ),
            }
            continue
        rendered = {
            "section_id": section_id,
            "title": str(section.get("title") or ""),
            "applicability": str(section.get("applicability") or ""),
            "blocks": deepcopy(list(section.get("blocks") or [])),
        }
        target = document["appendices"] if route.get("target") == "appendices" else document["sections"]
        target.append(rendered)
    document["open_items"] = all_open_items
    document["review_items"] = all_review_items
    source_manifest = _mapping_value(document.get("source_manifest"))
    bundle = _mapping_value(preparation.get("source_bundle"))
    source_manifest.update(
        {
            "author_context_sha256": _mapping_value(bundle.get("author_input_identity")).get("sha256", ""),
            "survey_binding": deepcopy(_mapping_value(bundle.get("survey_binding"))),
            "template_family": routing.get("template_family", ""),
            "theory_sampling_power_status": routing.get("theory_sampling_power_status", "route_specific"),
        }
    )
    document["source_manifest"] = source_manifest
    return document


def run_research_plan_author(
    author_input_path: str | Path,
    *,
    survey_manifest_path: str | Path,
    idea_result_path: str | Path | None = None,
    include_idea_evolution: str = "auto",
    max_idea_iterations: int = 3,
    strict_survey_binding: bool = False,
    quantitative_handoff_manifest_path: str | Path | None = None,
    llm_call: Callable[..., object] | None = None,
    max_contract_repairs: int = 1,
    composer_concurrency: int = 5,
    section_cache_config: Mapping[str, Any] | None = None,
    document_quality_config: Mapping[str, Any] | None = None,
    quality_judge_llm_call: Callable[..., object] | None = None,
    quality_revision_llm_call: Callable[..., object] | None = None,
    collect_section_contract_errors: bool = True,
    logger: AuthorRunLogger | None = None,
) -> dict[str, Any]:
    """Run preparation, section composition, and final proposal-only validation.

    Every routed section is attempted even when earlier sections fail. Failed
    sections emit warnings and the run stops only after the full section batch
    has completed, with one aggregate failure audit. The legacy
    ``collect_section_contract_errors`` argument is retained for callers but
    section failures are always aggregated.
    """

    if max_contract_repairs not in (0, 1):
        raise AuthorRunError(
            "input",
            "max_contract_repairs must be 0 or 1; each section supports at most one generic repair",
        )
    resolved_input_path = _resolve_optional_path(author_input_path)
    preparation = run_author_preparation(
        author_input_path,
        survey_manifest_path=survey_manifest_path,
        idea_result_path=idea_result_path,
        include_idea_evolution=include_idea_evolution,
        max_idea_iterations=max_idea_iterations,
        strict_survey_binding=strict_survey_binding,
        quantitative_handoff_manifest_path=quantitative_handoff_manifest_path,
        logger=logger,
    )
    if composer_concurrency < 1:
        raise AuthorRunError("input", "composer_concurrency must be at least 1")
    source_registry = build_frozen_source_registry(preparation)
    # The catalog remains source-bounded, but all sections receive the same
    # upstream knowledge base.  Route recommendations are a writing aid, not
    # a permission system.
    source_registry["authoring_knowledge_base"] = build_authoring_knowledge_base(
        preparation,
        source_registry,
    )
    author_context = _mapping_value(_mapping_value(preparation.get("source_bundle")).get("author_context"))
    routing = route_author_sections(author_context)
    planner = AuthoringBlueprintPlanner()
    section_repairs_enabled = bool(max_contract_repairs)
    resolved_cache_config = dict(section_cache_config or {})
    if "root" not in resolved_cache_config and resolved_input_path is not None:
        resolved_cache_config["root"] = str(
            resolved_input_path.parent / ".science" / "cache" / "research_plan_author" / "v1"
        )
    section_cache = SectionCompositionCache(resolved_cache_config)
    repair_audits: list[Mapping[str, Any]] = []
    try:
        if logger is None:
            blueprint, blueprint_audit = planner.plan_with_audit(
                preparation,
                routing=routing,
                source_registry=source_registry,
                llm_call=llm_call,
                allow_contract_repair=section_repairs_enabled,
                logger=logger,
            )
        else:
            with logger.stage("blueprint", template_family=routing["template_family"]):
                blueprint, blueprint_audit = planner.plan_with_audit(
                    preparation,
                    routing=routing,
                    source_registry=source_registry,
                    llm_call=llm_call,
                    allow_contract_repair=section_repairs_enabled,
                    logger=logger,
                )
        if blueprint_audit is not None:
            repair_audits.append(blueprint_audit)
    except AuthorContractRepairError as error:
        raise AuthorCompositionError(str(error), audit=error.audit) from error
    except AuthoringBlueprintError as error:
        raise AuthorCompositionError(str(error), audit=error.audit) from error
    except Exception as error:
        raise AuthorCompositionError(str(error)) from error

    blueprint_sections = {
        str(section.get("section_id") or ""): section
        for section in blueprint.get("sections") or []
        if isinstance(section, Mapping)
    }
    composed_sections: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    section_failures: list[dict[str, Any]] = []
    section_jobs = [
        (
            route_index,
            route,
            _mapping_value(blueprint_sections.get(str(route["section_id"]))),
        )
        for route_index, route in enumerate(routing["routes"])
    ]

    def compose_section(
        route_index: int,
        route: Mapping[str, Any],
        blueprint_section: Mapping[str, Any],
    ) -> tuple[int, Mapping[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None, dict[str, Any] | None]:
        section_id = str(route["section_id"])
        section_source_registry = source_registry_for_blueprint_section(source_registry, route, blueprint_section)
        cache_identity = section_cache_identity(
            preparation=preparation,
            blueprint=blueprint,
            route=route,
            blueprint_section=blueprint_section,
            source_registry=section_source_registry,
        )
        cached_section = section_cache.read(cache_identity)
        if cached_section is not None:
            cached_errors = validate_section_output(
                cached_section,
                route=route,
                blueprint_section=blueprint_section,
                preparation=preparation,
                source_registry=section_source_registry,
                allow_cross_reference_quality_warnings=True,
            )
            if not cached_errors:
                if logger is not None:
                    logger.emit(
                        "section_composition",
                        "cache_hit",
                        status="CACHED",
                        section_id=section_id,
                    )
                return route_index, route, cached_section, None, None
            if logger is not None:
                logger.emit(
                    "section_composition",
                    "cache_rejected",
                    level="WARNING",
                    status="CACHE_REJECTED",
                    section_id=section_id,
                    validation_error_count=len(cached_errors),
                )
        try:
            if logger is None:
                section, audit = SectionComposer().compose(
                    preparation,
                    blueprint=blueprint,
                    route=route,
                    blueprint_section=blueprint_section,
                    source_registry=section_source_registry,
                    llm_call=llm_call,
                    allow_contract_repair=section_repairs_enabled,
                )
            else:
                with logger.stage(
                    "section_composition",
                    failure_level="WARNING",
                    failure_status="WARNING",
                    section_id=section_id,
                ):
                    section, audit = SectionComposer().compose(
                        preparation,
                        blueprint=blueprint,
                        route=route,
                        blueprint_section=blueprint_section,
                        source_registry=section_source_registry,
                        llm_call=llm_call,
                        allow_contract_repair=section_repairs_enabled,
                    )
        except (AuthorContractRepairError, SectionCompositionError) as error:
            failure = {
                "section_id": section_id,
                "error_code": type(error).__name__,
                "error": str(error),
            }
            if isinstance(error.audit, Mapping):
                failure["audit"] = deepcopy(dict(error.audit))
                validation_errors = error.audit.get("initial_validation_errors") or error.audit.get("repair_validation_errors") or []
                if isinstance(validation_errors, list):
                    failure["validation_error_count"] = len(validation_errors)
            return route_index, route, None, None, failure
        except Exception as error:
            return (
                route_index,
                route,
                None,
                None,
                {
                    "section_id": section_id,
                    "error_code": type(error).__name__,
                    "error": str(error),
                    "validation_error_count": 0,
                },
            )
        section_cache.write(cache_identity, section)
        return route_index, route, section, audit, None

    with ThreadPoolExecutor(
        max_workers=min(int(composer_concurrency), len(section_jobs)),
        thread_name_prefix="author-section",
    ) as executor:
        futures = [
            executor.submit(compose_section, route_index, route, blueprint_section)
            for route_index, route, blueprint_section in section_jobs
        ]
        section_results = [future.result() for future in as_completed(futures)]
    section_quality_warning_count = 0
    for _route_index, route, section, audit, failure in sorted(section_results, key=lambda result: result[0]):
        if failure is not None:
            section_failures.append(failure)
            continue
        if audit is not None:
            repair_audits.append(audit)
            quality_warnings = audit.get("quality_warnings") if isinstance(audit, Mapping) else []
            if quality_warnings:
                section_quality_warning_count += 1
                if logger is not None:
                    logger.emit(
                        "section_composition",
                        "quality_warning",
                        level="WARNING",
                        status="WARNING",
                        section_id=str(route.get("section_id") or ""),
                        warning_count=len(quality_warnings),
                    )
        if section is not None:
            composed_sections.append((route, section))
    if section_failures:
        diagnostic_audit = {
            "schema_version": "research_plan_author_section_contract_diagnostics_v1",
            "artifact_kind": "section_contract_preflight",
            "mode": "complete_all_sections_before_abort",
            "section_count": len(routing["routes"]),
            "attempted_section_count": len(routing["routes"]),
            "passed_section_count": len(composed_sections),
            "failed_section_count": len(section_failures),
            "section_cache": section_cache.summary(),
            "failures": section_failures,
        }
        if logger is not None:
            logger.emit(
                "section_diagnostics",
                "completed",
                level="WARNING",
                status="REJECTED",
                section_count=len(routing["routes"]),
                failed_section_count=len(section_failures),
                passed_section_count=len(composed_sections),
            )
        failed_section_ids = ", ".join(failure["section_id"] for failure in section_failures)
        raise AuthorCompositionError(
            f"section contract preflight found {len(section_failures)} failing section(s): {failed_section_ids}",
            audit=diagnostic_audit,
        )
    document = _render_composed_document(
        preparation,
        blueprint=blueprint,
        routing=routing,
        source_registry=source_registry,
        composed_sections=composed_sections,
        repair_audits=repair_audits,
    )
    quantitative_evidence = _mapping_value(
        _mapping_value(preparation.get("source_bundle")).get("quantitative_evidence")
    )
    if quantitative_evidence:
        document = append_quantitative_evidence_section(document, quantitative_evidence)
        disclosure_errors = validate_quantitative_disclosure(document)
        if disclosure_errors:
            raise AuthorCompositionError(
                "quantitative evidence disclosure validation failed: " + "; ".join(disclosure_errors)
            )
    # Whole-document quality scoring and revision now owns cross-section
    # coherence, deduplication, and scholarly depth.  Do not pre-edit the
    # canonical 15-section manuscript with the legacy constrained editor:
    # it makes an unscored extra LLM call and prevents the quality loop from
    # considering the actual composed draft as its baseline candidate.
    if logger is not None:
        logger.emit("document_quality", "started", status="RUNNING")
    try:
        document, document_quality = optimize_research_plan_document(
            document,
            preparation=preparation,
            routing=routing,
            source_registry=source_registry,
            quality_config=document_quality_config,
            judge_llm_call=quality_judge_llm_call,
            revision_llm_call=quality_revision_llm_call,
            logger=logger,
        )
    except Exception as error:
        document_quality = {
            "schema_version": "research_plan_author_document_quality_v1",
            "enabled": bool(_mapping_value(document_quality_config).get("enabled")),
            "candidates": [],
            "selected_candidate_index": 0,
            "warnings": [f"document quality loop failed without blocking composition: {type(error).__name__}: {error}"],
        }
        if logger is not None:
            logger.emit("document_quality", "failed", level="WARNING", status="WARNING", error=str(error))
    else:
        if logger is not None:
            logger.emit(
                "document_quality",
                "completed",
                status="COMPLETED",
                selected_candidate_index=document_quality.get("selected_candidate_index", 0),
                candidate_count=len(document_quality.get("candidates") or []),
                warning_count=len(document_quality.get("warnings") or []),
            )
    errors = validate_composed_research_plan(
        document,
        preparation=preparation,
        routing=routing,
        source_registry=source_registry,
    )
    if errors:
        raise AuthorCompositionError("final semantic validation failed: " + "; ".join(errors))
    result = deepcopy(preparation)
    result["status"] = "COMPOSED_FOR_RENDERING"
    result["document"] = document
    result["section_cache"] = section_cache.summary()
    result["document_quality"] = document_quality
    if logger is not None:
        logger.emit(
            "composition",
            "completed",
            status="COMPLETED",
            source_design_id=result["source_design_id"],
            template_family=routing["template_family"],
            contract_repair_count=sum(
                1 for audit in repair_audits if isinstance(audit, Mapping) and audit.get("repair_attempted")
            ),
            section_quality_warning_count=section_quality_warning_count,
            section_cache_hits=result["section_cache"]["hits"],
            section_cache_writes=result["section_cache"]["writes"],
            language=AUTHORING_LANGUAGE,
        )
    return result


__all__ = ["AuthorCompositionError", "AuthorRunError", "run_author_preparation", "run_research_plan_author"]
